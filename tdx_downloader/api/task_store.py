from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import time
from typing import Any
from uuid import uuid4

from .constants import STAGE_LABELS, TASK_EVENT_LIMIT, TASK_HISTORY_LIMIT
from .serialization import _json_dict

PROGRESS_ONLY_STAGES = {
    "tdx_request_start",
    "tdx_request_done",
    "tdx_batch_start",
    "tdx_batch_done",
    "worker_fetch_window_start",
    "worker_fetch_window_done",
    "worker_commit_progress",
}
IMPORTANT_EVENT_KEYWORDS = ("failed", "error", "cancel", "waiting", "skipped", "paused", "resumed")


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
    control: str = "run"


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tdx-api")
_tasks: dict[str, TaskState] = {}
_tasks_lock = threading.Lock()


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
    _enrich_progress_event(event_payload)
    event_payload["label"] = _progress_label(event_payload)
    with _tasks_lock:
        task = _tasks[task_id]
        task.events.append(event_payload)
        if len(task.events) > TASK_EVENT_LIMIT:
            del task.events[: len(task.events) - TASK_EVENT_LIMIT]


def _request_task_control(task_id: str, control: str) -> TaskState | None:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        if control == "pause":
            if task.status not in {"queued", "running"}:
                return task
            task.control = "pause"
            if task.status == "running":
                task.status = "pausing"
        elif control == "resume":
            if task.status not in {"paused", "pausing"}:
                return task
            task.control = "run"
            task.status = "running"
        elif control == "cancel":
            if task.status in {"succeeded", "failed", "cancelled"}:
                return task
            task.control = "cancel"
            if task.status in {"queued", "running", "pausing", "paused"}:
                task.status = "cancelling"
        else:
            raise ValueError(f"未知任务控制指令：{control}")
        return task


def _task_control(task_id: str) -> str:
    with _tasks_lock:
        task = _tasks.get(task_id)
        return task.control if task is not None else "cancel"


def _wait_if_task_paused(task_id: str) -> None:
    pause_event_written = False
    while True:
        control = _task_control(task_id)
        if control == "cancel":
            raise TaskCancelled("任务已终止。")
        if control != "pause":
            if pause_event_written:
                _append_event(task_id, {"stage": "task_resumed", "message": "任务已继续执行。"})
            return
        if not pause_event_written:
            _update_task(task_id, status="paused")
            _append_event(task_id, {"stage": "task_paused", "message": "任务已暂停，等待继续或终止。"})
            pause_event_written = True
        time.sleep(0.5)


def _raise_if_task_cancelled(task_id: str) -> None:
    if _task_control(task_id) == "cancel":
        raise TaskCancelled("任务已终止。")


class TaskCancelled(RuntimeError):
    pass


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
        "control": task.control,
    }


def _progress_label(event: dict[str, object]) -> str:
    stage = str(event.get("stage", ""))
    label = STAGE_LABELS.get(stage, stage)
    timeframe = str(event.get("timeframe") or "")
    window_index = event.get("window_step_index")
    window_count = event.get("window_step_count")
    batch_index = event.get("batch_index")
    batch_count = event.get("batch_count")
    if _positive_number(window_index) and _positive_number(window_count):
        parts = [label]
        if timeframe:
            parts.append(timeframe)
        parts.append(f"窗口 {int(window_index)}/{int(window_count)}")
        if (
            _positive_number(batch_index)
            and _positive_number(batch_count)
            and int(batch_count) > 1
        ):
            parts.append(f"子批次 {int(batch_index)}/{int(batch_count)}")
        return " · ".join(parts)
    if batch_index and batch_count:
        return f"{label} · {timeframe} · {batch_index}/{batch_count}"
    if timeframe:
        return f"{label} · {timeframe}"
    return label


def _enrich_progress_event(event: dict[str, object]) -> None:
    stage = str(event.get("stage") or "")
    current = event.get("step_index") or event.get("window_step_index") or event.get("batch_index")
    total = event.get("step_count") or event.get("window_step_count") or event.get("batch_count")
    if _positive_number(current) and _positive_number(total):
        total_int = max(int(total), 1)
        current_int = min(max(int(current), 0), total_int)
        event.setdefault("progress_current", current_int)
        event.setdefault("progress_total", total_int)
        event.setdefault("progress_ratio", current_int / total_int)
    if "visible" not in event:
        event["visible"] = _event_visible_by_default(stage)


def _event_visible_by_default(stage: str) -> bool:
    if stage not in PROGRESS_ONLY_STAGES:
        return True
    return any(keyword in stage for keyword in IMPORTANT_EVENT_KEYWORDS)


def _positive_number(value: object) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
