from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
import pandas as pd

from tdx_downloader.data.manager import (
    DataDownloadConfig,
    DataManagementService,
    normalize_download_mode,
    normalize_symbol_tuple,
    normalize_timeframes,
)
from tdx_downloader.data.parallels_runtime import (
    download_with_runtime,
    should_use_parallels_runtime,
    symbol_metadata_with_runtime,
)
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES
from tdx_downloader.data.symbols import load_symbol_metadata

from ..serialization import _json_dict, _numeric_sum, _records
from ..schemas import DownloadPayload
from ..task_store import _append_event, _create_task, _executor, _now_text, _task_payload, _update_task


def register_download_routes(app: FastAPI) -> None:
    @app.post("/api/plan")
    def plan(payload: DownloadPayload) -> dict[str, Any]:
        config = _download_config(payload)
        if not config.symbols:
            raise HTTPException(status_code=400, detail="预览计划需要标的代码。")
        service = DataManagementService(payload.data_root, adjust=payload.adjust)
        table = _sort_plan_table(service.download_plan(config), config.timeframes)
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


def _sort_plan_table(table: pd.DataFrame, requested_timeframes: tuple[str, ...]) -> pd.DataFrame:
    if table.empty or "timeframe" not in table.columns:
        return table
    display_order = _plan_timeframe_display_order(requested_timeframes)
    requested_order = {timeframe: index for index, timeframe in enumerate(display_order)}
    fallback_order = len(requested_order)
    sorted_table = table.copy()
    sorted_table["_timeframe_order"] = sorted_table["timeframe"].map(
        lambda value: requested_order.get(str(value), fallback_order)
    )
    sorted_table["_original_order"] = range(len(sorted_table))
    return (
        sorted_table.sort_values(["_timeframe_order", "_original_order"])
        .drop(columns=["_timeframe_order", "_original_order"])
        .reset_index(drop=True)
    )


def _plan_timeframe_display_order(requested_timeframes: tuple[str, ...]) -> tuple[str, ...]:
    requested = tuple(dict.fromkeys(str(timeframe) for timeframe in requested_timeframes))
    intraday = tuple(timeframe for timeframe in requested if timeframe != "1d")
    daily = tuple(timeframe for timeframe in requested if timeframe == "1d")
    return intraday + daily if intraday else requested


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
        symbol_metadata = (
            symbol_metadata_with_runtime(payload.data_root, payload.tdx_path)
            if should_use_parallels_runtime()
            else load_symbol_metadata(payload.data_root, tdx_path=payload.tdx_path)
        )
        snapshot = service.cache_snapshot(
            timeframes=SUPPORTED_TIMEFRAMES,
            symbols=None,
            tdx_path=payload.tdx_path,
            symbol_metadata=symbol_metadata,
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
