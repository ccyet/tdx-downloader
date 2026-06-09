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


def test_cross_section_candidate_range_is_visible_but_mode_gated() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert 'v-model="crossForm.traversal_start"' in source
    assert 'v-model="crossForm.traversal_end"' in source
    assert ':disabled="crossForm.search_mode !== \'traversal\'"' in source
    assert "applyCandidateDateShortcut" in source


def test_cross_section_candidate_symbols_have_asset_shortcuts() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "所有ETF" in source
    assert "所有个股" in source
    assert "所有指数" in source
    assert "setCrossUniverseFromAssetType('etf')" in source
    assert "setCrossUniverseFromAssetType('stock')" in source
    assert "setCrossUniverseFromAssetType('index')" in source
    assert "symbolsForAssetType" in source
    assert "cacheSymbolsForAssetType" in source


def test_cross_section_kline_uses_chart_context_and_target_highlight() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "target_chart_window" in source
    assert "chart_candles" in source
    assert "target_segments" in source
    assert "row.segments" in source
    assert "对标窗口" in source
