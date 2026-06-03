from __future__ import annotations

from fastapi.testclient import TestClient
import pandas as pd

from tdx_downloader import web_api
from tdx_downloader.data.catalog import query_catalog
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
    groups = {group["name"]: group["symbols"] for group in response.json()["groups"]}
    assert groups["全A股票"] == ["000001.SZ", "600000.SH"]
    assert groups["板块指数"] == ["880001.SH"]


def test_api_overview_does_not_require_existing_catalog(tmp_path) -> None:
    client = TestClient(create_app())

    response = client.get("/api/overview", params={"data_root": str(tmp_path)})

    assert response.status_code == 200
    data = response.json()
    assert data["catalog_exists"] is False
    assert data["records"] == []
    assert data["summary"]["catalog_row_count"] == 0.0


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


def test_api_pick_directory_returns_selected_path(monkeypatch, tmp_path) -> None:
    def fake_dialog(initial_directory: str, title: str):
        assert initial_directory == str(tmp_path)
        assert title == "选择行情根目录"
        return tmp_path

    monkeypatch.setattr(web_api, "_open_native_directory_dialog", fake_dialog)
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

    monkeypatch.setattr(web_api, "_open_native_directory_dialog", fake_dialog)
    client = TestClient(create_app())

    response = client.post("/api/pick-directory", json={})

    assert response.status_code == 400
    assert "暂不支持" in response.json()["detail"]


def test_existing_directory_uses_nearest_existing_parent(tmp_path) -> None:
    missing_child = tmp_path / "missing" / "child"

    assert web_api._existing_directory(missing_child) == tmp_path


def test_api_clear_tasks_keeps_running_queue_empty() -> None:
    client = TestClient(create_app())

    response = client.delete("/api/tasks")

    assert response.status_code == 200
    data = response.json()
    assert data["removed_count"] >= 0
    assert data["running_count"] >= 0


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

    monkeypatch.setattr(web_api, "download_with_runtime", fake_download_with_runtime)
    monkeypatch.setattr(web_api, "should_use_parallels_runtime", lambda: False)
    with web_api._tasks_lock:
        web_api._tasks.clear()
    payload = web_api.DownloadPayload(
        data_root=str(data_root),
        symbols=["000750.SZ"],
        timeframes=["1d"],
        start="2026-06-01",
        end="2026-06-01",
        mode="force",
    )
    task = web_api._create_task("download")

    web_api._run_download_task(task.id, payload, "force")

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


def test_api_research_cross_section_reads_local_cache_with_date_tolerance(tmp_path) -> None:
    data_root = tmp_path / "market"
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
    assert data["results"][0]["symbol"] == "000002.SZ"


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
    assert data["ai"]["evidence"]["mode"] == "multi_stock"
    assert data["ai"]["evidence"]["comparisons"][0]["标的"] == "000300.SH"
    assert data["ai"]["messages"][0]["role"] == "system"
    assert "critique" in data["ai"]["messages"][0]["content"]
    assert "研究端排序复盘" in data["text"]["review"]
    assert "视频脚本视角" in data["text"]["video_script"]
