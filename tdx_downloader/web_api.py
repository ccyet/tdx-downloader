from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any
import urllib.error
import urllib.request
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
    should_use_parallels_runtime,
    symbol_metadata_with_runtime,
)
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES, inclusive_end_timestamp, normalize_symbol
from tdx_downloader.data.storage import load_local_bars
from tdx_downloader.data.symbols import DEFAULT_STOCK_NAME_BY_CODE, load_symbol_metadata
from tdx_downloader.research.history import HistorySearchConfig, search_history
from tdx_downloader.research.review import (
    ReviewConfig,
    analyze_price_review,
    build_comparison_stats,
    rank_review_results,
    render_multi_review_text,
    render_multi_video_script_text,
)
from tdx_downloader.research.review_ai import (
    ReviewAIFormatError,
    build_multi_review_ai_evidence,
    build_review_ai_messages,
    parse_review_ai_result,
)
from tdx_downloader.research.similarity import (
    CrossSectionSearchConfig,
    CrossSectionWindowTraversalConfig,
    search_cross_section,
    search_cross_section_window_traversal,
)

DEFAULT_TDX_PATH = "/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user"
DEFAULT_ADJUST = "qfq"
DEFAULT_TIMEFRAMES = ("1d",)
DEFAULT_BATCH_SIZE = 100
MAX_TABLE_RECORDS = 500
TASK_HISTORY_LIMIT = 50
TASK_EVENT_LIMIT = 40
PICKER_LIQUIDITY_SORT_GROUPS = frozenset({"ETF列表", "板块指数"})
PICKER_LIQUIDITY_LOOKBACK_BARS = 20

STAGE_LABELS = {
    "task_start": "任务启动",
    "local_task_start": "Windows 本地",
    "parallels_task_start": "Windows 调度",
    "parallels_command_start": "Windows 执行",
    "parallels_batch_retry_incomplete": "质量容错",
    "local_quality_gate_retry_incomplete": "质量容错",
    "parallels_command_done": "Windows 返回",
    "tdx_connection_check": "连接检查",
    "tdx_connection_ok": "连接成功",
    "tdx_connection_skipped": "未连接 TDX",
    "task_summary": "结果汇总",
    "catalog_refresh_start": "刷新索引",
    "catalog_refresh_done": "索引完成",
    "daily_sessions_start": "交易日锚点",
    "daily_sessions_done": "锚点完成",
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
    candidate_n: int = 100
    top_n: int = 10
    exclusion_bars: int = 20
    nearby_gap_days: int = 20
    path_weight: float = 0.7
    forward_windows: list[int] = Field(default_factory=lambda: [5, 20, 60])
    lookback_start: str = "1990-01-01"
    window_start: str | None = None
    algorithm: str = "baseline_price_feature"


class CrossSectionSearchPayload(ResearchBasePayload):
    target_symbol: str
    universe_symbols: list[str] = Field(default_factory=list)
    start: str
    end: str
    search_mode: str = "same_date"
    traversal_start: str | None = None
    traversal_end: str | None = None
    top_n: int = 20
    min_coverage: float = 0.8
    path_weight: float = 0.7
    exclusion_bars: int = 0
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


class ReviewAIPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.2
    timeout_seconds: int = 60


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
        symbol_metadata = load_symbol_metadata(DEFAULT_DATA_ROOT, tdx_path=DEFAULT_TDX_PATH)
        groups = shortcut_symbol_groups(metadata=symbol_metadata)
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
            "symbol_groups": groups,
            "symbol_names": _symbol_group_names(groups, symbol_metadata=symbol_metadata),
            "runtime": "parallels" if should_use_parallels_runtime() else "local",
        }

    @app.get("/api/symbol-groups")
    def symbol_groups(
        data_root: str = DEFAULT_DATA_ROOT,
        tdx_path: str = DEFAULT_TDX_PATH,
        adjust: str = DEFAULT_ADJUST,
        target: str = "",
    ) -> dict[str, Any]:
        try:
            symbol_metadata = symbol_metadata_with_runtime(data_root, tdx_path)
            groups = shortcut_symbol_groups(metadata=symbol_metadata)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        sorted_groups = _sort_picker_symbol_groups_by_recent_amount(groups, data_root=data_root, adjust=adjust)
        return {
            "groups": sorted_groups,
            "symbol_names": _symbol_group_names(sorted_groups, symbol_metadata=symbol_metadata),
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
                    candidate_n=payload.candidate_n,
                    top_n=payload.top_n,
                    exclusion_bars=payload.exclusion_bars,
                    nearby_gap_days=payload.nearby_gap_days,
                    path_weight=payload.path_weight,
                    window_start=payload.window_start,
                    algorithm=payload.algorithm,
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stock_names = _history_stock_names(payload, result.symbol)
        stock_name = stock_names.get(result.symbol, "")
        result_rows = result.results.copy()
        if not result_rows.empty and "股票" not in result_rows.columns:
            result_rows.insert(1, "股票", stock_name)
        return {
            "summary": {
                "symbol": result.symbol,
                "stock_name": stock_name,
                "timeframe": timeframe,
                "as_of": result.as_of,
                "window_start": result.current_window["date"].iloc[0] if not result.current_window.empty else None,
                "window_size": result.window_size,
                "match_count": len(result.results),
                "algorithm": payload.algorithm,
            },
            "current_window": _records(result.current_window),
            "historical_windows": [_records(window) for window in result.historical_windows],
            "historical_chart_windows": [_records(window) for window in result.historical_chart_windows],
            "results": _records(result_rows),
        }

    @app.post("/api/research/cross-section")
    def research_cross_section(payload: CrossSectionSearchPayload) -> dict[str, Any]:
        try:
            timeframe = _single_timeframe(payload.timeframe)
            symbols = normalize_symbol_tuple([payload.target_symbol, *payload.universe_symbols])
            if len(symbols) < 2:
                raise ValueError("横截面相似至少需要目标标的和 1 个候选标的。")
            search_mode = _cross_section_search_mode(payload.search_mode)
            bars = load_local_bars(
                data_root=payload.data_root,
                timeframe=timeframe,
                adjust=payload.adjust,
                symbols=symbols,
                start=_cross_section_payload_read_start(payload, search_mode),
                end=_cross_section_payload_read_end(payload, search_mode),
            )
            if search_mode == "traversal":
                traversal_start = payload.traversal_start or payload.start
                traversal_end = payload.traversal_end or payload.end
                result = search_cross_section_window_traversal(
                    bars,
                    CrossSectionWindowTraversalConfig(
                        target_symbol=payload.target_symbol,
                        universe_symbols=tuple(payload.universe_symbols),
                        target_start=payload.start,
                        target_end=payload.end,
                        traversal_start=traversal_start,
                        traversal_end=traversal_end,
                        top_n=payload.top_n,
                        min_coverage=payload.min_coverage,
                        path_weight=payload.path_weight,
                        exclusion_bars=payload.exclusion_bars,
                        forward_windows=tuple(payload.forward_windows),
                    ),
                )
            else:
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
        stock_names = _cross_section_stock_names(payload, symbols)
        stock_name = stock_names.get(result.target_symbol, "")
        result_rows = result.results.copy()
        if not result_rows.empty and "股票" not in result_rows.columns:
            result_rows.insert(1, "股票", result_rows["symbol"].map(lambda value: stock_names.get(normalize_symbol(value), "")))
        summary = {
            "target_symbol": result.target_symbol,
            "stock_name": stock_name,
            "timeframe": timeframe,
            "start": result.start if hasattr(result, "start") else result.target_start,
            "end": result.end if hasattr(result, "end") else result.target_end,
            "window_size": result.window_size,
            "match_count": len(result.results),
            "skipped_count": len(result.skipped),
            "search_mode": search_mode,
        }
        if search_mode == "traversal":
            summary.update(
                {
                    "traversal_start": result.traversal_start,
                    "traversal_end": result.traversal_end,
                }
            )
        return {
            "summary": summary,
            "results": _records(result_rows),
            "skipped": _records(result.skipped),
            "target_window": _symbol_window_candles(bars, result.target_symbol, summary["start"], summary["end"]),
            "candidate_windows": _cross_section_candidate_windows(bars, result_rows, stock_names=stock_names),
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
            stock_names = _review_stock_names(payload, symbols)
            ranking = rank_review_results(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
            warnings = [warning for result in results for warning in result.warnings]
            evidence = build_multi_review_ai_evidence(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
                warnings=warnings,
            )
            messages = build_review_ai_messages(evidence)
            review_text = render_multi_review_text(
                results,
                comparisons,
                stock_names=stock_names,
                direction_by_symbol=payload.direction_by_symbol,
            )
            video_script_text = render_multi_video_script_text(
                results,
                comparisons,
                stock_names=stock_names,
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
                    "candles": _review_candles(result.window),
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

    @app.post("/api/research/review-ai")
    def research_review_ai(payload: ReviewAIPayload) -> dict[str, Any]:
        try:
            return _call_review_ai(payload)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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


def _sort_picker_symbol_groups_by_recent_amount(
    groups: list[dict[str, Any]],
    *,
    data_root: str,
    adjust: str,
) -> list[dict[str, Any]]:
    sortable_symbols = [
        symbol
        for group in groups
        if str(group.get("name", "")) in PICKER_LIQUIDITY_SORT_GROUPS
        for symbol in _symbol_group_symbols(group)
    ]
    scores = _recent_amount_scores(data_root=data_root, adjust=adjust, symbols=sortable_symbols)
    if not scores:
        return groups

    sorted_groups: list[dict[str, Any]] = []
    for group in groups:
        name = str(group.get("name", ""))
        symbols = _symbol_group_symbols(group)
        if name not in PICKER_LIQUIDITY_SORT_GROUPS or not symbols:
            sorted_groups.append(group)
            continue
        ranked = _sort_symbols_by_amount(symbols, scores)
        sorted_groups.append({**group, "symbols": ranked})
    return sorted_groups


def _symbol_group_symbols(group: dict[str, Any]) -> list[str]:
    raw_symbols = group.get("symbols", [])
    if not isinstance(raw_symbols, list | tuple):
        return []
    return [symbol for symbol in (normalize_symbol(item) for item in raw_symbols) if symbol]


def _recent_amount_scores(*, data_root: str, adjust: str, symbols: list[str]) -> dict[str, float]:
    unique = normalize_symbol_tuple(symbols)
    if not unique:
        return {}
    bars = load_local_bars(
        data_root=data_root,
        timeframe="1d",
        adjust=adjust,
        symbols=unique,
        start="1900-01-01",
        end="2100-01-01",
    )
    if bars.empty or "amount" not in bars.columns:
        return {}
    frame = bars.loc[:, ["stock_code", "date", "amount"]].copy()
    frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
    frame = frame.dropna(subset=["stock_code", "date", "amount"])
    frame = frame.loc[frame["amount"].gt(0)].sort_values(["stock_code", "date"])
    if frame.empty:
        return {}
    recent = frame.groupby("stock_code", group_keys=False).tail(PICKER_LIQUIDITY_LOOKBACK_BARS)
    scores = recent.groupby("stock_code")["amount"].mean()
    return {str(symbol): float(value) for symbol, value in scores.items() if math.isfinite(float(value))}


def _sort_symbols_by_amount(symbols: list[str], scores: dict[str, float]) -> list[str]:
    original_order = {symbol: index for index, symbol in enumerate(symbols)}

    def sort_key(symbol: str) -> tuple[int, float, int]:
        score = scores.get(symbol)
        if score is None or not math.isfinite(score):
            return (1, 0.0, original_order[symbol])
        return (0, -score, original_order[symbol])

    return sorted(symbols, key=sort_key)


def _symbol_group_names(
    groups: list[dict[str, Any]],
    *,
    symbol_metadata: pd.DataFrame,
) -> dict[str, str]:
    symbols = normalize_symbol_tuple(symbol for group in groups for symbol in group.get("symbols", []))
    names = {symbol: DEFAULT_STOCK_NAME_BY_CODE[symbol] for symbol in symbols if symbol in DEFAULT_STOCK_NAME_BY_CODE}
    if not symbol_metadata.empty:
        for row in symbol_metadata.itertuples(index=False):
            symbol = normalize_symbol(getattr(row, "stock_code", ""))
            name = str(getattr(row, "stock_name", "") or "").strip()
            if symbol in symbols and name:
                names[symbol] = name
    return names


def _cross_section_search_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"same_date", "same", "cross", "同区间"}:
        return "same_date"
    if normalized in {"traversal", "window_traversal", "search_interval", "指定区间", "窗口遍历"}:
        return "traversal"
    raise ValueError("横截面搜索模式仅支持 same_date 或 traversal。")


def _cross_section_payload_read_start(payload: CrossSectionSearchPayload, search_mode: str) -> str:
    if search_mode == "traversal":
        values = [pd.Timestamp(payload.start), pd.Timestamp(payload.traversal_start or payload.start)]
        return min(values).date().isoformat()
    return _cross_section_read_start(payload.start, payload.date_tolerance_bars)


def _cross_section_payload_read_end(payload: CrossSectionSearchPayload, search_mode: str) -> str:
    if search_mode == "traversal":
        end = max(pd.Timestamp(payload.end), pd.Timestamp(payload.traversal_end or payload.end))
        return _cross_section_read_end(end.date().isoformat(), tuple(payload.forward_windows))
    return _cross_section_read_end(payload.end, tuple(payload.forward_windows))


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


def _review_stock_names(payload: ReviewSearchPayload, symbols: tuple[str, ...]) -> dict[str, str]:
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    resolved = service.repository.symbol_names(symbols=symbols)
    explicit = {
        normalize_symbol_tuple([symbol])[0]: str(name).strip()
        for symbol, name in payload.stock_names.items()
        if str(name).strip()
    }
    return {**resolved, **explicit}


def _history_stock_names(payload: HistorySearchPayload, symbol: str) -> dict[str, str]:
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    return service.repository.symbol_names(symbols=(symbol,))


def _cross_section_stock_names(payload: CrossSectionSearchPayload, symbols: tuple[str, ...]) -> dict[str, str]:
    service = DataManagementService(payload.data_root, adjust=payload.adjust)
    return service.repository.symbol_names(symbols=symbols)


def _review_candles(window: pd.DataFrame, *, include_symbol: bool = False) -> list[dict[str, Any]]:
    if window.empty:
        return []
    columns = ["date", "open", "high", "low", "close", "volume", "amount"]
    if include_symbol:
        columns.insert(1, "stock_code")
    present = [column for column in columns if column in window.columns]
    return _records(window[present], limit=None)


def _symbol_window_candles(
    bars: pd.DataFrame,
    symbol: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> list[dict[str, Any]]:
    if bars.empty:
        return []
    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol)
    normalized_symbol = normalize_symbol(symbol)
    window = frame.loc[
        (frame["stock_code"] == normalized_symbol)
        & frame["date"].between(pd.Timestamp(start), inclusive_end_timestamp(end))
    ].sort_values("date")
    return _review_candles(window, include_symbol=True)


def _cross_section_candidate_windows(
    bars: pd.DataFrame,
    results: pd.DataFrame,
    *,
    stock_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if results.empty:
        return []
    name_map = stock_names or {}
    rows: list[dict[str, Any]] = []
    for index, row in results.reset_index(drop=True).iterrows():
        symbol = normalize_symbol(row.get("symbol", ""))
        if not symbol:
            continue
        start = row.get("区间开始")
        end = row.get("区间结束")
        rows.append(
            {
                "rank": index + 1,
                "symbol": symbol,
                "name": name_map.get(symbol, ""),
                "start": _json_value(start),
                "end": _json_value(end),
                "candles": _symbol_window_candles(bars, symbol, pd.Timestamp(start), pd.Timestamp(end)),
            }
        )
    return rows


def _call_review_ai(payload: ReviewAIPayload) -> dict[str, Any]:
    base_url = payload.base_url.strip()
    api_key = payload.api_key.strip()
    model = payload.model.strip()
    if not base_url:
        raise ValueError("请填写 AI 接口 URL。")
    if not api_key:
        raise ValueError("请填写 AI API Key。")
    if not model:
        raise ValueError("请填写 AI 模型名称。")
    if not payload.messages:
        raise ValueError("缺少可提交给模型的 messages。")
    request_body = {
        "model": model,
        "messages": payload.messages,
        "temperature": float(payload.temperature),
    }
    request = urllib.request.Request(
        _chat_completions_url(base_url),
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_ai_timeout(payload.timeout_seconds)) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"AI 接口调用失败：HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI 接口连接失败：{exc.reason}") from exc
    try:
        response_payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI 接口返回不是合法 JSON：{exc}") from exc
    content = _ai_message_content(response_payload)
    try:
        parsed = parse_review_ai_result(content, evidence=payload.evidence or None)
    except ReviewAIFormatError as exc:
        raise ValueError(f"AI 输出格式错误：{exc}") from exc
    return {
        "review": parsed.review,
        "analysis": parsed.analysis,
        "critique": parsed.critique,
        "script_cards": [
            {
                "title": card.title,
                "body": card.body,
                "grade": card.grade,
                "tomorrow_check": card.tomorrow_check,
            }
            for card in parsed.script_cards
        ],
        "evidence_refs": list(parsed.evidence_refs),
        "disclaimer": parsed.disclaimer,
        "raw": parsed.raw,
    }


def _chat_completions_url(base_url: str) -> str:
    text = base_url.strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        raise ValueError("AI 接口 URL 必须以 http:// 或 https:// 开头。")
    if text.endswith("/chat/completions"):
        return text
    return f"{text}/chat/completions"


def _ai_timeout(value: int) -> int:
    return max(5, min(int(value or 60), 180))


def _ai_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("AI 接口返回缺少 choices。")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI 接口返回缺少 message.content。")
    return content


def _open_native_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    if sys.platform == "darwin":
        return _open_macos_directory_dialog(initial_directory, title)
    if sys.platform.startswith("win"):
        return _open_windows_directory_dialog(initial_directory, title)
    raise RuntimeError("当前系统暂不支持弹窗选择文件夹，请直接输入路径。")


def _open_macos_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
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


def _open_windows_directory_dialog(initial_directory: str | Path, title: str) -> Path | None:
    script = r"""
param(
    [string]$DialogTitle,
    [string]$InitialDirectory
)
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $DialogTitle
$dialog.SelectedPath = $InitialDirectory
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $dialog.SelectedPath
    exit 0
}
if ($result -eq [System.Windows.Forms.DialogResult]::Cancel) {
    exit 2
}
exit 1
"""
    initial_path = Path(initial_directory) if str(initial_directory).strip() else Path.home()
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
                title or "选择文件夹",
                str(_existing_directory(initial_path)),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("文件夹选择窗口超时，请重新点击选择。") from exc
    except OSError as exc:
        raise RuntimeError("无法打开 Windows 文件夹选择窗口，请确认服务在当前桌面用户会话中启动。") from exc

    if result.returncode == 2:
        return None
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Windows 文件夹选择失败。")

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
        "records": _records(catalog, limit=None),
        "record_count": int(len(catalog)),
        "catalog_path": str(path),
        "catalog_exists": path.exists(),
        "rebuilt": rebuilt,
        "record_limit": None,
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
        else:
            _append_event(
                task_id,
                {
                    "stage": "local_task_start",
                    "message": "Windows 本地模式已启动，将先审计缓存，再按需连接通达信。",
                },
            )
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
        task = _tasks[task_id]
        task.events.append(event_payload)
        if len(task.events) > TASK_EVENT_LIMIT:
            del task.events[: len(task.events) - TASK_EVENT_LIMIT]


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


def _records(frame: pd.DataFrame, *, limit: int | None = MAX_TABLE_RECORDS) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    records = frame if limit is None else frame.head(limit)
    return [_json_dict(record) for record in records.to_dict("records")]


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
