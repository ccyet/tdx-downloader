from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

from tdx_downloader.data.catalog import infer_asset_type, query_catalog
from tdx_downloader.data.audit import audit_local_data, data_gap_episodes
from tdx_downloader.data.inventory import inventory_local_data
from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataManagementService,
    shortcut_symbol_groups,
    shortcut_symbols,
)
from tdx_downloader.data.symbols import load_symbol_metadata, load_tdx_symbol_metadata
from tdx_downloader.data.storage import write_local_bars


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
    metadata.mkdir(parents=True)
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
    assert "未覆盖请求窗口" in plan.loc[0, "message"]


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
    assert "2026-06-03" in plan.loc[0, "message"]
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
