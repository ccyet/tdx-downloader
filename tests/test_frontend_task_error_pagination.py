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
