from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"
STYLES_CSS = APP_VUE.parent / "styles.css"


def test_quality_gate_errors_render_as_paginated_rows() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "selectedTaskQualityIssues.length" in source
    assert "pagedTaskQualityIssueRows" in source
    assert "taskQualityIssuePagination" in source
    assert "parseQualityGateIssues" in source


def test_raw_task_error_and_task_list_are_bounded() -> None:
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert ".task-list {" in styles
    assert "max-height: 520px;" in styles
    assert ".error-box {" in styles
    assert "max-height: 240px;" in styles
    assert ".quality-issue-list" in styles


def test_download_tasks_expose_pause_resume_cancel_controls() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert "controlTask(task, 'pause')" in source
    assert "controlTask(task, 'resume')" in source
    assert "controlTask(task, 'cancel')" in source
    assert "taskCanPause" in source
    assert "taskCanResume" in source
    assert "taskCanCancel" in source
    assert "taskPauseTitle(task)" in source
    assert "taskResumeTitle(task)" in source
    assert "taskCancelTitle(task)" in source
    assert ':disabled="!taskCanPause(task) || taskControlBusy(task)"' in source
    assert ':disabled="!taskCanResume(task) || taskControlBusy(task)"' in source
    assert ':disabled="!taskCanCancel(task) || taskControlBusy(task)"' in source
    assert 'v-if="taskCanPause(task)"' not in source
    assert 'v-if="taskCanResume(task)"' not in source
    assert 'v-if="taskCanCancel(task)"' not in source
    assert "最近任务控制" in source
    assert "controlTask(latestTask, 'pause')" in source
    assert "TASK_STATUS_LABELS" in source
    assert "apiPost(`/tasks/${task.id}/${action}`, {})" in source
    assert ".task-control-actions" in styles
    assert ".latest-task-actions" in styles
    assert ".task-item-main" in styles
