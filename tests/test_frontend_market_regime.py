from __future__ import annotations

from pathlib import Path


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"
STYLES = APP_VUE.parent / "styles.css"


def test_market_regime_research_tab_is_wired_to_api_snapshot_and_export() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "'regime'" in source
    assert "市场风险偏好" in source
    assert "Market Regime Research" in source
    assert "regimeForm" in source
    assert "runMarketRegimeResearch" in source
    assert "apiPost('/research/market-regime'" in source
    assert "universe_groups" in source
    assert "tdx_path: settings.tdx_path" in source
    assert "regimeUniverseOptions" in source
    assert "activeRegimeUniverseGroups" in source
    assert "高级参数" in source
    assert "REGIME_ADVANCED_PARAMETERS" in source
    assert "hint-popover-trigger" in source
    assert "现金压力分" in source
    assert "时间线交易日数" in source
    assert "liquidity_high_percentile" in source
    assert "volatility_high_percentile" in source
    assert "high_position_drawdown_threshold" in source
    assert "benchmark_rally_60_threshold" in source
    assert "benchmark_pullback_20_threshold" in source
    assert "percentOrDefault(regimeForm.benchmark_rally_60_threshold, 8)" in source
    assert "percent-input" in source
    assert "参数预设" in source
    assert "REGIME_PARAMETER_PRESETS" in source
    assert "pendingRegimePresetKey" in source
    assert "regimePresetConfirmText" in source
    assert "requestRegimeParameterPreset" in source
    assert "cancelRegimeParameterPreset" in source
    assert "confirmRegimeParameterPreset" in source
    assert "应用参数预设前需要确认" in source
    assert ':aria-pressed="regimeActivePresetKey === preset.key"' in source
    assert "确认后将用“" in source
    assert "当前高级参数未修改" in source
    assert "@click=\"applyRegimeParameterPreset(preset.key)\"" not in source
    assert ".regime-preset-confirm" in styles
    assert ".regime-preset-button.pending" in styles
    assert "百分比直接填" in source
    assert "percentOrDefault(regimeForm.stress_return_5d_threshold, 0)" in source
    assert "stress_ma20_break_threshold" in source
    assert "high_liquidity_selloff_threshold" in source
    assert "concentration_top_n" in source
    assert "daily_report_days" in source
    assert "flow_candidate_limit" in source
    assert "risk_timeline_days" in source
    assert "regimeResult" in source
    assert "downloadMarketRegimeJson" in source
    assert "confirmingRunRegimeResearch" in source
    assert "regimeResearchConfirmText" in source
    assert "requestRunMarketRegimeResearch" in source
    assert "cancelRunMarketRegimeResearch" in source
    assert "confirmRunMarketRegimeResearch" in source
    assert "运行市场风险偏好研究前需要确认" in source
    assert "确认后将按" in source
    assert "市场风偏研究未运行" in source
    assert "当前市场风险偏好结果未修改" in source
    assert '@submit.prevent="requestRunMarketRegimeResearch"' in source
    assert '@submit.prevent="runMarketRegimeResearch"' not in source
    assert "saveActiveResearchSnapshot" in source
    assert "activeResearchSnapshotDisabledReason" in source
    assert "activeResearchSnapshotDisabled" in source
    assert '保存当前工作台结果到本机快照' in source
    assert "resultActionDisabledReason" in source
    assert "regimeExportDisabledReason" in source
    assert "先运行市场风险偏好研究，生成结果后才能导出 JSON" in source
    assert "confirmingRegimeExport" in source
    assert "regimeExportFilename" in source
    assert "regimeExportConfirmText" in source
    assert "requestMarketRegimeJsonExport" in source
    assert "cancelMarketRegimeJsonExport" in source
    assert "confirmMarketRegimeJsonExport" in source
    assert "导出当前市场风险偏好研究 JSON 前需要确认" in source
    assert "确认导出市场风偏 JSON" in source
    assert "市场风偏 JSON 未导出" in source
    assert "市场风偏 JSON 已导出" in source
    assert "@click=\"downloadMarketRegimeJson\"" not in source
    assert "@click=\"requestMarketRegimeJsonExport\"" in source
    assert "regimeManualSymbols" in source
    assert "regimeManualSymbolsClearDisabledReason" in source
    assert "confirmingClearRegimeManualSymbols" in source
    assert "requestClearRegimeManualSymbols" in source
    assert "cancelClearRegimeManualSymbols" in source
    assert "confirmClearRegimeManualSymbols" in source
    assert "清空手动补充标的前需要确认" in source
    assert "市场风偏手动补充标的未修改" in source
    assert "@click=\"regimeForm.symbols = ''\"" not in source
    assert ".regime-universe-summary" in styles
    assert "Risk Appetite Index" in source


def test_market_regime_view_exposes_decoupled_result_surfaces() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    for token in [
        "regimeSummaryCards",
        "regimeDailyReportCards",
        "regimeAnswerCards",
        "regimeSectionTabs",
        "activeRegimeSectionTab",
        "regimeRaiChartPoints",
        "regimeRaiLinePoints",
        "regimeRaiWindowStart",
        "regimeRaiWindowLabel",
        "activeRegimeRaiPoint",
        "regimeRaiDrivers",
        "regimeRiskHeatmapRows",
        "regimeRiskTimelineDates",
        "regimeRiskTimelineDateHeaders",
        "displayRegimeDailyEvidenceCards",
        "displayRegimeDailyHistoryRows",
        "displayRegimeComponentRows",
        "displayRegimeFlowCandidateRows",
        "pagedRegimeFlowCandidateRows",
        "regimeFlowCandidatePagination",
        "regimeFlowCandidateTotalPages",
        "displayRegimeBenchmarkRows",
        "displayRegimeAdjustmentFactorAdvantageRows",
        "displayRegimeAdjustmentFactorRows",
        "displayRegimeFactorAdvantageRows",
        "displayRegimeFactorRows",
        "displayRegimeMigrationRows",
        "displayRegimeSequenceRows",
        "displayRegimeHighLiquidityBreakRows",
        "displayRegimeMarketScopeRows",
        "pagedRegimeMarketScopeRows",
        "regimeMarketScopePagination",
        "regimeMarketScopeTotalPages",
        "displayRegimeAssetRows",
        "regimeFactorColumns",
        "regimeMigrationColumns",
        "regimeSequenceColumns",
        "regimeHighLiquidityBreakColumns",
        "regimeDailyHistoryColumns",
        "regimeComponentColumns",
        "regimeFlowCandidateColumns",
        "regimeBenchmarkColumns",
        "regimeFactorAdvantageColumns",
        "regimeMarketScopeColumns",
        "regimeAssetColumns",
    ]:
        assert token in source

    assert "每日市场状态报告" in source
    assert "regime-summary-grid" in source
    assert "市场风险偏好摘要" in source
    assert "dashboard-strip regime-summary-strip" not in source
    assert "regime-evidence-grid" in source
    assert "regime-evidence-card" in source
    assert "dailyEvidenceDetail" in source
    assert "dailyEvidenceTone" in source
    assert "核心结论" in source
    assert "因子优势" in source
    assert "RAI 趋势" in source
    assert "RAI 0-100" in source
    assert "'当日收益': formatPercentValue(row.return_1d)" in source
    assert "{ key: '当日收益', label: '当日收益' }" in source
    assert "拖动时间轴" in source
    assert "onRegimeRaiWindowInput" in source
    assert "越低代表现金偏好与风险释放越强" in source
    assert "setActiveRegimeRaiPoint(point)" in source
    assert "@pointerenter=\"setActiveRegimeRaiPoint(point)\"" in source
    assert ':aria-label="point.title"' in source
    assert ':aria-pressed="activeRegimeRaiPoint?.key === point.key"' in source
    assert ":r=\"activeRegimeRaiPoint?.key === point.key ? 3.1 : 1.8\"" in source
    assert "regime-rai-active-card" in source
    assert "regime-rai-driver-list" in source
    assert "RAI驱动指标" in source
    assert "站上MA20资产占比，低于35%偏弱" in source
    assert "越高越偏" not in source
    assert "风险偏好扩张" in source
    assert "收缩/释放" in source
    assert "风险释放路径图" in source
    assert "谁先承压，压力是否向后扩散" in source
    assert "压力强度图例" in source
    assert "regimeRiskReleaseSummary" in source
    assert "regimeRiskReleaseNarrative" in source
    assert "latestRegimeRiskTriggerLayers" in source
    assert "riskHeatmapStatusLabel" in source
    assert "heatmapScoreLabel" in source
    assert "regime-heatmap-frame" in source
    assert "regime-heatmap-axis" in source
    assert "regimeHeatmapAxisStyle" in source
    assert "regimeHeatmapRowTemplate" in source
    assert 'gridTemplateColumns: `repeat(${Math.max(1, regimeRiskTimelineDates.value.length)}, 56px)`' in source
    assert "index % 5 === 0" in source
    assert "uniqueStringsInOrder(regimeRiskTimelineRows.value.map((row: Record<string, any>) => row.date)).sort()" in source
    assert "regime-heatmap-date', { muted: !item.show }" in source
    assert "最近日报序列" in source
    assert "RAI 组成拆解" in source
    assert "PaginatedDataTable" in source
    assert ":rows=\"displayRegimeDailyHistoryRows\"" in source
    assert ":rows=\"displayRegimeComponentRows\"" in source
    assert ":rows=\"displayRegimeAssetRows\"" in source
    assert "资金回流候选" in source
    assert "'名称': displaySymbolName(row.stock_code)" in source
    assert "REGIME_FLOW_CANDIDATE_PAGE_SIZE_OPTIONS = [10, 20, 30]" in source
    assert "setRegimeFlowCandidatePageSize" in source
    assert "goRegimeFlowCandidatePage" in source
    assert "DataTable :rows=\"pagedRegimeFlowCandidateRows\"" in source
    assert "基准调整阶段" in source
    assert "调整阶段因子优势" in source
    assert "调整阶段回测明细" in source
    assert "研究宇宙" in source
    assert "回调充分 + 转强" in source
    assert "波动率 × 流动性" in source
    assert "资金迁移" in source
    assert "风险释放顺序" in source
    assert "高流动性补跌" in source
    assert "市场缩圈" in source
    assert "REGIME_MARKET_SCOPE_PAGE_SIZE_OPTIONS = [10, 15, 30]" in source
    assert "DataTable :rows=\"pagedRegimeMarketScopeRows\"" in source
    assert "setRegimeMarketScopePageSize" in source
    assert "goRegimeMarketScopePage" in source
    assert "资产池" in source
