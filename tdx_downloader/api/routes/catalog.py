from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
import pandas as pd

from tdx_downloader.data.catalog import (
    CATALOG_COLUMNS,
    CatalogDatabaseBusy,
    catalog_path_for,
    maintain_catalog,
    query_catalog,
    query_coverage_runs,
    refresh_coverage_runs,
)
from tdx_downloader.data.manager import (
    DataManagementService,
    annotate_catalog_coverage,
    cache_by_asset_type,
    cache_by_dataset,
    cache_by_status,
    cache_by_timeframe,
    cache_readiness,
    cache_summary,
)
from tdx_downloader.data.parallels_runtime import symbol_metadata_with_runtime
from tdx_downloader.data.schema import SUPPORTED_TIMEFRAMES
from tdx_downloader.data.storage import compact_delta_sidecars, delta_sidecar_summary

from ..constants import DEFAULT_ADJUST, DEFAULT_DATA_ROOT, DEFAULT_TDX_PATH
from ..serialization import _json_dict, _records
from ..task_store import _append_event, _create_task, _executor, _now_text, _task_payload, _update_task

COVERAGE_REFRESH_BATCH_SIZE = 500


def register_catalog_routes(app: FastAPI) -> None:
    @app.get("/api/overview")
    def overview(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        tdx_path: str = DEFAULT_TDX_PATH,
        refresh: bool = False,
        include_records: bool = True,
        timeframes: list[str] | None = Query(default=None),
        start: str = "",
        end: str = "",
    ) -> dict[str, Any]:
        service = DataManagementService(data_root, adjust=adjust)
        if refresh:
            snapshot = service.cache_snapshot(
                timeframes=tuple(timeframes or SUPPORTED_TIMEFRAMES),
                symbols=None,
                tdx_path=tdx_path,
                symbol_metadata=symbol_metadata_with_runtime(data_root, tdx_path),
                rebuild_catalog=True,
                refresh_coverage=False,
            )
            catalog = (
                annotate_catalog_coverage(snapshot.catalog, data_root=data_root, adjust=adjust, start=start, end=end)
                if include_records
                else snapshot.catalog
            )
            return _catalog_payload(catalog, data_root=data_root, adjust=adjust, rebuilt=True, include_records=include_records)
        try:
            catalog = query_catalog(data_root=data_root)
            if include_records:
                catalog = annotate_catalog_coverage(catalog, data_root=data_root, adjust=adjust, start=start, end=end)
            return _catalog_payload(catalog, data_root=data_root, adjust=adjust, rebuilt=False, include_records=include_records)
        except CatalogDatabaseBusy:
            catalog = pd.DataFrame(columns=pd.Index(CATALOG_COLUMNS))
            payload = _catalog_payload(catalog, data_root=data_root, adjust=adjust, rebuilt=False, include_records=include_records)
            payload["catalog_locked"] = True
            payload["message"] = "本地缓存索引正在写入，稍后会自动恢复。"
            return payload

    @app.post("/api/coverage/refresh")
    def refresh_coverage(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        timeframes: list[str] | None = Query(default=None),
        symbols: list[str] | None = Query(default=None),
        limit: int | None = Query(default=None, ge=1),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        task = _create_task("coverage_refresh")
        _executor.submit(
            _run_coverage_refresh_task,
            task.id,
            data_root,
            adjust,
            tuple(timeframes or SUPPORTED_TIMEFRAMES),
            tuple(symbols or ()),
            limit,
            offset,
        )
        return _task_payload(task)

    @app.post("/api/delta/compact")
    def compact_delta(
        data_root: str = DEFAULT_DATA_ROOT,
        adjust: str = DEFAULT_ADJUST,
        timeframes: list[str] | None = Query(default=None),
        symbols: list[str] | None = Query(default=None),
    ) -> dict[str, Any]:
        task = _create_task("delta_compact")
        _executor.submit(
            _run_delta_compact_task,
            task.id,
            data_root,
            adjust,
            tuple(timeframes or SUPPORTED_TIMEFRAMES),
            tuple(symbols or ()),
        )
        return _task_payload(task)

    @app.post("/api/catalog/maintain")
    def maintain_catalog_route(
        data_root: str = DEFAULT_DATA_ROOT,
        vacuum: bool = True,
    ) -> dict[str, Any]:
        task = _create_task("catalog_maintain")
        _executor.submit(_run_catalog_maintain_task, task.id, data_root, vacuum)
        return _task_payload(task)


def _catalog_payload(
    catalog: pd.DataFrame,
    *,
    data_root: str,
    rebuilt: bool,
    adjust: str = DEFAULT_ADJUST,
    include_records: bool = True,
) -> dict[str, Any]:
    path = catalog_path_for(data_root)
    return {
        "summary": _json_dict(cache_summary(catalog)),
        "by_timeframe": _records(cache_by_timeframe(catalog)),
        "by_asset_type": _records(cache_by_asset_type(catalog)),
        "by_status": _records(cache_by_status(catalog)),
        "by_dataset": _records(cache_by_dataset(catalog)),
        "readiness": _records(cache_readiness(catalog)),
        "records": _records(catalog, limit=None) if include_records else [],
        "record_count": int(len(catalog)),
        "catalog_path": str(path),
        "catalog_exists": path.exists(),
        "rebuilt": rebuilt,
        "record_limit": None if include_records else 0,
        "delta": _json_dict(delta_sidecar_summary(data_root=data_root, adjust=adjust)),
    }


def _run_coverage_refresh_task(
    task_id: str,
    data_root: str,
    adjust: str,
    timeframes: tuple[str, ...],
    symbols: tuple[str, ...],
    limit: int | None = None,
    offset: int = 0,
) -> None:
    started_at = pd.Timestamp.utcnow()
    _update_task(task_id, status="running", started_at=_now_text())
    _append_event(
        task_id,
        {
            "stage": "coverage_refresh_start",
            "message": "开始刷新本地 K 线覆盖索引。",
            "timeframe_count": len(timeframes),
            "symbol_count": len(symbols),
            "limit": int(limit) if limit is not None else None,
            "offset": int(offset),
        },
    )
    try:
        inventory = query_catalog(
            data_root=data_root,
            symbols=symbols or None,
            adjust=adjust,
            timeframes=timeframes,
            data_kinds=("price",),
            indicators=("ohlcv",),
            statuses=("cached",),
        )
        total_catalog_rows = int(len(inventory))
        if offset or limit is not None:
            inventory = inventory.iloc[int(offset) :]
            if limit is not None:
                inventory = inventory.iloc[: int(limit)]
        refreshed_rows = 0
        batches = list(_coverage_refresh_batches(inventory, timeframes=timeframes))
        by_timeframe = (
            inventory.groupby("timeframe", sort=False)["stock_code"].nunique().astype(int).to_dict()
            if not inventory.empty and {"timeframe", "stock_code"}.issubset(inventory.columns)
            else {}
        )
        _append_event(
            task_id,
            {
                "stage": "coverage_refresh_planned",
                "message": (
                    f"覆盖索引计划刷新 {len(inventory)} / {total_catalog_rows} 条 catalog 记录，"
                    f"offset={int(offset)}，limit={limit if limit is not None else 'all'}，拆成 {len(batches)} 批。"
                ),
                "catalog_rows": int(len(inventory)),
                "total_catalog_rows": total_catalog_rows,
                "offset": int(offset),
                "limit": int(limit) if limit is not None else None,
                "remaining_rows": max(total_catalog_rows - int(offset) - int(len(inventory)), 0),
                "batch_count": int(len(batches)),
                "by_timeframe": {str(key): int(value) for key, value in by_timeframe.items()},
            },
        )
        for index, batch in enumerate(batches, start=1):
            batch_started_at = pd.Timestamp.utcnow()
            batch_symbols = tuple(batch["stock_code"].dropna().astype(str).drop_duplicates().tolist())
            batch_timeframes = tuple(batch["timeframe"].dropna().astype(str).drop_duplicates().tolist())
            if not batch_symbols or not batch_timeframes:
                continue
            refreshed = refresh_coverage_runs(
                data_root=data_root,
                adjust=adjust,
                timeframes=batch_timeframes,
                symbols=batch_symbols,
                inventory=batch,
            )
            refreshed_rows += int(len(refreshed))
            batch_elapsed_ms = int((pd.Timestamp.utcnow() - batch_started_at).total_seconds() * 1000)
            _append_event(
                task_id,
                {
                    "stage": "coverage_refresh_progress",
                    "message": (
                        f"覆盖索引刷新 {index}/{len(batches)}：{','.join(batch_timeframes)}，"
                        f"{len(batch_symbols)} 个标的，用时 {batch_elapsed_ms}ms。"
                    ),
                    "batch_index": index,
                    "batch_count": len(batches),
                    "symbol_count": len(batch_symbols),
                    "timeframes": list(batch_timeframes),
                    "refreshed_rows": int(len(refreshed)),
                    "batch_elapsed_ms": batch_elapsed_ms,
                    "catalog_rows_done": min(int(offset) + index * COVERAGE_REFRESH_BATCH_SIZE, int(offset) + int(len(inventory))),
                    "catalog_rows_total": total_catalog_rows,
                },
            )
        total = query_coverage_runs(data_root=data_root, adjust=adjust, timeframes=timeframes, symbols=symbols or None)
        elapsed_ms = int((pd.Timestamp.utcnow() - started_at).total_seconds() * 1000)
        result = {
            "summary": {
                "refreshed_rows": refreshed_rows,
                "coverage_rows": int(len(total)),
                "elapsed_ms": elapsed_ms,
                "catalog_rows": int(len(inventory)),
                "total_catalog_rows": total_catalog_rows,
                "remaining_rows": max(total_catalog_rows - int(offset) - int(len(inventory)), 0),
                "offset": int(offset),
                "limit": int(limit) if limit is not None else None,
            },
            "records": [],
        }
        _append_event(
            task_id,
            {
                "stage": "coverage_refresh_done",
                "message": f"覆盖索引刷新完成：当前 {len(total)} 段。",
                "row_count": int(len(total)),
                "refreshed_rows": refreshed_rows,
                "elapsed_ms": elapsed_ms,
            },
        )
        _update_task(task_id, status="succeeded", finished_at=_now_text(), result=result)
    except Exception as exc:  # noqa: BLE001
        _append_event(task_id, {"stage": "task_failed", "message": str(exc)})
        _update_task(task_id, status="failed", finished_at=_now_text(), error=str(exc))


def _run_delta_compact_task(
    task_id: str,
    data_root: str,
    adjust: str,
    timeframes: tuple[str, ...],
    symbols: tuple[str, ...],
) -> None:
    started_at = pd.Timestamp.utcnow()
    _update_task(task_id, status="running", started_at=_now_text())
    _append_event(
        task_id,
        {
            "stage": "delta_compact_start",
            "message": "开始压实 delta 缓存。",
            "timeframe_count": len(timeframes),
            "symbol_count": len(symbols),
        },
    )
    try:
        frames: list[pd.DataFrame] = []

        def emit(event: dict[str, object]) -> None:
            _append_event(task_id, event)

        for timeframe in timeframes:
            result = compact_delta_sidecars(
                data_root=data_root,
                timeframe=timeframe,
                adjust=adjust,
                symbols=symbols or None,
                progress_callback=emit,
                refresh_coverage=True,
            )
            if not result.empty:
                result = result.copy()
                result["timeframe"] = timeframe
                result["adjust"] = adjust
                frames.append(result)
        table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        elapsed_ms = int((pd.Timestamp.utcnow() - started_at).total_seconds() * 1000)
        success_count = int(table["status"].astype(str).eq("success").sum()) if not table.empty and "status" in table.columns else 0
        result = {
            "summary": {
                "compacted_symbols": success_count,
                "delta_parts": int(pd.to_numeric(table.get("delta_parts", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not table.empty else 0,
                "delta_rows": int(pd.to_numeric(table.get("delta_rows", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not table.empty else 0,
                "elapsed_ms": elapsed_ms,
            },
            "records": _records(table, limit=None),
        }
        _append_event(
            task_id,
            {
                "stage": "delta_compact_done",
                "message": f"delta 缓存压实完成：{success_count} 个标的。",
                "compacted_symbols": success_count,
                "elapsed_ms": elapsed_ms,
            },
        )
        _update_task(task_id, status="succeeded", finished_at=_now_text(), result=result)
    except Exception as exc:  # noqa: BLE001
        _append_event(task_id, {"stage": "task_failed", "message": str(exc)})
        _update_task(task_id, status="failed", finished_at=_now_text(), error=str(exc))


def _run_catalog_maintain_task(task_id: str, data_root: str, vacuum: bool) -> None:
    started_at = pd.Timestamp.utcnow()
    _update_task(task_id, status="running", started_at=_now_text())
    _append_event(
        task_id,
        {
            "stage": "catalog_maintain_start",
            "message": "开始维护 SQLite 缓存索引。",
            "vacuum": bool(vacuum),
        },
    )
    try:
        result = maintain_catalog(data_root=data_root, vacuum=vacuum)
        elapsed_ms = int((pd.Timestamp.utcnow() - started_at).total_seconds() * 1000)
        result["elapsed_ms"] = elapsed_ms
        _append_event(
            task_id,
            {
                "stage": "catalog_maintain_done",
                "message": "SQLite 缓存索引维护完成。",
                "elapsed_ms": elapsed_ms,
                "before": result.get("before"),
                "after": result.get("after"),
            },
        )
        _update_task(task_id, status="succeeded", finished_at=_now_text(), result=result)
    except Exception as exc:  # noqa: BLE001
        _append_event(task_id, {"stage": "task_failed", "message": str(exc)})
        _update_task(task_id, status="failed", finished_at=_now_text(), error=str(exc))


def _coverage_refresh_batches(inventory: pd.DataFrame, *, timeframes: tuple[str, ...]) -> list[pd.DataFrame]:
    if inventory.empty:
        return []
    batches: list[pd.DataFrame] = []
    for timeframe in timeframes:
        frame = inventory.loc[inventory["timeframe"].astype(str).eq(str(timeframe))].copy()
        if frame.empty:
            continue
        symbols = frame["stock_code"].dropna().astype(str).drop_duplicates().tolist()
        for offset in range(0, len(symbols), COVERAGE_REFRESH_BATCH_SIZE):
            batch_symbols = set(symbols[offset : offset + COVERAGE_REFRESH_BATCH_SIZE])
            batches.append(frame.loc[frame["stock_code"].astype(str).isin(batch_symbols)].copy())
    return batches
