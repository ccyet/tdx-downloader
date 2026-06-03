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
    shortcut_symbol_groups,
    shortcut_symbols,
)
from tdx_downloader.data.parallels_runtime import (
    download_with_runtime,
    shortcut_symbol_groups_with_runtime,
    should_use_parallels_runtime,
    symbol_metadata_with_runtime,
)
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.research.history import HistorySearchConfig, search_history
from tdx_downloader.research.review import (
    ReviewConfig,
    analyze_price_review,
    build_comparison_stats,
    rank_review_results,
    render_multi_review_text,
    render_multi_video_script_text,
)
from tdx_downloader.research.review_ai import build_multi_review_ai_evidence, build_review_ai_messages
from tdx_downloader.research.similarity import CrossSectionSearchConfig, search_cross_section

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
    "catalog_refresh_start": "刷新索引",
    "catalog_refresh_done": "索引完成",
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


class ResearchBasePayload(BaseModel):
    data_root: str = DEFAULT_DATA_ROOT
    adjust: str = DEFAULT_ADJUST
    timeframe: str = "1d"


class HistorySearchPayload(ResearchBasePayload):
    symbol: str
    as_of: str = Field(default_factory=lambda: date.today().isoformat())
    window_size: int = 20
    top_n: int = 10
    exclusion_bars: int = 20
    path_weight: float = 0.7
    forward_windows: list[int] = Field(default_factory=lambda: [5, 20, 60])
    lookback_start: str = "1990-01-01"
    window_start: str | None = None


class CrossSectionSearchPayload(ResearchBasePayload):
    target_symbol: str
    universe_symbols: list[str] = Field(default_factory=list)
    start: str
    end: str
    top_n: int = 20
    min_coverage: float = 0.8
    path_weight: float = 0.7
    forward_windows: list[int] = Field(default_factory=lambda: [3, 5, 10])
    date_tolerance_bars: int = 0


class ReviewSearchPayload(ResearchBasePayload):
    symbols: list[str] = Field(default_factory=list)
    start: str
    end: str
    benchmark_symbol: str = ""
    min_swing_return: float = 0.05
    min_segment_bars: int = 3
    max_segments: int = 6
    stock_names: dict[str, str] = Field(default_factory=dict)
    direction_by_symbol: dict[str, str] = Field(default_factory=dict)


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
            "symbol_groups": shortcut_symbol_groups(data_root=DEFAULT_DATA_ROOT, tdx_path=DEFAULT_TDX_PATH),
            "runtime": "parallels" if should_use_parallels_runtime() else "local",
        }

    @app.get("/api/symbol-groups")
    def symbol_groups(
        data_root: str = DEFAULT_DATA_ROOT,
        tdx_path: str = DEFAULT_TDX_PATH,
        target: str = "",
    ) -> dict[str, Any]:
        try:
            groups = shortcut_symbol_groups_with_runtime(data_root, tdx_path, target=target)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"groups": groups}

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
                symbol_metadata=symbol_metadata_with_runtime(data_root, tdx_path),
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

    @app.post("/api/research/history")
    def research_history(payload: HistorySearchPayload) -> dict[str, Any]:
        try:
            timeframe = _single_timeframe(payload.timeframe)
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=[payload.symbol],
                start=payload.lookback_start,
                end=payload.as_of,
            )
            result = search_history(
                bars,
                HistorySearchConfig(
                    symbol=payload.symbol,
                    as_of=payload.as_of,
                    window_size=payload.window_size,
                    forward_windows=tuple(payload.forward_windows),
                    top_n=payload.top_n,
                    exclusion_bars=payload.exclusion_bars,
                    path_weight=payload.path_weight,
                    window_start=payload.window_start,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": {
                "symbol": result.symbol,
                "timeframe": timeframe,
                "as_of": result.as_of,
                "window_size": result.window_size,
                "match_count": len(result.results),
            },
            "current_window": _records(result.current_window),
            "historical_windows": [_records(window) for window in result.historical_windows],
            "results": _records(result.results),
        }

    @app.post("/api/research/cross-section")
    def research_cross_section(payload: CrossSectionSearchPayload) -> dict[str, Any]:
        try:
            timeframe = _single_timeframe(payload.timeframe)
            symbols = normalize_symbol_tuple([payload.target_symbol, *payload.universe_symbols])
            if len(symbols) < 2:
                raise ValueError("横截面相似至少需要目标标的和 1 个候选标的。")
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=symbols,
                start=_cross_section_read_start(payload.start, payload.date_tolerance_bars),
                end=_cross_section_read_end(payload.end, tuple(payload.forward_windows)),
            )
            result = search_cross_section(
                bars,
                CrossSectionSearchConfig(
                    target_symbol=payload.target_symbol,
                    universe_symbols=tuple(payload.universe_symbols),
                    start=payload.start,
                    end=payload.end,
                    top_n=payload.top_n,
                    min_coverage=payload.min_coverage,
                    path_weight=payload.path_weight,
                    forward_windows=tuple(payload.forward_windows),
                    date_tolerance_bars=payload.date_tolerance_bars,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": {
                "target_symbol": result.target_symbol,
                "timeframe": timeframe,
                "start": result.start,
                "end": result.end,
                "window_size": result.window_size,
                "match_count": len(result.results),
                "skipped_count": len(result.skipped),
            },
            "results": _records(result.results),
            "skipped": _records(result.skipped),
        }

    @app.post("/api/research/review")
    def research_review(payload: ReviewSearchPayload) -> dict[str, Any]:
        try:
            timeframe = _single_timeframe(payload.timeframe)
            symbols = normalize_symbol_tuple(payload.symbols)
            if not symbols:
                raise ValueError("多股复盘至少需要 1 个标的代码。")
            benchmark_symbols = normalize_symbol_tuple([payload.benchmark_symbol]) if payload.benchmark_symbol else ()
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=[*symbols, *benchmark_symbols],
                start=payload.start,
                end=payload.end,
            )
            results = [
                analyze_price_review(
                    bars,
                    ReviewConfig(
                        symbol=symbol,
                        start=payload.start,
                        end=payload.end,
                        min_swing_return=payload.min_swing_return,
                        min_segment_bars=payload.min_segment_bars,
                        max_segments=payload.max_segments,
                    ),
                )
                for symbol in symbols
            ]
            comparisons = _review_comparisons(results, bars, benchmark_symbols[0] if benchmark_symbols else "")
            ranking = rank_review_results(
                results,
                comparisons,
                stock_names=payload.stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
            warnings = [warning for result in results for warning in result.warnings]
            evidence = build_multi_review_ai_evidence(
                results,
                comparisons,
                stock_names=payload.stock_names,
                direction_by_symbol=payload.direction_by_symbol,
                warnings=warnings,
            )
            messages = build_review_ai_messages(evidence)
            review_text = render_multi_review_text(
                results,
                comparisons,
                stock_names=payload.stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
            video_script_text = render_multi_video_script_text(
                results,
                comparisons,
                stock_names=payload.stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": {
                "timeframe": timeframe,
                "start": payload.start,
                "end": payload.end,
                "symbol_count": len(symbols),
                "ranked_count": len(ranking),
            },
            "ranking": _records(ranking),
            "comparisons": _records(comparisons),
            "reviews": [
                {
                    "symbol": result.symbol,
                    "start": result.start,
                    "end": result.end,
                    "overview": _json_dict(result.overview),
                    "warnings": list(result.warnings),
                    "main_segments": _records(result.main_segments),
                }
                for result in results
            ],
            "ai": {
                "evidence": _json_dict(evidence),
                "messages": [_json_dict(message) for message in messages],
            },
            "text": {
                "review": review_text,
                "video_script": video_script_text,
            },
        }

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


def _single_timeframe(timeframe: str) -> str:
    return normalize_timeframes([timeframe])[0]


def _cross_section_read_start(start: str, tolerance_bars: int) -> str:
    padding_days = max(14, int(tolerance_bars) * 5 + 7)
    return (pd.Timestamp(start) - pd.Timedelta(days=padding_days)).date().isoformat()


def _cross_section_read_end(end: str, forward_windows: tuple[int, ...]) -> str:
    max_forward = max(forward_windows) if forward_windows else 0
    padding_days = max(14, int(max_forward) * 5 + 7)
    return (pd.Timestamp(end) + pd.Timedelta(days=padding_days)).date().isoformat()


def _review_comparisons(results: list[Any], bars: pd.DataFrame, benchmark_symbol: str) -> pd.DataFrame:
    if not benchmark_symbol:
        return pd.DataFrame()
    benchmark = bars.loc[bars["stock_code"] == benchmark_symbol].copy()
    rows: list[dict[str, object]] = []
    for result in results:
        if result.window.empty:
            continue
        rows.append({"代码": result.symbol, **build_comparison_stats(result.window, benchmark, benchmark_symbol)})
    return pd.DataFrame(rows)


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
        _append_event(task_id, {"stage": "catalog_refresh_start", "message": "开始刷新缓存资产索引。"})
        snapshot = service.cache_snapshot(
            timeframes=SUPPORTED_TIMEFRAMES,
            symbols=None,
            tdx_path=payload.tdx_path,
            symbol_metadata=symbol_metadata_with_runtime(payload.data_root, payload.tdx_path),
            rebuild_catalog=True,
        )
        _append_event(
            task_id,
            {"stage": "catalog_refresh_done", "message": f"缓存资产索引已刷新：{len(snapshot.catalog)} 条。"},
        )
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
    if isinstance(value, dict):
        return _json_dict(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
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
