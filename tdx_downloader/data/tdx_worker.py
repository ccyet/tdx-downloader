from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Any
from uuid import uuid4

import pandas as pd
import pyarrow.parquet as pq

from tdx_downloader.data.catalog import (
    coverage_run_records_from_identity,
    query_catalog,
    upsert_catalog_records,
    upsert_market_data_parts,
    upsert_partial_coverage_runs_from_bars,
    upsert_partial_coverage_runs_from_records,
)
from tdx_downloader.data.manager import DataDownloadConfig, DataManagementService, download_summary
from tdx_downloader.data.repository import MarketDataRepository, clear_fast_plan_cache
from tdx_downloader.data.schema import CANONICAL_COLUMNS, normalize_bars, normalize_symbol, resolve_timeframe_root, unique_symbols
from tdx_downloader.data.storage import append_shared_delta_bars
from tdx_downloader.data.tdx import diagnose_tdx_source

DEFAULT_WORKER_HOST = "0.0.0.0"
DEFAULT_WORKER_PORT = 8765
DEFAULT_WORKER_SCRATCH = r"C:\tdx_jobs" if sys.platform == "win32" else str(Path.home() / "tdx_jobs")
WORKER_PROTOCOL_VERSION = 1
WORKER_EVENT_LIMIT = 500
PART_FILE_NAME = "part-000.parquet"
MANIFEST_FILE_NAME = "manifest.json"


class _WorkerCancelled(RuntimeError):
    pass


@dataclass
class WorkerJob:
    id: str
    payload: dict[str, Any]
    status: str = "queued"
    created_at: str = field(default_factory=lambda: _now_text())
    started_at: str | None = None
    finished_at: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    event_next_index: int = 0
    summary: dict[str, Any] | None = None
    records: list[dict[str, Any]] | None = None
    manifest_path: str = ""
    error: str = ""
    cancel_requested: bool = False
    future: Future[Any] | None = None


class TdxWorkerStore:
    def __init__(self, *, scratch_root: str | Path | None = None) -> None:
        self.scratch_root = Path(scratch_root or os.getenv("TDX_WORKER_SCRATCH", DEFAULT_WORKER_SCRATCH))
        self.scratch_root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, WorkerJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tdx-worker")

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "protocol_version": WORKER_PROTOCOL_VERSION,
            "python": sys.executable,
            "platform": sys.platform,
            "cwd": str(Path.cwd()),
            "scratch_root": str(self.scratch_root),
            "tdx_worker_url": os.getenv("TDX_WORKER_URL", ""),
            "tdx_tqcenter_path": os.getenv("TDX_TQCENTER_PATH", ""),
            "time": _now_text(),
            "dependencies": _dependency_status(),
        }

    def create_job(self, payload: dict[str, Any]) -> WorkerJob:
        job = WorkerJob(id=uuid4().hex, payload=dict(payload))
        with self._lock:
            self._jobs[job.id] = job
        self._append_event(job.id, {"stage": "worker_job_queued", "message": "Windows Worker 已接收任务。"})
        job.future = self._executor.submit(self._run_job, job.id)
        return job

    def get_job(self, job_id: str) -> WorkerJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> WorkerJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.cancel_requested = True
            if job.status in {"queued"} and job.future is not None:
                job.future.cancel()
                job.status = "cancelled"
                job.finished_at = _now_text()
        self._append_event(job_id, {"stage": "worker_job_cancel_requested", "message": "已请求终止 Worker 任务。"})
        return self.get_job(job_id)

    def payload(
        self,
        job: WorkerJob,
        *,
        after_event_index: int | None = None,
        event_limit: int | None = None,
        include_records: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            current = self._jobs.get(job.id, job)
            events = list(current.events)
            event_next_index = int(current.event_next_index)
            records = (current.records or []) if include_records else []
            payload = {
                "job_id": current.id,
                "status": current.status,
                "created_at": current.created_at,
                "started_at": current.started_at,
                "finished_at": current.finished_at,
                "summary": current.summary or {},
                "records": records,
                "manifest_path": current.manifest_path,
                "error": current.error,
            }
        event_start_index = _event_index(events[0]) if events else event_next_index
        filtered_events = events
        if after_event_index is not None:
            filtered_events = [event for event in events if _event_index(event) > after_event_index]
        if event_limit is not None and event_limit >= 0:
            filtered_events = filtered_events[: min(int(event_limit), WORKER_EVENT_LIMIT)]
        return {
            **payload,
            "events": filtered_events,
            "event_start_index": event_start_index,
            "event_next_index": event_next_index,
            "event_count": event_next_index,
            "events_returned": len(filtered_events),
            "events_truncated": bool(after_event_index is not None and after_event_index + 1 < event_start_index),
        }

    def manifest_file(self, job_id: str) -> Path:
        return self.scratch_root / job_id / MANIFEST_FILE_NAME

    def part_file(self, job_id: str, name: str) -> Path:
        path = (self.scratch_root / job_id / name).resolve()
        root = (self.scratch_root / job_id).resolve()
        if root not in path.parents and path != root:
            raise ValueError(f"非法 part 路径：{name}")
        return path

    def _run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None:
            return
        self._update_job(job_id, status="running", started_at=_now_text())
        self._append_event(job_id, {"stage": "worker_job_start", "message": "Windows Worker 开始执行任务。"})
        try:
            self._raise_if_cancelled(job_id)
            payload = job.payload
            mode = str(payload.get("mode") or "smart")
            service = DataManagementService(str(payload.get("data_root") or ""), adjust=str(payload.get("adjust") or "qfq"))
            config = DataDownloadConfig(
                symbols=tuple(str(item) for item in payload.get("symbols", []) or []),
                timeframes=tuple(str(item) for item in payload.get("timeframes", []) or []),
                start=str(payload.get("start") or ""),
                end=str(payload.get("end") or ""),
                tqcenter_path=str(payload.get("tdx_path") or ""),
                batch_size=max(int(payload.get("batch_size") or 100), 1),
                min_coverage_ratio=payload.get("min_coverage_ratio"),
                strict_after_update=bool(payload.get("strict_after_update", True)),
            )
            if mode == "force":
                table, parts = _force_fetch_to_manifest(
                    job_id=job_id,
                    store=self,
                    service=service,
                    config=config,
                    progress_callback=lambda event: self._append_event(job_id, event),
                    cancel_check=lambda: self._raise_if_cancelled(job_id),
                )
            elif mode == "fetch-windows":
                table, parts = _fetch_windows_to_manifest(
                    job_id=job_id,
                    store=self,
                    service=service,
                    payload=payload,
                    config=config,
                    progress_callback=lambda event: self._append_event(job_id, event),
                    cancel_check=lambda: self._raise_if_cancelled(job_id),
                )
            else:
                raise ValueError(f"未知 Worker 下载模式：{mode}")
            summary = download_summary(table)
            manifest_path = self._write_summary_manifest(job_id=job_id, table=table, summary=summary, mode=mode, parts=parts)
            self._update_job(
                job_id,
                status="succeeded",
                finished_at=_now_text(),
                summary=summary,
                records=_records(table),
                manifest_path=str(manifest_path),
            )
            self._append_event(job_id, {"stage": "worker_job_done", "message": "Windows Worker 任务完成。"})
        except _WorkerCancelled as exc:
            self._update_job(job_id, status="cancelled", finished_at=_now_text(), error=str(exc))
            self._append_event(job_id, {"stage": "worker_job_cancelled", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._update_job(job_id, status="failed", finished_at=_now_text(), error=str(exc))
            self._append_event(job_id, {"stage": "worker_job_failed", "message": str(exc)})

    def _write_summary_manifest(
        self,
        *,
        job_id: str,
        table: pd.DataFrame,
        summary: dict[str, Any],
        mode: str,
        parts: list[dict[str, Any]],
    ) -> Path:
        job_dir = self.scratch_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = job_dir / MANIFEST_FILE_NAME
        manifest = {
            "protocol_version": WORKER_PROTOCOL_VERSION,
            "job_id": job_id,
            "mode": mode,
            "summary": summary,
            "records": _records(table),
            "parts": parts,
            "created_at": _now_text(),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, default=str), encoding="utf-8")
        return manifest_path

    def _append_event(self, job_id: str, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("time", _now_text())
        with self._lock:
            job = self._jobs[job_id]
            payload.setdefault("event_index", job.event_next_index)
            job.event_next_index += 1
            job.events.append(payload)
            if len(job.events) > WORKER_EVENT_LIMIT:
                del job.events[: len(job.events) - WORKER_EVENT_LIMIT]

    def _update_job(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)

    def _raise_if_cancelled(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is not None and job.cancel_requested:
            raise _WorkerCancelled("Worker 任务已终止。")


def create_worker_app(*, scratch_root: str | Path | None = None):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse

    app = FastAPI(title="TDX Worker")
    store = TdxWorkerStore(scratch_root=scratch_root)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return store.health()

    @app.post("/jobs")
    def create_job(payload: dict[str, Any]) -> dict[str, Any]:
        job = store.create_job(payload)
        return store.payload(job)

    @app.get("/jobs/{job_id}")
    def get_job(
        job_id: str,
        after_event_index: int | None = None,
        event_limit: int | None = None,
        include_records: bool = True,
    ) -> dict[str, Any]:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return store.payload(
            job,
            after_event_index=after_event_index,
            event_limit=event_limit,
            include_records=include_records,
        )

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        job = store.cancel_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return store.payload(job)

    @app.get("/jobs/{job_id}/manifest")
    def get_manifest(job_id: str):
        path = store.manifest_file(job_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="manifest not found")
        return FileResponse(path)

    @app.get("/jobs/{job_id}/parts/{name}")
    def get_part(job_id: str, name: str):
        try:
            path = store.part_file(job_id, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not path.exists():
            raise HTTPException(status_code=404, detail="part not found")
        return FileResponse(path)

    return app


def run_worker(*, host: str = DEFAULT_WORKER_HOST, port: int = DEFAULT_WORKER_PORT, scratch_root: str | Path | None = None) -> None:
    import uvicorn

    uvicorn.run(create_worker_app(scratch_root=scratch_root), host=host, port=port)


def diagnose_worker_environment(*, tqcenter_path: str, symbols: tuple[str, ...], timeframes: tuple[str, ...], start: str, end: str, adjust: str) -> dict[str, Any]:
    diagnostics = diagnose_tdx_source(
        symbols=symbols,
        timeframes=timeframes,
        start=start,
        end=end,
        adjust=adjust,
        tqcenter_path=tqcenter_path,
    )
    return {
        "python": sys.executable,
        "cwd": str(Path.cwd()),
        "scratch_root": os.getenv("TDX_WORKER_SCRATCH", DEFAULT_WORKER_SCRATCH),
        "tdx_path": tqcenter_path,
        "diagnostics": _records(diagnostics),
    }


def _force_fetch_to_manifest(
    *,
    job_id: str,
    store: TdxWorkerStore,
    service: DataManagementService,
    config: DataDownloadConfig,
    progress_callback,
    cancel_check=None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    from tdx_downloader.data.tdx import fetch_tdx_bars
    from tdx_downloader.data.repository import _tdx_fetch_window_for_timeframe
    from tdx_downloader.data.manager import _force_download_frame

    frames: list[pd.DataFrame] = []
    parts: list[dict[str, Any]] = []
    for step_index, timeframe in enumerate(config.timeframes, start=1):
        _raise_if_cancelled(cancel_check)
        fetch_start, fetch_end = _tdx_fetch_window_for_timeframe(timeframe, start=config.start, end=config.end)
        progress_callback(
            {
                "stage": "worker_force_fetch_start",
                "timeframe": timeframe,
                "step_index": step_index,
                "step_count": len(config.timeframes),
                "symbol_count": len(config.symbols),
            }
        )
        bars = fetch_tdx_bars(
            symbols=config.symbols,
            start=fetch_start,
            end=fetch_end,
            timeframe=timeframe,
            adjust=service.adjust,
            tqcenter_path=config.tqcenter_path,
            batch_size=config.batch_size,
            progress_callback=_window_progress_callback(
                progress_callback,
                timeframe=timeframe,
                step_index=step_index,
                step_count=len(config.timeframes),
                start=fetch_start,
                end=fetch_end,
            ),
        )
        _raise_if_cancelled(cancel_check)
        part = _write_part(
            store=store,
            job_id=job_id,
            timeframe=timeframe,
            adjust=service.adjust,
            bars=bars,
            name_prefix=f"{step_index:03d}",
        )
        if part.get("name"):
            parts.append(part)
        summary = _part_summary_rows(part)
        frames.append(_force_download_frame(summary, timeframe=timeframe, adjust=service.adjust))
        progress_callback(
            {
                "stage": "worker_force_fetch_done",
                "timeframe": timeframe,
                "rows": len(bars),
                "part": part["path"],
            }
        )
        _raise_if_cancelled(cancel_check)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), parts


def _fetch_windows_to_manifest(
    *,
    job_id: str,
    store: TdxWorkerStore,
    service: DataManagementService,
    payload: dict[str, Any],
    config: DataDownloadConfig,
    progress_callback,
    cancel_check=None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    from tdx_downloader.data.tdx import fetch_tdx_bars
    from tdx_downloader.data.manager import _force_download_frame

    frames: list[pd.DataFrame] = []
    parts: list[dict[str, Any]] = []
    groups_by_timeframe = payload.get("groups_by_timeframe") or {}
    if not isinstance(groups_by_timeframe, dict):
        raise ValueError("groups_by_timeframe 必须是对象。")
    step_count = sum(len(groups or []) for groups in groups_by_timeframe.values())
    step_index = 0
    for timeframe, groups in groups_by_timeframe.items():
        _raise_if_cancelled(cancel_check)
        if not isinstance(groups, list):
            continue
        for group in groups:
            _raise_if_cancelled(cancel_check)
            step_index += 1
            symbols = tuple(str(item) for item in (group.get("symbols") or []) if str(item).strip())
            start = str(group.get("start") or config.start)
            end = str(group.get("end") or config.end)
            progress_callback(
                {
                    "stage": "worker_fetch_window_start",
                    "timeframe": str(timeframe),
                    "step_index": step_index,
                    "step_count": step_count,
                    "symbol_count": len(symbols),
                    "start": start,
                    "end": end,
                }
            )
            bars = fetch_tdx_bars(
                symbols=symbols,
                start=start,
                end=end,
                timeframe=str(timeframe),
                adjust=service.adjust,
                tqcenter_path=config.tqcenter_path,
                batch_size=config.batch_size,
                progress_callback=_window_progress_callback(
                    progress_callback,
                    timeframe=str(timeframe),
                    step_index=step_index,
                    step_count=step_count,
                    start=start,
                    end=end,
                ),
            )
            _raise_if_cancelled(cancel_check)
            write_started_at = time.perf_counter()
            part = _write_part(
                store=store,
                job_id=job_id,
                timeframe=str(timeframe),
                adjust=service.adjust,
                bars=bars,
                name_prefix=f"{step_index:03d}",
            )
            write_ms = int((time.perf_counter() - write_started_at) * 1000)
            if part.get("name"):
                parts.append(part)
                part_summary = _part_summary_rows(part)
                if not part_summary.empty:
                    frames.append(_force_download_frame(part_summary, timeframe=str(timeframe), adjust=service.adjust))
            progress_callback(
                {
                    "stage": "worker_fetch_window_done",
                    "timeframe": str(timeframe),
                    "step_index": step_index,
                    "step_count": step_count,
                    "rows": len(bars),
                    "part": part.get("path", ""),
                    "write_ms": write_ms,
                }
            )
            _raise_if_cancelled(cancel_check)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), parts


def _write_part(
    *,
    store: TdxWorkerStore,
    job_id: str,
    timeframe: str,
    adjust: str,
    bars: pd.DataFrame,
    name_prefix: str,
) -> dict[str, Any]:
    normalized = normalize_bars(bars)
    if normalized.empty:
        return {"name": "", "path": "", "timeframe": timeframe, "adjust": adjust, "rows": 0, "sha256": ""}
    job_dir = store.scratch_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    name = f"{name_prefix}-{timeframe}-{adjust}-{PART_FILE_NAME}"
    path = job_dir / name
    normalized.loc[:, CANONICAL_COLUMNS].to_parquet(path, index=False)
    summary = _summary_rows_from_bars(normalized, path=path)
    coverage = coverage_run_records_from_identity(
        identity=normalized.loc[:, ["date", "stock_code"]],
        timeframe=timeframe,
        adjust=adjust,
        path=path,
    )
    return {
        "name": name,
        "path": str(path),
        "timeframe": timeframe,
        "adjust": adjust,
        "rows": int(len(normalized)),
        "sha256": _sha256_file(path),
        "summary_rows": _records(summary),
        "coverage_rows": _records(coverage),
    }


def _part_summary_rows(part: dict[str, Any]) -> pd.DataFrame:
    summary_rows = part.get("summary_rows")
    if isinstance(summary_rows, list):
        return pd.DataFrame(summary_rows, columns=["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"])
    path = Path(str(part["path"]))
    if not path.exists() or int(part.get("rows") or 0) <= 0:
        return pd.DataFrame(columns=["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"])
    frame = normalize_bars(pd.read_parquet(path))
    return _summary_rows_from_bars(frame, path=path)


def _summary_rows_from_bars(frame: pd.DataFrame, *, path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol, grouped in frame.groupby("stock_code", sort=True):
        rows.append(
            {
                "symbol": str(symbol),
                "status": "success",
                "rows": int(len(grouped)),
                "new_rows": int(len(grouped)),
                "path": str(path),
                "start": grouped["date"].min(),
                "end": grouped["date"].max(),
                "message": "TDX 行情已写入 Worker scratch。",
            }
        )
    return pd.DataFrame(rows)


def commit_worker_manifest(
    *,
    data_root: str | Path,
    manifest: dict[str, Any],
    part_loader,
    progress_callback=None,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for part in manifest.get("parts", []) or []:
        part_started_at = time.perf_counter()
        name = str(part.get("name") or "")
        timeframe = str(part.get("timeframe") or "")
        adjust = str(part.get("adjust") or "qfq")
        expected_sha256 = str(part.get("sha256") or "")
        local_path = Path(part_loader(name))
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "worker_commit_part_read_start",
                    "timeframe": timeframe,
                    "part": name,
                    "message": f"开始读取 Worker part：{name}。",
                }
            )
        if expected_sha256 and _sha256_file(local_path) != expected_sha256:
            raise RuntimeError(f"Worker part checksum 不匹配：{name}")
        direct = _commit_worker_part_direct(
            data_root=data_root,
            manifest=manifest,
            part=part,
            local_path=local_path,
            timeframe=timeframe,
            adjust=adjust,
            progress_callback=progress_callback,
        )
        if direct is not None:
            written = direct["written"]
            read_ms = int(direct["read_ms"])
            delta_ms = int(direct["delta_ms"])
            registry_ms = int(direct["registry_ms"])
            registered_parts = int(direct["registered_parts"])
            committed_symbols = int(direct["committed_symbols"])
            frame_for_coverage = direct.get("coverage")
            coverage_input_kind = "records"
            rows_read = int(direct["rows_read"])
        else:
            read_started_at = time.perf_counter()
            frame = normalize_bars(pd.read_parquet(local_path))
            read_ms = int((time.perf_counter() - read_started_at) * 1000)
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "worker_commit_start",
                        "timeframe": timeframe,
                        "rows": len(frame),
                        "part": name,
                        "read_ms": read_ms,
                        "message": f"Worker part 读取完成：{timeframe}，{len(frame)} 行。",
                    }
                )
            delta_started_at = time.perf_counter()
            written = append_shared_delta_bars(
                data_root=data_root,
                timeframe=timeframe,
                adjust=adjust,
                bars=frame,
                job_id=str(manifest.get("job_id") or ""),
                progress_callback=progress_callback,
                refresh_coverage=False,
                estimate_existing_overlap=False,
            )
            delta_ms = int((time.perf_counter() - delta_started_at) * 1000)
            registry_ms = 0
            registered_parts = int(written["delta_path"].dropna().astype(str).nunique()) if "delta_path" in written.columns else 0
            committed_symbols = int(written["symbol"].dropna().astype(str).nunique()) if "symbol" in written.columns else 0
            frame_for_coverage = frame
            coverage_input_kind = "bars"
            rows_read = int(len(frame))
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "worker_commit_delta_done",
                    "timeframe": timeframe,
                    "rows": int(written.get("rows", pd.Series(dtype=int)).sum() if not written.empty else 0),
                    "new_rows": int(written.get("new_rows", pd.Series(dtype=int)).sum() if not written.empty else 0),
                    "shared_part_count": registered_parts,
                    "symbol_count": committed_symbols,
                    "elapsed_ms": delta_ms,
                    "part": name,
                    "message": f"共享 delta 缓存写入完成：{timeframe}，{registered_parts} 个 part / {committed_symbols} 只标的，用时 {delta_ms}ms。",
                }
            )
        coverage_started_at = time.perf_counter()
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "worker_commit_coverage_start",
                    "timeframe": timeframe,
                    "rows": rows_read,
                    "part": name,
                    "message": f"开始更新覆盖索引：{timeframe}，{rows_read} 行。",
                }
            )
        if coverage_input_kind == "records":
            partial_coverage = upsert_partial_coverage_runs_from_records(
                data_root=data_root,
                records=frame_for_coverage if isinstance(frame_for_coverage, pd.DataFrame) else pd.DataFrame(),
                merge_existing=False,
            )
        else:
            partial_coverage = upsert_partial_coverage_runs_from_bars(
                data_root=data_root,
                timeframe=timeframe,
                adjust=adjust,
                bars=frame_for_coverage,
                merge_existing=False,
            )
        clear_fast_plan_cache()
        coverage_ms = int((time.perf_counter() - coverage_started_at) * 1000)
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "worker_commit_coverage",
                    "timeframe": timeframe,
                    "coverage_rows": int(len(partial_coverage)),
                    "elapsed_ms": coverage_ms,
                    "message": f"已按本次 Worker 数据增量更新覆盖索引：{len(partial_coverage)} 段。",
                }
            )
        if not written.empty:
            written = written.copy()
            written["timeframe"] = timeframe
            written["adjust"] = adjust
        rows.append(written)
        if progress_callback is not None:
            rows_total = int(written.get("rows", pd.Series(dtype=int)).sum() if not written.empty else 0)
            new_rows = int(written.get("new_rows", pd.Series(dtype=int)).sum() if not written.empty else 0)
            elapsed_ms = int((time.perf_counter() - part_started_at) * 1000)
            progress_callback(
                {
                    "stage": "worker_commit_done",
                    "timeframe": timeframe,
                    "rows": rows_total,
                    "new_rows": new_rows,
                    "part": name,
                    "elapsed_ms": elapsed_ms,
                    "read_ms": read_ms,
                    "delta_ms": delta_ms,
                    "registry_ms": registry_ms,
                    "coverage_ms": coverage_ms,
                    "shared_part_count": registered_parts,
                    "symbol_count": committed_symbols,
                    "message": f"Worker 缓存提交完成：{timeframe}，新增 {new_rows} 根 K 线，{registered_parts} 个共享 part / {committed_symbols} 只标的，用时 {elapsed_ms}ms。",
                }
            )
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _commit_worker_part_direct(
    *,
    data_root: str | Path,
    manifest: dict[str, Any],
    part: dict[str, Any],
    local_path: Path,
    timeframe: str,
    adjust: str,
    progress_callback=None,
) -> dict[str, object] | None:
    """Import a Worker part without rereading and rewriting OHLCV columns."""
    if not _worker_part_has_canonical_schema(local_path):
        return None
    identity_started_at = time.perf_counter()
    summary = _summary_rows_from_part(part=part, path=local_path)
    coverage = _coverage_rows_from_part(part)
    identity: pd.DataFrame | None = None
    if summary.empty or coverage.empty:
        try:
            identity = pd.read_parquet(local_path, columns=["date", "stock_code"])
        except Exception:  # noqa: BLE001
            return None
        identity["date"] = pd.to_datetime(identity["date"], errors="coerce")
        identity["stock_code"] = identity["stock_code"].map(normalize_symbol)
        identity = identity.dropna(subset=["date", "stock_code"]).loc[:, ["date", "stock_code"]]
        if identity.empty:
            return None
    if summary.empty and identity is not None:
        summary = _summary_rows_from_part_identity(part=part, identity=identity, path=local_path)
    if summary.empty:
        return None
    if coverage.empty and identity is not None:
        coverage = coverage_run_records_from_identity(
            identity=identity,
            timeframe=timeframe,
            adjust=adjust,
            path=local_path,
        )
    if coverage.empty:
        return None
    trade_months = _trade_months_from_coverage(coverage)
    if not trade_months:
        return None
    trade_month = str(trade_months[0]) if len(trade_months) == 1 else "multi"
    read_ms = int((time.perf_counter() - identity_started_at) * 1000)
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "worker_commit_start",
                "timeframe": timeframe,
                "rows": int(part.get("rows") or pd.to_numeric(coverage["row_count"], errors="coerce").sum()),
                "part": str(part.get("name") or ""),
                "read_ms": read_ms,
                "message": f"Worker part 元数据读取完成：{timeframe}，{int(part.get('rows') or pd.to_numeric(coverage['row_count'], errors='coerce').sum())} 行。",
            }
        )
    delta_started_at = time.perf_counter()
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    delta_root = root / "_delta_parts" / f"trade_month={trade_month}"
    delta_root.mkdir(parents=True, exist_ok=True)
    commit_id = _safe_worker_commit_id(str(manifest.get("job_id") or ""))
    target_path = delta_root / f"{commit_id}-{hashlib.sha256(str(local_path).encode('utf-8')).hexdigest()[:8]}.parquet"
    if local_path.resolve() != target_path.resolve():
        shutil.copy2(local_path, target_path)
    stat = target_path.stat()
    part_id = hashlib.sha256(f"{commit_id}|{target_path}|{timeframe}|{adjust}".encode("utf-8")).hexdigest()
    symbol_rows = _part_symbol_rows_from_summary(part_id=part_id, summary=summary)
    if not symbol_rows and identity is not None:
        symbol_rows = _part_symbol_rows_from_identity(part_id=part_id, identity=identity)
    min_at, max_at = _coverage_min_max(coverage)
    part_record = {
        "part_id": part_id,
        "job_id": commit_id,
        "timeframe": timeframe,
        "adjust": adjust,
        "trade_month": trade_month,
        "path": str(target_path),
        "rows": int(part.get("rows") or pd.to_numeric(coverage["row_count"], errors="coerce").sum()),
        "min_at": min_at.isoformat(),
        "max_at": max_at.isoformat(),
        "file_size_bytes": int(stat.st_size),
        "sha256": str(part.get("sha256") or ""),
        "commit_version": time.time_ns(),
        "state": "active",
        "created_at": _now_text(),
    }
    upsert_market_data_parts(
        data_root=data_root,
        parts=pd.DataFrame([part_record]),
        part_symbols=pd.DataFrame(symbol_rows),
    )
    rows = _direct_written_rows(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        summary=summary,
        target_path=target_path,
        identity=identity,
    )
    _emit_direct_commit_progress(progress_callback, timeframe=timeframe, rows=rows)
    _upsert_catalog_from_direct_rows(data_root=data_root, timeframe=timeframe, adjust=adjust, rows=rows)
    return {
        "written": rows,
        "identity": identity,
        "read_ms": read_ms,
        "delta_ms": int((time.perf_counter() - delta_started_at) * 1000),
        "registry_ms": 0,
        "registered_parts": 1,
        "committed_symbols": int(len(symbol_rows)),
        "rows_read": int(part.get("rows") or pd.to_numeric(coverage["row_count"], errors="coerce").sum()),
        "coverage": _coverage_rows_for_catalog(
            coverage,
            data_root=data_root,
            timeframe=timeframe,
            adjust=adjust,
        ),
    }


def _worker_part_has_canonical_schema(path: Path) -> bool:
    try:
        schema_names = set(pq.ParquetFile(path).schema.names)
    except Exception:  # noqa: BLE001
        return False
    return set(CANONICAL_COLUMNS).issubset(schema_names)


def _emit_direct_commit_progress(progress_callback, *, timeframe: str, rows: pd.DataFrame) -> None:
    if progress_callback is None or rows.empty:
        return
    total = len(rows)
    for index, row in enumerate(rows.itertuples(index=False), start=1):
        symbol = str(getattr(row, "symbol", "") or "")
        if index == 1 or index == total or index % 100 == 0:
            progress_callback(
                {
                    "stage": "worker_commit_progress",
                    "timeframe": timeframe,
                    "symbol": symbol,
                    "symbol_index": index,
                    "symbol_count": total,
                    "action": "direct_shared_delta",
                    "message": f"提交本地缓存 {timeframe}：{index}/{total}，{symbol}，direct_shared_delta。",
                }
            )


def _direct_written_rows(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    summary: pd.DataFrame,
    target_path: Path,
    identity: pd.DataFrame | None,
) -> pd.DataFrame:
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    symbols = tuple(
        normalize_symbol(value)
        for value in summary["symbol"].dropna().astype(str).tolist()
        if normalize_symbol(value)
    )
    existing_by_symbol = _catalog_summary_by_symbol(
        data_root=data_root,
        timeframe=timeframe,
        adjust=adjust,
        symbols=symbols,
    )
    rows: list[dict[str, object]] = []
    file_size_bytes = int(target_path.stat().st_size)
    modified_at = pd.Timestamp(target_path.stat().st_mtime, unit="s")
    for item in summary.itertuples(index=False):
        symbol = normalize_symbol(getattr(item, "symbol", ""))
        if not symbol:
            continue
        symbol_identity = (
            identity.loc[identity["stock_code"].eq(symbol)]
            if identity is not None and not identity.empty
            else pd.DataFrame(columns=["date", "stock_code"])
        )
        start = pd.Timestamp(symbol_identity["date"].min()) if not symbol_identity.empty else pd.Timestamp(getattr(item, "start", pd.NaT))
        end = pd.Timestamp(symbol_identity["date"].max()) if not symbol_identity.empty else pd.Timestamp(getattr(item, "end", pd.NaT))
        incoming_rows = int(getattr(item, "new_rows", 0) or len(symbol_identity) or getattr(item, "rows", 0) or 0)
        existing = existing_by_symbol.get(symbol)
        if existing:
            start_values = [value for value in (existing.get("start"), start) if not pd.isna(value)]
            end_values = [value for value in (existing.get("end"), end) if not pd.isna(value)]
            total_rows = int(existing.get("rows", 0) or 0) + incoming_rows
            catalog_start = min(start_values) if start_values else start
            catalog_end = max(end_values) if end_values else end
        else:
            total_rows = int(getattr(item, "rows", 0) or len(symbol_identity))
            catalog_start = start
            catalog_end = end
        rows.append(
            {
                "symbol": symbol,
                "status": str(getattr(item, "status", "success") or "success"),
                "rows": total_rows,
                "new_rows": incoming_rows,
                "path": str(root / f"{symbol}.parquet"),
                "delta_path": str(target_path),
                "delta_part_count": 1,
                "file_size_bytes": file_size_bytes,
                "modified_at": modified_at,
                "start": catalog_start,
                "end": catalog_end,
                "delta_start": start,
                "delta_end": end,
                "message": "TDX 行情已直接挂载 Worker shared delta part。",
            }
        )
    return pd.DataFrame(rows)


def _summary_rows_from_part_identity(*, part: dict[str, Any], identity: pd.DataFrame, path: Path) -> pd.DataFrame:
    summary = _summary_rows_from_part(part=part, path=path)
    if not summary.empty:
        return summary
    rows: list[dict[str, object]] = []
    for symbol, group in identity.groupby("stock_code", sort=True):
        rows.append(
            {
                "symbol": str(symbol),
                "status": "success",
                "rows": int(len(group.drop_duplicates(subset=["date"]))),
                "new_rows": int(len(group.drop_duplicates(subset=["date"]))),
                "path": str(path),
                "start": group["date"].min(),
                "end": group["date"].max(),
                "message": "TDX 行情已写入 Worker scratch。",
            }
        )
    return pd.DataFrame(rows)


def _summary_rows_from_part(*, part: dict[str, Any], path: Path) -> pd.DataFrame:
    summary_rows = part.get("summary_rows")
    if not isinstance(summary_rows, list) or not summary_rows:
        return pd.DataFrame(columns=["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"])
    frame = pd.DataFrame(summary_rows)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"])
    for column in ("symbol", "status", "rows", "new_rows", "path", "start", "end", "message"):
        if column not in frame.columns:
            frame[column] = ""
    frame["symbol"] = frame["symbol"].map(normalize_symbol).replace("", pd.NA)
    frame["rows"] = pd.to_numeric(frame["rows"], errors="coerce").fillna(0).astype(int)
    frame["new_rows"] = pd.to_numeric(frame["new_rows"], errors="coerce").fillna(frame["rows"]).astype(int)
    frame["start"] = pd.to_datetime(frame["start"], errors="coerce")
    frame["end"] = pd.to_datetime(frame["end"], errors="coerce")
    frame["path"] = frame["path"].fillna("").astype(str).replace("", str(path))
    frame["status"] = frame["status"].fillna("success").astype(str).replace("", "success")
    frame["message"] = frame["message"].fillna("").astype(str)
    frame = frame.dropna(subset=["symbol", "start", "end"])
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"])
    return frame.loc[:, ["symbol", "status", "rows", "new_rows", "path", "start", "end", "message"]].reset_index(drop=True)


def _coverage_rows_from_part(part: dict[str, Any]) -> pd.DataFrame:
    coverage_rows = part.get("coverage_rows")
    if not isinstance(coverage_rows, list) or not coverage_rows:
        return pd.DataFrame(columns=["stock_code", "timeframe", "adjust", "start_at", "end_at", "row_count", "file_size_bytes", "mtime_ns", "path", "updated_at"])
    frame = pd.DataFrame(coverage_rows)
    columns = ["stock_code", "timeframe", "adjust", "start_at", "end_at", "row_count", "file_size_bytes", "mtime_ns", "path", "updated_at"]
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    frame["stock_code"] = frame["stock_code"].map(normalize_symbol).replace("", pd.NA)
    frame["start_at"] = pd.to_datetime(frame["start_at"], errors="coerce")
    frame["end_at"] = pd.to_datetime(frame["end_at"], errors="coerce")
    frame["row_count"] = pd.to_numeric(frame["row_count"], errors="coerce").fillna(0).astype(int)
    frame = frame.dropna(subset=["stock_code", "start_at", "end_at"])
    frame = frame.loc[frame["row_count"].gt(0)].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    return frame.loc[:, columns].reset_index(drop=True)


def _trade_months_from_coverage(coverage: pd.DataFrame) -> list[str]:
    if coverage.empty:
        return []
    start_values = pd.to_datetime(coverage["start_at"], errors="coerce").dropna()
    end_values = pd.to_datetime(coverage["end_at"], errors="coerce").dropna()
    months = set(start_values.dt.strftime("%Y-%m").tolist())
    months.update(end_values.dt.strftime("%Y-%m").tolist())
    return sorted(month for month in months if str(month))


def _coverage_min_max(coverage: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_values = pd.to_datetime(coverage["start_at"], errors="coerce").dropna()
    end_values = pd.to_datetime(coverage["end_at"], errors="coerce").dropna()
    if start_values.empty or end_values.empty:
        return pd.NaT, pd.NaT
    return pd.Timestamp(start_values.min()), pd.Timestamp(end_values.max())


def _coverage_rows_for_catalog(
    coverage: pd.DataFrame,
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
) -> pd.DataFrame:
    if coverage.empty:
        return coverage
    root = resolve_timeframe_root(data_root, timeframe) / adjust
    result = coverage.copy()
    result["path"] = result["stock_code"].map(lambda symbol: str(root / f"{normalize_symbol(symbol)}.parquet"))
    result["file_size_bytes"] = 0
    result["mtime_ns"] = 0
    result["updated_at"] = _now_text()
    return result


def _part_symbol_rows_from_summary(*, part_id: str, summary: pd.DataFrame) -> list[dict[str, object]]:
    if summary.empty:
        return []
    rows: list[dict[str, object]] = []
    for item in summary.itertuples(index=False):
        symbol = normalize_symbol(getattr(item, "symbol", ""))
        start = pd.Timestamp(getattr(item, "start", pd.NaT))
        end = pd.Timestamp(getattr(item, "end", pd.NaT))
        if not symbol or pd.isna(start) or pd.isna(end):
            continue
        rows.append(
            {
                "part_id": part_id,
                "stock_code": symbol,
                "min_at": start.isoformat(),
                "max_at": end.isoformat(),
                "rows": int(getattr(item, "rows", 0) or 0),
            }
        )
    return rows


def _part_symbol_rows_from_identity(*, part_id: str, identity: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for symbol, group in identity.groupby("stock_code", sort=True):
        rows.append(
            {
                "part_id": part_id,
                "stock_code": str(symbol),
                "min_at": pd.Timestamp(group["date"].min()).isoformat(),
                "max_at": pd.Timestamp(group["date"].max()).isoformat(),
                "rows": int(len(group.drop_duplicates(subset=["date"]))),
            }
        )
    return rows


def _catalog_summary_by_symbol(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    symbols: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    if not symbols:
        return {}
    frames: list[pd.DataFrame] = []
    for chunk in _symbol_chunks(symbols, 500):
        try:
            catalog = query_catalog(data_root=data_root, symbols=chunk, adjust=adjust, timeframes=(timeframe,), statuses=("cached",))
        except Exception:  # noqa: BLE001
            continue
        if not catalog.empty:
            frames.append(catalog)
    if not frames:
        return {}
    catalog = pd.concat(frames, ignore_index=True)
    result: dict[str, dict[str, object]] = {}
    for row in catalog.itertuples(index=False):
        symbol = normalize_symbol(getattr(row, "stock_code", ""))
        if not symbol:
            continue
        result[symbol] = {
            "rows": int(getattr(row, "rows", 0) or 0),
            "start": _safe_timestamp(getattr(row, "start_at", pd.NaT)),
            "end": _safe_timestamp(getattr(row, "end_at", pd.NaT)),
        }
    return result


def _symbol_chunks(values: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _safe_timestamp(value: object) -> pd.Timestamp:
    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError):
        return pd.NaT


def _safe_worker_commit_id(value: str) -> str:
    text = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in str(value).strip())
    return text or uuid4().hex


def _upsert_catalog_from_direct_rows(
    *,
    data_root: str | Path,
    timeframe: str,
    adjust: str,
    rows: pd.DataFrame,
) -> None:
    if rows.empty:
        return
    records: list[dict[str, object]] = []
    for item in rows.itertuples(index=False):
        symbol = normalize_symbol(getattr(item, "symbol", ""))
        if not symbol:
            continue
        records.append(
            {
                "stock_code": symbol,
                "timeframe": timeframe,
                "adjust": adjust,
                "status": "cached",
                "exists": True,
                "rows": int(getattr(item, "rows", 0) or 0),
                "start": getattr(item, "start", pd.NaT),
                "end": getattr(item, "end", pd.NaT),
                "file_size_bytes": int(getattr(item, "file_size_bytes", 0) or 0),
                "modified_at": getattr(item, "modified_at", pd.NaT),
                "missing_columns": "",
                "path": str(getattr(item, "path", "") or ""),
                "message": "本地 parquet 可用于读取；Worker part 已直接挂载。",
            }
        )
    if records:
        upsert_catalog_records(data_root=data_root, inventory=pd.DataFrame(records), refresh_coverage=False)


def _register_delta_parts(
    *,
    data_root: str | Path,
    written: pd.DataFrame,
    manifest: dict[str, Any],
    timeframe: str,
    adjust: str,
) -> int:
    if written.empty or "delta_path" not in written.columns:
        return 0
    job_id = str(manifest.get("job_id") or "")
    created_at = _now_text()
    commit_version = time.time_ns()
    part_rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    for row in written.itertuples(index=False):
        delta_path_text = str(getattr(row, "delta_path", "") or "")
        symbol = normalize_symbol(getattr(row, "symbol", ""))
        if not delta_path_text or not symbol:
            continue
        delta_path = Path(delta_path_text)
        if not delta_path.exists():
            continue
        start = pd.Timestamp(getattr(row, "delta_start", getattr(row, "start", pd.NaT)))
        end = pd.Timestamp(getattr(row, "delta_end", getattr(row, "end", pd.NaT)))
        if pd.isna(start) or pd.isna(end):
            continue
        part_id = hashlib.sha256(f"{job_id}|{delta_path}|{symbol}|{start.isoformat()}|{end.isoformat()}".encode("utf-8")).hexdigest()
        trade_month = start.strftime("%Y-%m") if start.strftime("%Y-%m") == end.strftime("%Y-%m") else "multi"
        rows_count = int(getattr(row, "new_rows", 0) or getattr(row, "rows", 0) or 0)
        stat = delta_path.stat()
        part_rows.append(
            {
                "part_id": part_id,
                "job_id": job_id,
                "timeframe": timeframe,
                "adjust": adjust,
                "trade_month": trade_month,
                "path": str(delta_path),
                "rows": rows_count,
                "min_at": start.isoformat(),
                "max_at": end.isoformat(),
                "file_size_bytes": int(stat.st_size),
                "sha256": _sha256_file(delta_path),
                "commit_version": commit_version,
                "state": "active",
                "created_at": created_at,
            }
        )
        symbol_rows.append(
            {
                "part_id": part_id,
                "stock_code": symbol,
                "min_at": start.isoformat(),
                "max_at": end.isoformat(),
                "rows": rows_count,
            }
        )
    if not part_rows:
        return 0
    upsert_market_data_parts(data_root=data_root, parts=pd.DataFrame(part_rows), part_symbols=pd.DataFrame(symbol_rows))
    return len(part_rows)


def _dependency_status() -> dict[str, bool]:
    result: dict[str, bool] = {}
    for name in ("numpy", "pandas", "pyarrow", "dateutil", "pytz", "fastapi", "uvicorn"):
        try:
            __import__(name)
            result[name] = True
        except Exception:  # noqa: BLE001
            result[name] = False
    return result


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return frame.astype(object).where(frame.notna(), None).to_dict("records")


def _event_index(event: dict[str, Any]) -> int:
    try:
        return int(event.get("event_index", -1))
    except (TypeError, ValueError):
        return -1


def _window_progress_callback(
    callback,
    *,
    timeframe: str,
    step_index: int,
    step_count: int,
    start: str,
    end: str,
):
    def emit(event: dict[str, object]) -> None:
        payload = dict(event)
        payload.setdefault("timeframe", timeframe)
        payload["window_step_index"] = step_index
        payload["window_step_count"] = step_count
        payload["window_start"] = start
        payload["window_end"] = end
        callback(payload)

    return emit


def _raise_if_cancelled(cancel_check) -> None:
    if cancel_check is None:
        return
    cancel_check()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
