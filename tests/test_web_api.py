from __future__ import annotations

from fastapi.testclient import TestClient
import pandas as pd

from tdx_downloader import web_api
from tdx_downloader.data.catalog import query_catalog
from tdx_downloader.data.manager import DataDownloadResult, download_summary
from tdx_downloader.data.storage import write_local_bars
from tdx_downloader.web_api import create_app


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
