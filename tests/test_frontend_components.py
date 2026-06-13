from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web" / "src" / "App.vue"
EMPTY_STATE = ROOT / "web" / "src" / "components" / "EmptyState.vue"
KLINE_CHART = ROOT / "web" / "src" / "components" / "KlineChart.vue"
METRIC_CARD = ROOT / "web" / "src" / "components" / "MetricCard.vue"
PANEL = ROOT / "web" / "src" / "components" / "Panel.vue"
STYLES = ROOT / "web" / "src" / "styles.css"


def test_empty_state_announces_status_changes() -> None:
    source = EMPTY_STATE.read_text(encoding="utf-8")

    assert 'role="status"' in source
    assert 'aria-live="polite"' in source
    assert "{{ title }}" in source
    assert "{{ body }}" in source


def test_panel_title_labels_region() -> None:
    source = PANEL.read_text(encoding="utf-8")

    assert ':aria-labelledby="titleId"' in source
    assert ':id="titleId"' in source
    assert "getCurrentInstance" in source


def test_metric_card_has_readable_summary_label() -> None:
    source = METRIC_CARD.read_text(encoding="utf-8")

    assert ':aria-label="`${title}：${value}，${detail}`"' in source


def test_notice_bar_announces_errors_as_alerts() -> None:
    source = APP.read_text(encoding="utf-8")

    assert ':role="noticeRole(notice)"' in source
    assert ':aria-live="noticeAriaLive(notice)"' in source
    assert "payload.type === 'error' ? 'alert' : 'status'" in source
    assert "payload.type === 'error' ? 'assertive' : 'polite'" in source


def test_kline_chart_uses_empty_state_when_no_candles() -> None:
    source = KLINE_CHART.read_text(encoding="utf-8")

    assert "import EmptyState from './EmptyState.vue'" in source
    assert 'v-if="!hasCandles"' in source
    assert 'title="暂无K线"' in source
    assert "const hasCandles = computed(() => candleCount.value > 0)" in source
    assert "共 ${candleCount} 根K线" in source


def test_navigation_and_ai_tabs_expose_current_state() -> None:
    source = APP.read_text(encoding="utf-8")

    assert ':aria-current="activeView === item.key ? \'page\' : undefined"' in source
    assert ":aria-label=\"sidebarCollapsed ? '展开侧栏' : '收起侧栏'\"" in source
    assert ":title=\"sidebarCollapsed ? '展开侧栏' : '收起侧栏'\"" in source
    assert ':id="aiWorkbenchTabId(tab.key)"' in source
    assert ':aria-controls="aiWorkbenchPanelId(tab.key)"' in source
    assert ':tabindex="activeAiWorkbenchTab === tab.key ? 0 : -1"' in source
    assert '@keydown="handleAiWorkbenchTabKeydown($event, tab.key)"' in source
    assert 'role="tabpanel"' in source
    assert ':aria-labelledby="aiWorkbenchTabId(\'chat\')"' in source
    assert ':aria-labelledby="aiWorkbenchTabId(\'symbols\')"' in source
    assert "event.key === 'ArrowRight'" in source
    assert "event.key === 'ArrowLeft'" in source
    assert "event.key === 'Home'" in source
    assert "event.key === 'End'" in source


def test_research_and_regime_tabs_expose_current_state() -> None:
    source = APP.read_text(encoding="utf-8")

    assert 'role="tablist" aria-label="研究工具页签"' in source
    assert ':id="researchTabId(tab.key)"' in source
    assert ':aria-controls="researchPanelId(tab.key)"' in source
    assert ':tabindex="activeResearchTab === tab.key ? 0 : -1"' in source
    assert '@keydown="handleResearchTabKeydown($event, tab.key)"' in source
    assert ':id="researchPanelId(\'history\')"' in source
    assert ':id="researchPanelId(\'cross\')"' in source
    assert ':id="researchPanelId(\'review\')"' in source
    assert ':id="researchPanelId(\'etf\')"' in source
    assert ':id="researchPanelId(\'regime\')"' in source
    assert ':aria-labelledby="researchTabId(\'review\')"' in source

    assert 'role="tablist" aria-label="市场风险偏好功能页签"' in source
    assert ':id="regimeSectionTabId(tab.key)"' in source
    assert ':aria-controls="regimeSectionPanelId(tab.key)"' in source
    assert ':tabindex="activeRegimeSectionTab === tab.key ? 0 : -1"' in source
    assert '@keydown="handleRegimeSectionTabKeydown($event, tab.key)"' in source
    assert source.count(':title="`切换到${tab.label}`"') >= 2
    assert ':id="regimeSectionPanelId(\'overview\')"' in source
    assert ':id="regimeSectionPanelId(\'daily\')"' in source
    assert ':id="regimeSectionPanelId(\'flow\')"' in source
    assert ':id="regimeSectionPanelId(\'asset\')"' in source
    assert ':id="regimeSectionPanelId(\'factor\')"' in source
    assert "function handleTabKeydown<T extends string>" in source


def test_global_focus_styles_cover_workbench_controls() -> None:
    styles = STYLES.read_text(encoding="utf-8")

    for selector in [
        ".nav-button:focus-visible",
        ".research-tab:focus-visible",
        ".date-shortcut:focus-visible",
        ".table-expand-toggle:focus-visible",
        ".ai-workbench-tabs button:focus-visible",
        ".directory-browser-row:focus-visible",
        ".task-form input:focus-visible",
    ]:
        assert selector in styles
    assert "box-shadow: inset 3px 0 0 var(--accent-deep)" in styles


def test_dialogs_are_described_and_focus_first_control() -> None:
    source = APP.read_text(encoding="utf-8")

    assert '@keydown.esc="closeDirectoryBrowser"' in source
    assert '@keydown.esc="closeReviewSymbolPicker"' in source
    assert 'aria-describedby="directory-browser-description"' in source
    assert 'id="directory-browser-description"' in source
    assert 'aria-describedby="review-symbol-picker-description"' in source
    assert 'id="review-symbol-picker-description"' in source
    assert 'ref="directoryBrowserPathInput"' in source
    assert 'ref="reviewSymbolPickerSearchInput"' in source
    assert "directoryBrowserPathInput.value?.focus()" in source
    assert "directoryBrowserPathInput.value?.select()" in source
    assert "reviewSymbolPickerSearchInput.value?.focus()" in source
    assert ':aria-pressed="reviewSymbolPickerType === tabItem.key"' in source
    assert source.count('class="asset-picker-summary" role="status" aria-live="polite"') >= 2
    assert source.count('class="action-status inline"\n            role="status"\n            aria-live="polite"') >= 2


def test_buttons_declare_explicit_type() -> None:
    files = [APP, *sorted((ROOT / "web" / "src" / "components").glob("*.vue"))]
    missing: list[str] = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<button\b[\s\S]*?>", source):
            tag = match.group(0)
            if re.search(r"\btype\s*=", tag):
                continue
            line = source[: match.start()].count("\n") + 1
            missing.append(f"{path.relative_to(ROOT)}:{line}")

    assert missing == []


def test_unwrapped_form_controls_have_accessible_names() -> None:
    source = APP.read_text(encoding="utf-8")
    missing: list[str] = []

    for match in re.finditer(r"<(input|select|textarea)\b[\s\S]*?>", source):
        tag = match.group(0)
        before = source[: match.start()]
        is_inside_label = before.rfind("<label") > before.rfind("</label>")
        has_name = (
            'aria-label=' in tag
            or ':aria-label=' in tag
            or re.search(r"\bid\s*=", tag)
            or re.search(r"\b:id\s*=", tag)
        )
        if is_inside_label or has_name:
            continue
        line = before.count("\n") + 1
        missing.append(f"App.vue:{line}")

    assert missing == []


def test_native_tables_have_accessible_names() -> None:
    files = [APP, *sorted((ROOT / "web" / "src" / "components").glob("*.vue"))]
    missing: list[str] = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<table\b[\s\S]*?>", source):
            tag = match.group(0)
            has_name = (
                'aria-label=' in tag
                or ':aria-label=' in tag
                or 'aria-labelledby=' in tag
                or ':aria-labelledby=' in tag
            )
            if has_name:
                continue
            line = source[: match.start()].count("\n") + 1
            missing.append(f"{path.relative_to(ROOT)}:{line}")

    assert missing == []


def test_table_headers_declare_column_scope() -> None:
    files = [APP, *sorted((ROOT / "web" / "src" / "components").glob("*.vue"))]
    missing: list[str] = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<th\b[\s\S]*?>", source):
            tag = match.group(0)
            if re.search(r"\bscope\s*=", tag) or re.search(r"\b:scope\s*=", tag):
                continue
            line = source[: match.start()].count("\n") + 1
            missing.append(f"{path.relative_to(ROOT)}:{line}")

    assert missing == []
