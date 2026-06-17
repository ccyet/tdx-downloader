from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from tdx_downloader.data.audit import audit_local_data, data_gap_episodes
from tdx_downloader.data.catalog import query_coverage_runs, query_market_data_part_symbols, refresh_coverage_runs
from tdx_downloader.data.inventory import inventory_local_data
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.data.manager import DataDownloadConfig, DataManagementService
from tdx_downloader.data.repository import clear_fast_plan_cache
from tdx_downloader.data.schema import empty_bars
from tdx_downloader.data.tdx_worker import (
    WorkerJob,
    _fetch_windows_to_manifest,
    _part_summary_rows,
    _write_part,
    commit_worker_manifest,
    create_worker_app,
)
from tdx_downloader.data.tdx_worker import TdxWorkerStore
from tdx_downloader.data.tdx_worker_client import TdxWorkerClient
import tdx_downloader.data.tdx_worker_client as worker_client


def test_worker_health_reports_python_and_scratch(tmp_path: Path) -> None:
    app = create_worker_app(scratch_root=tmp_path / "jobs")

    routes = {route.path: route for route in app.routes}

    assert "/health" in routes


def test_worker_client_wait_emits_heartbeat(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(worker_client, "WORKER_POLL_SECONDS", 0)
    monkeypatch.setattr(worker_client, "WORKER_WAIT_HEARTBEAT_SECONDS", 0)

    class Client(TdxWorkerClient):
        def __init__(self) -> None:
            super().__init__("http://worker.test")
            self.calls = 0

        def get_job(self, job_id: str, **_: object) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                return {
                    "status": "running",
                    "events": [{"stage": "worker_fetch_window_start"}],
                }
            return {"status": "succeeded", "events": [{"stage": "worker_job_done"}]}

    events: list[dict[str, object]] = []
    payload = Client().wait("job1", progress_callback=events.append)

    assert payload["status"] == "succeeded"
    heartbeat = next(event for event in events if event.get("stage") == "worker_job_waiting")
    assert heartbeat["job_id"] == "job1"
    assert heartbeat["last_worker_stage"] == "worker_fetch_window_start"


def test_worker_payload_supports_incremental_events(tmp_path: Path) -> None:
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    job = WorkerJob(id="job1", payload={})
    with store._lock:  # noqa: SLF001
        store._jobs[job.id] = job  # noqa: SLF001
    store._append_event(job.id, {"stage": "first"})  # noqa: SLF001
    store._append_event(job.id, {"stage": "second"})  # noqa: SLF001

    payload = store.payload(job, after_event_index=0, event_limit=10, include_records=False)

    assert payload["event_count"] == 2
    assert payload["event_start_index"] == 0
    assert payload["event_next_index"] == 2
    assert payload["records"] == []
    assert [event["stage"] for event in payload["events"]] == ["second"]
    assert payload["events"][0]["event_index"] == 1


def test_worker_client_wait_uses_incremental_event_cursor(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(worker_client, "WORKER_POLL_SECONDS", 0)
    monkeypatch.setattr(worker_client, "WORKER_WAIT_HEARTBEAT_SECONDS", 3600)

    class Client(TdxWorkerClient):
        def __init__(self) -> None:
            super().__init__("http://worker.test")
            self.calls: list[dict[str, object]] = []

        def get_job(self, job_id: str, **kwargs: object) -> dict[str, object]:
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return {
                    "status": "running",
                    "events": [{"event_index": 0, "stage": "first"}],
                    "event_next_index": 1,
                    "event_count": 1,
                }
            if len(self.calls) == 2:
                return {
                    "status": "running",
                    "events": [{"event_index": 1, "stage": "second"}],
                    "event_next_index": 2,
                    "event_count": 2,
                }
            return {"status": "succeeded", "events": [], "event_next_index": 2, "event_count": 2}

    events: list[dict[str, object]] = []
    payload = Client()
    result = payload.wait("job1", progress_callback=events.append)

    assert result["status"] == "succeeded"
    assert [event["stage"] for event in events] == ["first", "second"]
    assert payload.calls[0]["after_event_index"] == -1
    assert payload.calls[1]["after_event_index"] == 0
    assert payload.calls[2]["after_event_index"] == 1
    assert payload.calls[0]["include_records"] is False


def test_worker_client_wait_does_not_skip_limited_event_page(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(worker_client, "WORKER_POLL_SECONDS", 0)
    monkeypatch.setattr(worker_client, "WORKER_WAIT_HEARTBEAT_SECONDS", 3600)
    monkeypatch.setattr(worker_client, "WORKER_EVENT_PAGE_LIMIT", 2)

    class Client(TdxWorkerClient):
        def __init__(self) -> None:
            super().__init__("http://worker.test")
            self.calls: list[int] = []

        def get_job(self, job_id: str, **kwargs: object) -> dict[str, object]:
            after = int(kwargs.get("after_event_index", -1))
            self.calls.append(after)
            all_events = [{"event_index": index, "stage": f"event_{index}"} for index in range(5)]
            events = [event for event in all_events if int(event["event_index"]) > after][:2]
            status = "succeeded" if after >= 4 else "running"
            return {
                "status": status,
                "events": events,
                "event_next_index": 5,
                "event_count": 5,
            }

    events: list[dict[str, object]] = []
    client = Client()
    result = client.wait("job1", progress_callback=events.append)

    assert result["status"] == "succeeded"
    assert [event["stage"] for event in events] == [f"event_{index}" for index in range(5)]
    assert client.calls == [-1, 1, 3, 4]


def test_worker_client_wait_retries_transient_poll_timeout(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(worker_client, "WORKER_POLL_SECONDS", 0)
    monkeypatch.setattr(worker_client, "WORKER_WAIT_HEARTBEAT_SECONDS", 3600)

    class Client(TdxWorkerClient):
        def __init__(self) -> None:
            super().__init__("http://worker.test")
            self.calls = 0

        def get_job(self, job_id: str, **_: object) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                raise worker_client.WorkerUnavailable("timed out")
            return {"status": "succeeded", "events": [], "event_next_index": 0, "event_count": 0}

    events: list[dict[str, object]] = []
    result = Client().wait("job1", progress_callback=events.append)

    assert result["status"] == "succeeded"
    assert [event["stage"] for event in events] == ["worker_poll_retry"]


def test_commit_worker_manifest_writes_shared_delta_part(tmp_path: Path) -> None:
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)
    manifest = {
        "parts": [
            {
                "name": part_path.name,
                "timeframe": "1d",
                "adjust": "qfq",
                "sha256": "",
            }
        ]
    }

    result = commit_worker_manifest(
        data_root=tmp_path / "data",
        manifest=manifest,
        part_loader=lambda name: part_dir / name,
    )

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert result.loc[0, "timeframe"] == "1d"
    assert not (tmp_path / "data" / "daily" / "qfq" / "000001.SZ.parquet").exists()
    assert not (tmp_path / "data" / "daily" / "qfq" / "000001.SZ.delta").exists()
    assert len(list((tmp_path / "data" / "daily" / "qfq" / "_delta_parts").glob("trade_month=*/*.parquet"))) == 1
    part_index = query_market_data_part_symbols(
        data_root=tmp_path / "data",
        symbols=("000001.SZ",),
        adjust="qfq",
        timeframes=("1d",),
    )
    assert len(part_index) == 1
    loaded = load_local_bars(
        data_root=tmp_path / "data",
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-01",
        end="2026-06-02",
    )
    assert len(loaded) == 2


def test_commit_worker_manifest_keeps_multi_symbol_worker_part_batched(tmp_path: Path) -> None:
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-01"]),
            "stock_code": ["000001.SZ", "000002.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)
    data_root = tmp_path / "data"

    result = commit_worker_manifest(
        data_root=data_root,
        manifest={"job_id": "job-batched", "parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    shared_parts = list((data_root / "daily" / "qfq" / "_delta_parts").glob("trade_month=*/*.parquet"))
    assert len(shared_parts) == 1
    assert not (data_root / "daily" / "qfq" / "000001.SZ.delta").exists()
    assert not (data_root / "daily" / "qfq" / "000002.SZ.delta").exists()
    assert sorted(result["symbol"].tolist()) == ["000001.SZ", "000002.SZ"]
    part_index = query_market_data_part_symbols(data_root=data_root, adjust="qfq", timeframes=("1d",))
    assert len(part_index) == 2
    assert part_index["part_id"].nunique() == 1


def test_coverage_refresh_keeps_shared_delta_part_data(tmp_path: Path) -> None:
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)
    data_root = tmp_path / "data"
    commit_worker_manifest(
        data_root=data_root,
        manifest={"job_id": "job-coverage", "parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    refreshed = refresh_coverage_runs(
        data_root=data_root,
        symbols=("000001.SZ",),
        adjust="qfq",
        timeframes=("1d",),
    )

    assert not refreshed.empty
    assert int(refreshed["row_count"].sum()) == 2
    assert int(refreshed["file_size_bytes"].max()) > 0


def test_strict_audit_reads_shared_delta_only_worker_data(tmp_path: Path) -> None:
    morning = pd.date_range("2026-06-12 09:35:00", "2026-06-12 11:30:00", freq="5min")
    afternoon = pd.date_range("2026-06-12 13:05:00", "2026-06-12 15:00:00", freq="5min")
    dates = morning.append(afternoon)
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-5m-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": dates,
            "stock_code": ["000001.SZ"] * len(dates),
            "open": [1.0] * len(dates),
            "high": [1.1] * len(dates),
            "low": [0.9] * len(dates),
            "close": [1.0] * len(dates),
            "volume": [100] * len(dates),
            "amount": [1000] * len(dates),
        }
    ).to_parquet(part_path, index=False)
    data_root = tmp_path / "data"
    commit_worker_manifest(
        data_root=data_root,
        manifest={"job_id": "job-strict-audit", "parts": [{"name": part_path.name, "timeframe": "5m", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    audit = audit_local_data(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-12",
        end="2026-06-12",
    )
    gaps = data_gap_episodes(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-12",
        end="2026-06-12",
    )

    row = audit.iloc[0]
    assert row["status"] == "ok"
    assert int(row["rows_in_window"]) == 48
    assert int(row["expected_rows"]) == 48
    assert int(row["missing_rows"]) == 0
    assert float(row["coverage_ratio"]) == 1.0
    assert gaps.empty


def test_inventory_handles_timezone_mixed_shared_delta_metadata(tmp_path: Path) -> None:
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01"]),
            "stock_code": ["000001.SZ"],
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.0],
            "volume": [100],
            "amount": [1000],
        }
    ).to_parquet(part_path, index=False)
    data_root = tmp_path / "data"
    base_path = data_root / "daily" / "qfq" / "000001.SZ.parquet"
    base_path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-31"]),
            "stock_code": ["000001.SZ"],
            "open": [0.9],
            "high": [1.0],
            "low": [0.8],
            "close": [0.95],
            "volume": [90],
            "amount": [900],
        }
    ).to_parquet(base_path, index=False)
    commit_worker_manifest(
        data_root=data_root,
        manifest={"job_id": "job-tz", "parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    inventory = inventory_local_data(data_root=data_root, timeframes=("1d",), adjust="qfq", symbols=("000001.SZ",))

    assert len(inventory) == 1
    assert inventory.loc[0, "status"] == "cached"


def test_commit_worker_manifest_emits_commit_progress(tmp_path: Path) -> None:
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-01"]),
            "stock_code": ["000001.SZ", "000002.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)
    events: list[dict[str, object]] = []

    commit_worker_manifest(
        data_root=tmp_path / "data",
        manifest={"parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
        progress_callback=events.append,
    )

    stages = [str(event.get("stage")) for event in events]
    assert "worker_commit_start" in stages
    assert "worker_commit_progress" in stages
    assert "worker_commit_coverage" in stages
    assert "worker_commit_done" in stages


def test_commit_worker_manifest_skips_full_coverage_refresh(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01"]),
            "stock_code": ["000001.SZ"],
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.0],
            "volume": [100],
            "amount": [1000],
        }
    ).to_parquet(part_path, index=False)

    def fail_full_refresh(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("worker commit should not refresh full-file coverage")

    monkeypatch.setattr("tdx_downloader.data.catalog.refresh_coverage_runs", fail_full_refresh)

    data_root = tmp_path / "data"
    result = commit_worker_manifest(
        data_root=data_root,
        manifest={"parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    assert result.loc[0, "symbol"] == "000001.SZ"
    coverage = query_coverage_runs(data_root=data_root, symbols=("000001.SZ",), adjust="qfq", timeframes=("1d",))
    assert not coverage.empty
    assert coverage.loc[0, "file_size_bytes"] == 0


def test_commit_worker_manifest_does_not_read_existing_base_parquet(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "data"
    base_root = data_root / "daily" / "qfq"
    base_root.mkdir(parents=True)
    base_path = base_root / "000001.SZ.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-31"]),
            "stock_code": ["000001.SZ"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [100],
            "amount": [1000],
        }
    ).to_parquet(base_path, index=False)
    before_mtime = base_path.stat().st_mtime_ns
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01"]),
            "stock_code": ["000001.SZ"],
            "open": [2.0],
            "high": [2.1],
            "low": [1.9],
            "close": [2.0],
            "volume": [200],
            "amount": [2000],
        }
    ).to_parquet(part_path, index=False)
    original_read_parquet = pd.read_parquet

    def guarded_read_parquet(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        if Path(path) == base_path:
            raise AssertionError("worker commit should not read existing base parquet")
        return original_read_parquet(path, *args, **kwargs)

    monkeypatch.setattr("tdx_downloader.data.storage.pd.read_parquet", guarded_read_parquet)
    result = commit_worker_manifest(
        data_root=data_root,
        manifest={"parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert base_path.stat().st_mtime_ns == before_mtime


def test_commit_worker_manifest_skips_delta_overlap_coverage_lookup(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)

    def fail_coverage_lookup(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("worker commit should not query coverage just to estimate overlap")

    monkeypatch.setattr("tdx_downloader.data.storage.query_coverage_runs", fail_coverage_lookup)

    result = commit_worker_manifest(
        data_root=tmp_path / "data",
        manifest={"parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    assert int(result.loc[0, "new_rows"]) == 2


def test_commit_worker_manifest_registers_delta_part_index(tmp_path: Path) -> None:
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)
    data_root = tmp_path / "data"

    commit_worker_manifest(
        data_root=data_root,
        manifest={"job_id": "job-index", "parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    catalog_path = data_root / "metadata" / "market_data_catalog.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        part_count = connection.execute("SELECT COUNT(*) FROM market_data_parts").fetchone()[0]
        symbol_count = connection.execute("SELECT COUNT(*) FROM market_data_part_symbols").fetchone()[0]

    assert part_count == 1
    assert symbol_count == 1


def test_commit_worker_manifest_uses_fast_coverage_insert(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-5m-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01 09:35:00", "2026-06-01 09:40:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)

    def fail_existing_window_lookup(*_: object, **__: object) -> dict[object, object]:
        raise AssertionError("worker commit coverage should not query existing windows")

    monkeypatch.setattr("tdx_downloader.data.catalog._query_coverage_records_for_windows", fail_existing_window_lookup)

    result = commit_worker_manifest(
        data_root=tmp_path / "data",
        manifest={"job_id": "job-fast-coverage", "parts": [{"name": part_path.name, "timeframe": "5m", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    assert int(result.loc[0, "new_rows"]) == 2


def test_commit_worker_manifest_direct_import_reuses_manifest_summary(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-01"]),
            "stock_code": ["000001.SZ", "000002.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)

    def fail_identity_groupby(*_: object, **__: object) -> list[dict[str, object]]:
        raise AssertionError("direct import should reuse manifest summary for part-symbol rows")

    monkeypatch.setattr("tdx_downloader.data.tdx_worker._part_symbol_rows_from_identity", fail_identity_groupby)

    result = commit_worker_manifest(
        data_root=tmp_path / "data",
        manifest={
            "job_id": "job-summary",
            "parts": [
                {
                    "name": part_path.name,
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "sha256": "",
                    "summary_rows": [
                        {
                            "symbol": "000001.SZ",
                            "status": "success",
                            "rows": 1,
                            "new_rows": 1,
                            "path": str(part_path),
                            "start": "2026-06-01",
                            "end": "2026-06-01",
                            "message": "from manifest",
                        },
                        {
                            "symbol": "000002.SZ",
                            "status": "success",
                            "rows": 1,
                            "new_rows": 1,
                            "path": str(part_path),
                            "start": "2026-06-01",
                            "end": "2026-06-01",
                            "message": "from manifest",
                        },
                    ],
                }
            ],
        },
        part_loader=lambda name: part_dir / name,
    )

    assert sorted(result["symbol"].tolist()) == ["000001.SZ", "000002.SZ"]


def test_commit_worker_manifest_direct_import_accepts_multi_month_part(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-5m-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-27 15:00:00", "2026-03-02 09:35:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    ).to_parquet(part_path, index=False)

    def fail_shared_import(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("multi-month worker part should still use direct import")

    monkeypatch.setattr("tdx_downloader.data.tdx_worker.append_shared_delta_bars", fail_shared_import)

    data_root = tmp_path / "data"
    result = commit_worker_manifest(
        data_root=data_root,
        manifest={"job_id": "job-multi-month", "parts": [{"name": part_path.name, "timeframe": "5m", "adjust": "qfq", "sha256": ""}]},
        part_loader=lambda name: part_dir / name,
    )

    assert int(result.loc[0, "new_rows"]) == 2
    assert len(list((data_root / "5m" / "qfq" / "_delta_parts" / "trade_month=multi").glob("*.parquet"))) == 1
    catalog_path = data_root / "metadata" / "market_data_catalog.sqlite"
    with sqlite3.connect(catalog_path) as connection:
        trade_month = connection.execute("SELECT trade_month FROM market_data_parts").fetchone()[0]
    assert trade_month == "multi"


def test_commit_worker_manifest_invalidates_fast_plan_cache(tmp_path: Path) -> None:
    clear_fast_plan_cache()
    data_root = tmp_path / "data"
    service = DataManagementService(data_root, adjust="qfq")
    config = DataDownloadConfig(
        symbols=("000001.SZ",),
        timeframes=("5m",),
        start="2026-06-12",
        end="2026-06-12",
    )
    before = service.preview_download_plan(config)
    assert set(before["action"].astype(str)) == {"fetch"}

    morning = pd.date_range("2026-06-12 09:35:00", "2026-06-12 11:30:00", freq="5min")
    afternoon = pd.date_range("2026-06-12 13:05:00", "2026-06-12 15:00:00", freq="5min")
    dates = morning.append(afternoon)
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-5m-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": dates,
            "stock_code": ["000001.SZ"] * len(dates),
            "open": [1.0] * len(dates),
            "high": [1.1] * len(dates),
            "low": [0.9] * len(dates),
            "close": [1.0] * len(dates),
            "volume": [100] * len(dates),
            "amount": [1000] * len(dates),
        }
    ).to_parquet(part_path, index=False)

    commit_worker_manifest(
        data_root=data_root,
        manifest={
            "job_id": "job-cache-clear",
            "parts": [{"name": part_path.name, "timeframe": "5m", "adjust": "qfq", "sha256": ""}],
        },
        part_loader=lambda name: part_dir / name,
    )

    after = service.preview_download_plan(config)
    five_minute = after.loc[after["timeframe"].astype(str).eq("5m")].iloc[0]
    assert five_minute["action"] == "cached"
    assert int(five_minute["missing_rows"]) == 0


def test_commit_worker_manifest_direct_import_requires_canonical_schema(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    part_dir = tmp_path / "parts"
    part_dir.mkdir()
    part_path = part_dir / "001-1d-qfq-part-000.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01"]),
            "stock_code": ["000001.SZ"],
        }
    ).to_parquet(part_path, index=False)

    def fail_shared_import(*_: object, **__: object) -> pd.DataFrame:
        raise RuntimeError("fallback path reached")

    monkeypatch.setattr("tdx_downloader.data.tdx_worker.append_shared_delta_bars", fail_shared_import)

    try:
        commit_worker_manifest(
            data_root=tmp_path / "data",
            manifest={"job_id": "bad-schema", "parts": [{"name": part_path.name, "timeframe": "1d", "adjust": "qfq", "sha256": ""}]},
            part_loader=lambda name: part_dir / name,
        )
    except RuntimeError as exc:
        assert "fallback path reached" in str(exc)
    else:
        raise AssertionError("non-canonical worker part must not be directly registered")


def test_worker_part_summary_reuses_in_memory_summary(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    )
    part = _write_part(store=store, job_id="job1", timeframe="1d", adjust="qfq", bars=bars, name_prefix="001")

    monkeypatch.setattr(
        "tdx_downloader.data.tdx_worker.pd.read_parquet",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("summary should not reread part parquet")),
    )
    summary = _part_summary_rows(part)

    assert summary.loc[0, "symbol"] == "000001.SZ"
    assert summary.loc[0, "rows"] == 2


def test_commit_worker_manifest_reuses_manifest_coverage_without_reading_part(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.0, 2.0],
            "volume": [100, 200],
            "amount": [1000, 2000],
        }
    )
    part = _write_part(store=store, job_id="job-coverage-manifest", timeframe="1d", adjust="qfq", bars=bars, name_prefix="001")

    monkeypatch.setattr(
        "tdx_downloader.data.tdx_worker.pd.read_parquet",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("commit should reuse manifest coverage rows")),
    )
    result = commit_worker_manifest(
        data_root=tmp_path / "data",
        manifest={"job_id": "job-coverage-manifest", "parts": [part]},
        part_loader=lambda name: store.part_file("job-coverage-manifest", name),
    )

    assert int(result.loc[0, "new_rows"]) == 2
    coverage = query_coverage_runs(data_root=tmp_path / "data", symbols=("000001.SZ",), adjust="qfq", timeframes=("1d",))
    assert int(coverage["row_count"].sum()) == 2


def test_fetch_windows_writes_each_group_as_part(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    service = DataManagementService(tmp_path / "data", adjust="qfq")
    calls: list[tuple[tuple[str, ...], str, str]] = []
    events: list[dict[str, object]] = []

    def fake_fetch_tdx_bars(**kwargs: object) -> pd.DataFrame:
        symbols = tuple(str(item) for item in kwargs["symbols"])  # type: ignore[index]
        start = str(kwargs["start"])
        end = str(kwargs["end"])
        calls.append((symbols, start, end))
        progress_callback = kwargs.get("progress_callback")
        if callable(progress_callback):
            progress_callback({"stage": "tdx_batch_start", "batch_index": 1, "batch_count": 1})
        return pd.DataFrame(
            {
                "date": pd.to_datetime([start]),
                "stock_code": [symbols[0]],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.0],
                "volume": [100],
                "amount": [1000],
            }
        )

    monkeypatch.setattr("tdx_downloader.data.tdx.fetch_tdx_bars", fake_fetch_tdx_bars)
    table, parts = _fetch_windows_to_manifest(
        job_id="job1",
        store=store,
        service=service,
        payload={
            "groups_by_timeframe": {
                "5m": [
                    {"symbols": ["000001.SZ"], "start": "2026-06-01 09:35:00", "end": "2026-06-01 09:35:00"},
                    {"symbols": ["000002.SZ"], "start": "2026-06-01 09:40:00", "end": "2026-06-01 09:40:00"},
                ]
            }
        },
        config=DataDownloadConfig(
            symbols=("000001.SZ", "000002.SZ"),
            timeframes=("5m",),
            start="2026-06-01",
            end="2026-06-01",
        ),
        progress_callback=events.append,
    )

    assert calls == [
        (("000001.SZ",), "2026-06-01 09:35:00", "2026-06-01 09:35:00"),
        (("000002.SZ",), "2026-06-01 09:40:00", "2026-06-01 09:40:00"),
    ]
    assert [part["name"] for part in parts] == ["001-5m-qfq-part-000.parquet", "002-5m-qfq-part-000.parquet"]
    assert set(table["stock_code"]) == {"000001.SZ", "000002.SZ"}
    assert table["rows_written"].sum() == 2
    tdx_event = next(event for event in events if event.get("stage") == "tdx_batch_start")
    assert tdx_event["window_step_index"] == 1
    assert tdx_event["window_step_count"] == 2
    assert tdx_event["window_start"] == "2026-06-01 09:35:00"


def test_fetch_windows_stops_after_initial_empty_tdx_windows(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    service = DataManagementService(tmp_path / "data", adjust="qfq")
    calls = 0
    events: list[dict[str, object]] = []

    def fake_fetch_tdx_bars(**_: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return empty_bars()

    monkeypatch.setattr("tdx_downloader.data.tdx.fetch_tdx_bars", fake_fetch_tdx_bars)

    with pytest.raises(RuntimeError, match="TDX 连续返回 0 行"):
        _fetch_windows_to_manifest(
            job_id="job-empty",
            store=store,
            service=service,
            payload={
                "groups_by_timeframe": {
                    "1d": [
                        {"symbols": ["000001.SZ"], "start": "2026-06-15", "end": "2026-06-15"},
                        {"symbols": ["000002.SZ"], "start": "2026-06-15", "end": "2026-06-15"},
                        {"symbols": ["000003.SZ"], "start": "2026-06-15", "end": "2026-06-15"},
                        {"symbols": ["000004.SZ"], "start": "2026-06-15", "end": "2026-06-15"},
                    ]
                }
            },
            config=DataDownloadConfig(
                symbols=("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"),
                timeframes=("1d",),
                start="2026-06-15",
                end="2026-06-15",
            ),
            progress_callback=events.append,
        )

    assert calls == 3
    assert [event.get("stage") for event in events].count("tdx_no_rows") == 3


def test_fetch_windows_honors_cancel_between_groups(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    service = DataManagementService(tmp_path / "data", adjust="qfq")
    calls = 0

    def fake_fetch_tdx_bars(**kwargs: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        symbols = tuple(str(item) for item in kwargs["symbols"])  # type: ignore[index]
        return pd.DataFrame(
            {
                "date": pd.to_datetime([kwargs["start"]]),
                "stock_code": [symbols[0]],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.0],
                "volume": [100],
                "amount": [1000],
            }
        )

    def cancel_after_first_group() -> None:
        if calls >= 1:
            raise RuntimeError("cancelled")

    monkeypatch.setattr("tdx_downloader.data.tdx.fetch_tdx_bars", fake_fetch_tdx_bars)

    try:
        _fetch_windows_to_manifest(
            job_id="job-cancel",
            store=store,
            service=service,
            payload={
                "groups_by_timeframe": {
                    "5m": [
                        {"symbols": ["000001.SZ"], "start": "2026-06-01 09:35:00", "end": "2026-06-01 09:35:00"},
                        {"symbols": ["000002.SZ"], "start": "2026-06-01 09:40:00", "end": "2026-06-01 09:40:00"},
                    ]
                }
            },
            config=DataDownloadConfig(
                symbols=("000001.SZ", "000002.SZ"),
                timeframes=("5m",),
                start="2026-06-01",
                end="2026-06-01",
            ),
            progress_callback=lambda event: None,
            cancel_check=cancel_after_first_group,
        )
    except RuntimeError as exc:
        assert str(exc) == "cancelled"
    else:
        raise AssertionError("cancel_check should stop the worker before the second group")

    assert calls == 1


def test_worker_job_cancelled_status_when_cancel_requested(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    store = TdxWorkerStore(scratch_root=tmp_path / "jobs")
    job_id = "job-cancel-status"

    def fake_fetch_tdx_bars(**_: object) -> pd.DataFrame:
        store.cancel_job(job_id)
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01 09:35:00"]),
                "stock_code": ["000001.SZ"],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.0],
                "volume": [100],
                "amount": [1000],
            }
        )

    monkeypatch.setattr("tdx_downloader.data.tdx.fetch_tdx_bars", fake_fetch_tdx_bars)
    store._jobs[job_id] = WorkerJob(
        id=job_id,
        payload={
            "mode": "fetch-windows",
            "symbols": ["000001.SZ"],
            "timeframes": ["5m"],
            "start": "2026-06-01",
            "end": "2026-06-01",
            "adjust": "qfq",
            "data_root": str(tmp_path / "data"),
            "groups_by_timeframe": {
                "5m": [
                    {"symbols": ["000001.SZ"], "start": "2026-06-01 09:35:00", "end": "2026-06-01 09:35:00"},
                ]
            },
        },
    )
    store._run_job(job_id)

    cancelled = store.get_job(job_id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.error == "Worker 任务已终止。"
