from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pandas as pd

from tdx_downloader.api import ai_client, constants, fuyao_client, native_picker, schemas, task_store
from tdx_downloader.api.routes import catalog as catalog_routes
from tdx_downloader.api.routes import config as config_routes
from tdx_downloader.api.routes import download as download_routes
from tdx_downloader.api.routes import native as native_routes
from tdx_downloader.api.routes import trading_calendar as trading_calendar_routes
from tdx_downloader.data.catalog import build_catalog, query_catalog
from tdx_downloader.data.inventory import inventory_local_data
from tdx_downloader.data.manager import DataDownloadResult, download_summary
from tdx_downloader.data.storage import write_local_bars
from tdx_downloader.web_api import create_app


def _bars(symbol: str, closes: list[float], *, start: str = "2026-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "stock_code": symbol,
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0 + index for index, _ in enumerate(closes)],
            "amount": [100000.0 + index * 100 for index, _ in enumerate(closes)],
        }
    )


def test_api_config_exposes_sub2api_style_web_defaults() -> None:
    client = TestClient(create_app())

    response = client.get("/api/config")

    assert response.status_code == 200
    data = response.json()
    assert data["defaults"]["data_root"] == "/Volumes/ccOUT 1/tdx-data"
    assert data["defaults"]["timeframes"] == ["1d"]
    assert {"name": "核心样例", "symbols": ["000001.SZ", "600519.SH", "300750.SZ", "601318.SH"]} in data[
        "symbol_groups"
    ]
    assert isinstance(data["integrations"]["fuyao_calendar"]["configured"], bool)


def test_catalog_payload_returns_all_cache_records(tmp_path) -> None:
    row_count = constants.MAX_TABLE_RECORDS + 1
    catalog = pd.DataFrame(
        {
            "cache_key": [f"key-{index}" for index in range(row_count)],
            "stock_code": [f"{index:06d}.SZ" for index in range(row_count)],
            "stock_name": ["测试"] * row_count,
            "asset_type": ["stock"] * row_count,
            "data_kind": ["price"] * row_count,
            "indicator": ["ohlcv"] * row_count,
            "timeframe": ["1d"] * row_count,
            "adjust": ["qfq"] * row_count,
            "storage_format": ["parquet"] * row_count,
            "status": ["cached"] * row_count,
            "rows": [10] * row_count,
            "start_at": ["2026-01-01T00:00:00"] * row_count,
            "end_at": ["2026-01-10T00:00:00"] * row_count,
            "file_size_bytes": [1024] * row_count,
            "modified_at": ["2026-01-10T10:00:00"] * row_count,
            "path": [""] * row_count,
            "message": [""] * row_count,
        }
    )

    payload = catalog_routes._catalog_payload(catalog, data_root=str(tmp_path), rebuilt=False)

    assert len(payload["records"]) == row_count
    assert payload["record_count"] == row_count


def test_catalog_payload_can_skip_cache_records(tmp_path) -> None:
    catalog = pd.DataFrame(
        {
            "cache_key": ["key-1"],
            "stock_code": ["000001.SZ"],
            "stock_name": ["平安银行"],
            "asset_type": ["stock"],
            "data_kind": ["price"],
            "indicator": ["ohlcv"],
            "timeframe": ["1d"],
            "adjust": ["qfq"],
            "storage_format": ["parquet"],
            "status": ["cached"],
            "rows": [10],
            "start_at": ["2026-01-01T00:00:00"],
            "end_at": ["2026-01-10T00:00:00"],
            "file_size_bytes": [1024],
            "modified_at": ["2026-01-10T10:00:00"],
            "path": [""],
            "message": [""],
        }
    )

    payload = catalog_routes._catalog_payload(catalog, data_root=str(tmp_path), rebuilt=False, include_records=False)

    assert payload["records"] == []
    assert payload["record_count"] == 1
    assert payload["record_limit"] == 0


def test_api_symbol_groups_uses_current_local_symbol_metadata(tmp_path) -> None:
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n"
        "000001.SZ,平安银行\n"
        "600000.SH,浦发银行\n"
        "510300.SH,沪深300ETF\n"
        "000300.SH,沪深300\n"
        "880001.SH,种植业\n",
        encoding="utf-8",
    )
    client = TestClient(create_app())

    response = client.get("/api/symbol-groups", params={"data_root": str(tmp_path), "tdx_path": ""})

    assert response.status_code == 200
    data = response.json()
    groups = {group["name"]: group["symbols"] for group in data["groups"]}
    assert groups["ETF列表"] == ["510300.SH"]
    assert groups["全A股票"] == ["000001.SZ", "600000.SH"]
    assert groups["板块指数"] == ["880001.SH"]
    assert data["symbol_names"]["510300.SH"] == "沪深300ETF"
    assert data["symbol_names"]["880001.SH"] == "种植业"


def test_api_symbol_groups_forwards_refresh_target(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    received: list[tuple[str, str]] = []

    def fake_symbol_metadata(data_root: str, tdx_path: str) -> pd.DataFrame:
        received.append((data_root, tdx_path))
        return pd.DataFrame(
            [
                {"stock_code": "510300.SH", "stock_name": "沪深300ETF", "source": "test", "path": ""},
            ]
        )

    monkeypatch.setattr(config_routes, "symbol_metadata_with_runtime", fake_symbol_metadata)
    client = TestClient(create_app())

    response = client.get("/api/symbol-groups", params={"data_root": "/tmp/data", "tdx_path": "C:\\tdx", "target": "etf"})

    assert response.status_code == 200
    data = response.json()
    groups = {group["name"]: group["symbols"] for group in data["groups"]}
    assert groups["ETF列表"] == ["510300.SH"]
    assert data["symbol_names"]["510300.SH"] == "沪深300ETF"
    assert received == [("/tmp/data", "C:\\tdx")]


def test_api_symbol_groups_uses_runtime_shortcut_groups_for_target(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    received: list[tuple[str, str, str]] = []

    def fake_runtime_groups(data_root: str, tdx_path: str, *, target: str = "") -> list[dict[str, object]]:
        received.append((data_root, tdx_path, target))
        return [
            {"name": "核心样例", "symbols": ["000001.SZ"]},
            {"name": "板块指数", "symbols": ["880001.SH"]},
        ]

    def fake_symbol_metadata(data_root: str, tdx_path: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"stock_code": "000001.SZ", "stock_name": "平安银行", "source": "catalog", "path": ""},
            ]
        )

    monkeypatch.setattr(config_routes, "shortcut_symbol_groups_with_runtime", fake_runtime_groups)
    monkeypatch.setattr(config_routes, "symbol_metadata_with_runtime", fake_symbol_metadata)
    client = TestClient(create_app())

    response = client.get("/api/symbol-groups", params={"data_root": "/tmp/data", "tdx_path": "C:\\tdx", "target": "index"})

    assert response.status_code == 200
    data = response.json()
    groups = {group["name"]: group["symbols"] for group in data["groups"]}
    assert groups["板块指数"] == ["880001.SH"]
    assert received == [("/tmp/data", "C:\\tdx", "index")]


def test_api_symbol_groups_sorts_picker_groups_by_recent_amount(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    def fake_symbol_metadata(data_root: str, tdx_path: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"stock_code": "510300.SH", "stock_name": "沪深300ETF", "source": "test", "path": ""},
                {"stock_code": "159915.SZ", "stock_name": "创业板ETF", "source": "test", "path": ""},
                {"stock_code": "512100.SH", "stock_name": "中证1000ETF", "source": "test", "path": ""},
                {"stock_code": "880001.SH", "stock_name": "种植业", "source": "test", "path": ""},
                {"stock_code": "880002.SH", "stock_name": "半导体", "source": "test", "path": ""},
                {"stock_code": "000001.SZ", "stock_name": "平安银行", "source": "test", "path": ""},
                {"stock_code": "000002.SZ", "stock_name": "万科A", "source": "test", "path": ""},
            ]
        )

    monkeypatch.setattr(config_routes, "symbol_metadata_with_runtime", fake_symbol_metadata)
    write_local_bars(
        data_root=tmp_path,
        timeframe="1d",
        adjust="qfq",
        bars=pd.concat(
            [
                _bars("510300.SH", [1.0, 1.1]).assign(amount=[1000.0, 2000.0]),
                _bars("159915.SZ", [2.0, 2.1]).assign(amount=[9000.0, 11000.0]),
                _bars("880001.SH", [3.0, 3.1]).assign(amount=[5000.0, 6000.0]),
                _bars("880002.SH", [4.0, 4.1]).assign(amount=[12000.0, 13000.0]),
                _bars("000002.SZ", [5.0, 5.1]).assign(amount=[20000.0, 21000.0]),
            ],
            ignore_index=True,
        ),
    )
    client = TestClient(create_app())

    response = client.get("/api/symbol-groups", params={"data_root": str(tmp_path), "adjust": "qfq"})

    assert response.status_code == 200
    groups = {group["name"]: group["symbols"] for group in response.json()["groups"]}
    assert groups["ETF列表"] == ["159915.SZ", "510300.SH", "512100.SH"]
    assert groups["板块指数"] == ["880002.SH", "880001.SH"]
    assert groups["全A股票"] == ["000001.SZ", "000002.SZ"]


def test_api_etf_tracking_returns_tdx_tracking_records(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    received: list[tuple[str, str, tuple[str, ...]]] = []

    def fake_etf_tracking(data_root: str, tdx_path: str, *, index_symbols: tuple[str, ...]) -> pd.DataFrame:
        received.append((data_root, tdx_path, index_symbols))
        return pd.DataFrame(
            [
                {
                    "tracking_symbol": "000300.SH",
                    "stock_code": "510300.SH",
                    "stock_name": "沪深300ETF华泰柏瑞",
                    "now_price": 3.88,
                    "iopv": 3.87,
                    "market_value": 2298.6,
                }
            ]
        )

    monkeypatch.setattr(config_routes, "etf_tracking_with_runtime", fake_etf_tracking)
    monkeypatch.setattr(
        config_routes,
        "load_symbol_metadata",
        lambda *_args, **_kwargs: pd.DataFrame(
            [{"stock_code": "000300.SH", "stock_name": "沪深300", "source": "test", "path": ""}]
        ),
    )
    client = TestClient(create_app())

    response = client.get(
        "/api/etf-tracking",
        params=[
            ("data_root", str(tmp_path)),
            ("tdx_path", "C:\\tdx"),
            ("index_symbols", "000300.SH"),
            ("index_symbols", "399006.SZ"),
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["record_count"] == 1
    assert data["index_symbols"] == ["000300.SH", "399006.SZ"]
    assert data["records"][0]["tracking_name"] == "沪深300"
    assert data["records"][0]["stock_code"] == "510300.SH"
    assert received == [(str(tmp_path), "C:\\tdx", ("000300.SH", "399006.SZ"))]


def test_api_etf_tracking_uses_memory_cache(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    config_routes._clear_etf_route_caches()
    calls = 0

    def fake_etf_tracking(data_root: str, tdx_path: str, *, index_symbols: tuple[str, ...]) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return pd.DataFrame(
            [
                {
                    "tracking_symbol": "000300.SH",
                    "stock_code": "510300.SH",
                    "stock_name": "沪深300ETF",
                    "now_price": 4.1,
                    "iopv": 4.09,
                    "market_value": 100.0,
                }
            ]
        )

    monkeypatch.setattr(config_routes, "etf_tracking_with_runtime", fake_etf_tracking)
    monkeypatch.setattr(config_routes, "_enrich_etf_tracking_names", lambda frame, **_kwargs: frame)
    client = TestClient(create_app())

    params = {"data_root": str(tmp_path), "tdx_path": "C:\\tdx", "index_symbols": "000300.SH"}
    first = client.get("/api/etf-tracking", params=params)
    second = client.get("/api/etf-tracking", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is True
    config_routes._clear_etf_route_caches()


def test_api_etf_tracking_uses_disk_cache_after_memory_clear(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    config_routes._clear_etf_route_caches()
    calls = 0

    def fake_etf_tracking(data_root: str, tdx_path: str, *, index_symbols: tuple[str, ...]) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return pd.DataFrame(
            [
                {
                    "tracking_symbol": "000300.SH",
                    "stock_code": "510300.SH",
                    "stock_name": "沪深300ETF",
                    "now_price": 4.1,
                    "iopv": 4.09,
                    "market_value": 100.0,
                }
            ]
        )

    monkeypatch.setattr(config_routes, "etf_tracking_with_runtime", fake_etf_tracking)
    monkeypatch.setattr(config_routes, "_enrich_etf_tracking_names", lambda frame, **_kwargs: frame)
    client = TestClient(create_app())
    params = {"data_root": str(tmp_path), "tdx_path": "C:\\tdx", "index_symbols": "000300.SH"}

    first = client.get("/api/etf-tracking", params=params)
    config_routes._clear_etf_route_caches()
    second = client.get("/api/etf-tracking", params=params)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert first.json()["cache"]["persisted"] is True
    assert second.json()["cache"]["hit"] is True
    assert second.json()["cache"]["scope"] == "disk"
    config_routes._clear_etf_route_caches()


def test_fuyao_trading_calendar_normalizes_days() -> None:
    data = {
        "timestamp": 1780848000000,
        "item": [
            {"date": "20260605", "date_ms": 1780588800000},
            {"date": "2026-06-08", "date_ms": 1780848000000},
        ],
    }

    payload = fuyao_client.normalize_trading_days(data)

    assert payload["days"] == ["2026-06-05", "2026-06-08"]
    assert payload["raw_count"] == 2
    assert payload["timestamp"] == 1780848000000


def test_api_trading_calendar_returns_fuyao_days(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_fetch(api_key: str = "") -> dict[str, object]:
        assert api_key == ""
        return {
            "timestamp": 1780848000000,
            "item": [
                {"date": "20260605", "date_ms": 1780588800000},
                {"date": "20260608", "date_ms": 1780848000000},
            ],
        }

    monkeypatch.setattr(trading_calendar_routes, "fetch_trading_days", fake_fetch)
    client = TestClient(create_app())

    response = client.get("/api/trading-calendar")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "fuyao"
    assert data["days"] == ["2026-06-05", "2026-06-08"]
    assert data["raw_count"] == 2


def test_api_trading_calendar_forwards_local_fuyao_key_header(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    received: list[str] = []

    def fake_fetch(api_key: str = "") -> dict[str, object]:
        received.append(api_key)
        return {
            "timestamp": 1780848000000,
            "item": [{"date": "20260608", "date_ms": 1780848000000}],
        }

    monkeypatch.setattr(trading_calendar_routes, "fetch_trading_days", fake_fetch)
    client = TestClient(create_app())

    response = client.get("/api/trading-calendar", headers={"x-fuyao-api-key": "local-secret"})

    assert response.status_code == 200
    assert response.json()["days"] == ["2026-06-08"]
    assert received == ["local-secret"]


def test_api_trading_calendar_surfaces_missing_api_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fake_fetch(api_key: str = "") -> dict[str, object]:
        assert api_key == ""
        raise RuntimeError("未配置 FUYAO_API_KEY。")

    monkeypatch.setattr(trading_calendar_routes, "fetch_trading_days", fake_fetch)
    client = TestClient(create_app())

    response = client.get("/api/trading-calendar")

    assert response.status_code == 503
    assert "FUYAO_API_KEY" in response.json()["detail"]


def test_api_etf_returns_calculates_local_daily_return_windows(tmp_path) -> None:
    data_root = tmp_path / "market"
    dates = pd.bdate_range("2025-12-30", periods=60)
    closes = [100.0 + index for index in range(len(dates))]
    bars = pd.DataFrame(
        {
            "date": dates,
            "stock_code": "510300.SH",
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1000.0] * len(dates),
            "amount": [1000000.0 + index for index in range(len(dates))],
        }
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    client = TestClient(create_app())

    response = client.post(
        "/api/etf-returns",
        json={
            "data_root": str(data_root),
            "adjust": "qfq",
            "symbols": ["510300.SH"],
            "end": "2026-03-23",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["record_count"] == 1
    row = data["records"][0]
    assert row["symbol"] == "510300.SH"
    assert row["latest_date"].startswith("2026-03-23")
    assert row["amount"] == 1000059.0
    assert row["return_1d"] == (159.0 / 158.0) - 1.0
    assert row["return_5d"] == (159.0 / 154.0) - 1.0
    assert row["return_20d"] == (159.0 / 139.0) - 1.0
    assert row["return_50d"] == (159.0 / 109.0) - 1.0
    assert row["return_ytd"] == (159.0 / 102.0) - 1.0


def test_api_etf_returns_uses_memory_cache(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    config_routes._clear_etf_route_caches()
    calls = 0

    def fake_return_records(**_kwargs: object) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [{"symbol": "510300.SH", "latest_date": "2026-06-08", "close": 4.1, "amount": 1000000.0}]

    monkeypatch.setattr(config_routes, "_local_etf_return_records", fake_return_records)
    client = TestClient(create_app())
    payload = {
        "data_root": str(tmp_path),
        "adjust": "qfq",
        "symbols": ["510300.SH"],
        "end": "2026-06-08",
    }

    first = client.post("/api/etf-returns", json=payload)
    second = client.post("/api/etf-returns", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is True
    config_routes._clear_etf_route_caches()


def test_api_etf_returns_uses_disk_cache_after_memory_clear(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    config_routes._clear_etf_route_caches()
    calls = 0

    def fake_return_records(**_kwargs: object) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return [{"symbol": "510300.SH", "latest_date": "2026-06-08", "close": 4.1, "amount": 1000000.0}]

    monkeypatch.setattr(config_routes, "_local_etf_return_records", fake_return_records)
    client = TestClient(create_app())
    payload = {
        "data_root": str(tmp_path),
        "adjust": "qfq",
        "symbols": ["510300.SH"],
        "end": "2026-06-08",
    }

    first = client.post("/api/etf-returns", json=payload)
    config_routes._clear_etf_route_caches()
    second = client.post("/api/etf-returns", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert first.json()["cache"]["persisted"] is True
    assert second.json()["cache"]["hit"] is True
    assert second.json()["cache"]["scope"] == "disk"
    config_routes._clear_etf_route_caches()


def test_api_overview_does_not_require_existing_catalog(tmp_path) -> None:
    client = TestClient(create_app())

    response = client.get("/api/overview", params={"data_root": str(tmp_path)})

    assert response.status_code == 200
    data = response.json()
    assert data["catalog_exists"] is False
    assert data["records"] == []
    assert data["summary"]["catalog_row_count"] == 0.0


def test_api_overview_refresh_imports_symbol_names(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    write_local_bars(
        data_root=tmp_path,
        timeframe="1d",
        adjust="qfq",
        bars=_bars("000750.SZ", [10.0, 10.5]),
    )

    def fake_symbol_metadata(data_root: str, tdx_path: str) -> pd.DataFrame:
        assert data_root == str(tmp_path)
        assert tdx_path == "C:\\new_tdx64\\PYPlugins\\user"
        return pd.DataFrame(
            [
                {
                    "stock_code": "000750.SZ",
                    "stock_name": "国海证券",
                    "source": "tdx_tnf",
                    "path": "C:\\new_tdx64\\T0002\\hq_cache\\szs.tnf",
                }
            ]
        )

    monkeypatch.setattr(catalog_routes, "symbol_metadata_with_runtime", fake_symbol_metadata)
    client = TestClient(create_app())

    response = client.get(
        "/api/overview",
        params={"data_root": str(tmp_path), "tdx_path": "C:\\new_tdx64\\PYPlugins\\user", "refresh": "true"},
    )

    assert response.status_code == 200
    records = response.json()["records"]
    assert records[0]["stock_code"] == "000750.SZ"
    assert records[0]["stock_name"] == "国海证券"


def test_api_download_requires_symbols() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/download",
        json={
            "symbols": [],
            "timeframes": ["1d"],
            "start": "2026-06-01",
            "end": "2026-06-02",
        },
    )

    assert response.status_code == 400
    assert "标的代码" in response.json()["detail"]


def test_api_plan_sorts_requested_timeframes_before_dependencies() -> None:
    table = pd.DataFrame(
        {
            "stock_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "timeframe": ["1d", "5m", "1d"],
            "action": ["fetch", "fetch", "cached"],
        }
    )

    sorted_table = download_routes._sort_plan_table(table, ("5m",))

    assert sorted_table["timeframe"].tolist() == ["5m", "1d", "1d"]
    assert sorted_table["stock_code"].tolist() == ["000001.SZ", "000001.SZ", "000002.SZ"]


def test_api_plan_prioritizes_intraday_when_daily_is_also_selected() -> None:
    table = pd.DataFrame(
        {
            "stock_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "timeframe": ["1d", "5m", "1d"],
            "action": ["fetch", "fetch", "cached"],
        }
    )

    sorted_table = download_routes._sort_plan_table(table, ("1d", "5m"))

    assert sorted_table["timeframe"].tolist() == ["5m", "1d", "1d"]


def test_api_pick_directory_returns_selected_path(monkeypatch, tmp_path) -> None:
    def fake_dialog(initial_directory: str, title: str):
        assert initial_directory == str(tmp_path)
        assert title == "选择行情根目录"
        return tmp_path

    monkeypatch.setattr(native_routes, "_open_native_directory_dialog", fake_dialog)
    client = TestClient(create_app())

    response = client.post(
        "/api/pick-directory",
        json={"initial_directory": str(tmp_path), "title": "选择行情根目录"},
    )

    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path), "cancelled": False}


def test_api_pick_directory_surfaces_runtime_error(monkeypatch) -> None:
    def fake_dialog(initial_directory: str, title: str):
        raise RuntimeError("当前系统暂不支持弹窗选择文件夹，请直接输入路径。")

    monkeypatch.setattr(native_routes, "_open_native_directory_dialog", fake_dialog)
    client = TestClient(create_app())

    response = client.post("/api/pick-directory", json={})

    assert response.status_code == 400
    assert "暂不支持" in response.json()["detail"]


def test_windows_directory_picker_uses_powershell_folder_dialog(monkeypatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        assert kwargs["timeout"] == 120
        return native_picker.subprocess.CompletedProcess(command, 0, stdout=f"{tmp_path}\n", stderr="")

    monkeypatch.setattr(native_picker.sys, "platform", "win32")
    monkeypatch.setattr(native_picker.subprocess, "run", fake_run)

    selected = native_picker._open_native_directory_dialog(str(tmp_path), "选择行情根目录")

    assert selected == tmp_path
    assert calls
    command = calls[0]
    assert command[:6] == ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command"]
    assert "System.Windows.Forms.FolderBrowserDialog" in command[6]
    assert command[-2:] == ["选择行情根目录", str(tmp_path)]


def test_windows_directory_picker_returns_none_when_cancelled(monkeypatch, tmp_path) -> None:
    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        return native_picker.subprocess.CompletedProcess(command, 2, stdout="", stderr="")

    monkeypatch.setattr(native_picker.sys, "platform", "win32")
    monkeypatch.setattr(native_picker.subprocess, "run", fake_run)

    assert native_picker._open_native_directory_dialog(str(tmp_path), "选择目录") is None


def test_existing_directory_uses_nearest_existing_parent(tmp_path) -> None:
    missing_child = tmp_path / "missing" / "child"

    assert native_picker._existing_directory(missing_child) == tmp_path


def test_api_clear_tasks_keeps_running_queue_empty() -> None:
    client = TestClient(create_app())

    response = client.delete("/api/tasks")

    assert response.status_code == 200
    data = response.json()
    assert data["removed_count"] >= 0
    assert data["running_count"] >= 0


def test_task_events_keep_recent_fifo_window() -> None:
    with task_store._tasks_lock:
        task_store._tasks.clear()

    task = task_store._create_task("download")
    for index in range(constants.TASK_EVENT_LIMIT + 5):
        task_store._append_event(task.id, {"stage": "parallels_command_start", "message": f"第 {index} 批"})

    payload = task_store._task_payload(task_store._get_task(task.id))  # type: ignore[arg-type]

    assert len(payload["events"]) == constants.TASK_EVENT_LIMIT
    assert payload["events"][0]["message"] == "第 5 批"
    assert payload["events"][-1]["message"] == f"第 {constants.TASK_EVENT_LIMIT + 4} 批"


def test_download_task_refreshes_catalog_after_writing_cache(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    data_root = tmp_path / "market"

    def fake_download_with_runtime(service, config, *, mode, progress_callback):  # type: ignore[no-untyped-def]
        bars = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01"]),
                "stock_code": ["000750.SZ"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000.0],
                "amount": [10200.0],
            }
        )
        written = write_local_bars(data_root=service.data_root, timeframe="1d", adjust=service.adjust, bars=bars)
        table = written.rename(columns={"symbol": "stock_code", "rows": "rows_written"}).copy()
        table["timeframe"] = "1d"
        table["adjust"] = service.adjust
        table["action"] = "fetched"
        return DataDownloadResult(table=table, summary=download_summary(table))

    monkeypatch.setattr(download_routes, "download_with_runtime", fake_download_with_runtime)
    monkeypatch.setattr(download_routes, "should_use_parallels_runtime", lambda: False)
    with task_store._tasks_lock:
        task_store._tasks.clear()
    payload = schemas.DownloadPayload(
        data_root=str(data_root),
        symbols=["000750.SZ"],
        timeframes=["1d"],
        start="2026-06-01",
        end="2026-06-01",
        mode="force",
    )
    task = task_store._create_task("download")

    download_routes._run_download_task(task.id, payload, "force")

    events = task_store._task_payload(task_store._get_task(task.id))["events"]  # type: ignore[arg-type]
    assert [event["stage"] for event in events[:2]] == ["task_start", "local_task_start"]
    refreshed = query_catalog(data_root=data_root)
    cached = refreshed.loc[(refreshed["stock_code"] == "000750.SZ") & (refreshed["timeframe"] == "1d")]
    assert cached["status"].tolist() == ["cached"]


def test_api_research_history_reads_local_timeframe_cache(tmp_path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=_bars("000001.SZ", [10, 11, 12, 13, 11, 10, 11, 12, 13, 14, 13, 14, 15, 16]),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/research/history",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbol": "000001.SZ",
            "as_of": "2026-01-20",
            "window_size": 4,
            "top_n": 3,
            "exclusion_bars": 1,
            "forward_windows": [2],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["timeframe"] == "1d"
    assert data["summary"]["match_count"] > 0
    assert "综合相似度" in data["results"][0]
    assert data["current_window"][0]["open"] == 13.0
    assert data["historical_windows"][0][0]["date"].startswith("2026-")
    assert len(data["historical_chart_windows"][0]) == len(data["historical_windows"][0]) + 2


def test_api_research_history_reports_requested_window_start(tmp_path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=_bars("000001.SZ", [10, 11, 12, 13, 11, 10, 11, 12, 13, 14, 13, 14, 15, 16]),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/research/history",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbol": "000001.SZ",
            "window_start": "2026-01-09",
            "as_of": "2026-01-14",
            "window_size": 4,
            "top_n": 3,
            "exclusion_bars": 1,
            "forward_windows": [2],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["window_start"].startswith("2026-01-09")
    assert data["summary"]["window_size"] == 4
    assert data["current_window"][0]["date"].startswith("2026-01-09")
    assert data["current_window"][-1]["date"].startswith("2026-01-14")


def test_api_research_history_resolves_local_symbol_name(tmp_path) -> None:
    data_root = tmp_path / "market"
    metadata = data_root / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "symbols.csv").write_text("stock_code,stock_name\n000001.SZ,平安银行\n", encoding="utf-8")
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=_bars("000001.SZ", [10, 11, 12, 13, 11, 10, 11, 12, 13, 14, 13, 14, 15, 16]),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/research/history",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbol": "000001.SZ",
            "as_of": "2026-01-20",
            "window_size": 4,
            "top_n": 3,
            "exclusion_bars": 1,
            "forward_windows": [2],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["stock_name"] == "平安银行"
    assert data["results"][0]["股票"] == "平安银行"


def test_api_research_history_uses_default_index_name(tmp_path) -> None:
    data_root = tmp_path / "market"
    write_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust="qfq",
        bars=_bars("399006.SZ", [10, 11, 12, 13, 11, 10, 11, 12, 13, 14, 13, 14, 15, 16]),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/research/history",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbol": "399006",
            "as_of": "2026-01-20",
            "window_size": 4,
            "top_n": 3,
            "exclusion_bars": 1,
            "forward_windows": [2],
        },
    )

    assert response.status_code == 200
    assert response.json()["summary"]["stock_name"] == "创业板指"


def test_api_research_cross_section_reads_local_cache_with_date_tolerance(tmp_path) -> None:
    data_root = tmp_path / "market"
    metadata = data_root / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n000001.SZ,平安银行\n000002.SZ,候选银行\n000003.SZ,弱势样例\n",
        encoding="utf-8",
    )
    bars = pd.concat(
        [
            _bars("000001.SZ", [10, 11, 12, 13, 14, 15, 16, 17]),
            _bars("000002.SZ", [8, 9, 10, 11, 12, 13, 15, 16]),
            _bars("000003.SZ", [20, 19, 18, 17, 16, 15, 14, 13]),
        ],
        ignore_index=True,
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    client = TestClient(create_app())

    response = client.post(
        "/api/research/cross-section",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "target_symbol": "000001.SZ",
            "universe_symbols": ["000002.SZ", "000003.SZ"],
            "start": "2026-01-06",
            "end": "2026-01-09",
            "top_n": 2,
            "date_tolerance_bars": 2,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["window_size"] == 4
    assert data["summary"]["stock_name"] == "平安银行"
    assert data["results"][0]["symbol"] == "000002.SZ"
    assert data["results"][0]["股票"] == "候选银行"
    assert data["target_window"][0]["stock_code"] == "000001.SZ"
    assert data["target_window"][0]["open"] == 13.0
    assert data["candidate_windows"][0]["symbol"] == "000002.SZ"
    assert data["candidate_windows"][0]["name"] == "候选银行"
    assert data["candidate_windows"][0]["candles"][0]["stock_code"] == "000002.SZ"


def test_api_research_cross_section_returns_chart_context_without_replacing_windows(tmp_path) -> None:
    data_root = tmp_path / "market"
    closes = [10.0 + index * 0.1 for index in range(70)]
    bars = pd.concat(
        [
            _bars("000001.SZ", closes),
            _bars("000002.SZ", [value * 0.9 for value in closes]),
        ],
        ignore_index=True,
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    target_dates = pd.bdate_range("2026-01-01", periods=70)
    start = target_dates[25].date().isoformat()
    end = target_dates[28].date().isoformat()
    client = TestClient(create_app())

    response = client.post(
        "/api/research/cross-section",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "target_symbol": "000001.SZ",
            "universe_symbols": ["000002.SZ"],
            "start": start,
            "end": end,
            "top_n": 1,
            "date_tolerance_bars": 0,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["target_window"]) == 4
    assert len(data["target_chart_window"]) == 44
    assert data["target_segments"] == [{"start": start, "end": end, "direction": "对标窗口"}]
    assert len(data["candidate_windows"][0]["candles"]) == 4
    assert len(data["candidate_windows"][0]["chart_candles"]) == 44
    assert data["candidate_windows"][0]["segments"][0]["direction"] == "对标窗口"


def test_api_research_cross_section_window_traversal_uses_search_interval(tmp_path) -> None:
    data_root = tmp_path / "market"
    metadata = data_root / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n000001.SZ,目标样例\n000002.SZ,候选样例\n",
        encoding="utf-8",
    )
    bars = pd.concat(
        [
            _bars("000001.SZ", [10, 12, 11, 13], start="2026-05-18"),
            _bars("000002.SZ", [7, 8, 10, 12, 11, 13, 14], start="2021-01-01"),
        ],
        ignore_index=True,
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    client = TestClient(create_app())

    response = client.post(
        "/api/research/cross-section",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "target_symbol": "000001.SZ",
            "universe_symbols": ["000002.SZ"],
            "start": "2026-05-18",
            "end": "2026-05-21",
            "search_mode": "traversal",
            "traversal_start": "2021-01-01",
            "traversal_end": "2021-01-11",
            "top_n": 1,
            "min_coverage": 1.0,
            "forward_windows": [1],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["search_mode"] == "traversal"
    assert data["summary"]["target_start"] == "2026-05-18T00:00:00"
    assert data["summary"]["target_end"] == "2026-05-21T23:59:59.999999"
    assert data["summary"]["candidate_start"] == "2021-01-01T00:00:00"
    assert data["summary"]["candidate_end"] == "2021-01-11T23:59:59.999999"
    assert data["summary"]["traversal_start"] == "2021-01-01T00:00:00"
    assert data["results"][0]["symbol"] == "000002.SZ"
    assert data["results"][0]["股票"] == "候选样例"
    assert data["results"][0]["区间开始"] == "2021-01-05T00:00:00"
    assert data["candidate_windows"][0]["name"] == "候选样例"


def test_api_research_review_ranks_local_cache(tmp_path) -> None:
    data_root = tmp_path / "market"
    bars = pd.concat(
        [
            _bars("000001.SZ", [10, 10.5, 11, 12, 13, 14]),
            _bars("000002.SZ", [10, 9.8, 9.5, 9.7, 9.6, 9.4]),
            _bars("000300.SH", [10, 10.1, 10.2, 10.4, 10.6, 10.8]),
        ],
        ignore_index=True,
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    client = TestClient(create_app())

    response = client.post(
        "/api/research/review",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbols": ["000001.SZ", "000002.SZ"],
            "start": "2026-01-01",
            "end": "2026-01-08",
            "benchmark_symbol": "000300.SH",
            "stock_names": {"000001.SZ": "强势样例", "000002.SZ": "弱势样例"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["ranked_count"] == 2
    assert data["ranking"][0]["代码"] == "000001.SZ"
    assert "锐评结论" in data["ranking"][0]
    assert data["ranking"][0]["对标指数"] == "000300.SH"
    assert data["comparisons"][0]["标的"] == "000300.SH"
    strong_review = next(row for row in data["reviews"] if row["symbol"] == "000001.SZ")
    assert strong_review["candles"][0] == {
        "date": "2026-01-01T00:00:00",
        "open": 10.0,
        "high": 10.1,
        "low": 9.9,
        "close": 10.0,
        "volume": 1000.0,
        "amount": 100000.0,
    }
    assert strong_review["candles"][-1]["close"] == 14.0
    assert data["ai"]["evidence"]["mode"] == "multi_stock"
    assert data["ai"]["evidence"]["comparisons"][0]["标的"] == "000300.SH"
    assert data["ai"]["messages"][0]["role"] == "system"
    assert "critique" in data["ai"]["messages"][0]["content"]
    assert "研究端排序复盘" in data["text"]["review"]
    assert "视频脚本视角" in data["text"]["video_script"]


def test_api_research_review_resolves_local_symbol_names(tmp_path) -> None:
    data_root = tmp_path / "market"
    metadata = data_root / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "symbols.csv").write_text(
        "stock_code,stock_name\n000001.SZ,本地强势\n000002.SZ,本地弱势\n",
        encoding="utf-8",
    )
    bars = pd.concat(
        [
            _bars("000001.SZ", [10, 10.5, 11, 12, 13, 14]),
            _bars("000002.SZ", [10, 9.8, 9.5, 9.7, 9.6, 9.4]),
        ],
        ignore_index=True,
    )
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    client = TestClient(create_app())

    response = client.post(
        "/api/research/review",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbols": ["000001.SZ", "000002.SZ"],
            "start": "2026-01-01",
            "end": "2026-01-08",
        },
    )

    assert response.status_code == 200
    names = {row["代码"]: row["股票"] for row in response.json()["ranking"]}
    assert names == {"000001.SZ": "本地强势", "000002.SZ": "本地弱势"}


def test_api_research_review_resolves_sector_names_from_catalog(tmp_path) -> None:
    data_root = tmp_path / "market"
    bars = _bars("880413.SH", [900, 910, 905, 930, 940, 955])
    write_local_bars(data_root=data_root, timeframe="1d", adjust="qfq", bars=bars)
    inventory = inventory_local_data(
        data_root=data_root,
        adjust="qfq",
        timeframes=("1d",),
        symbols=("880413.SH",),
    )
    build_catalog(
        data_root=data_root,
        inventory=inventory,
        symbol_metadata=pd.DataFrame(
            [{"stock_code": "880413.SH", "stock_name": "半导体", "source": "test", "path": ""}]
        ),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/research/review",
        json={
            "data_root": str(data_root),
            "timeframe": "1d",
            "symbols": ["880413.SH"],
            "start": "2026-01-01",
            "end": "2026-01-08",
        },
    )

    assert response.status_code == 200
    assert response.json()["ranking"][0]["股票"] == "半导体"


def test_api_research_review_ai_calls_compatible_chat(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}
    model_content = json.dumps(
        {
            "review": "研究复盘",
            "analysis": "数据分析",
            "critique": "视频锐评",
            "script_cards": [{"title": "平安银行", "body": "强", "grade": "人上人", "tomorrow_check": "看承接"}],
            "evidence_refs": ["rankings[0]"],
            "disclaimer": "仅供研究",
        },
        ensure_ascii=False,
    )

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": model_content}}]}).encode("utf-8")

    def fake_urlopen(request, timeout: int):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)
    client = TestClient(create_app())

    response = client.post(
        "/api/research/review-ai",
        json={
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret",
            "model": "compatible-model",
            "messages": [{"role": "user", "content": "{}"}],
            "evidence": {"rankings": [{"代码": "000001.SZ"}]},
            "temperature": 0.3,
            "timeout_seconds": 12,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-secret"
    assert captured["timeout"] == 12
    assert captured["body"] == {
        "model": "compatible-model",
        "messages": [{"role": "user", "content": "{}"}],
        "temperature": 0.3,
    }
    assert data["review"] == "研究复盘"
    assert data["analysis"] == "数据分析"
    assert data["critique"] == "视频锐评"
    assert data["script_cards"][0]["grade"] == "人上人"
    assert "sk-secret" not in response.text
