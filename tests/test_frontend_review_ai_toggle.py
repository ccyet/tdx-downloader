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

    assert "confirmingRunReviewSearch" in source
    assert "reviewSearchConfirmText" in source
    assert "requestRunReviewSearch" in source
    assert "cancelRunReviewSearch" in source
    assert "confirmRunReviewSearch" in source
    assert '@submit.prevent="requestRunReviewSearch"' in source
    assert '@submit.prevent="runReviewSearch"' not in source
    assert "生成多股复盘前需要确认" in source
    assert "确认生成多股复盘" in source
    assert "确认后将按" in source
    assert "多股复盘未生成" in source
    assert "当前排序、K 线和锐评未修改" in source
    assert "确认生成" in source
    assert "if (reviewForm.enable_ai_review) await runAiReview({ fallbackToLocal: true })" in source
    assert "else aiReviewOutput.value = null" in source
    assert "reviewAiActionDisabledReason" in source
    assert "reviewAiActionStatusText" in source
    assert "confirmingRunAiReview" in source
    assert "reviewAiConfirmText" in source
    assert "requestRunAiReview" in source
    assert "cancelRunAiReview" in source
    assert "confirmRunAiReview" in source
    assert "AI 覆盖复盘前需要确认" in source
    assert "确认后将发送多股复盘证据给模型" in source
    assert "AI 覆盖未执行" in source
    assert "当前复盘与锐评输出未修改" in source
    assert '@click="runAiReview()"' not in source
    assert "先生成多股复盘，得到可发送给 AI 的证据" in source
    assert "AI 覆盖正在生成" in source


def test_multi_review_ai_toggle_uses_compact_single_line_layout() -> None:
    styles = (APP_VUE.parent / "styles.css").read_text(encoding="utf-8")

    assert "grid-template-columns: auto auto minmax(0, 1fr);" in styles
    assert ".review-ai-toggle em" in styles
    assert "text-overflow: ellipsis;" in styles
