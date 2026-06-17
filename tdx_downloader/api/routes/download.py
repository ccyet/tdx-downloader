from __future__ import annotations

import logging
import time
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
from tdx_downloader.data.catalog import CatalogDatabaseBusy
from tdx_downloader.data.parallels_runtime import (
    download_with_runtime,
    should_use_parallels_runtime,
    symbol_metadata_with_runtime,
)
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES
from tdx_downloader.data.symbols import load_symbol_metadata

from ..serialization import _json_dict, _numeric_sum, _records
from ..schemas import DownloadPayload
from ..task_store import (
    TaskCancelled,
    _append_event,
    _create_task,
    _executor,
    _now_text,
    _raise_if_task_cancelled,
    _task_payload,
    _update_task,
    _wait_if_task_paused,
)

_LOGGER = logging.getLogger(__name__)


def register_download_routes(app: FastAPI) -> None:
    @app.post("/api/plan")
    def plan(payload: DownloadPayload) -> dict[str, Any]:
        started_at = time.perf_counter()
        config = _download_config(payload)
        if not config.symbols:
            raise HTTPException(status_code=400, detail="预览计划需要标的代码。")
        service = DataManagementService(payload.data_root, adjust=payload.adjust)
        try:
            table = _sort_plan_table(service.preview_download_plan(config), config.timeframes)
        except CatalogDatabaseBusy as exc:
            raise HTTPException(
                status_code=409,
                detail="本地缓存索引正在写入，预览计划暂时不可用；请稍后重试或先等待刷新完成。",
            ) from exc
        action = table["action"].fillna("").astype(str) if "action" in table.columns else pd.Series(dtype=str)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        _LOGGER.info(
            "api_plan completed elapsed_ms=%s symbols=%s timeframes=%s rows=%s fetch=%s cached=%s",
            elapsed_ms,
            len(config.symbols),
            ",".join(config.timeframes),
            len(table),
            int(action.eq("fetch").sum()),
            int(action.eq("cached").sum()),
        )
        return {
            "summary": {
                "row_count": int(len(table)),
                "fetch_count": int(action.eq("fetch").sum()),
                "cached_count": int(action.eq("cached").sum()),
                "missing_rows": _numeric_sum(table, "missing_rows"),
                "expected_rows": _numeric_sum(table, "expected_rows"),
            },
            "record_count": int(len(table)),
            "returned_count": int(len(table)),
            "records": _records(table, limit=None),
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
    try:
        _raise_if_task_cancelled(task_id)
        _update_task(task_id, status="running", started_at=_now_text())
        _append_event(task_id, {"stage": "task_start", "message": "下载任务已进入后台执行。"})
        _wait_if_task_paused(task_id)
        service = DataManagementService(payload.data_root, adjust=payload.adjust)
        config = _download_config(payload)

        def on_progress(event: dict[str, object]) -> None:
            _raise_if_task_cancelled(task_id)
            _wait_if_task_paused(task_id)
            _append_event(task_id, event)
            _raise_if_task_cancelled(task_id)

        if should_use_parallels_runtime():
            _raise_if_task_cancelled(task_id)
            _append_event(task_id, {"stage": "parallels_task_start", "message": "按任务计划调度 Parallels/Windows。"})
        else:
            _raise_if_task_cancelled(task_id)
            _append_event(
                task_id,
                {
                    "stage": "local_task_start",
                    "message": "Windows 本地模式已启动，将先审计缓存，再按需连接通达信。",
                },
            )
        _wait_if_task_paused(task_id)
        result = download_with_runtime(
            service,
            config,
            mode=mode,
            progress_callback=on_progress,
            cancel_check=lambda: _raise_if_task_cancelled(task_id),
        )
        _raise_if_task_cancelled(task_id)
        if should_use_parallels_runtime():
            rows_written = int(float(result.summary.get("rows_written") or 0))
            fetched_count = int(float(result.summary.get("fetched_count") or 0))
            unresolved_count = int(float(result.summary.get("unresolved_count") or 0))
            message = (
                f"Parallels/Windows 下载完成：{fetched_count} 项 fetch，写入 {rows_written} 行。"
                if fetched_count or rows_written
                else f"本轮无可执行下载窗口：{unresolved_count} 项为已知供应商缺口，未建立 TDX 取数连接。"
                if unresolved_count
                else "本地缓存已覆盖当前任务，未建立 TDX 取数连接。"
            )
            _append_event(task_id, {"stage": "task_summary", "message": message})
        _wait_if_task_paused(task_id)
        table_payload = {"summary": _json_dict(result.summary), "records": _records(result.table)}
        _append_event(task_id, {"stage": "task_done", "message": "下载任务完成。"})
        _update_task(task_id, status="succeeded", finished_at=_now_text(), result=table_payload)
        rows_written = int(float(result.summary.get("rows_written") or 0))
        _append_event(
            task_id,
            {
                "stage": "catalog_refresh_skipped",
                "message": (
                    "本次未写入新数据，无需刷新缓存资产索引。"
                    if rows_written <= 0
                    else "写入流程已同步更新相关缓存索引，跳过全量扫描。"
                ),
            },
        )
    except TaskCancelled as exc:
        message = str(exc) or "任务已终止。"
        _append_event(task_id, {"stage": "task_cancelled", "message": message})
        _update_task(task_id, status="cancelled", finished_at=_now_text(), error=message)
    except Exception as exc:
        _append_event(task_id, {"stage": "task_failed", "message": str(exc)})
        _update_task(task_id, status="failed", finished_at=_now_text(), error=str(exc))
