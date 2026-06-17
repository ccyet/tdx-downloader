from __future__ import annotations

from pathlib import Path

import pandas as pd

from tdx_downloader.data import parallels_runtime
from tdx_downloader.data.catalog import upsert_unresolved_gaps
from tdx_downloader.data.manager import DataDownloadConfig, DataDownloadResult
from tdx_downloader.data.parallels_runtime import (
    download_with_parallels_cli,
    download_with_runtime,
    etf_tracking_with_runtime,
    parse_cli_table,
    parallels_doctor_command,
    parallels_etf_tracking_command,
    parallels_prepare_command,
    shortcut_symbol_groups_with_runtime,
    symbol_metadata_with_runtime,
)
from tdx_downloader.data.storage import write_local_bars
from tdx_downloader.data.tdx_worker_client import WorkerUnavailable


def test_parse_cli_table_prefers_json_records_with_unc_paths() -> None:
    stdout = (
        "TQ数据接口初始化成功\n"
        '[{"stock_code":"510300.SH","timeframe":"1d","action":"cached",'
        '"rows_written":0,"path":"\\\\\\\\psf\\\\ccOUT 1\\\\tdx-data\\\\daily\\\\qfq\\\\510300.SH.parquet",'
        '"message":"覆盖和质量检查通过。"}]\n'
        "TQ数据连接已关闭\n"
    )

    frame = parse_cli_table(stdout)

    assert frame.loc[0, "stock_code"] == "510300.SH"
    assert frame.loc[0, "action"] == "cached"
    assert frame.loc[0, "rows_written"] == 0
    assert frame.loc[0, "path"] == r"\\psf\ccOUT 1\tdx-data\daily\qfq\510300.SH.parquet"


def test_runtime_skips_parallels_when_smart_plan_is_fully_cached(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class LocalCachedService:
        data_root = Path("/Volumes/ccOUT 1/tdx-data/daily")
        adjust = "qfq"

        def download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            raise AssertionError("Parallels preflight must use fast preview, not strict download_plan")

        def preview_download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            return pd.DataFrame({"stock_code": ["000001.SZ"], "action": ["cached"]})

        def download(
            self,
            config: DataDownloadConfig,
            *,
            mode: str,
            progress_callback,
        ) -> DataDownloadResult:
            progress_callback({"stage": "fetch_skipped", "timeframe": "1d", "reason": "local_ok"})
            return DataDownloadResult(
                table=pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["1d"], "action": ["cached"]}),
                summary={"row_count": 1.0, "fetched_count": 0.0, "cached_count": 1.0},
            )

    def fail_parallels(*_: object, **__: object) -> DataDownloadResult:
        raise AssertionError("cached smart plan must not connect to Parallels/TDX")

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "download_with_parallels_cli", fail_parallels)
    events: list[dict[str, object]] = []

    result = download_with_runtime(
        LocalCachedService(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
        mode="smart",
        progress_callback=events.append,
    )

    assert result.summary["fetched_count"] == 0.0
    assert [event["stage"] for event in events] == [
        "preflight_plan_start",
        "preflight_plan_done",
        "tdx_connection_skipped",
        "fetch_skipped",
    ]


def test_runtime_skips_parallels_when_smart_plan_only_has_unresolved_provider_gaps(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class LocalUnresolvedService:
        data_root = Path("/Volumes/ccOUT 1/tdx-data")
        adjust = "qfq"

        def download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            raise AssertionError("Parallels preflight must use fast preview, not strict download_plan")

        def preview_download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            return pd.DataFrame({"stock_code": ["000001.SZ"], "action": ["unresolved"]})

        def download(
            self,
            config: DataDownloadConfig,
            *,
            mode: str,
            progress_callback,
        ) -> DataDownloadResult:
            return DataDownloadResult(
                table=pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["1d"], "action": ["unresolved"]}),
                summary={"row_count": 1.0, "fetched_count": 0.0, "cached_count": 0.0},
            )

    def fail_parallels(*_: object, **__: object) -> DataDownloadResult:
        raise AssertionError("known provider gaps must not reconnect to Parallels/TDX")

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "download_with_parallels_cli", fail_parallels)
    events: list[dict[str, object]] = []

    result = download_with_runtime(
        LocalUnresolvedService(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
        mode="smart",
        progress_callback=events.append,
    )

    assert result.summary["fetched_count"] == 0.0
    assert result.table.loc[0, "action"] == "unresolved"
    preflight = next(event for event in events if event["stage"] == "preflight_plan_done")
    assert preflight["unresolved_count"] == 1


def test_runtime_uses_fast_preview_before_parallels_fetch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data")
        adjust = "qfq"

        def download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            raise AssertionError("Parallels preflight must not run strict plan")

        def preview_download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            return pd.DataFrame({"stock_code": ["000001.SZ"], "action": ["fetch"]})

    def fake_parallels(
        service: Service,
        config: DataDownloadConfig,
        *,
        mode: str,
        progress_callback=None,
        cancel_check=None,
    ) -> DataDownloadResult:
        progress_callback({"stage": "parallels_command_start", "symbol_count": 1})
        return DataDownloadResult(
            table=pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["1d"], "action": ["fetched"]}),
            summary={"row_count": 1.0, "fetched_count": 1.0, "cached_count": 0.0},
        )

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "download_with_parallels_cli", fake_parallels)
    events: list[dict[str, object]] = []

    result = download_with_runtime(
        Service(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
        mode="smart",
        progress_callback=events.append,
    )

    assert result.summary["fetched_count"] == 1.0
    assert [event["stage"] for event in events] == [
        "preflight_plan_start",
        "preflight_plan_done",
        "parallels_command_start",
    ]


def test_runtime_keeps_local_derivation_action_in_runtime_path(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data")
        adjust = "qfq"

        def download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            raise AssertionError("Parallels preflight must not run strict plan")

        def preview_download_plan(self, config: DataDownloadConfig) -> pd.DataFrame:
            return pd.DataFrame({"stock_code": ["000001.SZ"], "action": ["derive"]})

        def download(
            self,
            config: DataDownloadConfig,
            *,
            mode: str,
            progress_callback,
        ) -> DataDownloadResult:
            raise AssertionError("derive preview must not be treated as fully cached")

    def fake_parallels(
        service: Service,
        config: DataDownloadConfig,
        *,
        mode: str,
        progress_callback=None,
        cancel_check=None,
    ) -> DataDownloadResult:
        progress_callback({"stage": "local_derive_start"})
        return DataDownloadResult(
            table=pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["15m"], "action": ["fetched"]}),
            summary={"row_count": 1.0, "fetched_count": 1.0, "cached_count": 0.0},
        )

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "download_with_parallels_cli", fake_parallels)
    events: list[dict[str, object]] = []

    result = download_with_runtime(
        Service(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("000001.SZ",), timeframes=("5m", "15m"), start="2026-06-01", end="2026-06-02"),
        mode="smart",
        progress_callback=events.append,
    )

    assert result.summary["fetched_count"] == 1.0
    assert [event["stage"] for event in events] == [
        "preflight_plan_start",
        "preflight_plan_done",
        "local_derive_start",
    ]
    assert events[1]["derive_count"] == 1


def test_parallels_commands_request_json_output() -> None:
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data/daily")
        adjust = "qfq"

    config = DataDownloadConfig(
        symbols=("000001.SZ",),
        timeframes=("1d",),
        start="2026-06-01",
        end="2026-06-02",
        tqcenter_path="/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user",
    )

    prepare = parallels_prepare_command(Service(), config)  # type: ignore[arg-type]
    doctor = parallels_doctor_command(Service(), config)  # type: ignore[arg-type]

    assert "--output" in prepare
    assert prepare[prepare.index("--output") + 1] == "json"
    assert doctor[-2:] == ["--output", "json"]
    assert "--data-root" not in doctor


def test_parallels_smart_fallback_uses_fetch_not_prepare_data(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = tmp_path / "market"
        adjust = "qfq"

    commands: list[list[str]] = []

    monkeypatch.setenv(parallels_runtime.WORKER_CLI_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(parallels_runtime, "download_with_worker", lambda *args, **kwargs: (_ for _ in ()).throw(WorkerUnavailable("off")))

    def skip_connection_check(*_: object, **__: object) -> pd.DataFrame:
        return pd.DataFrame({"status": ["ok"]})

    def fake_run_table(command: list[str], *, cancel_check=None, progress_callback=None) -> pd.DataFrame:  # type: ignore[no-untyped-def]
        commands.append(command)
        assert "prepare-data" not in command
        assert "fetch" in command
        symbols = command[command.index("--symbols") + 1].split(",")
        timeframe = command[command.index("--timeframe") + 1]
        start = command[command.index("--start") + 1]
        end = command[command.index("--end") + 1]
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime([start] * len(symbols)),
                "stock_code": symbols,
                "open": [10.0] * len(symbols),
                "high": [11.0] * len(symbols),
                "low": [9.0] * len(symbols),
                "close": [10.5] * len(symbols),
                "volume": [1000.0] * len(symbols),
                "amount": [10500.0] * len(symbols),
            }
        )
        written = write_local_bars(data_root=Service.data_root, timeframe=timeframe, adjust="qfq", bars=bars)
        return written.rename(columns={"symbol": "stock_code", "rows": "rows_written"})

    monkeypatch.setattr(parallels_runtime, "verify_parallels_tdx_connection", skip_connection_check)
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_table", fake_run_table)
    symbols = tuple(f"{index:06d}.SZ" for index in range(3))

    result = download_with_parallels_cli(
        Service(),  # type: ignore[arg-type]
        DataDownloadConfig(
            symbols=symbols,
            timeframes=("1d",),
            start="2026-06-01",
            end="2026-06-02",
            batch_size=100,
        ),
        mode="smart",
    )

    assert len(commands) == 1
    assert commands[0][2:6] == ["tdx_downloader.cli", "fetch", "--runtime", "parallels"]
    assert len(commands[0][commands[0].index("--symbols") + 1].split(",")) == 3
    assert commands[0][commands[0].index("--batch-size") + 1] == "100"
    assert len(result.table) == 3
    assert result.summary["fetched_count"] == 3.0


def test_parallels_smart_fallback_fetches_only_gap_windows(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = tmp_path / "market"
        adjust = "qfq"

    existing = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-09"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 12.0],
            "high": [11.0, 13.0],
            "low": [9.0, 11.0],
            "close": [10.5, 12.5],
            "volume": [1000.0, 1200.0],
            "amount": [10500.0, 15000.0],
        }
    )
    write_local_bars(data_root=Service.data_root, timeframe="1d", adjust="qfq", bars=existing)
    commands: list[list[str]] = []

    monkeypatch.setenv(parallels_runtime.WORKER_CLI_FALLBACK_ENV_VAR, "1")
    monkeypatch.setattr(parallels_runtime, "download_with_worker", lambda *args, **kwargs: (_ for _ in ()).throw(WorkerUnavailable("off")))

    def skip_connection_check(*_: object, **__: object) -> pd.DataFrame:
        return pd.DataFrame({"status": ["ok"]})

    def fake_run_table(command: list[str], *, cancel_check=None, progress_callback=None) -> pd.DataFrame:  # type: ignore[no-untyped-def]
        commands.append(command)
        symbols = command[command.index("--symbols") + 1].split(",")
        start = command[command.index("--start") + 1]
        assert start == command[command.index("--end") + 1] == "2026-06-08"
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime([start] * len(symbols)),
                "stock_code": symbols,
                "open": [11.0] * len(symbols),
                "high": [12.0] * len(symbols),
                "low": [10.0] * len(symbols),
                "close": [11.5] * len(symbols),
                "volume": [1100.0] * len(symbols),
                "amount": [12650.0] * len(symbols),
            }
        )
        written = write_local_bars(data_root=Service.data_root, timeframe="1d", adjust="qfq", bars=bars)
        return written.rename(columns={"symbol": "stock_code", "rows": "rows_written"})

    monkeypatch.setattr(parallels_runtime, "verify_parallels_tdx_connection", skip_connection_check)
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_table", fake_run_table)
    events: list[dict[str, object]] = []

    result = download_with_parallels_cli(
        Service(),  # type: ignore[arg-type]
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-09",
            batch_size=1,
            strict_after_update=True,
        ),
        mode="smart",
        progress_callback=events.append,
    )

    assert len(commands) == 1
    assert result.summary["fetched_count"] == 1.0
    assert result.table.loc[0, "missing_rows"] == 0
    assert "parallels_fetch_window_start" in [event["stage"] for event in events]


def test_parallels_worker_unavailable_does_not_fallback_by_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data")
        adjust = "qfq"

    monkeypatch.delenv(parallels_runtime.WORKER_CLI_FALLBACK_ENV_VAR, raising=False)
    monkeypatch.setattr(
        parallels_runtime,
        "download_with_worker",
        lambda *args, **kwargs: (_ for _ in ()).throw(WorkerUnavailable("off")),
    )
    monkeypatch.setattr(
        parallels_runtime,
        "run_parallels_cli_table",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CLI fallback should be disabled")),
    )

    try:
        download_with_parallels_cli(
            Service(),  # type: ignore[arg-type]
            DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
            mode="smart",
        )
    except RuntimeError as exc:
        assert "已禁止自动回退 prlctl exec" in str(exc)
    else:
        raise AssertionError("Worker failure should be explicit by default")


def test_parallels_worker_job_failure_is_not_reported_as_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data")
        adjust = "qfq"

    monkeypatch.delenv(parallels_runtime.WORKER_CLI_FALLBACK_ENV_VAR, raising=False)
    monkeypatch.setattr(
        parallels_runtime,
        "download_with_worker",
        lambda *args, **kwargs: (_ for _ in ()).throw(parallels_runtime.WorkerJobFailed("TDX K线缓存刷新失败：接口无返回")),
    )

    try:
        download_with_parallels_cli(
            Service(),  # type: ignore[arg-type]
            DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
            mode="smart",
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "Windows Worker 任务失败" in message
        assert "Windows Worker 不可用" not in message
    else:
        raise AssertionError("Worker job failure should be reported as job failure")


def test_parallels_download_uses_worker_before_cli(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/Volumes/ccOUT 1/tdx-data")
        adjust = "qfq"

    def fake_worker(service, config, *, mode, progress_callback=None, cancel_check=None):  # type: ignore[no-untyped-def]
        progress_callback({"stage": "worker_job_done", "message": "ok"})
        return DataDownloadResult(
            table=pd.DataFrame({"stock_code": ["000001.SZ"], "timeframe": ["1d"], "action": ["fetched"]}),
            summary={"row_count": 1.0, "fetched_count": 1.0, "cached_count": 0.0},
        )

    monkeypatch.setattr(parallels_runtime, "download_with_worker", fake_worker)
    monkeypatch.setattr(
        parallels_runtime,
        "run_parallels_cli_table",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CLI fallback should not run")),
    )
    events: list[dict[str, object]] = []

    result = download_with_parallels_cli(
        Service(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("000001.SZ",), timeframes=("1d",), start="2026-06-01", end="2026-06-02"),
        mode="smart",
        progress_callback=events.append,
    )

    assert result.summary["fetched_count"] == 1.0
    assert [event["stage"] for event in events] == ["worker_job_done"]


def test_worker_smart_payload_uses_catalog_boundary_when_minute_coverage_missing(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 14:50:00", "2026-06-09 14:55:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000.0, 1100.0],
            "amount": [10100.0, 11220.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars, refresh_coverage=False)
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.3],
                "low": [9.9],
                "close": [10.2],
                "volume": [2100.0],
                "amount": [21320.0],
            }
        ),
        refresh_coverage=True,
    )
    service = parallels_runtime.DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d", "5m"), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)
    events: list[dict[str, object]] = []

    payload, before_audits = parallels_runtime._worker_smart_payload(
        service,
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-09 14:50:00",
            end="2026-06-09 15:00:00",
        ),
        progress_callback=events.append,
    )

    assert payload["groups_by_timeframe"] == {
        "5m": [{"symbols": ["000001.SZ"], "start": "2026-06-09 15:00:00", "end": "2026-06-09 15:05:00"}]
    }
    assert before_audits["5m"].loc[0, "missing_rows"] == 1
    assert "coverage_bootstrap_start" in [str(event.get("stage")) for event in events]
    assert "coverage_bootstrap_done" in [str(event.get("stage")) for event in events]


def test_worker_smart_payload_does_not_fetch_implicit_daily_for_minute_request(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:50:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
                "amount": [10100.0],
            }
        ),
        refresh_coverage=False,
    )
    service = parallels_runtime.DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("5m",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)

    payload, before_audits = parallels_runtime._worker_smart_payload(
        service,
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-09 14:50:00",
            end="2026-06-09 15:00:00",
        ),
    )

    assert "1d" not in payload["groups_by_timeframe"]
    assert "1d" not in before_audits
    assert list(payload["groups_by_timeframe"]) == ["5m"]


def test_worker_smart_payload_retries_completed_daily_provider_no_data(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-13"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
                "amount": [10100.0],
            }
        ),
        refresh_coverage=True,
    )
    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-15"),
                    "end_at": pd.Timestamp("2026-06-15"),
                    "missing_rows": 1,
                    "status": "provider_no_data",
                    "last_fetch_rows": 0,
                    "message": "provider returned no data",
                }
            ]
        ),
    )
    monkeypatch.setattr("tdx_downloader.data.repository.last_completed_trade_date", lambda **_: "2026-06-15")

    payload, before_audits = parallels_runtime._worker_smart_payload(
        parallels_runtime.DataManagementService(data_root, adjust="qfq"),
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-06-13",
            end="2026-06-15",
        ),
    )

    assert payload["groups_by_timeframe"] == {
        "1d": [{"symbols": ["000001.SZ"], "start": "2026-06-15", "end": "2026-06-15"}]
    }
    assert before_audits["1d"].loc[0, "missing_rows"] == 1


def test_worker_smart_payload_derives_high_timeframes_without_worker_fetch_when_5m_cached(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.3],
                "low": [9.9],
                "close": [10.2],
                "volume": [2100.0],
                "amount": [21320.0],
            }
        ),
    )
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.date_range("2026-06-09 09:35:00", "2026-06-09 10:30:00", freq="5min"),
                "stock_code": ["000001.SZ"] * 12,
                "open": list(range(10, 22)),
                "high": list(range(11, 23)),
                "low": list(range(9, 21)),
                "close": list(range(10, 22)),
                "volume": [100.0] * 12,
                "amount": [1000.0] * 12,
            }
        ),
    )
    service = parallels_runtime.DataManagementService(data_root, adjust="qfq")
    payload, before_audits = parallels_runtime._worker_smart_payload(
        service,
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m", "15m", "30m", "60m"),
            start="2026-06-09 09:35:00",
            end="2026-06-09 10:30:00",
        ),
    )

    assert payload["groups_by_timeframe"] == {}
    assert payload["derive_targets_by_timeframe"] == {
        "15m": ["000001.SZ"],
        "30m": ["000001.SZ"],
        "60m": ["000001.SZ"],
    }

    committed = parallels_runtime._derive_worker_targets_after_commit(
        service=service,
        config=DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m", "15m", "30m", "60m"),
            start="2026-06-09 09:35:00",
            end="2026-06-09 10:30:00",
        ),
        committed=pd.DataFrame(),
        derive_targets_by_timeframe=payload["derive_targets_by_timeframe"],
    )

    assert set(committed["timeframe"]) == {"15m", "30m", "60m"}
    assert before_audits["5m"].loc[0, "status"] == "ok"
    assert (data_root / "15m" / "qfq" / "000001.SZ.parquet").exists()


def test_worker_download_skips_health_check_for_local_only_derivation(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.3],
                "low": [9.9],
                "close": [10.2],
                "volume": [2100.0],
                "amount": [21320.0],
            }
        ),
    )
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.date_range("2026-06-09 09:35:00", "2026-06-09 10:30:00", freq="5min"),
                "stock_code": ["000001.SZ"] * 12,
                "open": list(range(10, 22)),
                "high": list(range(11, 23)),
                "low": list(range(9, 21)),
                "close": list(range(10, 22)),
                "volume": [100.0] * 12,
                "amount": [1000.0] * 12,
            }
        ),
    )

    def fail_health(self: object) -> dict[str, object]:
        raise AssertionError("local-only derivation should not check or start Windows Worker")

    monkeypatch.setattr(parallels_runtime.TdxWorkerClient, "health", fail_health)

    result = parallels_runtime.download_with_worker(
        parallels_runtime.DataManagementService(data_root, adjust="qfq"),
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m", "15m"),
            start="2026-06-09 09:35:00",
            end="2026-06-09 10:30:00",
            strict_after_update=False,
        ),
        mode="smart",
    )

    rows = result.table.set_index("timeframe")
    assert rows.loc["5m", "action"] == "cached"
    assert rows.loc["15m", "action"] == "fetched"


def test_worker_prepare_table_marks_zero_row_request_as_fetched(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    before = pd.DataFrame(
        {
            "stock_code": ["000668.SZ"],
            "timeframe": ["1d"],
            "adjust": ["qfq"],
            "status": ["coverage_gap"],
            "exists": [True],
            "rows_total": [21],
            "rows_in_window": [21],
            "expected_rows": [22],
            "coverage_ratio": [0.5],
            "missing_rows": [1],
            "max_missing_gap_minutes": [1440],
            "first_missing_at": [pd.Timestamp("2026-06-02")],
            "last_missing_at": [pd.Timestamp("2026-06-02")],
            "max_missing_gap_start_at": [pd.Timestamp("2026-06-02")],
            "max_missing_gap_end_at": [pd.Timestamp("2026-06-02")],
            "start": [pd.Timestamp("2026-05-14")],
            "end": [pd.Timestamp("2026-06-13")],
            "requested_start": [pd.Timestamp("2026-05-14")],
            "requested_end": [pd.Timestamp("2026-06-13")],
            "invalid_date_rows": [0],
            "invalid_symbol_rows": [0],
            "duplicate_rows": [0],
            "null_ohlc_rows": [0],
            "non_positive_price_rows": [0],
            "inconsistent_ohlc_rows": [0],
            "null_volume_amount_rows": [0],
            "zero_volume_amount_rows": [0],
            "negative_volume_amount_rows": [0],
            "missing_columns": [""],
            "path": [str(tmp_path / "daily" / "qfq" / "000668.SZ.parquet")],
            "message": ["missing"],
        }
    )
    recorded: list[dict[str, object]] = []

    def fake_post_update_audit(**_: object) -> pd.DataFrame:
        return before

    def fake_record_unresolved(**kwargs: object) -> pd.DataFrame:
        recorded.append(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(parallels_runtime, "_fast_expected_sessions_by_symbol", lambda **_: {})
    monkeypatch.setattr(parallels_runtime, "_post_update_audit", fake_post_update_audit)
    monkeypatch.setattr(parallels_runtime, "_record_unresolved_gaps_after_fetch", fake_record_unresolved)

    table = parallels_runtime._worker_prepare_table(
        service=parallels_runtime.DataManagementService(tmp_path, adjust="qfq"),
        config=DataDownloadConfig(symbols=("000668.SZ",), timeframes=("1d",), start="2026-05-14", end="2026-06-13"),
        before_audits={"1d": before},
        committed=pd.DataFrame(),
        requested_symbols_by_timeframe={"1d": {"000668.SZ"}},
    )

    assert table.loc[0, "action"] == "fetched"
    assert table.loc[0, "after_status"] == "provider_no_data"
    assert int(table.loc[0, "missing_rows"]) == 1
    assert "本次写入 0 根" in str(table.loc[0, "message"])
    assert recorded
    assert recorded[0]["fetched_symbols_by_timeframe"] == {"1d": ["000668.SZ"]}


def test_worker_empty_plan_returns_known_provider_gaps_without_local_strict_download(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/tmp/tdx-data")
        adjust = "qfq"

        def download(self, *_: object, **__: object) -> DataDownloadResult:
            raise AssertionError("empty worker plan must not rerun strict local download")

    table = pd.DataFrame(
        {
            "stock_code": ["159006.SZ", "000001.SZ"],
            "timeframe": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
            "action": ["unresolved", "cached"],
            "after_status": ["provider_no_data", "ok"],
            "missing_rows": [1, 0],
            "rows_written": [0, 0],
        }
    )
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        parallels_runtime,
        "_worker_smart_payload",
        lambda *_, **__: ({"groups_by_timeframe": {}, "derive_targets_by_timeframe": {}}, {}),
    )
    monkeypatch.setattr(parallels_runtime, "_worker_prepare_table", lambda **_: table)
    monkeypatch.setattr(
        parallels_runtime.TdxWorkerClient,
        "health",
        lambda self: (_ for _ in ()).throw(AssertionError("empty worker plan must not check worker health")),
    )

    result = parallels_runtime.download_with_worker(
        Service(),  # type: ignore[arg-type]
        DataDownloadConfig(symbols=("159006.SZ", "000001.SZ"), timeframes=("1d",), start="2026-06-05", end="2026-06-10"),
        mode="smart",
        progress_callback=events.append,
    )

    assert int(result.table["action"].astype(str).eq("unresolved").sum()) == 1
    assert int(result.table["action"].astype(str).eq("cached").sum()) == 1
    assert result.summary["fetched_count"] == 0.0
    assert any(
        event.get("stage") == "tdx_connection_skipped" and event.get("unresolved_count") == 1
        for event in events
    )


def test_worker_empty_plan_fails_when_unmatched_local_gap_remains(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("/tmp/tdx-data")
        adjust = "qfq"

    table = pd.DataFrame(
        {
            "stock_code": ["159006.SZ"],
            "timeframe": ["1d"],
            "adjust": ["qfq"],
            "action": ["cached"],
            "after_status": ["missing_index"],
            "missing_rows": [1],
            "message": ["本地文件索引缺失"],
        }
    )

    monkeypatch.setattr(
        parallels_runtime,
        "_worker_smart_payload",
        lambda *_, **__: ({"groups_by_timeframe": {}, "derive_targets_by_timeframe": {}}, {}),
    )
    monkeypatch.setattr(parallels_runtime, "_worker_prepare_table", lambda **_: table)

    try:
        parallels_runtime.download_with_worker(
            Service(),  # type: ignore[arg-type]
            DataDownloadConfig(symbols=("159006.SZ",), timeframes=("1d",), start="2026-06-05", end="2026-06-10"),
            mode="smart",
        )
    except RuntimeError as exc:
        assert "Worker 计划为空" in str(exc)
        assert "159006.SZ/1d=missing_index" in str(exc)
    else:
        raise AssertionError("empty worker plan with unmatched gap must fail explicitly")


def test_cancellable_parallels_command_terminates_running_process(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Cancelled(RuntimeError):
        pass

    class FakeProcess:
        def __init__(self, *_: object, **__: object) -> None:
            self.pid = 999999
            self.returncode = None
            self.terminated = False
            self.killed = False
            self.poll_count = 0

        def poll(self):  # type: ignore[no-untyped-def]
            self.poll_count += 1
            return None if self.poll_count == 1 else self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return self.returncode

        def communicate(self):  # type: ignore[no-untyped-def]
            return "", ""

    processes: list[FakeProcess] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        process = FakeProcess(*args, **kwargs)
        processes.append(process)
        return process

    checks = {"count": 0}

    def cancel_check() -> None:
        checks["count"] += 1
        if checks["count"] > 1:
            raise Cancelled("stop")

    monkeypatch.setattr(parallels_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(parallels_runtime.time, "sleep", lambda _: None)

    try:
        parallels_runtime.run_parallels_cli_table(["python", "-m", "tdx_downloader.cli"], cancel_check=cancel_check)
    except Cancelled:
        pass
    else:
        raise AssertionError("cancel_check should propagate cancellation")

    assert len(processes) == 1
    assert processes[0].terminated is True
    assert processes[0].killed is False


def test_parallels_cli_table_forwards_progress_events(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeStream:
        def __init__(self, lines: list[str]) -> None:
            self.lines = lines

        def __iter__(self):  # type: ignore[no-untyped-def]
            return iter(self.lines)

    class FakeProcess:
        def __init__(self, *_: object, **__: object) -> None:
            self.pid = 999999
            self.returncode = 0
            self.stdout = FakeStream(['[{"stock_code":"000001.SZ","action":"fetched"}]\n'])
            self.stderr = FakeStream(
                [
                    '__TDX_PROGRESS__={"stage":"tdx_batch_start","timeframe":"1d","batch_index":1,"batch_count":2}\n',
                    '__TDX_PROGRESS__={"stage":"tdx_batch_done","timeframe":"1d","batch_index":1,"batch_count":2,"rows":2}\n',
                ]
            )

        def poll(self):  # type: ignore[no-untyped-def]
            return self.returncode

    monkeypatch.setattr(parallels_runtime.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(*args, **kwargs))
    events: list[dict[str, object]] = []

    frame = parallels_runtime.run_parallels_cli_table(
        ["python", "-m", "tdx_downloader.cli"],
        progress_callback=events.append,
    )

    assert frame.loc[0, "stock_code"] == "000001.SZ"
    assert [event["stage"] for event in events] == ["tdx_batch_start", "tdx_batch_done"]
    assert events[1]["rows"] == 2


def test_local_download_retries_tolerant_after_quality_gate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Service:
        data_root = Path("C:/tdx-data")
        adjust = "qfq"

        def __init__(self) -> None:
            self.strict_values: list[bool] = []

        def download(
            self,
            config: DataDownloadConfig,
            *,
            mode: str,
            progress_callback,
        ) -> DataDownloadResult:
            self.strict_values.append(config.strict_after_update)
            if config.strict_after_update:
                raise ValueError(
                    "本地行情数据未通过质量门禁："
                    "399001.SZ/1d=quality_error(首个异常：2026-01-05 OHLC 高低点不一致 high=9 low=11)"
                )
            return DataDownloadResult(
                table=pd.DataFrame(
                    {
                        "stock_code": ["399001.SZ"],
                        "timeframe": ["1d"],
                        "action": ["cached"],
                        "rows_written": [0],
                    }
                ),
                summary={"row_count": 1.0, "fetched_count": 0.0, "cached_count": 1.0},
            )

    monkeypatch.setattr(parallels_runtime.sys, "platform", "win32")
    service = Service()
    events: list[dict[str, object]] = []

    result = download_with_runtime(
        service,  # type: ignore[arg-type]
        DataDownloadConfig(
            symbols=("399001.SZ",),
            timeframes=("1d",),
            start="1990-01-01",
            end="2026-06-05",
            strict_after_update=True,
        ),
        mode="smart",
        progress_callback=events.append,
    )

    assert service.strict_values == [True, False]
    assert result.summary["row_count"] == 1.0
    retry_event = next(event for event in events if event["stage"] == "local_quality_gate_retry_incomplete")
    assert "2026-01-05" in str(retry_event["message"])


def test_symbol_groups_runtime_uses_parallels_when_local_dynamic_groups_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    def local_groups(*_: object, **__: object) -> list[dict[str, object]]:
        return [{"name": "核心样例", "symbols": ["000001.SZ"]}]

    def windows_records(command: list[str]) -> list[dict[str, object]]:
        commands.append(command)
        return [
            {"name": "核心样例", "symbols": ["000001.SZ"]},
            {"name": "ETF列表", "symbols": ["510300.SH"]},
            {"name": "板块指数", "symbols": ["880001.SH"]},
            {"name": "全A股票", "symbols": ["000001.SZ", "600000.SH"]},
        ]

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "shortcut_symbol_groups", local_groups)
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_records", windows_records)

    groups = shortcut_symbol_groups_with_runtime(
        Path("/Volumes/ccOUT 1/tdx-data"),
        Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"),
    )

    assert {group["name"] for group in groups} >= {"ETF列表", "板块指数", "全A股票"}
    assert commands[0][2:6] == ["tdx_downloader.cli", "symbol-groups", "--runtime", "parallels"]
    assert commands[0][-2:] == ["--output", "json"]


def test_symbol_groups_target_does_not_require_unrelated_dynamic_groups(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def local_groups(*_: object, **__: object) -> list[dict[str, object]]:
        return [{"name": "ETF列表", "symbols": ["510300.SH"]}]

    def fail_windows_records(command: list[str]) -> list[dict[str, object]]:
        raise AssertionError(f"targeted ETF refresh should not call Windows CLI: {command}")

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "shortcut_symbol_groups", local_groups)
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_records", fail_windows_records)

    groups = shortcut_symbol_groups_with_runtime(
        Path("/Volumes/ccOUT 1/tdx-data"),
        Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"),
        target="etf",
    )

    assert groups == [{"name": "ETF列表", "symbols": ["510300.SH"]}]


def test_symbol_metadata_runtime_uses_windows_when_local_metadata_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    def empty_local_metadata(*_: object, **__: object) -> pd.DataFrame:
        return pd.DataFrame(columns=["stock_code", "stock_name", "source", "path"])

    def windows_records(command: list[str], **_: object) -> list[dict[str, object]]:
        commands.append(command)
        return [
            {
                "stock_code": "000750.SZ",
                "stock_name": "国海证券",
                "source": "tdx_tnf",
                "path": r"C:\new_tdx64\T0002\hq_cache\szs.tnf",
            }
        ]

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "load_symbol_metadata", empty_local_metadata)
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_records", windows_records)

    metadata = symbol_metadata_with_runtime(
        Path("/Volumes/ccOUT 1/tdx-data"),
        Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"),
    )

    assert metadata.loc[0, "stock_code"] == "000750.SZ"
    assert metadata.loc[0, "stock_name"] == "国海证券"
    assert commands[0][2:6] == ["tdx_downloader.cli", "symbol-metadata", "--runtime", "parallels"]
    assert commands[0][-2:] == ["--output", "json"]


def test_etf_tracking_runtime_uses_windows_command_on_macos(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    commands: list[list[str]] = []

    def windows_records(command: list[str], **_: object) -> list[dict[str, object]]:
        commands.append(command)
        return [
            {
                "tracking_symbol": "000300.SH",
                "stock_code": "510300.SH",
                "stock_name": "沪深300ETF华泰柏瑞",
                "now_price": 3.88,
            }
        ]

    monkeypatch.setattr(parallels_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(parallels_runtime, "run_parallels_cli_records", windows_records)

    frame = etf_tracking_with_runtime(
        Path("/Volumes/ccOUT 1/tdx-data"),
        Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"),
        index_symbols=("000300.SH",),
    )

    assert frame.loc[0, "stock_code"] == "510300.SH"
    assert commands[0][2:6] == ["tdx_downloader.cli", "etf-tracking", "--runtime", "parallels"]
    assert commands[0][-2:] == ["--output", "json"]


def test_parallels_etf_tracking_command_forwards_index_symbols() -> None:
    command = parallels_etf_tracking_command(
        Path("/Volumes/ccOUT 1/tdx-data"),
        Path("/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"),
        index_symbols=("000300.SH", "399006.SZ"),
    )

    assert command[2:6] == ["tdx_downloader.cli", "etf-tracking", "--runtime", "parallels"]
    assert command[command.index("--index-symbols") + 1] == "000300.SH,399006.SZ"
    assert command[-2:] == ["--output", "json"]


def test_symbol_groups_parallels_timeout_is_explicit(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def timeout_run(command: list[str], **_: object) -> object:
        raise parallels_runtime.subprocess.TimeoutExpired(command, timeout=12)

    monkeypatch.setattr(parallels_runtime.subprocess, "run", timeout_run)

    try:
        parallels_runtime.run_parallels_cli_records(["python", "-m", "tdx_downloader.cli", "symbol-groups"])
    except RuntimeError as exc:
        assert "快捷代码表超时" in str(exc)
    else:
        raise AssertionError("timeout should be surfaced")
