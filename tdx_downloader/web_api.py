from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tdx_downloader.cli import DEFAULT_DATA_ROOT
from tdx_downloader.data.catalog import ASSET_TYPE_LABELS, catalog_path_for, query_catalog
from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataManagementService,
    cache_by_asset_type,
    cache_by_dataset,
    cache_by_status,
    cache_by_timeframe,
    cache_readiness,
    cache_summary,
    normalize_download_mode,
    normalize_symbol_tuple,
    normalize_timeframes,
    shortcut_symbols,
)
from tdx_downloader.data.parallels_runtime import download_with_runtime, should_use_parallels_runtime
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES

DEFAULT_TDX_PATH = "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"
DEFAULT_ADJUST = "qfq"
DEFAULT_TIMEFRAMES = ("1d",)
DEFAULT_BATCH_SIZE = 100
MAX_TABLE_RECORDS = 500
TASK_HISTORY_LIMIT = 50

STAGE_LABELS = {
    "task_start": "任务启动",
    "parallels_task_start": "Windows 调度",
    "parallels_command_start": "Windows 执行",
    "parallels_command_done": "Windows 返回",
    "tdx_connection_check": "连接检查",
    "tdx_connection_ok": "连接成功",
    "tdx_connection_skipped": "未连接 TDX",
    "task_summary": "结果汇总",
    "audit_start": "审计缓存",
    "audit_done": "审计完成",
    "fetch_start": "请求 TDX",
    "tdx_request_start": "请求 TDX",
    "tdx_batch_start": "批次请求",
    "tdx_batch_done": "批次完成",
    "tdx_fallback_start": "5m 聚合补齐",
    "tdx_request_done": "请求完成",
    "write_start": "写入缓存",
    "write_done": "写入完成",
    "reaudit_start": "复核缓存",
    "reaudit_done": "复核完成",
    "fetch_skipped": "跳过下载",
    "prepare_done": "任务完成",
    "force_timeframe_start": "强制刷新",
    "force_timeframe_done": "刷新完成",
    "task_done": "任务完成",
    "task_failed": "任务失败",
}


class DownloadPayload(BaseModel):
    data_root: str = DEFAULT_DATA_ROOT
    adjust: str = DEFAULT_ADJUST
    tdx_path: str = DEFAULT_TDX_PATH
    symbols: list[str] = Field(default_factory=lambda: list(shortcut_symbols("核心样例")))
    timeframes: list[str] = Field(default_factory=lambda: list(DEFAULT_TIMEFRAMES))
    start: str = Field(default_factory=lambda: (date.today() - timedelta(days=20)).isoformat())
    end: str = Field(default_factory=lambda: date.today().isoformat())
    mode: str = "smart"
    batch_size: int = DEFAULT_BATCH_SIZE
    min_coverage_ratio: float | None = None
    strict_after_update: bool = True


class DirectoryPickerPayload(BaseModel):
    initial_directory: str = ""
    title: str = "选择文件夹"


@dataclass
class TaskState:
    id: str
    kind: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tdx-api")
_tasks: dict[str, TaskState] = {}
_tasks_lock = threading.Lock()


def create_app() -> FastAPI:
    app = FastAPI(title="TDX Downloader API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_routes(app)
    _mount_static_frontend(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "runtime": "parallels" if should_use_parallels_runtime() else "local",
            "time": _now_text(),
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        today = date.today()
        return {
            "defaults": {
                "data_root": DEFAULT_DATA_ROOT,
                "adjust": DEFAULT_ADJUST,
                "tdx_path": DEFAULT_TDX_PATH,
                "timeframes": list(DEFAULT_TIMEFRAMES),
                "batch_size": DEFAULT_BATCH_SIZE,
                "start": (today - timedelta(days=20)).isoformat(),
                "end": today.isoformat(),
                "mode": "smart",
                "strict_after_update": True,
            },
            "timeframes": list(SUPPORTED_TIMEFRAMES),
            "asset_types": [{"value": key, "label": label} for key, label in ASSET_TYPE_LABELS.items()],
            "symbol_groups": [
                {"name": "核心样例", "symbols": list(shortcut_symbols("核心样例"))},
                {"name": "宽基指数", "symbols": list(shortcut_symbols("宽基指数"))},
                {"name": "ETF样例", "symbols": list(shortcut_symbols("ETF样例"))},
            ],
            "runtime": "parallels" if should_use_parallels_runtime() else "local",
        }

    @app.get("/api/overview")
    def overview(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        tdx_path: str = DEFAULT_TDX_PATH,
        refresh: bool = False,
        timeframes: list[str] | None = Query(default=None),
    ) -> dict[str, Any]:
        service = DataManagementService(data_root, adjust=adjust)
        if refresh:
            snapshot = service.cache_snapshot(
                timeframes=tuple(timeframes or SUPPORTED_TIMEFRAMES),
                symbols=None,
                tdx_path=tdx_path,
                rebuild_catalog=True,
            )
            return _catalog_payload(snapshot.catalog, data_root=data_root, rebuilt=True)
        catalog = query_catalog(data_root=data_root)
        return _catalog_payload(catalog, data_root=data_root, rebuilt=False)

    @app.post("/api/plan")
    def plan(payload: DownloadPayload) -> dict[str, Any]:
        config = _download_config(payload)
        if not config.symbols:
            raise HTTPException(status_code=400, detail="预览计划需要标的代码。")
        service = DataManagementService(payload.data_root, adjust=payload.adjust)
        table = service.download_plan(config)
        action = table["action"].fillna("").astype(str) if "action" in table.columns else pd.Series(dtype=str)
        return {
            "summary": {
                "row_count": int(len(table)),
                "fetch_count": int(action.eq("fetch").sum()),
                "cached_count": int(action.eq("cached").sum()),
                "missing_rows": _numeric_sum(table, "missing_rows"),
                "expected_rows": _numeric_sum(table, "expected_rows"),
            },
            "records": _records(table),
        }

    @app.post("/api/download")
    def download(payload: DownloadPayload) -> dict[str, Any]:
        config = _download_config(payload)
        if not config.symbols:
            raise HTTPException(status_code=400, detail="执行下载需要标的代码。")
        mode = normalize_download_mode(payload.mode)
        task = _create_task("download")
        _executor.submit(_run_download_task, task.id, payload, mode)
        return _task_payload(task)

    @app.post("/api/pick-directory")
    def pick_directory(payload: DirectoryPickerPayload) -> dict[str, Any]:
        try:
            selected = _open_native_directory_dialog(payload.initial_directory, payload.title)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(selected) if selected is not None else None, "cancelled": selected is None}

    @app.get("/api/tasks")
    def tasks() -> dict[str, Any]:
        with _tasks_lock:
            ordered = sorted(_tasks.values(), key=lambda item: item.created_at, reverse=True)[:TASK_HISTORY_LIMIT]
            return {"tasks": [_task_payload(task) for task in ordered]}

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, Any]:
        task = _get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        return _task_payload(task)

    @app.delete("/api/tasks")
    def clear_tasks() -> dict[str, Any]:
        with _tasks_lock:
            running = {task_id: task for task_id, task in _tasks.items() if task.status in {"queued", "running"}}
            removed_count = len(_tasks) - len(running)
            _tasks.clear()
            _tasks.update(running)
        return {"removed_count": removed_count, "running_count": len(running)}


def _mount_static_frontend(app: FastAPI) -> None:
    dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")


def _download_config(payload: DownloadPayload) -> DataDownloadConfig:
    batch_size = max(int(payload.batch_size), 1)
    try:
        symbols = normalize_symbol_tuple(payload.symbols)
        timeframes = normalize_timeframes(payload.timeframes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DataDownloadConfig(
        symbols=symbols,
        timeframes=timeframes,
        start=payload.start,
        end=payload.end,
        tqcenter_path=payload.tdx_path,
        batch_size=batch_size,
        min_coverage_ratio=payload.min_coverage_ratio,
        strict_after_update=payload.strict_after_update,
    )


def _open_native_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    if sys.platform != "darwin":
        raise RuntimeError("当前系统暂不支持弹窗选择文件夹，请直接输入路径。")

    script = """
on run argv
    set dialogPrompt to item 1 of argv
    set defaultPath to item 2 of argv
    set chosenFolder to choose folder with prompt dialogPrompt default location (POSIX file defaultPath)
    return POSIX path of chosenFolder
end run
"""
    initial_path = Path(initial_directory) if str(initial_directory).strip() else Path.home()
    try:
        result = subprocess.run(
            ["osascript", "-e", script, title or "选择文件夹", str(_existing_directory(initial_path))],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("文件夹选择窗口超时，请重新点击选择。") from exc
    except OSError as exc:
        raise RuntimeError("无法打开系统文件夹选择窗口。") from exc

    stderr = result.stderr.strip()
    if result.returncode != 0:
        if "User canceled" in stderr or "用户已取消" in stderr:
            return None
        raise RuntimeError(stderr or "系统文件夹选择失败。")

    selected = result.stdout.strip()
    if not selected:
        return None
    return Path(selected).expanduser()


def _existing_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists() and expanded.is_dir():
        return expanded
    for parent in expanded.parents:
        if parent.exists() and parent.is_dir():
            return parent
    return Path.home()


def _catalog_payload(catalog: pd.DataFrame, *, data_root: str, rebuilt: bool) -> dict[str, Any]:
    path = catalog_path_for(data_root)
    return {
        "summary": _json_dict(cache_summary(catalog)),
        "by_timeframe": _records(cache_by_timeframe(catalog)),
        "by_asset_type": _records(cache_by_asset_type(catalog)),
        "by_status": _records(cache_by_status(catalog)),
        "by_dataset": _records(cache_by_dataset(catalog)),
        "readiness": _records(cache_readiness(catalog)),
        "records": _records(catalog, limit=MAX_TABLE_RECORDS),
        "catalog_path": str(path),
        "catalog_exists": path.exists(),
        "rebuilt": rebuilt,
        "record_limit": MAX_TABLE_RECORDS,
    }


def _run_download_task(task_id: str, payload: DownloadPayload, mode: str) -> None:
    _update_task(task_id, status="running", started_at=_now_text())
    _append_event(task_id, {"stage": "task_start", "message": "下载任务已进入后台执行。"})
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    config = _download_config(payload)

    def on_progress(event: dict[str, object]) -> None:
        _append_event(task_id, event)

    try:
        if should_use_parallels_runtime():
            _append_event(task_id, {"stage": "parallels_task_start", "message": "按任务计划调度 Parallels/Windows。"})
        result = download_with_runtime(service, config, mode=mode, progress_callback=on_progress)
        if should_use_parallels_runtime():
            rows_written = int(float(result.summary.get("rows_written") or 0))
            fetched_count = int(float(result.summary.get("fetched_count") or 0))
            message = (
                f"Parallels/Windows 下载完成：{fetched_count} 项 fetch，写入 {rows_written} 行。"
                if fetched_count or rows_written
                else "本地缓存已覆盖当前任务，未建立 TDX 取数连接。"
            )
            _append_event(task_id, {"stage": "task_summary", "message": message})
        table_payload = {"summary": _json_dict(result.summary), "records": _records(result.table)}
        _append_event(task_id, {"stage": "task_done", "message": "下载任务完成。"})
        _update_task(task_id, status="succeeded", finished_at=_now_text(), result=table_payload)
    except Exception as exc:
        _append_event(task_id, {"stage": "task_failed", "message": str(exc)})
        _update_task(task_id, status="failed", finished_at=_now_text(), error=str(exc))


def _create_task(kind: str) -> TaskState:
    task = TaskState(id=uuid4().hex, kind=kind)
    with _tasks_lock:
        _tasks[task.id] = task
        while len(_tasks) > TASK_HISTORY_LIMIT:
            oldest = min(_tasks.values(), key=lambda item: item.created_at)
            _tasks.pop(oldest.id, None)
    return task


def _get_task(task_id: str) -> TaskState | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def _update_task(task_id: str, **changes: Any) -> None:
    with _tasks_lock:
        task = _tasks[task_id]
        for key, value in changes.items():
            setattr(task, key, value)


def _append_event(task_id: str, event: dict[str, object]) -> None:
    event_payload = dict(event)
    event_payload["time"] = _now_text()
    event_payload["label"] = _progress_label(event_payload)
    with _tasks_lock:
        _tasks[task_id].events.append(event_payload)


def _task_payload(task: TaskState) -> dict[str, Any]:
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "events": [_json_dict(event) for event in task.events],
        "result": task.result,
        "error": task.error,
    }


def _records(frame: pd.DataFrame, *, limit: int = MAX_TABLE_RECORDS) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [_json_dict(record) for record in frame.head(limit).to_dict("records")]


def _json_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in values.items()}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _numeric_sum(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _progress_label(event: dict[str, object]) -> str:
    stage = str(event.get("stage", ""))
    label = STAGE_LABELS.get(stage, stage)
    timeframe = str(event.get("timeframe") or "")
    batch_index = event.get("batch_index")
    batch_count = event.get("batch_count")
    if batch_index and batch_count:
        return f"{label} · {timeframe} · {batch_index}/{batch_count}"
    if timeframe:
        return f"{label} · {timeframe}"
    return label


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    import uvicorn

    uvicorn.run("tdx_downloader.web_api:app", host="127.0.0.1", port=8622, reload=True)


app = create_app()


if __name__ == "__main__":
    main()
