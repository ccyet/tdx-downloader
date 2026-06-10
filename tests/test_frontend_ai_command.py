from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"
STYLES = APP_VUE.parent / "styles.css"
UPDATE_SCRIPT = APP_VUE.parents[2] / "scripts" / "update-local-data.sh"


def test_frontend_exposes_global_ai_command_box() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "大模型命令框" in source
    assert 'v-if="activeView !== \'ai\'"' in source
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


def test_frontend_exposes_ai_workbench_chatbot_layout() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "AI 工作台" in source
    assert "activeView === 'ai'" in source
    assert "ai-chat-layout" in source
    assert "ai-side-panel" in source
    assert "ai-chat-composer" in source
    assert "Skill 侧载" in source
    assert "标的选择" in source
    assert "runAiSymbolFilter" in source
    assert "replaceAiSymbolsFromGroup" in source
    assert "按标的上限载入前" in source
    assert "importAiSkillPrompt" in source
    assert "Skill 已导入" in source
    assert "runAiWorkbench" in source
    assert "apiPost('/ai/stock-agent'" in source
    assert "aiWorkbenchLatestRows" in source
    assert "aiWorkbenchMarkdownBlocks" in source
    assert "aiWorkbenchChartItems" in source
    assert "K线图" in source
    assert "max_charts: numberOrDefault(aiWorkbenchForm.max_charts, 3)" in source
    assert "review-markdown-code" in source
    assert "markdownTextBlock" in source
    assert ".ai-command-shell" in styles
    assert ".ai-chat-layout" in styles
    assert ".ai-symbol-list" in styles
    assert ".ai-chat-composer" in styles
    assert ".ai-workbench-output" in styles
    assert ".review-markdown-code" in styles
    assert ".skill-file-action input" in styles


def test_local_update_script_exists_for_host_side_data_refresh() -> None:
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert UPDATE_SCRIPT.exists()
    assert UPDATE_SCRIPT.stat().st_mode & 0o111
    assert "tdx_downloader.cli prepare-data" in source
    assert "--asset-types" in source
    assert "cache_snapshot" in source
