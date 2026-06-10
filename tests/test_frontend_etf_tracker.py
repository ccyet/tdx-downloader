from __future__ import annotations

from pathlib import Path
import re


APP_VUE = Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue"


def test_research_tools_include_etf_tracker_tab() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "type ResearchTabKey = 'history' | 'cross' | 'review' | 'etf'" in source
    assert "{ key: 'etf', label: '场内ETF跟踪', icon: 'archive' }" in source
    assert "activeResearchTab === 'etf'" in source


def test_etf_tracker_filters_by_type_category_and_tracking_index() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "etfTrackerForm.type" in source
    assert "etfTrackerForm.category" in source
    assert "ETF_TRACKER_CATEGORY_OPTIONS" in source
    assert "行业指数类" in source
    assert "主题类" in source
    assert "宽基类" in source
    assert "债类" in source
    assert "其他类" in source
    assert "股票型" in source
    assert "其他型" in source
    assert "etfTrackerForm.tracking_index" in source
    assert "filteredEtfTrackerRows" in source
    assert "etfTrackingIndexLabel" in source
    assert "etfFundType" in source


def test_etf_tracker_reuses_multi_review_pipeline() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "async function runEtfTrackerReview" in source
    assert "await apiPost('/research/review'" in source
    assert "reviewResult.value = await apiPost('/research/review'" in source
    assert "reviewForm.symbols = selected.join('\\n')" in source
    assert "ETF趋势对比" in source


def test_etf_tracker_loads_tdx_tracking_api_metadata() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const etfTrackingRows = ref<Array<Record<string, any>>>([])" in source
    assert "async function loadEtfTracking" in source
    assert "apiGet(`/etf-tracking?${params.toString()}`)" in source
    assert "etfTrackingMetaBySymbol" in source
    assert "刷新TDX ETF接口" in source
    assert "loadSymbolGroups(true, 'etf')" in source
    assert "'数据来源': row.source" in source
    assert "'IOPV': formatDecimalValue(row.iopv, 3)" in source


def test_etf_tracker_displays_return_windows_and_merge_option() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const etfReturnRows = ref<Array<Record<string, any>>>([])" in source
    assert "async function loadEtfReturns" in source
    assert "apiPost('/etf-returns'" in source
    assert "etfTrackerForm.merge_similar" in source
    assert "合并同类ETF" in source
    assert "mergeSimilarEtfRows" in source
    assert "largestAmountEtfRow" in source
    for label in ["当日", "近5日", "近20日", "近50日", "YTD", "成交额"]:
        assert label in source
    for field in ["return_1d", "return_5d", "return_20d", "return_50d", "return_ytd", "amount"]:
        assert field in source


def test_etf_tracker_uses_persistent_client_cache_and_status_surface() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "ETF_TRACKING_CACHE_STORAGE_KEY" in source
    assert "ETF_RETURNS_CACHE_STORAGE_KEY" in source
    assert "restoreEtfClientCache" in source
    assert "writeEtfClientCache" in source
    assert "clearEtfClientCache" in source
    assert "function etfApiCacheSource" in source
    assert "cache?.scope === 'disk'" in source
    assert "磁盘缓存" in source
    assert "etfCacheStatusCards" in source
    assert "loadEtfTracking(false, { preferCache: true })" in source
    assert "loadEtfReturns(false, { preferCache: true })" in source
    assert "缓存状态" in source


def test_etf_tracker_has_professional_workbench_sections() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "etf-control-surface" in source
    assert "etf-cache-strip" in source
    assert "etf-result-surface" in source
    assert "etf-insight-panel" in source
    assert "etf-soft-band" in source


def test_etf_tracker_candidate_pool_is_full_width_and_paginated() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "ETF_TRACKER_PAGE_SIZE_OPTIONS" in source
    assert "const etfTrackerPagination = reactive" in source
    assert "const etfTrackerTotalPages = computed" in source
    assert "const pagedEtfTrackerRows = computed" in source
    assert "pagedEtfTrackerRows.value.map" in source
    assert "setEtfTrackerPageSize" in source
    assert "goEtfTrackerPage" in source
    assert "etf-candidate-row" in source
    assert "etf-candidate-wide-panel" in source
    assert '<section class="content-grid two etf-tracker-grid etf-result-surface">\n              <Panel class="etf-candidate-panel"' not in source


def test_overview_records_are_lazy_loaded_for_cache_view() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "loadOverview(false, { includeRecords: false })" in source
    assert "include_records: String(includeRecords)" in source
    assert "view === 'cache' && !overviewRecordsLoaded.value" in source


def test_etf_tracker_uses_indexed_cache_lookup() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const cacheRecordsBySymbol = computed" in source
    assert "const cacheSymbolsByAssetType = computed" in source

    record_lookup = re.search(
        r"function cacheRecordForSymbol\(symbol: string, timeframe: string\) \{(?P<body>.*?)\n\}",
        source,
        re.S,
    )
    assert record_lookup is not None
    assert "cacheRecordsBySymbol.value.get" in record_lookup.group("body")
    assert "cacheRows.value.filter" not in record_lookup.group("body")

    symbol_lookup = re.search(
        r"function cacheSymbolsForAssetType\(type: AssetShortcutType\) \{(?P<body>.*?)\n\}",
        source,
        re.S,
    )
    assert symbol_lookup is not None
    assert "cacheSymbolsByAssetType.value.get(type)" in symbol_lookup.group("body")
    assert "cacheRows.value" not in symbol_lookup.group("body")


def test_etf_tracker_loads_full_cache_records_for_universe() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    ensure_loader = re.search(
        r"function ensureEtfTrackingLoaded\(\) \{(?P<body>.*?)\n\}",
        source,
        re.S,
    )
    assert ensure_loader is not None
    body = ensure_loader.group("body")
    assert "overviewRecordsLoaded.value" in body
    assert "loadOverview(false, { includeRecords: true })" in body
    assert "etfTrackingRows.value.length && !etfReturnRows.value.length" in body
    assert "loadEtfReturns(false, { preferCache: true })" in source


def test_review_symbol_picker_has_category_filters_and_bounded_rendering() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const REVIEW_SYMBOL_PICKER_VISIBLE_LIMIT" in source
    assert "reviewSymbolPickerCategory" in source
    assert "reviewSymbolPickerCategoryOptions" in source
    assert "reviewSymbolPickerVisibleRows" in source
    assert 'v-model="reviewSymbolPickerCategory"' in source
    assert 'v-for="row in reviewSymbolPickerVisibleRows"' in source


def test_review_symbol_picker_categories_cover_etf_and_sector_taxonomy() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    for label in [
        "股票型ETF",
        "债券/货币ETF",
        "商品/跨境/REIT",
        "LOF/其他基金",
        "行业一级",
        "行业二级",
        "通达信特色",
        "债券/基金",
        "昨日涨停",
    ]:
        assert label in source
    assert "defaultReviewSymbolCategory" in source
    assert "reviewSymbolCategory" in source


def test_symbol_group_refresh_merges_tdx_names_for_picker_classification() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "config.value.symbol_names = {" in source
    assert "...(config.value.symbol_names || {})" in source
    assert "...(data.symbol_names || {})" in source


def test_symbol_group_refresh_uses_persistent_metadata_refresh_endpoint() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "symbolMetadataCacheLabel" in source
    assert "apiPost('/symbol-metadata/refresh'" in source
    assert "更新代码表缓存" in source


def test_etf_category_handles_bond_money_code_ranges_when_name_is_generic() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "code.startsWith('511')" in source
    assert "code.startsWith('551')" in source
    assert "return 'bond_money_etf'" in source


def test_etf_category_handles_cross_border_code_ranges_and_labels() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "code.startsWith('513')" in source
    assert "香港" in source
    assert "美股" in source
    assert "return 'commodity_cross_reit'" in source


def test_sector_category_defaults_unknown_880_codes_to_tdx_special() -> None:
    source = APP_VUE.read_text(encoding="utf-8")

    assert "const TDX_LEVEL_ONE_INDUSTRY_NAMES = new Set" in source
    assert "'电力'" in source
    assert "'化工原料'" not in source
    sector_category = re.search(
        r"function sectorReviewCategory\(symbol: string, name: string, assetType = ''\) \{(?P<body>.*?)\n\}",
        source,
        re.S,
    )
    assert sector_category is not None
    body = sector_category.group("body")
    assert "TDX_LEVEL_ONE_INDUSTRY_NAMES.has(cleanedName)" in body
    assert "return 'industry_l1'" in body
    assert "return 'industry_l2'" in body
    assert body.rstrip().endswith("return 'tdx_special'")
