from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from ..constants import TASK_HISTORY_LIMIT
from ..task_store import _append_event, _get_task, _request_task_control, _task_payload, _tasks, _tasks_lock


def register_tasks_routes(app: FastAPI) -> None:
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

    @app.post("/api/tasks/{task_id}/pause")
    def pause_task(task_id: str) -> dict[str, Any]:
        task = _request_task_control(task_id, "pause")
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        _append_event(task_id, {"stage": "task_pause_requested", "message": "已请求暂停任务。"})
        return _task_payload(task)

    @app.post("/api/tasks/{task_id}/resume")
    def resume_task(task_id: str) -> dict[str, Any]:
        task = _request_task_control(task_id, "resume")
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        _append_event(task_id, {"stage": "task_resume_requested", "message": "已请求继续任务。"})
        return _task_payload(task)

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict[str, Any]:
        task = _request_task_control(task_id, "cancel")
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在。")
        _append_event(task_id, {"stage": "task_cancel_requested", "message": "已请求终止任务。"})
        return _task_payload(task)

    @app.delete("/api/tasks")
    def clear_tasks() -> dict[str, Any]:
        with _tasks_lock:
            running = {task_id: task for task_id, task in _tasks.items() if task.status in {"queued", "running"}}
            removed_count = len(_tasks) - len(running)
            _tasks.clear()
            _tasks.update(running)
        return {"removed_count": removed_count, "running_count": len(running)}
