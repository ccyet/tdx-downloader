from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

from tdx_downloader.data.ai_index import ai_index_path_for, query_ai_price_index, rank_symbols_by_ai_price_index
from tdx_downloader.data import catalog as catalog_module
from tdx_downloader.data import symbols as symbols_module
from tdx_downloader.data.catalog import (
    build_catalog,
    catalog_path_for,
    infer_asset_type,
    query_catalog,
    query_coverage_runs,
    query_market_data_part_symbols,
    query_unresolved_gaps,
    refresh_coverage_runs,
    maintain_catalog,
    upsert_market_data_parts,
    upsert_partial_coverage_runs_from_bars,
    upsert_unresolved_gaps,
)
from tdx_downloader.data import repository as repository_module
from tdx_downloader.data.indicators import IndicatorStore, load_indicator_values
from tdx_downloader.data.audit import audit_local_data, data_gap_episodes
from tdx_downloader.data.inventory import inventory_local_data
from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataManagementService,
    shortcut_symbol_groups,
    shortcut_symbols,
)
from tdx_downloader.data.symbols import load_symbol_metadata, load_tdx_symbol_metadata
from tdx_downloader.data.storage import append_delta_bars, compact_delta_sidecars, delta_sidecar_summary, load_local_bars, write_local_bars


class FakeTq:
    def __init__(self, payload: dict[str, pd.DataFrame]) -> None:
        self.payload = payload
        self.initialize_calls: list[str] = []
        self.market_calls: list[dict[str, object]] = []
        self.refresh_calls: list[tuple[list[str], str]] = []

    def initialize(self, caller_path: str) -> None:
        self.initialize_calls.append(caller_path)

    def refresh_kline(self, stock_list: list[str], period: str) -> str:
        self.refresh_calls.append((stock_list, period))
        return '{"ErrorId":"0","Msg":"ok"}'

    def get_market_data(self, **kwargs: object) -> dict[str, pd.DataFrame]:
        self.market_calls.append(kwargs)
        return self.payload


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-05-25 10:30:00", "2026-05-25 11:30:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.6],
            "high": [10.8, 11.4],
            "low": [9.9, 10.4],
            "close": [10.7, 11.2],
            "volume": [1000.0, 1200.0],
            "amount": [10700.0, 13440.0],
        }
    )


def _tdx_payload() -> dict[str, pd.DataFrame]:
    bars = _bars().set_index("date")
    return {
        "Open": pd.DataFrame({"000001.SZ": bars["open"]}),
        "High": pd.DataFrame({"000001.SZ": bars["high"]}),
        "Low": pd.DataFrame({"000001.SZ": bars["low"]}),
        "Close": pd.DataFrame({"000001.SZ": bars["close"]}),
        "Volume": pd.DataFrame({"000001.SZ": bars["volume"]}),
        "Amount": pd.DataFrame({"000001.SZ": bars["amount"]}),
    }


def test_data_management_service_summarizes_cache_snapshot(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    write_local_bars(data_root=data_root, timeframe="60m", adjust="qfq", bars=_bars())
    metadata = data_root.parent / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n000001.SZ,平安银行\n510300.SH,沪深300ETF\n000300.SH,沪深300\n",
        encoding="utf-8",
    )

    snapshot = DataManagementService(data_root, adjust="qfq").cache_snapshot(
        timeframes=("60m",),
        symbols=("000001.SZ", "510300.SH", "000300.SH"),
    )

    assert snapshot.summary["symbol_count"] == 3.0
    assert snapshot.summary["asset_type_count"] == 3.0
    assert snapshot.summary["dataset_count"] == 1.0
    assert snapshot.summary["data_inventory_cached_count"] == 1.0
    assert snapshot.summary["data_inventory_missing_file_count"] == 2.0
    assert snapshot.catalog_path.exists()
    readiness = snapshot.readiness.set_index(["timeframe", "asset_type"])
    assert readiness.loc[("60m", "stock"), "status"] == "ready"
    assert readiness.loc[("60m", "stock"), "coverage_ratio"] == 1.0
    assert readiness.loc[("60m", "etf"), "status"] == "empty"
    assert readiness.loc[("60m", "etf"), "missing_count"] == 1
    assert readiness.loc[("60m", "index"), "message"] == "没有可用缓存，回测前需要先补齐。"
    with sqlite3.connect(snapshot.catalog_path) as connection:
        indexes = pd.read_sql_query("PRAGMA index_list(market_data_files)", connection)
    assert "idx_market_data_lookup" in indexes["name"].tolist()
    assert "idx_market_data_filter_order" in indexes["name"].tolist()
    assert "idx_market_data_symbol_adjust" in indexes["name"].tolist()
    by_timeframe = snapshot.by_timeframe.set_index("timeframe")
    assert by_timeframe.loc["60m", "cached_count"] == 1
    assert by_timeframe.loc["60m", "unavailable_count"] == 2
    by_asset_type = snapshot.by_asset_type.set_index("asset_type")
    assert by_asset_type.loc["stock", "cached_count"] == 1
    assert by_asset_type.loc["etf", "unavailable_count"] == 1
    assert by_asset_type.loc["index", "unavailable_count"] == 1
    queried = query_catalog(data_root=data_root, asset_types=("stock",), timeframes=("60m",))
    assert queried["stock_code"].tolist() == ["000001.SZ"]


def test_cache_snapshot_rebuild_does_not_refresh_precise_coverage_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())

    def fail_coverage_refresh(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("cache snapshot should rebuild catalog without precise coverage refresh by default")

    monkeypatch.setattr("tdx_downloader.data.catalog.refresh_coverage_runs", fail_coverage_refresh)

    snapshot = DataManagementService(data_root, adjust="qfq").cache_snapshot(timeframes=("1d",), rebuild_catalog=True)

    assert snapshot.summary["catalog_row_count"] == 1.0
    assert snapshot.by_status.loc[0, "status"] == "cached"


def test_cache_snapshot_rebuild_preserves_existing_coverage_when_refresh_disabled(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    before = refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))
    assert not before.empty

    DataManagementService(data_root, adjust="qfq").cache_snapshot(timeframes=("1d",), rebuild_catalog=True)

    after = query_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))
    assert not after.empty


def test_cache_snapshot_reuses_unchanged_catalog_records_without_opening_parquet(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d",), rebuild_catalog=True)

    def fail_parquet_open(*_: object, **__: object) -> object:
        raise AssertionError("unchanged cache scan should reuse catalog stat metadata")

    monkeypatch.setattr("tdx_downloader.data.inventory.pq.ParquetFile", fail_parquet_open)
    monkeypatch.setattr("tdx_downloader.data.inventory.pd.read_parquet", fail_parquet_open)

    snapshot = service.cache_snapshot(timeframes=("1d",), rebuild_catalog=True)

    assert snapshot.summary["catalog_row_count"] == 1.0
    assert snapshot.summary["data_inventory_cached_count"] == 1.0


def test_query_catalog_read_path_does_not_initialize_schema(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    build_catalog(
        data_root=data_root,
        inventory=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "path": str(data_root / "daily" / "qfq" / "000001.SZ.parquet"),
                    "rows": 1,
                    "status": "cached",
                }
            ]
        ),
    )

    def fail_init(*_: object, **__: object) -> None:
        raise AssertionError("read-only catalog query must not initialize schema")

    monkeypatch.setattr(catalog_module, "_init_catalog", fail_init)
    queried = query_catalog(data_root=data_root, symbols=("000001.SZ",))

    assert queried["stock_code"].tolist() == ["000001.SZ"]


def test_query_catalog_accepts_scalar_string_filters(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    build_catalog(
        data_root=data_root,
        inventory=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "path": str(data_root / "daily" / "qfq" / "000001.SZ.parquet"),
                    "rows": 1,
                    "status": "cached",
                }
            ]
        ),
    )

    queried = query_catalog(
        data_root=data_root,
        symbols="000001.SZ",
        timeframes="1d",
        data_kinds="price",
        indicators="ohlcv",
        statuses="cached",
    )

    assert queried["stock_code"].tolist() == ["000001.SZ"]


def test_load_symbol_metadata_ignores_locked_catalog_metadata(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    build_catalog(
        data_root=data_root,
        inventory=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "path": str(data_root / "daily" / "qfq" / "000001.SZ.parquet"),
                    "rows": 1,
                    "status": "cached",
                }
            ]
        ),
    )

    def locked_read_sql(*_: object, **__: object) -> pd.DataFrame:
        raise pd.errors.DatabaseError("database is locked")

    monkeypatch.setattr(symbols_module.pd, "read_sql_query", locked_read_sql)

    metadata = load_symbol_metadata(data_root)

    assert metadata.empty


def test_ai_price_index_materializes_local_bars_for_ranked_queries(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    metadata = data_root / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n300001.SZ,创业A\n300002.SZ,创业B\n000001.SZ,主板\n",
        encoding="utf-8",
    )
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-06-09",
                    "2026-06-10",
                    "2026-06-09",
                    "2026-06-10",
                    "2026-06-09",
                    "2026-06-10",
                ]
            ),
            "stock_code": ["300001.SZ", "300001.SZ", "300002.SZ", "300002.SZ", "000001.SZ", "000001.SZ"],
            "open": [10.0] * 6,
            "high": [11.0] * 6,
            "low": [9.0] * 6,
            "close": [10.5] * 6,
            "volume": [100.0] * 6,
            "amount": [1000.0, 2000.0, 5000.0, 3000.0, 9000.0, 9000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    symbols, ranked, info = rank_symbols_by_ai_price_index(
        data_root=data_root,
        adjust="qfq",
        timeframe="1d",
        symbols=("300001.SZ", "300002.SZ"),
        start="2026-06-09",
        end="2026-06-09",
        metric="amount",
        limit=1,
        ascending=False,
    )

    assert ai_index_path_for(data_root).exists()
    assert info["table"] == "ai_price_bars"
    assert info["rows_indexed"] == 2
    assert symbols == ["300002.SZ"]
    assert ranked.loc[0, "stock_name"] == "创业B"
    reused_symbols, _, reused_info = rank_symbols_by_ai_price_index(
        data_root=data_root,
        adjust="qfq",
        timeframe="1d",
        symbols=("300001.SZ", "300002.SZ"),
        start="2026-06-09",
        end="2026-06-09",
        metric="amount",
        limit=1,
        ascending=False,
    )
    assert reused_symbols == ["300002.SZ"]
    assert reused_info["rows_indexed"] == 0
    indexed = query_ai_price_index(
        data_root=data_root,
        adjust="qfq",
        timeframe="1d",
        symbols=("300001.SZ", "300002.SZ"),
        start="2026-06-09",
        end="2026-06-09",
    )
    assert indexed["stock_code"].tolist() == ["300001.SZ", "300002.SZ"]


def test_indicator_cache_computes_ma_and_reuses_fresh_cache(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=6),
            "stock_code": ["000001.SZ"] * 6,
            "open": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "high": [1.1, 2.1, 3.1, 4.1, 5.1, 6.1],
            "low": [0.9, 1.9, 2.9, 3.9, 4.9, 5.9],
            "close": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "volume": [100.0] * 6,
            "amount": [1000.0] * 6,
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    service = DataManagementService(data_root, adjust="qfq")

    first = service.compute_indicators(
        symbols=["000001.SZ"],
        formula_ids=["ma5"],
        timeframe="1d",
        start="2026-01-01",
        end="2026-01-31",
    )
    values = load_indicator_values(
        data_root=data_root,
        adjust="qfq",
        timeframe="1d",
        symbols=["000001.SZ"],
        formula_ids=["ma5"],
        start="2026-01-01",
        end="2026-01-31",
    )
    second = service.compute_indicators(
        symbols=["000001.SZ"],
        formula_ids=["ma5"],
        timeframe="1d",
        start="2026-01-01",
        end="2026-01-31",
    )

    assert first.loc[0, "status"] == "computed"
    assert first.loc[0, "rows"] == 6
    assert values["ma5"].dropna().tolist() == [3.0, 4.0]
    assert second.loc[0, "status"] == "cached"
    assert second.loc[0, "new_rows"] == 0


def test_imported_tdx_formula_and_indicator_catalog_entry(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=5),
            "stock_code": ["000001.SZ"] * 5,
            "open": [1.0, 2.0, 3.0, 4.0, 5.0],
            "high": [1.1, 2.1, 3.1, 4.1, 5.1],
            "low": [0.9, 1.9, 2.9, 3.9, 4.9],
            "close": [1.0, 2.0, 3.0, 4.0, 5.0],
            "volume": [100.0] * 5,
            "amount": [1000.0] * 5,
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    service = DataManagementService(data_root, adjust="qfq")
    formulas = service.import_tdx_indicator_formulas("M3:MA(CLOSE,3);")

    result = service.compute_indicators(
        symbols=["000001.SZ"],
        formula_ids=[formulas[0].formula_id],
        timeframe="1d",
        start="2026-01-01",
        end="2026-01-31",
    )
    snapshot = service.cache_snapshot(timeframes=("1d",), symbols=("000001.SZ",))
    indicator_catalog = snapshot.catalog.loc[snapshot.catalog["data_kind"].eq("indicator")]

    assert formulas[0].formula_id == "m3"
    assert result.loc[0, "status"] == "computed"
    assert result.loc[0, "indicator"] == "m3"
    assert indicator_catalog["indicator"].tolist() == ["m3"]
    assert indicator_catalog["status"].tolist() == ["cached"]


def test_indicator_mapping_can_target_asset_type_and_timeframe(tmp_path: Path) -> None:
    store = IndicatorStore(tmp_path)

    store.upsert_mapping(formula_id="ma20", asset_type="stock", timeframe="1d")

    assert store.mapped_formula_ids_for_symbol(symbol="000001.SZ", asset_type="stock", timeframe="1d") == ("ma20",)
    assert store.mapped_formula_ids_for_symbol(symbol="510300.SH", asset_type="etf", timeframe="1d") == ()


def test_data_management_service_force_download_uses_batch_and_progress(tmp_path: Path) -> None:
    service = DataManagementService(tmp_path / "market" / "daily", adjust="qfq")
    fake = FakeTq(_tdx_payload())
    events: list[dict[str, object]] = []

    result = service.repository.update_from_tdx(
        symbols=("000001.SZ",),
        timeframe="60m",
        start="2026-05-25 09:30:00",
        end="2026-05-25 15:00:00",
        tq_client=fake,
        batch_size=1,
        progress_callback=events.append,
    )

    assert result.loc[0, "new_rows"] == 2
    assert fake.market_calls[0]["stock_list"] == ["000001.SZ"]
    assert "fetch_start" in [event["stage"] for event in events]
    assert "write_done" in [event["stage"] for event in events]
    assert any(int(event.get("coverage_rows", 0) or 0) > 0 for event in events if event["stage"] == "write_done")
    coverage = query_coverage_runs(data_root=service.data_root, adjust="qfq", timeframes=("60m",), symbols=("000001.SZ",))
    assert not coverage.empty
    assert int(coverage.loc[0, "file_size_bytes"]) == 0


def test_update_from_tdx_skips_full_coverage_refresh(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    service = DataManagementService(tmp_path / "market", adjust="qfq")
    fake = FakeTq(_tdx_payload())

    def fail_full_refresh(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("update_from_tdx should use incoming bars for partial coverage, not full refresh")

    monkeypatch.setattr("tdx_downloader.data.catalog.refresh_coverage_runs", fail_full_refresh)

    result = service.repository.update_from_tdx(
        symbols=("000001.SZ",),
        timeframe="5m",
        start="2026-05-25 09:30:00",
        end="2026-05-25 15:00:00",
        tq_client=fake,
    )

    coverage = query_coverage_runs(data_root=service.data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))
    assert result.loc[0, "new_rows"] == 2
    assert not coverage.empty


def test_download_plan_fetches_daily_cache_with_incomplete_requested_boundary(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "stock_code": ["399006.SZ", "399006.SZ"],
            "open": [3300.0, 3320.0],
            "high": [3350.0, 3360.0],
            "low": [3280.0, 3290.0],
            "close": [3340.0, 3350.0],
            "volume": [1000000.0, 1200000.0],
            "amount": [300000000.0, 360000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    service = DataManagementService(data_root, adjust="qfq")
    plan = service.download_plan(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2001-01-01",
            end="2026-06-03",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "coverage_gap"
    assert plan.loc[0, "before_status"] == "coverage_gap"
    assert "缺失" in plan.loc[0, "message"]
    assert "按缺口窗口补齐" in plan.loc[0, "message"]


def test_download_plan_fetches_daily_cache_with_recent_end_boundary_gap(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
            "stock_code": ["399006.SZ", "399006.SZ", "399006.SZ"],
            "open": [4000.0, 4020.0, 4040.0],
            "high": [4050.0, 4060.0, 4070.0],
            "low": [3980.0, 3990.0, 4010.0],
            "close": [4030.0, 4050.0, 4060.0],
            "volume": [1000000.0, 1200000.0, 1300000.0],
            "amount": [400000000.0, 480000000.0, 520000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    service = DataManagementService(data_root, adjust="qfq")
    plan = service.download_plan(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-01",
            end="2026-06-05",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "coverage_gap"
    assert plan.loc[0, "before_status"] == "coverage_gap"
    assert "2026-06-04" in plan.loc[0, "message"]
    assert "2026-06-05" in plan.loc[0, "message"]


def test_download_plan_counts_missing_daily_rows_when_window_has_no_local_data(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-03"]),
            "stock_code": ["399006.SZ"],
            "open": [4040.0],
            "high": [4070.0],
            "low": [4010.0],
            "close": [4060.0],
            "volume": [1300000.0],
            "amount": [520000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    service = DataManagementService(data_root, adjust="qfq")
    plan = service.download_plan(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-08",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "no_window_data"
    assert plan.loc[0, "expected_rows"] == 2
    assert plan.loc[0, "missing_rows"] == 2
    assert plan.loc[0, "first_missing_at"] == pd.Timestamp("2026-06-05")
    assert plan.loc[0, "last_missing_at"] == pd.Timestamp("2026-06-08")


def test_download_plan_counts_daily_trading_day_delta_when_local_data_is_partial(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["399006.SZ"],
            "open": [4040.0],
            "high": [4070.0],
            "low": [4010.0],
            "close": [4060.0],
            "volume": [1300000.0],
            "amount": [520000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    service = DataManagementService(data_root, adjust="qfq")
    plan = service.download_plan(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-08",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "coverage_gap"
    assert plan.loc[0, "expected_rows"] == 2
    assert plan.loc[0, "missing_rows"] == 1
    assert plan.loc[0, "first_missing_at"] == pd.Timestamp("2026-06-08")
    assert plan.loc[0, "last_missing_at"] == pd.Timestamp("2026-06-08")


def test_large_daily_audit_dataset_reads_only_requested_symbol_files(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    requested_symbols = tuple(f"{index:06d}.SZ" for index in range(200))
    requested_bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"] * len(requested_symbols)),
            "stock_code": list(requested_symbols),
            "open": [10.0] * len(requested_symbols),
            "high": [10.5] * len(requested_symbols),
            "low": [9.8] * len(requested_symbols),
            "close": [10.2] * len(requested_symbols),
            "volume": [1000.0] * len(requested_symbols),
            "amount": [10200.0] * len(requested_symbols),
        }
    )
    extra_bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["999999.SZ"],
            "open": [99.0],
            "high": [100.0],
            "low": [98.0],
            "close": [99.5],
            "volume": [9999.0],
            "amount": [999999.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=pd.concat([requested_bars, extra_bars]))

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=list(requested_symbols),
        start="2026-06-05",
        end="2026-06-05",
    )

    assert len(audit) == len(requested_symbols)
    assert set(audit["stock_code"]) == set(requested_symbols)
    assert "999999.SZ" not in set(audit["stock_code"])


def test_download_plan_fetches_middle_daily_trading_day_gap(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-09"]),
            "stock_code": ["399006.SZ", "399006.SZ"],
            "open": [4040.0, 4080.0],
            "high": [4070.0, 4110.0],
            "low": [4010.0, 4070.0],
            "close": [4060.0, 4100.0],
            "volume": [1300000.0, 1400000.0],
            "amount": [520000000.0, 560000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    service = DataManagementService(data_root, adjust="qfq")
    plan = service.download_plan(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-09",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "coverage_gap"
    assert plan.loc[0, "expected_rows"] == 3
    assert plan.loc[0, "missing_rows"] == 1
    assert plan.loc[0, "first_missing_at"] == pd.Timestamp("2026-06-08")
    assert plan.loc[0, "last_missing_at"] == pd.Timestamp("2026-06-08")


def test_preview_download_plan_uses_coverage_runs_for_middle_daily_gap(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-09"]),
            "stock_code": ["399006.SZ", "399006.SZ"],
            "open": [4040.0, 4080.0],
            "high": [4070.0, 4110.0],
            "low": [4010.0, 4070.0],
            "close": [4060.0, 4100.0],
            "volume": [1300000.0, 1400000.0],
            "amount": [520000000.0, 560000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    plan = DataManagementService(data_root, adjust="qfq").preview_download_plan(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-09",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "coverage_gap"
    assert plan.loc[0, "expected_rows"] == 3
    assert plan.loc[0, "missing_rows"] == 1
    assert plan.loc[0, "first_missing_at"] == pd.Timestamp("2026-06-08")
    assert plan.loc[0, "last_missing_at"] == pd.Timestamp("2026-06-08")


def test_coverage_refresh_reads_only_identity_columns_when_file_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    path = data_root / "daily" / "qfq" / "000001.SZ.parquet"
    extra = _bars().copy()
    extra["date"] = pd.to_datetime(["2026-05-26 10:30:00", "2026-05-26 11:30:00"])
    pd.concat([pd.read_parquet(path), extra], ignore_index=True).to_parquet(path, index=False)
    original_read_parquet = pd.read_parquet
    observed_columns: list[tuple[str, ...] | None] = []

    def tracked_read_parquet(*args: object, **kwargs: object) -> pd.DataFrame:
        columns = kwargs.get("columns")
        observed_columns.append(tuple(columns) if columns is not None else None)
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr("tdx_downloader.data.catalog.pd.read_parquet", tracked_read_parquet)
    refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))

    coverage = query_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))
    assert not coverage.empty
    assert observed_columns
    assert set(observed_columns) == {("date", "stock_code")}


def test_coverage_refresh_skips_unchanged_files_without_reading_parquet(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))

    def fail_read_parquet(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("unchanged coverage refresh should not read parquet")

    monkeypatch.setattr("tdx_downloader.data.catalog.pd.read_parquet", fail_read_parquet)
    coverage = refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))

    assert not coverage.empty


def test_coverage_refresh_limits_existing_state_query_to_targets(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    observed_sql: list[str] = []
    original_connect = sqlite3.connect

    class TrackingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters=(), /):  # type: ignore[override]
            if "FROM market_data_coverage_runs" in sql and "file_size_bytes > 0" in sql:
                observed_sql.append(sql)
            return super().execute(sql, parameters)

    def tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        kwargs["factory"] = TrackingConnection
        return original_connect(*args, **kwargs)

    monkeypatch.setattr("tdx_downloader.data.catalog.sqlite3.connect", tracking_connect)

    refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))

    assert observed_sql
    assert "stock_code = ?" in observed_sql[0]


def test_catalog_maintenance_reports_storage_stats(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())

    result = maintain_catalog(data_root=data_root, vacuum=False)

    assert result["exists"] is True
    assert int(result["before"]["file_size_bytes"]) > 0
    assert int(result["after"]["file_size_bytes"]) > 0
    assert "freelist_count" in result["after"]


def test_catalog_maintenance_marks_missing_active_parts(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    existing_part = data_root / "5m" / "qfq" / "_delta_parts" / "trade_month=2026-06" / "part.parquet"
    existing_part.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 15:00:00"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [10.1],
            "low": [9.9],
            "close": [10.0],
            "volume": [100.0],
            "amount": [1000.0],
        }
    ).to_parquet(existing_part, index=False)
    missing_part = existing_part.with_name("missing.parquet")
    upsert_market_data_parts(
        data_root=data_root,
        parts=pd.DataFrame(
            [
                {
                    "part_id": "existing-part",
                    "job_id": "job",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "trade_month": "2026-06",
                    "path": str(existing_part),
                    "rows": 1,
                    "min_at": "2026-06-09T15:00:00",
                    "max_at": "2026-06-09T15:00:00",
                    "file_size_bytes": existing_part.stat().st_size,
                    "sha256": "",
                    "commit_version": 1,
                    "state": "active",
                    "created_at": "2026-06-09T15:01:00",
                },
                {
                    "part_id": "missing-part",
                    "job_id": "job",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "trade_month": "2026-06",
                    "path": str(missing_part),
                    "rows": 1,
                    "min_at": "2026-06-09T15:00:00",
                    "max_at": "2026-06-09T15:00:00",
                    "file_size_bytes": 100,
                    "sha256": "",
                    "commit_version": 2,
                    "state": "active",
                    "created_at": "2026-06-09T15:01:00",
                },
            ]
        ),
        part_symbols=pd.DataFrame(
            [
                {
                    "part_id": "existing-part",
                    "stock_code": "000001.SZ",
                    "min_at": "2026-06-09T15:00:00",
                    "max_at": "2026-06-09T15:00:00",
                    "rows": 1,
                },
                {
                    "part_id": "missing-part",
                    "stock_code": "000001.SZ",
                    "min_at": "2026-06-09T15:00:00",
                    "max_at": "2026-06-09T15:00:00",
                    "rows": 1,
                },
            ]
        ),
    )

    result = maintain_catalog(data_root=data_root, vacuum=False)
    parts = query_market_data_part_symbols(
        data_root=data_root,
        symbols=("000001.SZ",),
        adjust="qfq",
        timeframes=("5m",),
        start="2026-06-09",
        end="2026-06-09",
    )

    assert result["stale_parts_marked_missing"] == 1
    assert len(parts) == 1
    assert parts.loc[0, "part_id"] == "existing-part"


def test_coverage_refresh_ignores_partial_stat_rows_when_checking_staleness(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from tdx_downloader.data.catalog import upsert_partial_coverage_runs_from_bars

    data_root = tmp_path / "market"
    bars = _bars()
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars, refresh_coverage=False)
    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    first = refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))
    assert not first.empty
    assert int(pd.to_numeric(first["file_size_bytes"], errors="coerce").max()) > 0

    def fail_read_parquet(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("full coverage stat rows should make unchanged refresh skip parquet reads")

    monkeypatch.setattr("tdx_downloader.data.catalog.pd.read_parquet", fail_read_parquet)
    second = refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("1d",), symbols=("000001.SZ",))

    assert not second.empty


def test_intraday_coverage_runs_merge_across_adjacent_trading_days(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    dates = pd.to_datetime(
        [
            "2026-06-08 14:55:00",
            "2026-06-08 15:00:00",
            "2026-06-09 09:35:00",
            "2026-06-09 09:40:00",
        ]
    )
    bars = pd.DataFrame(
        {
            "date": dates,
            "stock_code": ["000001.SZ"] * len(dates),
            "open": [10.0] * len(dates),
            "high": [11.0] * len(dates),
            "low": [9.0] * len(dates),
            "close": [10.5] * len(dates),
            "volume": [1000.0] * len(dates),
            "amount": [10500.0] * len(dates),
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars)

    refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))

    coverage = query_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))
    assert len(coverage) == 1
    assert coverage.loc[0, "start_at"] == pd.Timestamp("2026-06-08 14:55:00").isoformat()
    assert coverage.loc[0, "end_at"] == pd.Timestamp("2026-06-09 09:40:00").isoformat()
    assert coverage.loc[0, "row_count"] == 4


def test_preview_download_plan_quarantines_malformed_catalog_without_rebuild(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    catalog_path = catalog_path_for(data_root)
    catalog_path.write_bytes(b"this is not a sqlite database")

    plan = DataManagementService(data_root, adjust="qfq").preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-05-25",
            end="2026-05-25",
        )
    )

    backups = list(catalog_path.parent.glob(f"{catalog_path.name}.corrupt.*"))
    assert backups
    assert not catalog_path.exists()
    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "catalog_status"] == "missing_index"
    assert plan.loc[0, "coverage_status"] == "coverage_missing_index"
    assert plan.loc[0, "before_status"] == "missing_index"
    assert "预览未扫描 parquet" in plan.loc[0, "message"]


def test_catalog_rebuild_clears_stale_coverage_runs(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    assert not query_coverage_runs(
        data_root=data_root,
        adjust="qfq",
        timeframes=("1d",),
        symbols=("000001.SZ",),
    ).empty

    build_catalog(
        data_root=data_root,
        inventory=pd.DataFrame(columns=["stock_code", "timeframe", "adjust", "path"]),
    )

    assert query_coverage_runs(
        data_root=data_root,
        adjust="qfq",
        timeframes=("1d",),
        symbols=("000001.SZ",),
    ).empty


def test_smart_download_fetches_only_missing_daily_gap_window(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["399006.SZ"],
            "open": [4040.0],
            "high": [4070.0],
            "low": [4010.0],
            "close": [4060.0],
            "volume": [1300000.0],
            "amount": [520000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    calls: list[dict[str, object]] = []

    def fake_update_from_tdx(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        incoming = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-08"]),
                "stock_code": ["399006.SZ"],
                "open": [4060.0],
                "high": [4090.0],
                "low": [4050.0],
                "close": [4080.0],
                "volume": [1200000.0],
                "amount": [500000000.0],
            }
        )
        return write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=incoming)

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fake_update_from_tdx)

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-08",
            min_coverage_ratio=1.0,
        ),
        mode="smart",
    )

    assert len(calls) == 1
    assert calls[0]["symbols"] == ("399006.SZ",)
    assert calls[0]["start"] == "2026-06-08"
    assert calls[0]["end"] == "2026-06-08"
    assert result.table.loc[0, "action"] == "fetched"
    assert result.table.loc[0, "missing_rows"] == 0


def test_smart_download_splits_discrete_missing_daily_gap_windows(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-09", "2026-06-11"]),
            "stock_code": ["399006.SZ", "399006.SZ", "399006.SZ"],
            "open": [4040.0, 4080.0, 4100.0],
            "high": [4070.0, 4110.0, 4130.0],
            "low": [4010.0, 4070.0, 4090.0],
            "close": [4060.0, 4100.0, 4120.0],
            "volume": [1300000.0, 1400000.0, 1500000.0],
            "amount": [520000000.0, 560000000.0, 600000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    calls: list[dict[str, object]] = []

    def fake_update_from_tdx(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        date = pd.Timestamp(str(kwargs["start"]))
        incoming = pd.DataFrame(
            {
                "date": [date],
                "stock_code": ["399006.SZ"],
                "open": [4060.0],
                "high": [4090.0],
                "low": [4050.0],
                "close": [4080.0],
                "volume": [1200000.0],
                "amount": [500000000.0],
            }
        )
        return write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=incoming)

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fake_update_from_tdx)

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-11",
        ),
        mode="smart",
    )

    assert [(call["start"], call["end"]) for call in calls] == [
        ("2026-06-08", "2026-06-08"),
        ("2026-06-10", "2026-06-10"),
    ]
    assert result.table.loc[0, "missing_rows"] == 0


def test_smart_download_intraday_unknown_coverage_bootstraps_index_before_fetch(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    intraday_dates = pd.to_datetime(
        list(pd.date_range("2026-06-05 09:35:00", "2026-06-05 11:30:00", freq="5min"))
        + list(pd.date_range("2026-06-05 13:05:00", "2026-06-05 15:00:00", freq="5min"))
    )
    existing = pd.DataFrame(
        {
            "date": intraday_dates,
            "stock_code": ["000001.SZ"] * len(intraday_dates),
            "open": [10.0] * len(intraday_dates),
            "high": [10.2] * len(intraday_dates),
            "low": [9.9] * len(intraday_dates),
            "close": [10.1] * len(intraday_dates),
            "volume": [1000.0] * len(intraday_dates),
            "amount": [10100.0] * len(intraday_dates),
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=existing, refresh_coverage=False)
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-05", "2026-06-08"]),
                "stock_code": ["000001.SZ", "000001.SZ"],
                "open": [10.0, 10.2],
                "high": [10.3, 10.5],
                "low": [9.9, 10.1],
                "close": [10.2, 10.4],
                "volume": [1000.0, 1200.0],
                "amount": [10200.0, 12480.0],
            }
        ),
    )
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d", "5m"), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    def fake_update_from_tdx(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        incoming = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-08 09:35:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.2],
                "high": [10.4],
                "low": [10.1],
                "close": [10.3],
                "volume": [1200.0],
                "amount": [12360.0],
            }
        )
        return write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=incoming, refresh_coverage=False)

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fake_update_from_tdx)

    result = service.download(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-05",
            end="2026-06-08",
        ),
        mode="smart",
        progress_callback=events.append,
    )

    assert len(calls) == 1
    assert calls[0]["start"] == "2026-06-08 09:35:00"
    assert calls[0]["end"] == "2026-06-08 15:05:00"
    assert "coverage_bootstrap_start" in [str(event.get("stage")) for event in events]
    assert "coverage_bootstrap_done" in [str(event.get("stage")) for event in events]
    assert result.table.loc[result.table["timeframe"].eq("5m"), "action"].iloc[0] == "fetched"


def test_smart_download_ignores_nan_missing_windows(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    calls: list[dict[str, object]] = []

    def fake_update_from_tdx(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        date = pd.Timestamp(str(kwargs["start"]))
        incoming = pd.DataFrame(
            {
                "date": [date],
                "stock_code": ["000002.SZ"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000.0],
                "amount": [10200.0],
            }
        )
        return write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=incoming)

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fake_update_from_tdx)

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("000001.SZ", "000002.SZ"),
            timeframes=("1d",),
            start="2026-05-25",
            end="2026-05-25",
        ),
        mode="smart",
    )

    assert calls == [
        {
            "data_root": data_root,
            "adjust": "qfq",
            "symbols": ("000002.SZ",),
            "timeframe": "1d",
            "start": "2026-05-25",
            "end": "2026-05-25",
            "tqcenter_path": "",
            "tq_client": None,
            "batch_size": 100,
            "progress_callback": None,
        }
    ]
    assert result.summary["fetched_count"] == 1.0


def test_smart_download_derives_high_intraday_timeframes_from_5m(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [12.0],
            "low": [9.8],
            "close": [11.8],
            "volume": [100000.0],
            "amount": [1180000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=daily)
    calls: list[dict[str, object]] = []

    def fake_update_from_tdx(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        assert kwargs["timeframe"] == "5m"
        dates = pd.date_range("2026-06-05 09:35:00", "2026-06-05 10:30:00", freq="5min")
        bars = pd.DataFrame(
            {
                "date": dates,
                "stock_code": ["000001.SZ"] * len(dates),
                "open": list(range(10, 10 + len(dates))),
                "high": list(range(11, 11 + len(dates))),
                "low": list(range(9, 9 + len(dates))),
                "close": list(range(10, 10 + len(dates))),
                "volume": [100.0] * len(dates),
                "amount": [1000.0] * len(dates),
            }
        )
        return write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars)

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fake_update_from_tdx)

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m", "15m", "30m", "60m"),
            start="2026-06-05",
            end="2026-06-05",
            strict_after_update=False,
        ),
        mode="smart",
    )

    assert [call["timeframe"] for call in calls] == ["5m"]
    rows = result.table.set_index("timeframe")
    assert rows.loc["5m", "action"] == "fetched"
    assert rows.loc["15m", "action"] == "fetched"
    assert (data_root / "15m" / "qfq" / "000001.SZ.parquet").exists()
    assert (data_root / "30m" / "qfq" / "000001.SZ.parquet").exists()
    assert (data_root / "60m" / "qfq" / "000001.SZ.parquet").exists()
    for timeframe in ("15m", "30m", "60m"):
        coverage = query_coverage_runs(data_root=data_root, adjust="qfq", timeframes=(timeframe,), symbols=("000001.SZ",))
        assert not coverage.empty
        assert int(pd.to_numeric(coverage["file_size_bytes"], errors="coerce").max()) == 0


def test_preview_marks_high_intraday_timeframes_as_derived_from_5m(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [12.0],
            "low": [9.8],
            "close": [11.8],
            "volume": [100000.0],
            "amount": [1180000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=daily)
    plan = DataManagementService(data_root, adjust="qfq").preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m", "15m", "30m", "60m"),
            start="2026-06-05",
            end="2026-06-05",
        )
    )
    rows = plan.set_index("timeframe")

    assert rows.loc["5m", "action"] == "fetch"
    for timeframe in ("15m", "30m", "60m"):
        assert rows.loc[timeframe, "action"] == "derive"
        assert rows.loc[timeframe, "reason"] == "derived_from_source"
        assert "不会单独请求 TDX" in rows.loc[timeframe, "message"]


def test_smart_download_derives_high_intraday_when_5m_is_already_cached(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [12.0],
            "low": [9.8],
            "close": [11.8],
            "volume": [100000.0],
            "amount": [1180000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=daily)
    dates = pd.date_range("2026-06-05 09:35:00", "2026-06-05 10:30:00", freq="5min")
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": dates,
                "stock_code": ["000001.SZ"] * len(dates),
                "open": list(range(10, 10 + len(dates))),
                "high": list(range(11, 11 + len(dates))),
                "low": list(range(9, 9 + len(dates))),
                "close": list(range(10, 10 + len(dates))),
                "volume": [100.0] * len(dates),
                "amount": [1000.0] * len(dates),
            }
        ),
    )

    def fail_update_from_tdx(**_: object) -> pd.DataFrame:
        raise AssertionError("high intraday targets should be derived from cached 5m, not fetched from TDX")

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fail_update_from_tdx)

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m", "15m", "30m", "60m"),
            start="2026-06-05 09:35:00",
            end="2026-06-05 10:30:00",
            strict_after_update=False,
        ),
        mode="smart",
    )

    rows = result.table.set_index("timeframe")
    assert rows.loc["5m", "action"] == "cached"
    assert rows.loc["15m", "action"] == "fetched"
    assert (data_root / "15m" / "qfq" / "000001.SZ.parquet").exists()
    assert (data_root / "30m" / "qfq" / "000001.SZ.parquet").exists()
    assert (data_root / "60m" / "qfq" / "000001.SZ.parquet").exists()


def test_smart_download_uses_fast_coverage_audit_before_strict_quality_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-08"]),
            "stock_code": ["399006.SZ", "399006.SZ"],
            "open": [4040.0, 4060.0],
            "high": [4070.0, 4050.0],
            "low": [4010.0, 4090.0],
            "close": [4060.0, 4080.0],
            "volume": [1300000.0, 1200000.0],
            "amount": [520000000.0, 500000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    def fail_update_from_tdx(**_: object) -> pd.DataFrame:
        raise AssertionError("fast coverage audit should not refetch full window for quality-only issues")

    monkeypatch.setattr("tdx_downloader.data.repository.update_from_tdx", fail_update_from_tdx)

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-08",
        ),
        mode="smart",
    )

    assert result.table.loc[0, "action"] == "cached"
    assert result.table.loc[0, "before_status"] == "ok"


def test_smart_download_reports_daily_session_anchor_progress(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-03"]),
            "stock_code": ["399006.SZ"],
            "open": [4040.0],
            "high": [4070.0],
            "low": [4010.0],
            "close": [4060.0],
            "volume": [1300000.0],
            "amount": [520000000.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    events: list[dict[str, object]] = []

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("399006.SZ",),
            timeframes=("1d",),
            start="2026-06-03",
            end="2026-06-03",
        ),
        mode="smart",
        progress_callback=events.append,
    )

    stages = [str(event["stage"]) for event in events]
    assert stages[:2] == ["daily_sessions_start", "daily_sessions_done"]
    assert "audit_start" in stages
    assert "fetch_skipped" in stages
    assert result.summary["fetched_count"] == 0


def test_write_local_bars_separates_timeframe_directories_from_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "market"

    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=_bars())

    assert (data_root / "daily" / "qfq" / "000001.SZ.parquet").exists()
    assert (data_root / "5m" / "qfq" / "000001.SZ.parquet").exists()
    assert not (data_root / "qfq" / "000001.SZ.parquet").exists()


def test_write_local_bars_skips_rewrite_when_incoming_rows_are_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    bars = _bars()
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    path = data_root / "daily" / "qfq" / "000001.SZ.parquet"
    before_mtime = path.stat().st_mtime_ns
    original_read_parquet = pd.read_parquet

    def guarded_read_parquet(*args: object, **kwargs: object) -> pd.DataFrame:
        columns = tuple(kwargs.get("columns") or ())
        assert columns, "unchanged write should not read the whole parquet file"
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr("tdx_downloader.data.storage.pd.read_parquet", guarded_read_parquet)

    result = write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    assert result.loc[0, "new_rows"] == 0
    assert "跳过重写" in result.loc[0, "message"]
    assert path.stat().st_mtime_ns == before_mtime


def test_write_local_bars_rewrites_when_existing_rows_change(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = _bars()
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    path = data_root / "daily" / "qfq" / "000001.SZ.parquet"
    changed = bars.copy()
    changed.loc[0, "close"] = 12.34

    result = write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=changed)
    stored = pd.read_parquet(path)

    assert result.loc[0, "new_rows"] == 0
    assert float(stored.loc[stored["date"].eq(changed.loc[0, "date"]), "close"].iloc[0]) == 12.34


def test_write_local_bars_appends_new_tail_after_unchanged_overlap(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    existing = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-08"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.5],
            "high": [10.8, 10.9],
            "low": [9.9, 10.2],
            "close": [10.6, 10.7],
            "volume": [1000.0, 1200.0],
            "amount": [10600.0, 12840.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=existing)
    incoming = pd.concat(
        [
            existing.tail(1),
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-06-09"]),
                    "stock_code": ["000001.SZ"],
                    "open": [10.7],
                    "high": [11.0],
                    "low": [10.4],
                    "close": [10.9],
                    "volume": [1300.0],
                    "amount": [14170.0],
                }
            ),
        ],
        ignore_index=True,
    )
    original_read_parquet = pd.read_parquet

    def guarded_read_parquet(*args: object, **kwargs: object) -> pd.DataFrame:
        assert "filters" in kwargs, "overlap append should not read the whole parquet file"
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr("tdx_downloader.data.storage.pd.read_parquet", guarded_read_parquet)

    result = write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=incoming)

    assert result.loc[0, "new_rows"] == 1
    assert "追加新 K 线" in result.loc[0, "message"]


def test_write_local_bars_writes_tail_to_delta_sidecar(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    existing = pd.DataFrame(
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
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=existing)
    path = data_root / "5m" / "qfq" / "000001.SZ.parquet"
    before_mtime = path.stat().st_mtime_ns
    incoming = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 15:00:00"]),
            "stock_code": ["000001.SZ"],
            "open": [10.2],
            "high": [10.4],
            "low": [10.1],
            "close": [10.3],
            "volume": [1200.0],
            "amount": [12360.0],
        }
    )

    def fail_read_table(*_: object, **__: object) -> object:
        raise AssertionError("tail delta append should not read the full base parquet table")

    monkeypatch.setattr("tdx_downloader.data.storage.pq.read_table", fail_read_table)
    result = write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=incoming)
    monkeypatch.undo()
    loaded = load_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-09 14:50:00",
        end="2026-06-09 15:00:00",
    )

    assert result.loc[0, "new_rows"] == 1
    assert "delta" in result.loc[0, "message"]
    assert path.stat().st_mtime_ns == before_mtime
    assert len(list((data_root / "5m" / "qfq" / "000001.SZ.delta").glob("*.parquet"))) == 1
    assert loaded["date"].tolist() == pd.to_datetime(
        ["2026-06-09 14:50:00", "2026-06-09 14:55:00", "2026-06-09 15:00:00"]
    ).tolist()


def test_inventory_includes_tail_delta_sidecar(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
                "amount": [10100.0],
            }
        ),
    )
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.1],
                "high": [10.3],
                "low": [10.0],
                "close": [10.2],
                "volume": [1100.0],
                "amount": [11220.0],
            }
        ),
    )

    inventory = inventory_local_data(data_root=data_root, timeframes=("5m",), adjust="qfq", symbols=("000001.SZ",))

    assert int(inventory.loc[0, "rows"]) == 2
    assert pd.Timestamp(inventory.loc[0, "end"]) == pd.Timestamp("2026-06-09 15:00:00")


def test_strict_audit_reads_tail_delta_sidecar(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
                "amount": [10100.0],
            }
        ),
    )
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.1],
                "high": [10.3],
                "low": [10.0],
                "close": [10.2],
                "volume": [1100.0],
                "amount": [11220.0],
            }
        ),
    )

    audit = audit_local_data(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-09 14:55:00",
        end="2026-06-09 15:00:00",
    )

    assert audit.loc[0, "status"] == "ok"
    assert audit.loc[0, "missing_rows"] == 0
    assert audit.loc[0, "rows_in_window"] == 2


def test_strict_audit_counts_zero_liquidity_intraday_bars_as_covered(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    morning = pd.date_range("2026-06-12 09:35:00", "2026-06-12 11:30:00", freq="5min")
    afternoon = pd.date_range("2026-06-12 13:05:00", "2026-06-12 15:00:00", freq="5min")
    dates = morning.append(afternoon)
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": dates,
                "stock_code": ["000004.SZ"] * len(dates),
                "open": [2.76] * len(dates),
                "high": [2.76] * len(dates),
                "low": [2.76] * len(dates),
                "close": [2.76] * len(dates),
                "volume": [0.0] * len(dates),
                "amount": [0.0] * len(dates),
            }
        ),
    )

    audit = audit_local_data(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000004.SZ",),
        start="2026-06-12",
        end="2026-06-12",
    )
    gaps = data_gap_episodes(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000004.SZ",),
        start="2026-06-12",
        end="2026-06-12",
    )

    assert audit.loc[0, "status"] == "ok"
    assert int(audit.loc[0, "rows_in_window"]) == 48
    assert int(audit.loc[0, "expected_rows"]) == 48
    assert int(audit.loc[0, "missing_rows"]) == 0
    assert int(audit.loc[0, "zero_volume_amount_rows"]) == 48
    assert gaps.empty


def test_preview_treats_zero_liquidity_lunch_shift_as_full_intraday_coverage(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    morning = pd.date_range("2026-06-12 09:35:00", "2026-06-12 11:25:00", freq="5min")
    afternoon = pd.date_range("2026-06-12 13:00:00", "2026-06-12 15:00:00", freq="5min")
    dates = morning.append(afternoon)
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": dates,
                "stock_code": ["002529.SZ"] * len(dates),
                "open": [1.0] * len(dates),
                "high": [1.0] * len(dates),
                "low": [1.0] * len(dates),
                "close": [1.0] * len(dates),
                "volume": [0.0] * len(dates),
                "amount": [0.0] * len(dates),
            }
        ),
    )

    plan = DataManagementService(data_root, adjust="qfq").preview_download_plan(
        DataDownloadConfig(
            symbols=("002529.SZ",),
            timeframes=("5m",),
            start="2026-06-12",
            end="2026-06-12",
        )
    )

    row = plan.loc[plan["timeframe"].eq("5m")].iloc[0]
    assert row["action"] == "cached"
    assert int(row["missing_rows"]) == 0
    assert float(row["coverage_ratio"]) == 1.0


def test_coverage_refresh_reads_tail_delta_sidecar(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
                "amount": [10100.0],
            }
        ),
    )
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.1],
                "high": [10.3],
                "low": [10.0],
                "close": [10.2],
                "volume": [1100.0],
                "amount": [11220.0],
            }
        ),
    )

    coverage = refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))

    assert not coverage.empty
    assert pd.Timestamp(coverage["end_at"].max()) == pd.Timestamp("2026-06-09 15:00:00")


def test_inventory_discovers_delta_only_sidecar(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.1],
                "high": [10.3],
                "low": [10.0],
                "close": [10.2],
                "volume": [1100.0],
                "amount": [11220.0],
            }
        ),
    )

    inventory = inventory_local_data(data_root=data_root, timeframes=("5m",), adjust="qfq")

    assert len(inventory) == 1
    assert inventory.loc[0, "stock_code"] == "000001.SZ"
    assert inventory.loc[0, "status"] == "cached"
    assert int(inventory.loc[0, "rows"]) == 1


def test_delta_append_without_catalog_does_not_double_count_rows(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ", "000001.SZ"],
                "open": [10.0, 10.1],
                "high": [10.2, 10.3],
                "low": [9.9, 10.0],
                "close": [10.1, 10.2],
                "volume": [1000.0, 1100.0],
                "amount": [10100.0, 11220.0],
            }
        ),
    )

    inventory = inventory_local_data(data_root=data_root, timeframes=("5m",), adjust="qfq")

    assert len(inventory) == 1
    assert int(inventory.loc[0, "rows"]) == 2


def test_delta_append_overlap_counts_only_new_unique_rows(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00"]),
                "stock_code": ["000001.SZ"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
                "amount": [10100.0],
            }
        ),
    )
    result = append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ", "000001.SZ"],
                "open": [10.4, 10.2],
                "high": [10.6, 10.4],
                "low": [10.3, 10.1],
                "close": [10.5, 10.3],
                "volume": [1500.0, 1200.0],
                "amount": [15750.0, 12360.0],
            }
        ),
    )
    inventory = inventory_local_data(data_root=data_root, timeframes=("5m",), adjust="qfq", symbols=("000001.SZ",))
    loaded = load_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-09 14:55:00",
        end="2026-06-09 15:00:00",
    )

    assert int(result.loc[0, "new_rows"]) == 1
    assert int(result.loc[0, "rows"]) == 2
    assert int(inventory.loc[0, "rows"]) == 2
    assert len(loaded) == 2
    assert float(loaded.loc[loaded["date"].eq(pd.Timestamp("2026-06-09 14:55:00")), "close"].iloc[0]) == 10.5


def test_delta_append_batches_coverage_lookup_for_new_row_counts(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    base_dates = pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 14:55:00"])
    write_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": base_dates,
                "stock_code": ["000001.SZ", "000002.SZ"],
                "open": [10.0, 20.0],
                "high": [10.2, 20.2],
                "low": [9.9, 19.9],
                "close": [10.1, 20.1],
                "volume": [1000.0, 2000.0],
                "amount": [10100.0, 40200.0],
            }
        ),
    )
    calls: list[tuple[str, ...]] = []
    original_query = repository_module.query_coverage_runs

    def tracked_query(**kwargs: object) -> pd.DataFrame:
        if kwargs.get("timeframes") == ("5m",):
            calls.append(tuple(str(item) for item in kwargs.get("symbols", ())))  # type: ignore[arg-type]
        return original_query(**kwargs)

    monkeypatch.setattr("tdx_downloader.data.storage.query_coverage_runs", tracked_query)

    result = append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2026-06-09 14:55:00",
                        "2026-06-09 15:00:00",
                        "2026-06-09 14:55:00",
                        "2026-06-09 15:00:00",
                    ]
                ),
                "stock_code": ["000001.SZ", "000001.SZ", "000002.SZ", "000002.SZ"],
                "open": [10.4, 10.2, 20.4, 20.2],
                "high": [10.6, 10.4, 20.6, 20.4],
                "low": [10.3, 10.1, 20.3, 20.1],
                "close": [10.5, 10.3, 20.5, 20.3],
                "volume": [1500.0, 1200.0, 2500.0, 2200.0],
                "amount": [15750.0, 12360.0, 51250.0, 44660.0],
            }
        ),
    )

    assert len(calls) == 1
    assert calls[0] == ("000001.SZ", "000002.SZ")
    assert int(result["new_rows"].sum()) == 2


def test_delta_append_falls_back_per_symbol_when_batch_coverage_is_missing(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 14:55:00"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.9],
            "close": [10.1],
            "volume": [1000.0],
            "amount": [10100.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=base, refresh_coverage=False)
    append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 15:00:00"]),
                "stock_code": ["000001.SZ", "000001.SZ"],
                "open": [10.4, 10.2],
                "high": [10.6, 10.4],
                "low": [10.3, 10.1],
                "close": [10.5, 10.3],
                "volume": [1500.0, 1200.0],
                "amount": [15750.0, 12360.0],
            }
        ),
    )
    result = append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 15:05:00"]),
                "stock_code": ["000001.SZ", "000001.SZ"],
                "open": [10.7, 10.3],
                "high": [10.9, 10.5],
                "low": [10.6, 10.2],
                "close": [10.8, 10.4],
                "volume": [1600.0, 1300.0],
                "amount": [17280.0, 13520.0],
            }
        ),
    )

    assert int(result.loc[0, "new_rows"]) == 1


def test_partial_coverage_upsert_replaces_touched_key_without_duplicate_growth(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 15:00:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.1, 10.2],
            "high": [10.3, 10.4],
            "low": [10.0, 10.1],
            "close": [10.2, 10.3],
            "volume": [1100.0, 1200.0],
            "amount": [11220.0, 12360.0],
        }
    )

    first = upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars)
    second = upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars)
    coverage = query_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))

    assert len(first) == 1
    assert len(second) == 0
    assert len(coverage) == 1
    assert int(coverage.loc[0, "row_count"]) == 2


def test_catalog_window_queries_treat_date_only_end_as_full_day(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 14:55:00", "2026-06-09 15:00:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.1, 10.2],
            "high": [10.3, 10.4],
            "low": [10.0, 10.1],
            "close": [10.2, 10.3],
            "volume": [1100.0, 1200.0],
            "amount": [11220.0, 12360.0],
        }
    )
    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars)
    upsert_market_data_parts(
        data_root=data_root,
        parts=pd.DataFrame(
            [
                {
                    "part_id": "part-20260609",
                    "job_id": "job-20260609",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "trade_month": "2026-06",
                    "path": str(data_root / "5m" / "qfq" / "_delta_parts" / "trade_month=2026-06" / "part.parquet"),
                    "rows": 2,
                    "min_at": "2026-06-09T14:55:00",
                    "max_at": "2026-06-09T15:00:00",
                    "file_size_bytes": 100,
                    "sha256": "",
                    "commit_version": 1,
                    "state": "active",
                    "created_at": "2026-06-09T15:01:00",
                }
            ]
        ),
        part_symbols=pd.DataFrame(
            [
                {
                    "part_id": "part-20260609",
                    "stock_code": "000001.SZ",
                    "min_at": "2026-06-09T14:55:00",
                    "max_at": "2026-06-09T15:00:00",
                    "rows": 2,
                }
            ]
        ),
    )
    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-09 14:55:00"),
                    "end_at": pd.Timestamp("2026-06-09 15:00:00"),
                    "missing_rows": 2,
                    "status": "provider_partial_gap",
                    "last_fetch_rows": 0,
                    "message": "test gap",
                }
            ]
        ),
    )

    coverage = query_coverage_runs(
        data_root=data_root,
        adjust="qfq",
        timeframes=("5m",),
        symbols=("000001.SZ",),
        start="2026-06-09",
        end="2026-06-09",
    )
    parts = query_market_data_part_symbols(
        data_root=data_root,
        adjust="qfq",
        timeframes=("5m",),
        symbols=("000001.SZ",),
        start="2026-06-09",
        end="2026-06-09",
    )
    gaps = query_unresolved_gaps(
        data_root=data_root,
        adjust="qfq",
        timeframes=("5m",),
        symbols=("000001.SZ",),
        start="2026-06-09",
        end="2026-06-09",
    )

    assert len(coverage) == 1
    assert len(parts) == 1
    assert len(gaps) == 1


def test_partial_coverage_merge_keeps_intraday_breaks_out_of_row_count(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    first = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-08 15:00:00"]),
            "stock_code": ["000001.SZ"],
            "open": [10.1],
            "high": [10.3],
            "low": [10.0],
            "close": [10.2],
            "volume": [1100.0],
            "amount": [11220.0],
        }
    )
    second = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-09 09:35:00", "2026-06-09 11:30:00", "2026-06-09 13:05:00"]),
            "stock_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [10.2, 10.3, 10.4],
            "high": [10.4, 10.5, 10.6],
            "low": [10.1, 10.2, 10.3],
            "close": [10.3, 10.4, 10.5],
            "volume": [1200.0, 1300.0, 1400.0],
            "amount": [12360.0, 13520.0, 14700.0],
        }
    )

    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=first)
    coverage = upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=second)
    stored = query_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))

    assert int(stored["row_count"].sum()) == 4
    assert pd.Timestamp(stored["start_at"].min()) == pd.Timestamp("2026-06-08 15:00:00")
    assert pd.Timestamp(coverage["end_at"].max()) == pd.Timestamp("2026-06-09 13:05:00")


def test_delta_sidecar_summary_uses_configured_compaction_threshold(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    for index in range(2):
        append_delta_bars(
            data_root=data_root,
            timeframe="5m",
            adjust="qfq",
            bars=pd.DataFrame(
                {
                    "date": pd.to_datetime([f"2026-06-09 14:{50 + index * 5:02d}:00"]),
                    "stock_code": ["000001.SZ"],
                    "open": [10.1 + index],
                    "high": [10.3 + index],
                    "low": [10.0 + index],
                    "close": [10.2 + index],
                    "volume": [1100.0],
                    "amount": [11220.0],
                }
            ),
        )

    summary = delta_sidecar_summary(data_root=data_root, adjust="qfq", timeframes=("5m",))

    assert summary["summary"]["symbol_count"] == 1
    assert summary["summary"]["part_count"] == 2
    assert summary["summary"]["file_size_bytes"] > 0
    assert summary["summary"]["needs_compaction"] is False
    assert summary["by_timeframe"][0]["timeframe"] == "5m"
    assert summary["by_timeframe"][0]["part_count"] == 2
    assert summary["by_timeframe"][0]["needs_compaction"] is False

    pressured = delta_sidecar_summary(data_root=data_root, adjust="qfq", timeframes=("5m",), part_threshold=2)

    assert pressured["summary"]["needs_compaction"] is True
    assert pressured["by_timeframe"][0]["needs_compaction"] is True


def test_compact_delta_sidecars_merges_base_and_deltas(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    base = pd.DataFrame(
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
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=base)
    append_delta_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-09 15:00:00", "2026-06-09 14:55:00"]),
                "stock_code": ["000001.SZ", "000001.SZ"],
                "open": [10.2, 10.4],
                "high": [10.4, 10.6],
                "low": [10.1, 10.3],
                "close": [10.3, 10.5],
                "volume": [1200.0, 1500.0],
                "amount": [12360.0, 15750.0],
            }
        ),
    )
    delta_root = data_root / "5m" / "qfq" / "000001.SZ.delta"
    assert delta_root.exists()

    result = compact_delta_sidecars(data_root=data_root, timeframe="5m", adjust="qfq", symbols=("000001.SZ",))
    loaded = load_local_bars(
        data_root=data_root,
        timeframe="5m",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-06-09 14:50:00",
        end="2026-06-09 15:00:00",
    )
    inventory = inventory_local_data(data_root=data_root, timeframes=("5m",), adjust="qfq", symbols=("000001.SZ",))
    coverage = refresh_coverage_runs(data_root=data_root, adjust="qfq", timeframes=("5m",), symbols=("000001.SZ",))

    assert result.loc[0, "status"] == "success"
    assert not delta_root.exists()
    assert loaded["date"].tolist() == pd.to_datetime(
        ["2026-06-09 14:50:00", "2026-06-09 14:55:00", "2026-06-09 15:00:00"]
    ).tolist()
    assert float(loaded.loc[loaded["date"].eq(pd.Timestamp("2026-06-09 14:55:00")), "close"].iloc[0]) == 10.5
    assert int(inventory.loc[0, "rows"]) == 3
    assert pd.Timestamp(coverage["end_at"].max()) == pd.Timestamp("2026-06-09 15:00:00")


def test_inventory_uses_parquet_metadata_for_standard_cache_files(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market" / "daily"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())

    def fail_read_parquet(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("inventory should not read parquet data columns for standard cache files")

    monkeypatch.setattr("tdx_downloader.data.inventory.pd.read_parquet", fail_read_parquet)

    result = inventory_local_data(
        data_root=data_root,
        adjust="qfq",
        timeframes=("1d",),
        symbols=("000001.SZ",),
    )

    assert result.loc[0, "status"] == "cached"
    assert result.loc[0, "rows"] == 2
    assert result.loc[0, "start"] == pd.Timestamp("2026-05-25 10:30:00")
    assert result.loc[0, "end"] == pd.Timestamp("2026-05-25 11:30:00")


def test_preview_download_plan_uses_catalog_metadata_without_reading_parquet_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=True)

    def fail_read_parquet(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("preview plan should use catalog metadata, not parquet data pages")

    monkeypatch.setattr("tdx_downloader.data.audit.pd.read_parquet", fail_read_parquet)
    monkeypatch.setattr("tdx_downloader.data.storage.pd.read_parquet", fail_read_parquet)
    monkeypatch.setattr("tdx_downloader.data.inventory.pd.read_parquet", fail_read_parquet)

    plan = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-05-25",
            end="2026-05-25",
        )
    )

    assert plan.loc[0, "action"] == "cached"
    assert plan.loc[0, "before_status"] == "ok"
    assert "metadata-only" in plan.loc[0, "message"]


def test_preview_download_plan_does_not_refresh_catalog_or_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=True)

    def fail_write_refresh(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("preview plan must be metadata read-only")

    monkeypatch.setattr("tdx_downloader.data.repository.refresh_coverage_runs", fail_write_refresh)
    monkeypatch.setattr("tdx_downloader.data.repository.upsert_catalog_records", fail_write_refresh)

    plan = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-05-25",
            end="2026-05-25",
        )
    )

    assert plan.loc[0, "action"] == "cached"
    assert plan.loc[0, "catalog_status"] == "cached"
    assert plan.loc[0, "coverage_status"] == "coverage_ready"


def test_preview_download_plan_uses_catalog_boundary_when_coverage_index_is_empty(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05", "2026-06-08"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.5],
            "high": [10.8, 10.9],
            "low": [9.9, 10.2],
            "close": [10.6, 10.7],
            "volume": [1000.0, 1200.0],
            "amount": [10600.0, 12840.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)

    plan = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-09",
        )
    )

    assert plan.loc[0, "action"] == "fetch"
    assert plan.loc[0, "reason"] == "coverage_gap"
    assert plan.loc[0, "catalog_status"] == "cached"
    assert plan.loc[0, "coverage_status"] == "coverage_partial"
    assert plan.loc[0, "expected_rows"] == 3
    assert plan.loc[0, "missing_rows"] == 1
    assert plan.loc[0, "first_missing_at"] == pd.Timestamp("2026-06-09")
    assert plan.loc[0, "last_missing_at"] == pd.Timestamp("2026-06-09")


def test_preview_intraday_plan_without_coverage_index_does_not_claim_zero_missing(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05 09:35:00", "2026-06-05 09:40:00"]),
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
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("5m",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)

    plan = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-05",
            end="2026-06-05 10:00:00",
        )
    )

    row = plan.loc[plan["timeframe"].eq("5m")].iloc[0]
    assert row["action"] == "fetch"
    assert row["reason"] == "coverage_unknown"
    assert row["coverage_status"] == "coverage_unknown"
    assert row["missing_rows"] == row["expected_rows"]
    assert row["missing_rows"] > 0
    assert "精准覆盖索引缺失" in row["message"]


def test_preview_intraday_plan_distinguishes_indexed_window_gap_from_unknown(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05 09:35:00", "2026-06-05 09:40:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000.0, 1100.0],
            "amount": [10100.0, 11220.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars, refresh_coverage=True)

    plan = DataManagementService(data_root, adjust="qfq").preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-06",
            end="2026-06-08",
        )
    )

    row = plan.loc[plan["timeframe"].eq("5m")].iloc[0]
    assert row["action"] == "fetch"
    assert row["reason"] == "no_window_data"
    assert row["coverage_status"] == "coverage_unavailable"
    assert row["missing_rows"] == row["expected_rows"]
    assert "覆盖索引已建立" in row["message"]


def test_preview_intraday_plan_includes_full_date_end_coverage(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-11", "2026-06-12"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000.0, 1100.0],
            "amount": [10100.0, 11220.0],
        }
    )
    intraday_dates = []
    for day in ("2026-06-11", "2026-06-12"):
        session = pd.Timestamp(day)
        for start_label, end_label in (("09:30", "11:30"), ("13:00", "15:00")):
            cursor = pd.Timestamp(f"{day} {start_label}") + pd.Timedelta(minutes=5)
            end_at = pd.Timestamp(f"{day} {end_label}")
            while cursor <= end_at:
                intraday_dates.append(cursor)
                cursor += pd.Timedelta(minutes=5)
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(intraday_dates),
            "stock_code": ["000001.SZ"] * len(intraday_dates),
            "open": [10.0] * len(intraday_dates),
            "high": [10.2] * len(intraday_dates),
            "low": [9.9] * len(intraday_dates),
            "close": [10.1] * len(intraday_dates),
            "volume": [1000.0] * len(intraday_dates),
            "amount": [10100.0] * len(intraday_dates),
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=daily)
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=bars)

    plan = DataManagementService(data_root, adjust="qfq").preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-11 09:35:00",
            end="2026-06-12",
        )
    )

    row = plan.loc[plan["timeframe"].eq("5m")].iloc[0]
    assert row["coverage_status"] == "coverage_ready"
    assert row["missing_rows"] == 0
    assert row["action"] == "cached"


def test_prepare_summary_rows_reports_rows_written_as_new_rows() -> None:
    before = pd.DataFrame(
        [
            {
                "stock_code": "000001.SZ",
                "timeframe": "5m",
                "adjust": "qfq",
                "status": "ok",
                "exists": True,
                "rows_total": 3552,
                "rows_in_window": 0,
                "expected_rows": 48,
                "missing_rows": 48,
                "coverage_ratio": 0.0,
                "max_missing_gap_minutes": 240,
                "first_missing_at": pd.Timestamp("2026-06-12 09:35:00"),
                "last_missing_at": pd.Timestamp("2026-06-12 15:00:00"),
                "max_missing_gap_start_at": pd.Timestamp("2026-06-12 09:35:00"),
                "max_missing_gap_end_at": pd.Timestamp("2026-06-12 15:00:00"),
                "start": pd.Timestamp("2026-05-06 09:35:00"),
                "end": pd.Timestamp("2026-06-11 15:00:00"),
                "requested_start": pd.Timestamp("2026-06-12 00:00:00"),
                "requested_end": pd.Timestamp("2026-06-12 23:59:59"),
                "invalid_date_rows": 0,
                "invalid_symbol_rows": 0,
                "duplicate_rows": 0,
                "null_ohlc_rows": 0,
                "non_positive_price_rows": 0,
                "inconsistent_ohlc_rows": 0,
                "null_volume_amount_rows": 0,
                "zero_volume_amount_rows": 0,
                "negative_volume_amount_rows": 0,
                "missing_columns": "",
                "path": "/tmp/000001.SZ.parquet",
                "message": "",
            }
        ]
    )
    after = before.copy()
    after.loc[0, ["rows_in_window", "missing_rows", "coverage_ratio", "max_missing_gap_minutes"]] = [48, 0, 1.0, 0]
    after.loc[0, ["first_missing_at", "last_missing_at", "max_missing_gap_start_at", "max_missing_gap_end_at"]] = pd.NaT
    write_summary = pd.DataFrame(
        [{"symbol": "000001.SZ", "rows": 3600, "new_rows": 48, "path": "/tmp/000001.SZ.parquet"}]
    )

    rows = repository_module._prepare_summary_rows(
        before=before,
        after=after,
        write_summary=write_summary,
        fetched_symbols={"000001.SZ"},
        min_coverage_ratio=None,
    )

    assert rows[0]["rows_written"] == 48
    assert rows[0]["new_rows"] == 48


def test_fetch_window_groups_respects_max_symbols_per_group() -> None:
    rows = []
    for index in range(5):
        rows.append(
            {
                "stock_code": f"00000{index}.SZ",
                "timeframe": "5m",
                "adjust": "qfq",
                "status": "ok",
                "exists": True,
                "rows_total": 0,
                "rows_in_window": 0,
                "expected_rows": 48,
                "missing_rows": 48,
                "coverage_ratio": 0.0,
                "max_missing_gap_minutes": 240,
                "first_missing_at": pd.Timestamp("2026-06-12 09:35:00"),
                "last_missing_at": pd.Timestamp("2026-06-12 15:00:00"),
                "max_missing_gap_start_at": pd.Timestamp("2026-06-12 09:35:00"),
                "max_missing_gap_end_at": pd.Timestamp("2026-06-12 15:00:00"),
                "start": pd.NaT,
                "end": pd.NaT,
                "requested_start": pd.Timestamp("2026-06-12 00:00:00"),
                "requested_end": pd.Timestamp("2026-06-12 23:59:59"),
                "invalid_date_rows": 0,
                "invalid_symbol_rows": 0,
                "duplicate_rows": 0,
                "null_ohlc_rows": 0,
                "non_positive_price_rows": 0,
                "inconsistent_ohlc_rows": 0,
                "null_volume_amount_rows": 0,
                "zero_volume_amount_rows": 0,
                "negative_volume_amount_rows": 0,
                "missing_columns": "",
                "path": "",
                "message": "",
            }
        )

    groups = repository_module._fetch_window_groups_from_audit(
        pd.DataFrame(rows),
        min_coverage_ratio=None,
        max_symbols_per_group=2,
    )

    assert [len(group.symbols) for group in groups] == [2, 2, 1]
    assert {group.start for group in groups} == {"2026-06-12 09:35:00"}
    assert {group.end for group in groups} == {"2026-06-12 15:05:00"}


def test_smart_download_preflight_does_not_refresh_catalog_or_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=_bars())
    service = DataManagementService(data_root, adjust="qfq")
    service.cache_snapshot(timeframes=("1d",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=True)

    def fail_write_refresh(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("smart download preflight must be metadata read-only")

    def fail_tdx_fetch(*_: object, **__: object) -> pd.DataFrame:
        raise AssertionError("covered smart download must not call TDX")

    monkeypatch.setattr("tdx_downloader.data.repository.refresh_coverage_runs", fail_write_refresh)
    monkeypatch.setattr("tdx_downloader.data.repository.upsert_catalog_records", fail_write_refresh)
    monkeypatch.setattr("tdx_downloader.data.tdx.fetch_tdx_bars", fail_tdx_fetch)

    result = service.download(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-05-25",
            end="2026-05-25",
        ),
        mode="smart",
    )

    assert result.summary["cached_count"] == 1.0
    assert result.summary["fetched_count"] == 0.0
    assert result.table.loc[0, "action"] == "cached"


def test_preview_download_plan_uses_short_metadata_read_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"
    service = DataManagementService(data_root, adjust="qfq")
    observed: list[float | None] = []

    def fake_query_coverage_runs(**kwargs: object) -> pd.DataFrame:
        observed.append(kwargs.get("read_timeout_seconds"))  # type: ignore[arg-type]
        return pd.DataFrame(
            {
                "stock_code": ["000001.SZ"],
                "timeframe": ["1d"],
                "adjust": ["qfq"],
                "start_at": ["2026-05-25T00:00:00"],
                "end_at": ["2026-05-25T00:00:00"],
                "row_count": [1],
                "file_size_bytes": [10],
                "mtime_ns": [100],
                "path": [str(data_root / "daily" / "qfq" / "000001.SZ.parquet")],
                "updated_at": ["2026-05-25T00:00:00"],
            }
        )

    def fake_query_catalog(**kwargs: object) -> pd.DataFrame:
        observed.append(kwargs.get("read_timeout_seconds"))  # type: ignore[arg-type]
        return pd.DataFrame(
            {
                "cache_key": ["000001.SZ|stock|price|ohlcv|1d|qfq|x"],
                "stock_code": ["000001.SZ"],
                "stock_name": [""],
                "asset_type": ["stock"],
                "data_kind": ["price"],
                "indicator": ["ohlcv"],
                "timeframe": ["1d"],
                "adjust": ["qfq"],
                "storage_format": ["parquet"],
                "status": ["cached"],
                "rows": [1],
                "start_at": ["2026-05-25T00:00:00"],
                "end_at": ["2026-05-25T00:00:00"],
                "file_size_bytes": [10],
                "modified_at": ["2026-05-25T00:00:00"],
                "path": [str(data_root / "daily" / "qfq" / "000001.SZ.parquet")],
                "message": [""],
            }
        )

    monkeypatch.setattr("tdx_downloader.data.repository.query_coverage_runs", fake_query_coverage_runs)
    monkeypatch.setattr("tdx_downloader.data.repository.query_catalog", fake_query_catalog)

    plan = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-05-25",
            end="2026-05-25",
        )
    )

    assert plan.loc[0, "action"] == "cached"
    assert observed
    assert set(observed) == {1.0}


def test_preview_download_plan_cache_invalidates_when_partial_coverage_window_changes(
    tmp_path: Path,
) -> None:
    repository_module._PLAN_FAST_CACHE.clear()
    data_root = tmp_path / "market"
    service = DataManagementService(data_root, adjust="qfq")
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-05"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [10.8],
            "low": [9.9],
            "close": [10.6],
            "volume": [1000.0],
            "amount": [10600.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=base, refresh_coverage=False)
    service.cache_snapshot(timeframes=("1d",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)
    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=base)

    first = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-08",
        )
    )
    upsert_partial_coverage_runs_from_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-08"]),
                "stock_code": ["000001.SZ"],
                "open": [10.7],
                "high": [10.9],
                "low": [10.5],
                "close": [10.8],
                "volume": [1200.0],
                "amount": [12960.0],
            }
        ),
    )
    second = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-06-05",
            end="2026-06-08",
        )
    )

    assert first.loc[0, "missing_rows"] == 1
    assert second.loc[0, "missing_rows"] == 0
    assert second.loc[0, "action"] == "cached"


def test_unresolved_gap_upsert_tracks_retry_count(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    records = pd.DataFrame(
        [
            {
                "stock_code": "000001.SZ",
                "timeframe": "5m",
                "adjust": "qfq",
                "start_at": pd.Timestamp("2026-06-12 11:30:00"),
                "end_at": pd.Timestamp("2026-06-12 11:35:00"),
                "missing_rows": 1,
                "status": "provider_partial_gap",
                "last_fetch_rows": 47,
                "message": "still missing",
            }
        ]
    )

    first = upsert_unresolved_gaps(data_root=data_root, records=records)
    second = upsert_unresolved_gaps(data_root=data_root, records=records)
    stored = query_unresolved_gaps(data_root=data_root, symbols=("000001.SZ",), adjust="qfq", timeframes=("5m",))

    assert int(first.loc[0, "retry_count"]) == 1
    assert int(second.loc[0, "retry_count"]) == 2
    assert len(stored) == 1
    assert int(stored.loc[0, "retry_count"]) == 2


def test_preview_plan_marks_known_provider_gap_unresolved(tmp_path: Path) -> None:
    repository_module._PLAN_FAST_CACHE.clear()
    data_root = tmp_path / "market"
    service = DataManagementService(data_root, adjust="qfq")
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-12 09:35:00", "2026-06-12 09:40:00"]),
            "stock_code": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000.0, 1100.0],
            "amount": [10100.0, 11220.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=base, refresh_coverage=False)
    service.cache_snapshot(timeframes=("5m",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)
    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=base)
    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-12 09:45:00"),
                    "end_at": pd.Timestamp("2026-06-12 15:05:00"),
                    "missing_rows": 46,
                    "status": "provider_partial_gap",
                    "last_fetch_rows": 2,
                    "message": "provider returned partial data",
                }
            ]
        ),
    )

    plan = service.preview_download_plan(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("5m",),
            start="2026-06-12",
            end="2026-06-12",
        )
    )

    row = plan.loc[plan["timeframe"].eq("5m")].iloc[0]
    assert row["action"] == "unresolved"
    assert row["reason"] == "provider_partial_gap"
    assert row["coverage_status"] == "provider_unresolved"


def test_prepare_marks_known_provider_gap_unresolved(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-11"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.9],
            "close": [10.1],
            "volume": [1000.0],
            "amount": [10100.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=base, refresh_coverage=False)
    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=base)
    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-12"),
                    "end_at": pd.Timestamp("2026-06-12"),
                    "missing_rows": 1,
                    "status": "provider_no_data",
                    "last_fetch_rows": 0,
                    "message": "provider returned no data",
                }
            ]
        ),
    )

    result = DataManagementService(data_root, adjust="qfq").download(
        DataDownloadConfig(
            symbols=("000001.SZ",),
            timeframes=("1d",),
            start="2026-06-12",
            end="2026-06-12",
            strict_after_update=False,
        ),
        mode="smart",
    )

    row = result.table.loc[result.table["timeframe"].eq("1d")].iloc[0]
    assert row["action"] == "unresolved"
    assert row["after_status"] == "provider_no_data"
    assert "真实请求 TDX 后仍未补齐" in row["message"]
    assert result.summary["cached_count"] == 0.0


def test_prepare_keeps_current_fetch_action_when_provider_gap_is_recorded(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    row = {
        "stock_code": "000001.SZ",
        "timeframe": "1d",
        "adjust": "qfq",
        "action": "fetched",
        "before_status": "coverage_gap",
        "after_status": "provider_no_data",
        "rows_written": 0,
        "new_rows": 0,
        "before_coverage_ratio": 0.0,
        "after_coverage_ratio": 0.0,
        "coverage_ratio": 0.0,
        "before_missing_rows": 1,
        "after_missing_rows": 1,
        "missing_rows": 1,
        "before_max_missing_gap_minutes": 1440,
        "after_max_missing_gap_minutes": 1440,
        "before_first_missing_at": pd.Timestamp("2026-06-12"),
        "before_last_missing_at": pd.Timestamp("2026-06-12"),
        "after_first_missing_at": pd.Timestamp("2026-06-12"),
        "after_last_missing_at": pd.Timestamp("2026-06-12"),
        "first_missing_at": pd.Timestamp("2026-06-12"),
        "last_missing_at": pd.Timestamp("2026-06-12"),
        "before_max_missing_gap_start_at": pd.Timestamp("2026-06-12"),
        "before_max_missing_gap_end_at": pd.Timestamp("2026-06-12"),
        "after_max_missing_gap_start_at": pd.Timestamp("2026-06-12"),
        "after_max_missing_gap_end_at": pd.Timestamp("2026-06-12"),
        "max_missing_gap_start_at": pd.Timestamp("2026-06-12"),
        "max_missing_gap_end_at": pd.Timestamp("2026-06-12"),
        "path": "",
        "message": "真实请求 TDX 后仍存在缺口。",
    }
    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "1d",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-12"),
                    "end_at": pd.Timestamp("2026-06-12"),
                    "missing_rows": 1,
                    "status": "provider_no_data",
                    "last_fetch_rows": 0,
                    "message": "provider returned no data",
                }
            ]
        ),
    )

    result = repository_module._apply_unresolved_gaps_to_prepare_result(
        pd.DataFrame([row]),
        data_root=data_root,
        adjust="qfq",
        symbols=["000001.SZ"],
        timeframes=["1d"],
        start="2026-06-12",
        end="2026-06-12",
    )

    assert result.loc[0, "action"] == "fetched"
    assert result.loc[0, "after_status"] == "provider_no_data"


def test_fetch_window_groups_skip_known_unresolved_provider_gap(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    rows = [
        {
            "stock_code": "000001.SZ",
            "timeframe": "5m",
            "adjust": "qfq",
            "status": "ok",
            "rows_in_window": 2,
            "expected_rows": 48,
            "missing_rows": 46,
            "coverage_ratio": 2 / 48,
            "max_missing_gap_minutes": 230,
            "first_missing_at": pd.Timestamp("2026-06-12 09:45:00"),
            "last_missing_at": pd.Timestamp("2026-06-12 15:00:00"),
            "max_missing_gap_start_at": pd.Timestamp("2026-06-12 09:45:00"),
            "max_missing_gap_end_at": pd.Timestamp("2026-06-12 15:00:00"),
            "missing_windows": [(pd.Timestamp("2026-06-12 09:45:00"), pd.Timestamp("2026-06-12 15:00:00"), 46)],
            "expected_timestamps": [],
            "missing_timestamps": [],
            "path": "",
            "message": "",
        }
    ]
    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-12 09:45:00"),
                    "end_at": pd.Timestamp("2026-06-12 15:00:00"),
                    "missing_rows": 46,
                    "status": "provider_partial_gap",
                    "last_fetch_rows": 2,
                    "message": "provider returned partial data",
                }
            ]
        ),
    )

    groups = repository_module._fetch_window_groups_from_audit(
        pd.DataFrame(rows),
        min_coverage_ratio=None,
        max_symbols_per_group=100,
        data_root=data_root,
        adjust="qfq",
        start="2026-06-12",
        end="2026-06-12",
    )

    assert groups == []


def test_preview_plan_cache_invalidates_when_unresolved_gap_is_added(tmp_path: Path) -> None:
    repository_module._PLAN_FAST_CACHE.clear()
    data_root = tmp_path / "market"
    service = DataManagementService(data_root, adjust="qfq")
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-12 09:35:00"]),
            "stock_code": ["000001.SZ"],
            "open": [10.0],
            "high": [10.2],
            "low": [9.9],
            "close": [10.1],
            "volume": [1000.0],
            "amount": [10100.0],
        }
    )
    write_local_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=base, refresh_coverage=False)
    service.cache_snapshot(timeframes=("5m",), symbols=("000001.SZ",), rebuild_catalog=True, refresh_coverage=False)
    upsert_partial_coverage_runs_from_bars(data_root=data_root, timeframe="5m", adjust="qfq", bars=base)
    config = DataDownloadConfig(
        symbols=("000001.SZ",),
        timeframes=("5m",),
        start="2026-06-12",
        end="2026-06-12",
    )
    first = service.preview_download_plan(config)

    upsert_unresolved_gaps(
        data_root=data_root,
        records=pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "timeframe": "5m",
                    "adjust": "qfq",
                    "start_at": pd.Timestamp("2026-06-12 09:40:00"),
                    "end_at": pd.Timestamp("2026-06-12 15:05:00"),
                    "missing_rows": 47,
                    "status": "provider_no_data",
                    "last_fetch_rows": 0,
                    "message": "provider returned no data",
                }
            ]
        ),
    )
    second = service.preview_download_plan(config)

    assert first.loc[first["timeframe"].eq("5m")].iloc[0]["action"] == "fetch"
    assert second.loc[second["timeframe"].eq("5m")].iloc[0]["action"] == "unresolved"


def test_record_unresolved_gap_after_fetch_persists_provider_no_data(tmp_path: Path) -> None:
    data_root = tmp_path / "market"
    audit_row = {
        "stock_code": "000001.SZ",
        "timeframe": "5m",
        "adjust": "qfq",
        "status": "ok",
        "exists": True,
        "rows_total": 0,
        "rows_in_window": 0,
        "expected_rows": 48,
        "missing_rows": 48,
        "coverage_ratio": 0.0,
        "max_missing_gap_minutes": 240,
        "first_missing_at": pd.Timestamp("2026-06-12 09:35:00"),
        "last_missing_at": pd.Timestamp("2026-06-12 15:00:00"),
        "max_missing_gap_start_at": pd.Timestamp("2026-06-12 09:35:00"),
        "max_missing_gap_end_at": pd.Timestamp("2026-06-12 15:00:00"),
        "start": pd.NaT,
        "end": pd.NaT,
        "requested_start": pd.Timestamp("2026-06-12 00:00:00"),
        "requested_end": pd.Timestamp("2026-06-12 23:59:59"),
        "invalid_date_rows": 0,
        "invalid_symbol_rows": 0,
        "duplicate_rows": 0,
        "null_ohlc_rows": 0,
        "non_positive_price_rows": 0,
        "inconsistent_ohlc_rows": 0,
        "null_volume_amount_rows": 0,
        "zero_volume_amount_rows": 0,
        "negative_volume_amount_rows": 0,
        "missing_columns": "",
        "path": "",
        "message": "",
    }

    repository_module._record_unresolved_gaps_after_fetch(
        data_root=data_root,
        adjust="qfq",
        before_audits={"5m": pd.DataFrame([audit_row])},
        after_audits={"5m": pd.DataFrame([audit_row])},
        write_summaries={"5m": pd.DataFrame(columns=["symbol", "new_rows"])},
        fetched_symbols_by_timeframe={"5m": ["000001.SZ"]},
    )
    stored = query_unresolved_gaps(data_root=data_root, symbols=("000001.SZ",), adjust="qfq", timeframes=("5m",))

    assert len(stored) == 1
    assert stored.loc[0, "status"] == "provider_no_data"
    assert int(stored.loc[0, "missing_rows"]) == 48


def test_audit_and_gap_calculation_read_only_canonical_parquet_columns(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market" / "daily"
    root = data_root / "qfq"
    root.mkdir(parents=True)
    bars = _bars().copy()
    bars["unused_factor"] = [1.0, 2.0]
    bars.to_parquet(root / "000001.SZ.parquet", index=False)
    original_read_parquet = pd.read_parquet
    observed_columns: list[tuple[str, ...] | None] = []

    def tracked_read_parquet(*args: object, **kwargs: object) -> pd.DataFrame:
        columns = kwargs.get("columns")
        observed_columns.append(tuple(columns) if columns is not None else None)
        return original_read_parquet(*args, **kwargs)

    monkeypatch.setattr("tdx_downloader.data.audit.pd.read_parquet", tracked_read_parquet)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-25",
    )
    gaps = data_gap_episodes(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "ok"
    assert gaps.empty
    assert observed_columns
    assert all(columns == tuple(["date", "stock_code", "open", "high", "low", "close", "volume", "amount"]) for columns in observed_columns)


def test_audit_rejects_inconsistent_ohlc_for_stock(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().iloc[[0]].copy()
    bars["high"] = [9.0]
    bars["low"] = [11.0]
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "quality_error"
    assert audit.loc[0, "inconsistent_ohlc_rows"] == 1


def test_audit_quality_error_message_includes_first_bad_point(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().copy()
    bars["date"] = pd.to_datetime(["2026-05-25", "2026-05-26"])
    bars.loc[bars.index[1], "high"] = 9.0
    bars.loc[bars.index[1], "low"] = 11.0
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-26",
    )

    message = audit.loc[0, "message"]
    assert audit.loc[0, "status"] == "quality_error"
    assert "首个异常" in message
    assert "OHLC 高低点不一致" in message
    assert "2026-05-26" in message
    assert "high=9" in message
    assert "low=11" in message


def test_audit_rejects_zero_ohlc_for_unadjusted_stock(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().iloc[[0]].copy()
    bars[["open", "high", "low", "close"]] = 0.0
    write_local_bars(data_root=data_root, timeframe="1d", adjust="", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "quality_error"
    assert audit.loc[0, "non_positive_price_rows"] == 1


def test_audit_allows_front_adjusted_non_positive_stock_prices(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().iloc[[0]].copy()
    bars[["open", "high", "low", "close"]] = [-2.0, -1.8, -2.2, -1.9]
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "ok"
    assert audit.loc[0, "non_positive_price_rows"] == 1
    assert "前复权" in audit.loc[0, "message"]


def test_audit_still_rejects_front_adjusted_inconsistent_ohlc(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().iloc[[0]].copy()
    bars[["open", "high", "low", "close"]] = [-2.0, -2.4, -2.1, -1.9]
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("000001.SZ",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "quality_error"
    assert audit.loc[0, "inconsistent_ohlc_rows"] == 1


def test_audit_relaxes_ohlc_semantics_for_tdx_sector_index(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().iloc[[0]].copy()
    bars["stock_code"] = ["880016.SH"]
    bars["open"] = [17.0]
    bars["high"] = [10.0]
    bars["low"] = [30.0]
    bars["close"] = [15.0]
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("880016.SH",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "ok"
    assert audit.loc[0, "inconsistent_ohlc_rows"] == 1
    assert "板块指数" in audit.loc[0, "message"]


def test_audit_marks_nonstandard_zero_price_tdx_sector_index_cached(tmp_path: Path) -> None:
    data_root = tmp_path / "market" / "daily"
    bars = _bars().copy()
    bars["stock_code"] = ["880774.SH", "880774.SH"]
    bars.loc[bars.index[0], ["open", "high", "low", "close"]] = 0.0
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)

    audit = audit_local_data(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        symbols=("880774.SH",),
        start="2026-05-25",
        end="2026-05-25",
    )

    assert audit.loc[0, "status"] == "ok"
    assert audit.loc[0, "non_positive_price_rows"] == 1
    assert "非常规" in audit.loc[0, "message"]


def test_data_management_service_download_rejects_unknown_mode(tmp_path: Path) -> None:
    service = DataManagementService(tmp_path / "market" / "daily", adjust="qfq")
    config = DataDownloadConfig(
        symbols=("000001.SZ",),
        timeframes=("60m",),
        start="2026-05-25",
        end="2026-05-25",
    )

    try:
        service.download(config, mode="other")
    except ValueError as exc:
        assert "下载模式只支持" in str(exc)
    else:
        raise AssertionError("unknown mode should fail")


def test_shortcut_symbols_exposes_non_manual_groups() -> None:
    assert "000300.SH" in shortcut_symbols("宽基指数")
    assert "510300.SH" in shortcut_symbols("ETF样例")


def test_shortcut_symbol_groups_adds_full_a_and_sector_indexes_from_metadata() -> None:
    metadata = pd.DataFrame(
        {
            "stock_code": ["000001.SZ", "600000.SH", "510300.SH", "000300.SH", "880001.SH", "880002.SH"],
            "stock_name": ["平安银行", "浦发银行", "沪深300ETF", "沪深300", "种植业", "半导体"],
            "source": ["test"] * 6,
            "path": [""] * 6,
        }
    )

    groups = {group["name"]: group["symbols"] for group in shortcut_symbol_groups(metadata=metadata)}

    assert groups["全A股票"] == ["000001.SZ", "600000.SH"]
    assert groups["板块指数"] == ["880001.SH", "880002.SH"]


def test_shortcut_symbol_groups_does_not_use_catalog_as_market_universe() -> None:
    metadata = pd.DataFrame(
        {
            "stock_code": ["000001.SZ", "510300.SH", "880001.SH"],
            "stock_name": ["平安银行", "沪深300ETF", "种植业"],
            "source": ["catalog", "catalog", "catalog"],
            "path": [""] * 3,
        }
    )

    groups = {group["name"]: group["symbols"] for group in shortcut_symbol_groups(metadata=metadata)}

    assert "全A股票" not in groups
    assert "ETF列表" not in groups
    assert "板块指数" not in groups


def test_shortcut_symbol_groups_can_use_catalog_as_docker_fallback() -> None:
    metadata = pd.DataFrame(
        {
            "stock_code": ["000001.SZ", "510300.SH", "880001.SH"],
            "stock_name": ["平安银行", "沪深300ETF", "种植业"],
            "source": ["catalog", "catalog", "catalog"],
            "path": [""] * 3,
        }
    )

    groups = {
        group["name"]: group["symbols"]
        for group in shortcut_symbol_groups(metadata=metadata, include_catalog_universe=True)
    }

    assert groups["全A股票"] == ["000001.SZ"]
    assert groups["ETF列表"] == ["510300.SH"]
    assert groups["板块指数"] == ["880001.SH"]


def test_infer_asset_type_keeps_880_fund_named_concepts_as_index() -> None:
    assert infer_asset_type("880801.SH", "基金重仓") == "index"
    assert infer_asset_type("510300.SH", "沪深300ETF") == "etf"


def test_tdx_symbol_metadata_reads_current_tdx_tnf_names(tmp_path: Path) -> None:
    hq_cache = tmp_path / "T0002" / "hq_cache"
    hq_cache.mkdir(parents=True)
    record = bytearray(360)
    record[0:6] = b"880001"
    name = "种植业".encode("gbk")
    record[31 : 31 + len(name)] = name
    (hq_cache / "shs.tnf").write_bytes(bytes(50) + bytes(record))

    metadata = load_tdx_symbol_metadata(tmp_path)

    assert metadata[["stock_code", "stock_name"]].to_dict("records") == [
        {"stock_code": "880001.SH", "stock_name": "种植业"}
    ]


def test_symbol_metadata_uses_disk_cache_after_tdx_table_moves(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    tdx_root = tmp_path / "tdx"
    hq_cache = tdx_root / "T0002" / "hq_cache"
    hq_cache.mkdir(parents=True)
    record = bytearray(360)
    record[0:6] = b"510300"
    name = "沪深300ETF".encode("gbk")
    record[31 : 31 + len(name)] = name
    table = hq_cache / "shs.tnf"
    table.write_bytes(bytes(50) + bytes(record))

    first = load_symbol_metadata(data_root, tdx_path=tdx_root)
    table.unlink()
    second = load_symbol_metadata(data_root, tdx_path=tdx_root)

    assert first[["stock_code", "stock_name"]].to_dict("records") == [
        {"stock_code": "510300.SH", "stock_name": "沪深300ETF"}
    ]
    assert second[["stock_code", "stock_name"]].to_dict("records") == [
        {"stock_code": "510300.SH", "stock_name": "沪深300ETF"}
    ]
