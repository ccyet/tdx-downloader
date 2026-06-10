from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"
STYLES = APP_VUE.parent / "styles.css"


def test_frontend_exposes_global_ai_command_box() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "大模型命令框" in source
    assert "aiCommandScopeLabel" in source
    assert "runAiCommand" in source
    assert "apiPost('/ai/command'" in source
    assert "base_url: aiSettings.base_url.trim()" in source
    assert "api_key: aiSettings.api_key.trim()" in source
    assert "applyAiCommandPatch" in source
    assert "applyAiFormFieldPatch" in source
    assert "applyAiDateShortcut" in source
    assert "activeView" in source
    assert "aiWorkbenchForm.symbols" in source
    assert "selectedTimeframes" in source
    assert "regimeForm.benchmark_rally_60_threshold" in source
    assert "帮我选择所有创业板股票" in source


def test_frontend_exposes_ai_workbench_and_chart_settings() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "AI 工作台" in source
    assert "activeView === 'ai'" in source
    assert "AI 模块" in source
    assert "Stock Data Interface" in source
    assert "importAiSkillPrompt" in source
    assert "Skill 已导入" in source
    assert "runAiWorkbench" in source
    assert "apiPost('/ai/stock-agent'" in source
    assert "aiWorkbenchLatestRows" in source
    assert "aiWorkbenchMarkdownBlocks" in source
    assert "aiWorkbenchChartItems" in source
    assert "输出K线图数" in source
    assert "max_charts: numberOrDefault(aiWorkbenchForm.max_charts, 3)" in source
    assert "统一图表设置" in source
    assert "chartSettings" in source
    assert "chartThemeClass" in source
    assert "chart-density-compact" in styles
    assert ".ai-command-shell" in styles
    assert ".ai-workbench-output" in styles
    assert ".skill-file-action input" in styles
