from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_multi_review_has_explicit_ai_review_toggle() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert 'v-model="reviewForm.enable_ai_review"' in source
    assert "启用 AI 锐评" in source
    assert 'class="review-ai-toggle"' in source
    assert 'class="span-full review-ai-toggle"' not in source


def test_multi_review_only_runs_ai_when_toggle_enabled() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "if (reviewForm.enable_ai_review) await runAiReview({ fallbackToLocal: true })" in source
    assert "else aiReviewOutput.value = null" in source


def test_multi_review_ai_toggle_uses_compact_single_line_layout() -> None:
    styles = (APP_VUE.parent / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns: auto auto minmax(0, 1fr);" in styles
    assert ".review-ai-toggle em" in styles
    assert "text-overflow: ellipsis;" in styles
