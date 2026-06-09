from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_download_date_shortcuts_use_trading_day_lookback() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

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


def test_fuyao_calendar_key_is_local_setting_not_source_secret() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const fuyaoSettings = reactive" in source
    assert "fuyaoSettings.api_key" in source
    assert "Fuyao API Key" in source
    assert "fuyaoApiHeaders" in source
    assert "x-fuyao-api-key" in source
    assert "saved.fuyao.api_key || ''" in source
