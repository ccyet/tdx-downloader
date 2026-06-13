from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_download_date_shortcuts_use_trading_day_lookback() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = (APP_VUE.parent / "styles.css").read_text(encoding="utf-8")

    assert "const tradingCalendarDays = ref<string[]>([])" in source
    assert "async function loadTradingCalendar" in source
    assert "if (!fuyaoCalendarAvailable()) return false" in source
    assert "function fuyaoCalendarAvailable" in source
    assert "config.value?.integrations?.fuyao_calendar?.configured" in source
    assert "apiGet('/trading-calendar', { headers: fuyaoApiHeaders() })" in source
    assert "function tradingLookbackStartText" in source
    assert "tradingCalendarDays.value" in source
    assert "if (key === '20d') return { start: tradingLookbackStartText(20), end }" in source
    assert "if (key === '50d') return { start: tradingLookbackStartText(50), end }" in source
    assert "settings.start = tradingLookbackStartText(days)" in source
    assert "近 N 交易日" in source
    assert "时间窗为近 ${days} 个交易日" in source
    assert "pendingDownloadDateShortcut" in source
    assert "downloadDateShortcutPendingRange" in source
    assert "downloadDateShortcutPendingText" in source
    assert "requestDownloadDateShortcut" in source
    assert "cancelDownloadDateShortcut" in source
    assert "confirmDownloadDateShortcut" in source
    assert "应用日期快捷前需要确认" in source
    assert "当前日期区间和预览计划未修改" in source
    assert "并清空当前预览计划" in source
    assert '@click="applyDateShortcut(settings, shortcut.key)"' not in source
    assert '@click="requestDownloadDateShortcut(shortcut.key)"' in source
    assert ':aria-pressed="isDateShortcutActive(settings, shortcut.key)"' in source
    assert ".download-date-shortcut-status" in styles


def test_research_date_shortcuts_require_confirmation() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = (APP_VUE.parent / "styles.css").read_text(encoding="utf-8")

    assert "type ResearchDateShortcutTarget" in source
    assert "pendingResearchDateShortcut" in source
    assert "researchDateShortcutPendingText" in source
    assert "requestResearchDateShortcut" in source
    assert "cancelResearchDateShortcut" in source
    assert "confirmResearchDateShortcut" in source
    assert "applyResearchDateShortcut" in source
    assert "researchDateShortcutAlreadyActive" in source
    assert "旧研究结果不会自动刷新" in source
    assert "请重新运行研究刷新结果" in source
    assert "候选区间只在指定区间模式下可修改" in source
    assert "应用历史相似日期快捷前需要确认" in source
    assert "应用目标日期快捷前需要确认" in source
    assert "应用候选日期快捷前需要确认" in source
    assert "应用 ETF 日期快捷前需要确认" in source
    assert "应用市场风偏日期快捷前需要确认" in source
    assert "应用复盘日期快捷前需要确认" in source
    assert '@click="applyHistoryDateShortcut(shortcut.key)"' not in source
    assert '@click="applyDateShortcut(crossForm, shortcut.key)"' not in source
    assert '@click="applyCandidateDateShortcut(shortcut.key)"' not in source
    assert '@click="applyDateShortcut(etfTrackerForm, shortcut.key)"' not in source
    assert '@click="applyDateShortcut(regimeForm, shortcut.key)"' not in source
    assert '@click="applyDateShortcut(reviewForm, shortcut.key)"' not in source
    assert '@click="requestResearchDateShortcut(\'history\', shortcut.key)"' in source
    assert '@click="requestResearchDateShortcut(\'crossTarget\', shortcut.key)"' in source
    assert '@click="requestResearchDateShortcut(\'crossCandidate\', shortcut.key)"' in source
    assert '@click="requestResearchDateShortcut(\'etf\', shortcut.key)"' in source
    assert '@click="requestResearchDateShortcut(\'regime\', shortcut.key)"' in source
    assert '@click="requestResearchDateShortcut(\'review\', shortcut.key)"' in source
    assert ':aria-pressed="isHistoryDateShortcutActive(shortcut.key)"' in source
    assert source.count(':aria-pressed="isDateShortcutActive(') >= 5
    assert ':aria-pressed="isCandidateDateShortcutActive(shortcut.key)"' in source
    assert ".research-date-shortcut-status" in styles


def test_fuyao_calendar_key_is_local_setting_not_source_secret() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const fuyaoSettings = reactive" in source
    assert "fuyaoSettings.api_key" in source
    assert "Fuyao API Key" in source
    assert "fuyaoApiHeaders" in source
    assert "x-fuyao-api-key" in source
    assert "saved.fuyao.api_key || ''" in source
