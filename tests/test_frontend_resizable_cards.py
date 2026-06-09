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
    assert "data-resizable-card" in panel
    assert "data-resizable-card" in metric_card
    assert "data-resizable-card" in kline_chart
    assert ".resizable-card" in styles
    assert "resize: vertical" in styles
    assert "max-width: 100%" in styles
    assert "box-sizing: border-box" in styles
    assert "resize: both" not in styles
