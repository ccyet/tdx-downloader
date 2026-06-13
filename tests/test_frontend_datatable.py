from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP_VUE = ROOT / "web" / "src" / "App.vue"
DATA_TABLE = ROOT / "web" / "src" / "components" / "DataTable.vue"
PAGINATED_DATA_TABLE = ROOT / "web" / "src" / "components" / "PaginatedDataTable.vue"
STYLES = ROOT / "web" / "src" / "styles.css"


def test_data_table_has_global_expand_sort_and_tone_behaviour() -> None:
    source = DATA_TABLE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "DEFAULT_COMPACT_COLUMN_COUNT" in source
    assert "展开查看" in source
    assert "更多指标" in source
    assert "aria-expanded" in source
    assert "展开查看全部指标列" in source
    assert "收起更多指标列" in source
    assert "visibleColumns" in source
    assert "expanded" in source

    assert "sortState" in source
    assert "toggleSort" in source
    assert "sortedRows" in source
    assert "aria-sort" in source
    assert "升序" in source
    assert "降序" in source

    assert "cellTone" in source
    assert "cell-badge" in source
    for tone in ["tone-positive", "tone-negative", "tone-success", "tone-warning", "tone-danger", "tone-info"]:
        assert tone in source

    assert "columnClass" in source
    assert "columnKind" in source
    assert "`column-${columnKind(column)}`" in source
    assert "return 'number'" in source
    assert "return 'date'" in source
    assert "排名|评分|数量" in source
    assert "日期|时间" in source
    assert ".column-number" in styles
    assert ".column-date" in styles
    assert "font-variant-numeric: tabular-nums" in styles


def test_data_table_sorts_by_clicking_header_without_visible_sort_text() -> None:
    source = DATA_TABLE.read_text(encoding="utf-8")

    assert "return '排序'" not in source
    assert "sortIndicator" in source
    assert "sortAriaLabel" in source
    assert "↓" in source
    assert "↑" in source


def test_data_table_announces_current_table_state() -> None:
    source = DATA_TABLE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "tableStateText" in source
    assert 'aria-live="polite"' in source
    assert ':aria-label="tableLabel"' in source
    assert '<caption class="sr-only">{{ tableStateText }}</caption>' in source
    assert "按${columnLabel(sortState.value.key)}" in source
    assert "当前显示 ${visibleColumns.value.length} / ${props.columns.length} 列" in source
    assert "props.ariaLabel || '数据表'" in source
    assert "props.ariaLabel || props.empty" not in source
    assert ".table-state-note" in styles
    assert ".sr-only" in styles


def test_all_data_table_usages_share_the_component_surface() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert source.count("<DataTable ") >= 10
    assert "expandEtf" not in source
    assert "sortEtf" not in source


def test_all_table_usages_have_specific_accessible_names() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    missing: list[str] = []

    for component in ["DataTable", "PaginatedDataTable"]:
        for match in re.finditer(rf"<{component}\b[\s\S]*?(?:/>|</{component}>)", source):
            block = match.group(0)
            if "aria-label=" in block or ":aria-label=" in block:
                continue
            line = source[: match.start()].count("\n") + 1
            missing.append(f"{component}:{line}")

    assert missing == []


def test_paginated_table_controls_explain_navigation_state() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "type PaginationAction = 'first' | 'prev' | 'next' | 'last'" in source
    assert "function normalizePageNumber" in source
    assert "function paginationActionDisabled" in source
    assert "function paginationActionTitle" in source
    assert "function pageSizeButtonTitle" in source
    assert "已在第一页" in source
    assert "已在最后一页" in source
    assert "aria-live=\"polite\"" in source
    assert "aria-pressed" in source
    assert "pagination-status" in source
    assert ".pagination-status" in styles
    assert "page <= 1" not in source
    assert "page >= planTotalPages" not in source
    assert "page >= cacheTotalPages" not in source


def test_paginated_data_table_controls_are_accessible() -> None:
    source = PAGINATED_DATA_TABLE.read_text(encoding="utf-8")

    assert "type PaginationAction = 'first' | 'prev' | 'next' | 'last'" in source
    assert "paginationActionDisabled" in source
    assert "paginationActionTitle" in source
    assert "pageSizeButtonTitle" in source
    assert ':aria-disabled="paginationActionDisabled(' in source
    assert ':aria-label="paginationActionTitle(' in source
    assert ':title="paginationActionTitle(' in source
    assert "aria-live=\"polite\"" in source
    assert "aria-pressed" in source
    assert "已在第一页" in source
    assert "已在最后一页" in source
    assert "切换为每页" in source
    assert ':aria-label="ariaLabel || empty || \'分页数据表\'"' in source
    assert ":disabled=\"page <=" not in source
    assert ":disabled=\"page >=" not in source


def test_etf_tracking_index_column_is_last() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    match = re.search(r"const etfTrackerColumns = \[(?P<body>.*?)\n\]", source, re.S)
    assert match is not None
    keys = re.findall(r"key: '([^']+)'", match.group("body"))

    assert keys[-1] == "跟踪指数"


def test_cache_view_exposes_indicator_price_table_controls() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "股票数据表" in source
    assert "指标公式" in source
    assert "indicator-chip-row" in source
    assert "loadPriceTable" in source
    assert "confirmingLoadPriceTable" in source
    assert "priceTableLoadConfirmText" in source
    assert "requestLoadPriceTable" in source
    assert "cancelLoadPriceTable" in source
    assert "confirmLoadPriceTable" in source
    assert "读取股票数据表前需要确认" in source
    assert "确认读取股票数据表" in source
    assert "股票数据表未读取" in source
    assert "当前页面表格未刷新" in source
    assert '@submit.prevent="requestLoadPriceTable"' in source
    assert '@submit.prevent="loadPriceTable"' not in source
    assert "confirmingPriceTableCommonIndicators" in source
    assert "priceTableCommonIndicatorsConfirmText" in source
    assert "requestPriceTableCommonIndicators" in source
    assert "cancelPriceTableCommonIndicators" in source
    assert "confirmPriceTableCommonIndicators" in source
    assert "应用常用均线前需要确认" in source
    assert "股票数据表指标列未修改" in source
    assert '@click="priceTableForm.indicators = \'ma5,ma10,ma20\'"' not in source
    assert "importIndicatorFormula" in source
    assert "computeSelectedIndicators" in source
    assert "mapSelectedIndicators" in source
    assert "priceTableActionDisabledReason" in source
    assert "priceTableActionStatusText" in source
    assert "indicatorImportDisabledReason" in source
    assert "indicatorMappingDisabledReason" in source
    assert "indicatorComputeDisabledReason" in source
    assert "indicatorActionStatusText" in source
    assert "confirmingImportIndicatorFormula" in source
    assert "indicatorImportConfirmText" in source
    assert "requestImportIndicatorFormula" in source
    assert "cancelImportIndicatorFormula" in source
    assert "confirmImportIndicatorFormula" in source
    assert "导入公式前需要确认" in source
    assert "公式文本、前缀和映射资产未修改" in source
    assert "confirmingMapSelectedIndicators" in source
    assert "indicatorMappingConfirmText" in source
    assert "requestMapSelectedIndicators" in source
    assert "cancelMapSelectedIndicators" in source
    assert "confirmMapSelectedIndicators" in source
    assert "绑定选中指标前需要确认" in source
    assert "本地指标映射未修改" in source
    assert "confirmingComputeSelectedIndicators" in source
    assert "indicatorComputeConfirmText" in source
    assert "requestComputeSelectedIndicators" in source
    assert "cancelComputeSelectedIndicators" in source
    assert "confirmComputeSelectedIndicators" in source
    assert "计算选中指标前需要确认" in source
    assert "本地指标数据未修改" in source
    assert '@click="mapSelectedIndicators"' not in source
    assert '@click="computeSelectedIndicators"' not in source
    assert '@submit.prevent="importIndicatorFormula"' not in source
    assert "正在读取股票数据表" in source
    assert "填写代码与日期后读取" in source
    assert "/indicators/import-tdx" in source
    assert "/indicators/compute" in source
    assert "/indicators/mappings" in source
    assert "/prices/bars" in source
    assert ".indicator-chip" in styles


def test_download_shortcut_actions_explain_disabled_state() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "symbolGroupRefreshDisabledReason" in source
    assert "symbolGroupRefreshDisabled" in source
    assert "symbolGroupRefreshTitle" in source
    assert "showNotice('info', '代码表正在更新', symbolGroupRefreshDisabledReason.value)" in source
    assert "pendingSymbolRefreshTarget" in source
    assert "pendingSymbolRefreshConfirmText" in source
    assert "requestSymbolGroupRefresh" in source
    assert "cancelSymbolGroupRefresh" in source
    assert "confirmSymbolGroupRefresh" in source
    assert "刷新指数前需要确认" in source
    assert "刷新 ETF 前需要确认" in source
    assert "股票、ETF、指数列表缓存未修改" in source
    assert "@click=\"refreshShortcutGroup('index')\"" not in source
    assert "@click=\"refreshShortcutGroup('etf')\"" not in source
    assert ".symbol-refresh-status" in styles
    assert "pendingDownloadSymbolGroup" in source
    assert "previousDownloadSymbolGroup" in source
    assert "requestApplySymbolGroup" in source
    assert "cancelApplySymbolGroup" in source
    assert "confirmApplySymbolGroup" in source
    assert "downloadSymbolGroupConfirmText" in source
    assert "确认后将用“" in source
    assert "handleDownloadSymbolsInput" in source
    assert '@change="applySymbolGroup"' not in source
    assert 'v-model="selectedGroup"' not in source
    assert '@input="handleDownloadSymbolsInput"' in source
    assert ".symbol-group-confirm-row" in styles
    assert "allAssetsUpdateDisabledReason" in source
    assert "allAssetsUpdateDisabled" in source
    assert "confirmingAllAssetsUpdate" in source
    assert "allAssetsUpdateConfirmText" in source
    assert "requestAllAssetsRecentUpdate" in source
    assert "cancelAllAssetsRecentUpdate" in source
    assert "confirmAllAssetsRecentUpdate" in source
    assert "quick-update-actions" in source
    assert "quick-update-status" in source
    assert ".quick-update-actions" in styles
    assert ".quick-update-status" in styles
    assert "应用全资产前需要确认" in source
    assert "下载任务标的、日期和当前预览计划未修改" in source
    assert "@click=\"applyAllAssetsRecentUpdate\"" not in source
    assert "showNotice('error', '全资产更新不可用', disabledReason)" in source
    assert "coverage_status" in source
    assert "coverage_missing_rows" in source
    assert "coverage_ratio" in source
    cache_columns = source.split("const cacheColumns = [", 1)[1].split("]\nconst resultColumns", 1)[0]
    visible_cache_columns = cache_columns.split("{ key: 'data_kind'", 1)[0]
    assert "{ key: 'coverage_status', label: '窗口覆盖' }" in visible_cache_columns
    assert "{ key: 'coverage_missing_rows', label: '缺失K数' }" in visible_cache_columns
    assert "{ key: 'coverage_ratio', label: '覆盖率' }" in visible_cache_columns
    assert "records: overview.value?.records || []" in source
    assert "function overviewCoverageWindow()" in source
    assert "tradingLookbackStartText(20)" in source
    assert "pendingDownloadTimeframeAction" in source
    assert "downloadTimeframePendingSelection" in source
    assert "downloadTimeframePendingText" in source
    assert "downloadTimeframePendingDisabledReason" in source
    assert "requestDownloadTimeframeAction" in source
    assert "cancelDownloadTimeframeAction" in source
    assert "confirmDownloadTimeframeAction" in source
    assert "选择全周期前需要确认" in source
    assert "恢复默认周期前需要确认" in source
    assert "当前周期选择和预览计划未修改" in source
    assert "并清空当前预览计划" in source
    assert '@click="selectAllDownloadTimeframes"' not in source
    assert '@click="selectDefaultDownloadTimeframe"' not in source
    assert ".timeframe-confirm-status" in styles


def test_start_download_requires_inline_confirmation() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "confirmingPreviewPlan" in source
    assert "previewPlanConfirmText" in source
    assert "requestPreviewPlan" in source
    assert "cancelPreviewPlan" in source
    assert "confirmPreviewPlan" in source
    assert "预览下载计划前需要确认" in source
    assert "确认预览下载计划" in source
    assert "下载计划未预览" in source
    assert "没有请求计划接口，当前预览结果未修改" in source
    assert '@submit.prevent="requestPreviewPlan"' in source
    assert '@submit.prevent="previewPlan"' not in source
    assert "confirmingStartDownload" in source
    assert "requestStartDownload" in source
    assert "cancelStartDownload" in source
    assert "confirmStartDownload" in source
    assert "startDownloadRequestTitle" in source
    assert "startDownloadConfirmTitle" in source
    assert "startDownloadConfirmStatusText" in source
    assert "确认后将提交后台任务并写入本地行情缓存" in source
    assert "没有提交后台任务，本地行情缓存未修改" in source
    assert "@click=\"startDownload\"" not in source
    assert ".download-confirm-status" in styles


def test_task_history_clear_requires_explicit_confirmation() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "confirmingClearTasks" in source
    assert "requestClearTaskHistory" in source
    assert "cancelClearTaskHistory" in source
    assert "confirmClearTaskHistory" in source
    assert "clearTasksConfirmStatusText" in source
    assert "clearTasksConfirmTitle" in source
    assert "clearTasksCancelDisabledReason" in source
    assert "clearTasksConfirmDisabledReason" in source
    assert "showNotice('info', '无法清空任务历史', clearTasksDisabledReason.value)" in source
    assert "showNotice('info', '任务历史未清理', disabledReason)" in source
    assert "不会删除本地行情数据" in source
    assert "确认清空" in source
    assert "将清理当前" in source
    assert '@click="clearTaskHistory"' not in source
    assert ".task-clear-actions" in styles


def test_research_snapshot_delete_requires_inline_confirmation() -> None:
    source = APP_VUE.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "confirmingResearchSnapshotLoadId" in source
    assert "requestLoadResearchSnapshot" in source
    assert "cancelLoadResearchSnapshot" in source
    assert "confirmLoadResearchSnapshot" in source
    assert "载入快照前需要确认" in source
    assert "确认载入快照" in source
    assert "当前研究表单和结果未修改" in source
    assert "覆盖当前研究表单和结果" in source
    assert "@click=\"loadResearchSnapshot(snapshot)\"" not in source
    assert "confirmingResearchSnapshotDeleteId" in source
    assert "requestDeleteResearchSnapshot" in source
    assert "cancelDeleteResearchSnapshot" in source
    assert "confirmDeleteResearchSnapshot" in source
    assert "删除快照前需要确认" in source
    assert "请先确认或取消删除" in source
    assert "确认删除快照" in source
    assert "再次点击该行的“删除”才会移除本地研究快照" in source
    assert "@click=\"deleteResearchSnapshot(snapshot.id)\"" not in source
    assert ".side-snapshot-row.confirming" in styles
    assert ".side-snapshot-confirm" in styles


def test_research_snapshot_save_rejects_stale_results() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "historyResultSignature" in source
    assert "crossResultSignature" in source
    assert "reviewResultSignature" in source
    assert "regimeResultSignature" in source
    assert "etfTrackerResultSignature" in source
    assert "historySearchSignature" in source
    assert "crossSearchSignature" in source
    assert "reviewSearchSignature" in source
    assert "regimeSearchSignature" in source
    assert "etfTrackerSearchSignature" in source
    assert "researchResultStaleReason" in source
    assert "const staleReason = researchResultStaleReason(tab)" in source
    assert "历史相似参数已变更，请重新搜索后再保存快照。" in source
    assert "横截面参数已变更，请重新搜索后再保存快照。" in source
    assert "多股复盘参数已变更，请重新生成后再保存快照。" in source
    assert "ETF 趋势参数已变更，请重新生成后再保存快照。" in source
    assert "市场风偏参数已变更，请重新运行后再保存快照。" in source
    assert "historyResultSignature.value = historySearchSignature()" in source
    assert "crossResultSignature.value = crossSearchSignature()" in source
    assert "regimeResultSignature.value = regimeSearchSignature()" in source
