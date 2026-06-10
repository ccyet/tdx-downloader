from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_VUE = ROOT / "web" / "src" / "App.vue"
PANEL = ROOT / "web" / "src" / "components" / "Panel.vue"
METRIC_CARD = ROOT / "web" / "src" / "components" / "MetricCard.vue"
KLINE_CHART = ROOT / "web" / "src" / "components" / "KlineChart.vue"
STYLES = ROOT / "web" / "src" / "styles.css"


def test_global_card_surfaces_are_resizable_and_resettable() -> None:
    app = APP_VUE.read_text(encoding="utf-8")
    panel = PANEL.read_text(encoding="utf-8")
    metric_card = METRIC_CARD.read_text(encoding="utf-8")
    kline_chart = KLINE_CHART.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "还原卡片尺寸" in app
    assert "resetResizableCards" in app
    assert "normalizeResizableCardWidths" in app
    assert "clearResizableCardInlineSize(false)" in app
    assert "data-resizable-card" in panel
    assert "data-resizable-card" in metric_card
    assert "data-resizable-card" in kline_chart
    assert ".resizable-card" in styles
    assert "resize: vertical" in styles
    assert "width: 100% !important" in styles
    assert "max-inline-size: 100%" in styles
    assert "max-width: 100%" in styles
    assert "box-sizing: border-box" in styles
    assert "resize: both" not in styles
    assert "resize: horizontal" not in styles


def test_resizable_cards_stay_in_layout_flow_without_horizontal_overlap() -> None:
    styles = STYLES.read_text(encoding="utf-8")

    assert "grid-auto-rows: max-content" in styles
    assert ".content-grid > *" in styles
    assert ".view-stack > *" in styles
    assert "isolation: isolate" in styles
    assert "contain: layout paint" in styles
    assert "overscroll-behavior: contain" in styles
    assert "overflow: hidden auto" in styles
    assert "width: 100%" in styles
    assert "justify-self: stretch" in styles
    assert "[data-resizable-card]:focus-within" in styles
    assert "[data-resizable-card]:hover" in styles
    assert "flex-wrap: wrap" in styles
    assert "white-space: normal" in styles
