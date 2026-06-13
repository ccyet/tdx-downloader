from __future__ import annotations

import re
from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"
STYLES = APP_VUE.parent / "styles.css"
UPDATE_SCRIPT = APP_VUE.parents[2] / "scripts" / "update-local-data.sh"


def test_frontend_exposes_global_ai_command_box() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "大模型命令框" in source
    assert 'v-if="activeView !== \'ai\'"' in source
    assert "aiCommandScopeLabel" in source
    assert "runAiCommand" in source
    assert "apiPost('/ai/command'" in source
    assert "end: aiCommandEndDate()" in source
    assert "base_url: aiSettings.base_url.trim()" in source
    assert "api_key: aiSettings.api_key.trim()" in source
    assert "aiCommandResultState" in source
    assert "AiCommandResultState" in source
    assert "confirmingRunAiCommand" in source
    assert "aiCommandRunConfirmText" in source
    assert "requestRunAiCommand" in source
    assert "cancelRunAiCommand" in source
    assert "confirmRunAiCommand" in source
    assert "aiCommandApplyConfirmText" in source
    assert "handleAiCommandInput" in source
    assert "cancelAiCommandApply" in source
    assert "confirmAiCommandApply" in source
    assert "解析命令" in source
    assert "解析命令前需要确认" in source
    assert "确认解析 AI 命令" in source
    assert "AI 命令未解析" in source
    assert "没有调用模型或本地规则，当前页面参数未修改" in source
    assert '@submit.prevent="requestRunAiCommand"' in source
    assert '@submit.prevent="runAiCommand"' not in source
    assert "确认应用" in source
    assert "AI 命令参数未修改" in source
    assert "命令已解析，确认后才会应用" in source
    assert "applyAiCommandPatch" in source
    assert "applyAiFormFieldPatch" in source
    assert "applyAiDateShortcut" in source
    assert ".ai-command-actions" in styles
    run_ai_command = re.search(r"async function runAiCommand\(\) \{(?P<body>.*?)\nfunction handleAiCommandInput", source, re.S)
    assert run_ai_command is not None
    assert "applyAiCommandResult(result)" not in run_ai_command.group("body")
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
    assert "标的池" in source
    assert "activeAiWorkbenchTab" in source
    assert "ai-symbol-workspace" in source
    assert "runAiSymbolFilter" in source
    assert "replaceAiSymbolsFromGroup" in source
    assert "appendFilteredAiSymbols" in source
    assert "selectTopAiSymbols" in source
    assert "pendingAiSymbolAction" in source
    assert "AiSymbolPendingAction" in source
    assert "filterResult" in source
    assert "pendingAiSymbolFilterResult" in source
    assert "pendingAiSymbolFilterSymbols" in source
    assert "requestAiSymbolAction" in source
    assert "cancelAiSymbolAction" in source
    assert "confirmAiSymbolAction" in source
    assert "confirmAiSymbolFilterResult" in source
    assert "aiSymbolPendingActionText" in source
    assert "载入 AI 筛选结果" in source
    assert "AI 筛选匹配" in source
    assert "替换本类前需要确认" in source
    assert "追加当前筛选前需要确认" in source
    assert "追加本页前需要确认" in source
    assert "AI 工作台标的未修改" in source
    run_ai_symbol_filter = re.search(r"async function runAiSymbolFilter\(\) \{(?P<body>.*?)\nfunction applyAllAssetsRecentUpdate", source, re.S)
    assert run_ai_symbol_filter is not None
    assert "applyAiCommandResult(result)" not in run_ai_symbol_filter.group("body")
    assert "requestAiSymbolAction('filterResult')" in run_ai_symbol_filter.group("body")
    assert '@click="selectTopAiSymbols"' not in source
    assert '@click="replaceAiSymbolsFromGroup"' not in source
    assert '@click="appendFilteredAiSymbols"' not in source
    assert '@click="appendPageAiSymbols"' not in source
    assert "loadAiSymbolMetrics" in source
    assert "aiSymbolMetricsDisabledReason" in source
    assert "aiSymbolFilterDisabledReason" in source
    assert "AiSymbolRunPendingAction" in source
    assert "pendingAiSymbolRunAction" in source
    assert "aiSymbolRunPendingText" in source
    assert "requestAiSymbolRunAction" in source
    assert "cancelAiSymbolRunAction" in source
    assert "confirmAiSymbolRunAction" in source
    assert "刷新当前标的池指标前需要确认" in source
    assert "执行 AI 筛选前需要确认" in source
    assert "AI 标的操作未执行" in source
    assert "当前标的指标、筛选结果和已选标的未修改" in source
    assert '@click="requestAiSymbolRunAction(\'metrics\')"' in source
    assert '@click="requestAiSymbolRunAction(\'filter\')"' in source
    assert '@click="loadAiSymbolMetrics(true, true)"' not in source
    assert '@click="runAiSymbolFilter"' not in source
    assert "aiSymbolTopNDisabledReason" in source
    assert "aiSymbolClearDisabledReason" in source
    assert "aiSymbolControlsDisabledReason" in source
    assert "请先确认或取消当前 AI 标的运行操作" in source
    assert "请先确认或取消当前 AI 标的操作" in source
    assert "请先确认或取消清空已选标的" in source
    assert ':disabled="Boolean(aiSymbolControlsDisabledReason)"' in source
    assert ':title="aiSymbolControlsDisabledReason || \'切换标的分组\'"' in source
    assert ':title="aiSymbolControlsDisabledReason || \'按代码、名称或类型筛选当前分组\'"' in source
    assert ':title="aiSymbolControlsDisabledReason || \'设置按当前排序选中的数量\'"' in source
    assert ':title="aiSymbolControlsDisabledReason || \'输入自然语言筛选条件\'"' in source
    assert source.count('aria-describedby="ai-symbol-status"') >= 4
    assert 'id="ai-symbol-status"' in source
    assert 'role="status"' in source
    assert 'aria-live="polite"' in source
    assert "requestClearAiSelectedSymbols" in source
    assert "cancelClearAiSelectedSymbols" in source
    assert "confirmClearAiSelectedSymbols" in source
    assert "confirmingClearAiSymbols" in source
    assert "没有可清空标的" in source
    assert "清空 AI 工作台已选标的前需要确认" in source
    assert "AI 工作台已选标的未修改" in source
    assert "@click=\"clearAiSelectedSymbols\"" not in source
    assert "aiSymbolActionStatusText" in source
    assert "ai-symbol-status" in source
    assert "正在解析筛选条件，并用本地结构化数据执行选股" in source
    assert "apiPost('/symbol-metrics'" in source
    assert "成交额" in source
    assert "成交额源字段为万元" in source
    assert "formatLargeNumberValue(row.volume)" in source
    assert "市值" in source
    assert "换手率" in source
    assert "aiFilteredSymbolRows.value.slice(0, REVIEW_SYMBOL_PICKER_VISIBLE_LIMIT)" not in source
    assert "aiWorkbenchDataSummary" in source
    assert "未选择标的" in source
    assert "confirmingLoadAiWorkbenchSymbols" in source
    assert "aiWorkbenchLoadSourceSymbols" in source
    assert "aiWorkbenchLoadSymbolsDisabledReason" in source
    assert "requestLoadAiWorkbenchSymbols" in source
    assert "cancelLoadAiWorkbenchSymbols" in source
    assert "confirmLoadAiWorkbenchSymbols" in source
    assert "载入标的前需要确认" in source
    assert "AI 工作台当前标的未修改" in source
    assert "@click=\"aiWorkbenchForm.symbols = reviewForm.symbols || symbolsText\"" not in source
    assert "标的上限" not in source
    assert "上下文上限" not in source
    assert "max_symbols" not in source
    assert "max_rows" not in source
    assert "importAiSkillPrompt" in source
    assert "Skill 已导入" in source
    assert "confirmingClearAiSkillPrompt" in source
    assert "aiSkillPromptClearDisabledReason" in source
    assert "requestClearAiSkillPrompt" in source
    assert "cancelClearAiSkillPrompt" in source
    assert "confirmClearAiSkillPrompt" in source
    assert "清空 Skill 提示词前需要确认" in source
    assert "AI 工作台侧载 Skill 提示词未修改" in source
    assert "@click=\"aiWorkbenchForm.skill_prompt = ''\"" not in source
    assert "runAiWorkbench" in source
    assert "apiPostStream('/ai/stock-agent-stream'" in source
    assert "saveSettings('ai')" in source
    assert "aiSettingsSaveFeedback" in source
    assert "AI 设置已保存" in source
    assert "confirmingResetAiPromptSettings" in source
    assert "resetAiPromptSettingsConfirmText" in source
    assert "requestResetAiPromptSettings" in source
    assert "cancelResetAiPromptSettings" in source
    assert "confirmResetAiPromptSettings" in source
    assert "恢复默认提示词前需要确认" in source
    assert "AI 自定义提示词草稿未修改" in source
    assert "@click=\"resetAiPromptSettings\"" not in source
    assert "settingsPathStatusText" in source
    assert "directoryPickerStatusText" in source
    assert "directoryPickDisabledReason" in source
    assert "directoryPickTitle" in source
    assert "confirmingResetSettings" in source
    assert "resetSettingsConfirmText" in source
    assert "requestResetSettings" in source
    assert "cancelResetSettings" in source
    assert "confirmResetSettings" in source
    assert "恢复默认前需要确认" in source
    assert "已保存到浏览器的当前配置会被移除" in source
    assert "@click=\"resetSettings\"" not in source
    assert "overviewRefreshDisabledReason" in source
    assert "正在扫描缓存并更新索引" in source
    assert "confirmingTopbarRefresh" in source
    assert "topbarRefreshConfirmText" in source
    assert "requestTopbarRefresh" in source
    assert "cancelTopbarRefresh" in source
    assert "confirmTopbarRefresh" in source
    assert "确认刷新当前页面" in source
    assert "当前页面未刷新" in source
    assert "页面数据和本地索引未修改" in source
    assert '@click="refreshActiveView"' not in source
    assert "confirmingOverviewRefresh" in source
    assert "overviewRefreshConfirmText" in source
    assert "requestOverviewRefresh" in source
    assert "cancelOverviewRefresh" in source
    assert "confirmOverviewRefresh" in source
    assert "扫描缓存前需要确认" in source
    assert "确认扫描缓存" in source
    assert "缓存未扫描" in source
    assert "SQLite 索引和缓存概览未刷新" in source
    assert "@click=\"loadOverview(true)\"" not in source
    assert "symbolGroupRefreshDisabledReason" in source
    assert "symbolGroupRefreshTitle" in source
    assert "股票、ETF、指数列表正在更新" in source
    assert "pendingSymbolRefreshTarget" in source
    assert "pendingSymbolRefreshConfirmText" in source
    assert "requestSymbolGroupRefresh" in source
    assert "cancelSymbolGroupRefresh" in source
    assert "confirmSymbolGroupRefresh" in source
    assert "更新代码表缓存前需要确认" in source
    assert "代码表未刷新" in source
    assert "股票、ETF、指数列表缓存未修改" in source
    assert "@click=\"refreshShortcutGroup('all')\"" not in source
    assert "allAssetsUpdateDisabledReason" in source
    assert "allAssetsUpdateDisabled" in source
    assert "confirmingAllAssetsUpdate" in source
    assert "应用全资产前需要确认" in source
    assert "symbolCacheRefreshTitle" in source
    assert "settingsActionStatusText" in source
    assert "aiSettingsActionStatusText" in source
    assert "Docker 挂载路径" in source
    assert "文件夹选择只显示当前服务进程可访问的目录" in source
    assert "浏览当前服务可访问" in source
    assert "builtinStockDataSkillPrompt" in source
    assert "ai_price_bars" in source
    assert "内置 stock-data skill" in source
    assert "aiWorkbenchStreamStatus" in source
    assert "aiWorkbenchStatusLabel" in source
    assert "aiWorkbenchRunDisabledReason" in source
    assert "aiWorkbenchRunStatusText" in source
    assert "confirmingRunAiWorkbench" in source
    assert "aiWorkbenchRunConfirmText" in source
    assert "requestRunAiWorkbench" in source
    assert "cancelRunAiWorkbench" in source
    assert "confirmRunAiWorkbench" in source
    assert "发送 AI 任务前需要确认" in source
    assert "确认后将发送" in source
    assert "AI 任务未发送" in source
    assert "模型未调用，本地行情上下文未发送" in source
    assert '@submit.prevent="requestRunAiWorkbench"' in source
    assert '@submit.prevent="runAiWorkbench"' not in source
    assert "请先在系统设置里填写接口 URL、API Key 和模型" in source
    assert "请先在标的池选择或手动输入至少 1 个代码" in source
    assert "ai-composer-status" in source
    assert "parseSseEvent" in source
    assert "aiWorkbenchLatestRows" in source
    assert "aiWorkbenchMarkdownBlocks" in source
    assert "aiWorkbenchChartItems" in source
    assert "K线图" in source
    assert "max_charts: numberOrDefault(aiWorkbenchForm.max_charts, 3)" in source
    assert "review-markdown-code" in source
    assert "markdownTextBlock" in source
    assert ".ai-command-shell" in styles
    assert ".ai-chat-layout" in styles
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in styles
    assert "overflow-y: auto" in styles
    assert ".ai-run-state" in styles
    assert ".ai-workbench-tabs" in styles
    assert ".ai-symbol-table-scroll" in styles
    assert ".ai-symbol-table" in styles
    assert 'aria-label="AI标的池"' in source
    assert "aiSymbolSortAriaLabel" in source
    assert ':aria-label="aiSymbolSortAriaLabel(column)"' in source
    assert "点击后按降序排列" in source
    assert "aiSymbolSelectionLabel(row)" in source
    assert "function aiSymbolSelectionLabel(row: { symbol: string; name?: unknown; assetLabel?: unknown })" in source
    assert 'aria-label="AI 输出结构化表格"' in source
    assert ".ai-symbol-table th button:focus-visible" in styles
    assert ".ai-symbol-status" in styles
    assert ".ai-chat-composer" in styles
    assert ".ai-composer-status" in styles
    assert ".ai-workbench-output" in styles
    assert ".review-markdown-code" in styles
    assert ".save-status" in styles
    assert ".settings-runtime-note" in styles
    assert ".settings-reset-status" in styles
    assert ".skill-file-action input" in styles
    assert ".ai-side-warning" in styles


def test_local_update_script_exists_for_host_side_data_refresh() -> None:
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert UPDATE_SCRIPT.exists()
    assert UPDATE_SCRIPT.stat().st_mode & 0o111
    assert "tdx_downloader.cli prepare-data" in source
    assert "DAILY_CHECK" in source
    assert "POST_CHECK" in source
    assert "tdx_downloader.cli daily-check" in source
    assert "--output json" in source
    assert "daily preflight summary" in source
    assert "preflight_action_count" in source
    assert "Skipping prepare-data: preflight found no fetch or derive work." in source
    assert "prepare summary: skipped" in source
    assert "--fail-on-fetch" in source
    assert "--fail-on-coverage-unknown" in source
    assert "POST_CHECK_STRICT" in source
    assert "POST_CHECK_STRICT:-1" in source
    assert "COMPACT_DELTA" in source
    assert 'COMPACT_DELTA:-0' in source
    assert "COMPACT_DELTA_PARTS" in source
    assert "COMPACT_DELTA_BYTES" in source
    assert "UPDATE_UNIVERSE" in source
    assert "cached-primary" in source
    assert "UPDATE_WINDOW" in source
    assert 'UPDATE_WINDOW:-daily' in source
    assert "UPDATE_WINDOW=$UPDATE_WINDOW; use daily or backfill" in source
    assert "window_mode:" in source
    assert "--symbol-source" in source
    assert "UPDATE_SHARDS" in source
    assert "UPDATE_SHARD_INDEX" in source
    assert "RUN_ALL_SHARDS" in source
    assert "run_update_for_shard" in source
    assert "for ((shard_index = 0; shard_index < UPDATE_SHARDS; shard_index++))" in source
    assert "--symbol-shard-count" in source
    assert "--symbol-shard-index" in source
    assert "SYMBOL_LIMIT" in source
    assert "SYMBOL_OFFSET" in source
    assert "PLAN_FETCH_THRESHOLD" in source
    assert "PLAN_FETCH_THRESHOLD:-6000" in source
    assert "PLAN_MISSING_THRESHOLD" in source
    assert "PLAN_MISSING_THRESHOLD:-400000" in source
    assert "FAIL_ON_LARGE_FETCH_PLAN" in source
    assert "--fail-on-large-fetch-plan" in source
    assert "FAIL_ON_LARGE_MISSING_PLAN" in source
    assert "--fail-on-large-missing-plan" in source
    assert "fetch_missing_rows" in source
    assert "DELTA_SUMMARY_JSON" in source
    assert "REFRESH_COVERAGE" in source
    assert "MAINTAIN_CATALOG" in source
    assert "FORCE_CATALOG_REFRESH" in source
    assert "Worker/delta commits update catalog incrementally" in source
    assert "UPDATE_LOCK" in source
    assert "update-local-data.lock" in source
    assert "Another update-local-data task is running" in source
    assert "Removing stale update lock" in source
    assert "UPDATE_LOG" in source
    assert "logs/update-local-data" in source
    assert "UPDATE_LOG_PATH" in source
    assert "tee -a" in source
    assert "tdx_downloader.cli delta-summary" in source
    assert "--part-threshold" in source
    assert "--byte-threshold" in source
    assert "tdx_downloader.cli delta-compact" in source
    assert "tdx_downloader.cli coverage-refresh" in source
    assert "catalog-maintain" in source
    assert "--asset-types" in source
    assert "cache_snapshot" in source
    assert "refresh_coverage=False" in source
