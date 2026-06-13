from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_WORKER_URL = "http://127.0.0.1:18765"
WORKER_URL_ENV_VAR = "TDX_WORKER_URL"
WORKER_POLL_SECONDS = 1.0
WORKER_TIMEOUT_SECONDS = 5
WORKER_JOB_TIMEOUT_SECONDS = 60 * 60
WORKER_WAIT_HEARTBEAT_SECONDS = 60.0
WORKER_EVENT_PAGE_LIMIT = 100
WORKER_POLL_MAX_ERRORS = 5


class WorkerUnavailable(RuntimeError):
    pass


class WorkerJobFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerResult:
    payload: dict[str, Any]
    manifest: dict[str, Any]
    part_dir: Path


class TdxWorkerClient:
    def __init__(self, base_url: str | None = None, *, timeout_seconds: float = WORKER_TIMEOUT_SECONDS) -> None:
        self.base_url = (base_url or os.getenv(WORKER_URL_ENV_VAR, DEFAULT_WORKER_URL)).rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/health")

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/jobs", payload)

    def get_job(
        self,
        job_id: str,
        *,
        after_event_index: int | None = None,
        event_limit: int | None = None,
        include_records: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, object] = {}
        if after_event_index is not None:
            params["after_event_index"] = int(after_event_index)
        if event_limit is not None:
            params["event_limit"] = int(event_limit)
        if not include_records:
            params["include_records"] = "false"
        suffix = f"?{urlencode(params)}" if params else ""
        return self._json("GET", f"/jobs/{quote(job_id)}{suffix}")

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self._json("POST", f"/jobs/{quote(job_id)}/cancel", {})

    def wait(self, job_id: str, *, progress_callback=None, cancel_check=None) -> dict[str, Any]:
        deadline = time.monotonic() + WORKER_JOB_TIMEOUT_SECONDS
        started_at = time.monotonic()
        last_heartbeat_at = started_at
        event_cursor = -1
        legacy_seen_events = 0
        poll_errors = 0
        while time.monotonic() < deadline:
            if cancel_check is not None:
                try:
                    cancel_check()
                except BaseException:
                    try:
                        self.cancel(job_id)
                    finally:
                        raise
            try:
                payload = self.get_job(
                    job_id,
                    after_event_index=event_cursor,
                    event_limit=WORKER_EVENT_PAGE_LIMIT,
                    include_records=False,
                )
                poll_errors = 0
            except WorkerUnavailable as exc:
                poll_errors += 1
                if progress_callback is not None:
                    progress_callback(
                        {
                            "stage": "worker_poll_retry",
                            "job_id": job_id,
                            "retry": poll_errors,
                            "max_retry": WORKER_POLL_MAX_ERRORS,
                            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                            "message": f"Windows Worker 状态轮询超时，准备重试：{poll_errors}/{WORKER_POLL_MAX_ERRORS}。{exc}",
                        }
                    )
                if poll_errors >= WORKER_POLL_MAX_ERRORS:
                    try:
                        self.health()
                    except WorkerUnavailable:
                        raise
                    if progress_callback is not None:
                        progress_callback(
                            {
                                "stage": "worker_poll_health_ok",
                                "job_id": job_id,
                                "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                                "message": "Worker health 正常，继续等待任务状态返回。",
                            }
                        )
                    poll_errors = 0
                time.sleep(min(WORKER_POLL_SECONDS * poll_errors, 5.0))
                continue
            events = payload.get("events") or []
            new_events: list[dict[str, Any]] = []
            if isinstance(events, list):
                new_events = _new_worker_events(events, event_cursor=event_cursor, legacy_seen_events=legacy_seen_events)
                if progress_callback is not None:
                    for event in new_events:
                        progress_callback(event)
                event_cursor = _advance_event_cursor(new_events, payload, event_cursor)
                if _uses_legacy_event_cursor(events):
                    legacy_seen_events += len(new_events)
            if progress_callback is not None and payload.get("events_truncated"):
                progress_callback(
                    {
                        "stage": "worker_event_gap",
                        "job_id": job_id,
                        "event_cursor": event_cursor,
                        "event_start_index": payload.get("event_start_index"),
                        "event_next_index": payload.get("event_next_index"),
                        "message": "Worker 事件已滚动截断，仅保留最近事件；任务状态仍按 Worker 实际状态继续跟踪。",
                    }
                )
            status = str(payload.get("status") or "")
            now = time.monotonic()
            if progress_callback is not None and now - last_heartbeat_at >= WORKER_WAIT_HEARTBEAT_SECONDS:
                last_stage = ""
                if isinstance(events, list):
                    for event in reversed(events):
                        if isinstance(event, dict):
                            last_stage = str(event.get("stage") or "")
                            break
                progress_callback(
                    {
                        "stage": "worker_job_waiting",
                        "job_id": job_id,
                        "worker_status": status,
                        "elapsed_ms": int((now - started_at) * 1000),
                        "event_count": _payload_event_count(payload, events),
                        "last_worker_stage": last_stage,
                        "message": f"等待 Windows Worker：{job_id}，状态 {status or 'unknown'}。",
                    }
                )
                last_heartbeat_at = now
            if status == "succeeded":
                return payload
            if status in {"failed", "cancelled"}:
                raise WorkerJobFailed(str(payload.get("error") or f"Worker job {status}"))
            time.sleep(WORKER_POLL_SECONDS)
        raise WorkerJobFailed(f"Worker job 超时：{job_id}")

    def fetch_manifest_and_parts(self, job_id: str) -> WorkerResult:
        part_dir = Path(tempfile.mkdtemp(prefix=f"tdx-worker-{job_id}-"))
        manifest_path = part_dir / "manifest.json"
        self._download(f"/jobs/{quote(job_id)}/manifest", manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for part in manifest.get("parts", []) or []:
            name = str(part.get("name") or "")
            if not name:
                continue
            self._download(f"/jobs/{quote(job_id)}/parts/{quote(name)}", part_dir / name)
        return WorkerResult(payload={}, manifest=manifest, part_dir=part_dir)

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise WorkerUnavailable(f"Worker HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WorkerUnavailable(f"Worker 不可用：{exc}") from exc

    def _download(self, path: str, target: Path) -> None:
        request = Request(self.base_url + path, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                with target.open("wb") as handle:
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise WorkerUnavailable(f"Worker 文件下载失败 HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise WorkerUnavailable(f"Worker 文件下载失败：{exc}") from exc


def _new_worker_events(events: list[Any], *, event_cursor: int, legacy_seen_events: int) -> list[dict[str, Any]]:
    if _uses_legacy_event_cursor(events):
        return [event for event in events[legacy_seen_events:] if isinstance(event, dict)]
    return [
        event
        for event in events
        if isinstance(event, dict) and _event_index(event) > event_cursor
    ]


def _advance_event_cursor(events: list[dict[str, Any]], payload: dict[str, Any], current: int) -> int:
    del payload
    cursor = current
    for event in events:
        cursor = max(cursor, _event_index(event))
    return cursor


def _uses_legacy_event_cursor(events: list[Any]) -> bool:
    return bool(events) and not any(isinstance(event, dict) and "event_index" in event for event in events)


def _event_index(event: dict[str, Any]) -> int:
    try:
        return int(event.get("event_index", -1))
    except (TypeError, ValueError):
        return -1


def _payload_event_count(payload: dict[str, Any], events: object) -> int:
    try:
        return int(payload.get("event_count"))
    except (TypeError, ValueError):
        return len(events) if isinstance(events, list) else 0
