from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_cross_section_form_separates_target_and_candidate_ranges() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "目标锚定区间" in source
    assert "目标开始" in source
    assert "目标结束" in source
    assert "候选搜索区间" in source
    assert "候选开始" in source
    assert "候选结束" in source


def test_history_and_cross_section_search_require_confirmation() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "confirmingRunHistorySearch" in source
    assert "historySearchConfirmText" in source
    assert "requestRunHistorySearch" in source
    assert "cancelRunHistorySearch" in source
    assert "confirmRunHistorySearch" in source
    assert '@submit.prevent="requestRunHistorySearch"' in source
    assert '@submit.prevent="runHistorySearch"' not in source
    assert "开始历史相似搜索前需要确认" in source
    assert "确认搜索历史相似" in source
    assert "历史相似未搜索" in source
    assert "当前历史匹配结果和窗口 K 线未修改" in source

    assert "confirmingRunCrossSearch" in source
    assert "crossSearchConfirmText" in source
    assert "requestRunCrossSectionSearch" in source
    assert "cancelRunCrossSectionSearch" in source
    assert "confirmRunCrossSectionSearch" in source
    assert '@submit.prevent="requestRunCrossSectionSearch"' in source
    assert '@submit.prevent="runCrossSectionSearch"' not in source
    assert "开始横截面相似搜索前需要确认" in source
    assert "确认搜索横截面相似" in source
    assert "横截面相似未搜索" in source
    assert "当前横截面匹配结果和窗口 K 线未修改" in source


def test_cross_section_candidate_range_is_visible_but_mode_gated() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert 'v-model="crossForm.traversal_start"' in source
    assert 'v-model="crossForm.traversal_end"' in source
    assert "crossCandidateRangeDisabledReason" in source
    assert "同区间模式下候选区间跟随目标区间；切换为指定区间后可编辑。" in source
    assert ':disabled="Boolean(crossCandidateRangeDisabledReason)"' in source
    assert ':title="crossCandidateRangeDisabledReason || \'设置候选搜索起始日期\'"' in source
    assert ':title="crossCandidateRangeDisabledReason || \'设置候选搜索结束日期\'"' in source
    assert ':title="crossCandidateRangeDisabledReason || \'应用候选日期快捷前需要确认\'"' in source
    assert "applyCandidateDateShortcut" in source
    assert '@click="requestResearchDateShortcut(\'crossCandidate\', shortcut.key)"' in source
    assert '@click="applyCandidateDateShortcut(shortcut.key)"' not in source


def test_cross_section_candidate_symbols_have_asset_shortcuts() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = (APP_VUE.parent / "styles.css").read_text(encoding="utf-8")

    assert "所有ETF" in source
    assert "所有个股" in source
    assert "所有指数" in source
    assert "pendingCrossUniverseAction" in source
    assert "requestCrossUniverseFromAssetType" in source
    assert "cancelCrossUniverseAction" in source
    assert "confirmCrossUniverseAction" in source
    assert "crossUniversePendingStatusText" in source
    assert "填入所有 ETF 前需要确认" in source
    assert "填入所有个股前需要确认" in source
    assert "填入所有指数前需要确认" in source
    assert "确认后将用" in source
    assert "@click=\"requestCrossUniverseFromAssetType('etf')\"" in source
    assert "@click=\"requestCrossUniverseFromAssetType('stock')\"" in source
    assert "@click=\"requestCrossUniverseFromAssetType('index')\"" in source
    assert "@click=\"setCrossUniverseFromAssetType(" not in source
    assert '@input="cancelCrossUniverseAction"' in source
    assert "symbolsForAssetType" in source
    assert "cacheSymbolsForAssetType" in source
    assert ".cross-universe-status" in styles


def test_cross_section_kline_uses_chart_context_and_target_highlight() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "target_chart_window" in source
    assert "chart_candles" in source
    assert "target_segments" in source
    assert "row.segments" in source
    assert "对标窗口" in source
