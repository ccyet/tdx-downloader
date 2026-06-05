<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="brand-row">
        <div class="brand-mark">TDX</div>
        <div v-if="!sidebarCollapsed" class="brand-text">
          <strong>TDX Downloader</strong>
          <span>行情数据工作台</span>
        </div>
      </div>

      <nav class="nav-list">
        <button
          v-for="item in navItems"
          :key="item.key"
          :class="['nav-button', { active: activeView === item.key }]"
          :aria-label="item.label"
          :title="item.label"
          @click="activeView = item.key"
        >
          <Icon :name="item.icon" />
          <span v-if="!sidebarCollapsed">{{ item.label }}</span>
        </button>
      </nav>

      <div v-if="activeView === 'research' && !sidebarCollapsed" class="sidebar-secondary">
        <details class="side-accordion" open>
          <summary>
            <span>研究参数</span>
            <em>{{ researchTimeframe }} · {{ settings.adjust || '不复权' }}</em>
          </summary>
          <div class="side-fields">
            <label>
              <span>周期</span>
              <select v-model="researchTimeframe">
                <option v-for="timeframe in config?.timeframes || []" :key="timeframe" :value="timeframe">
                  {{ timeframe }}
                </option>
              </select>
            </label>
            <label>
              <span>复权</span>
              <select v-model="settings.adjust">
                <option value="qfq">qfq</option>
                <option value="hfq">hfq</option>
                <option value="">不复权</option>
              </select>
            </label>
            <label>
              <span>行情根目录</span>
              <input v-model="settings.data_root" type="text" />
            </label>
          </div>
        </details>

        <details class="side-accordion">
          <summary>
            <span>研究快照</span>
            <em>{{ activeResearchSnapshots.length }} 个</em>
          </summary>
          <div class="side-snapshot-tools">
            <button class="btn secondary" type="button" :disabled="!activeResearchResult" @click="saveActiveResearchSnapshot">
              <Icon name="save" />
              保存当前结果
            </button>
          </div>
          <div v-if="activeResearchSnapshots.length" class="side-snapshot-list">
            <article v-for="snapshot in activeResearchSnapshots" :key="snapshot.id" class="side-snapshot-row">
              <button type="button" @click="loadResearchSnapshot(snapshot)">
                <strong>{{ snapshot.title }}</strong>
                <span>{{ snapshot.summary }}</span>
              </button>
              <button class="icon-button danger" type="button" title="删除快照" @click="deleteResearchSnapshot(snapshot.id)">
                <Icon name="trash" />
              </button>
            </article>
          </div>
          <p v-else class="side-empty">暂无当前模块快照。</p>
        </details>
      </div>

      <div class="sidebar-footer">
        <button class="nav-button" @click="sidebarCollapsed = !sidebarCollapsed">
          <Icon :name="sidebarCollapsed ? 'expand' : 'collapse'" />
          <span v-if="!sidebarCollapsed">收起侧栏</span>
        </button>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <div>
          <h1>{{ activeMeta.title }}</h1>
          <p>{{ activeMeta.description }}</p>
        </div>
        <div class="topbar-actions">
          <span class="runtime-pill">{{ runtimeLabel }}</span>
          <span class="path-pill" :title="settings.data_root">{{ compactPath(settings.data_root) }}</span>
          <button
            class="icon-button"
            :disabled="topbarRefreshing"
            :title="topbarRefreshTitle"
            :aria-label="topbarRefreshTitle"
            @click="refreshActiveView"
          >
            <Icon name="refresh" />
          </button>
          <div class="avatar">TD</div>
        </div>
      </header>

      <main>
        <div v-if="notice" :class="['notice-bar', notice.type]">
          <strong>{{ notice.title }}</strong>
          <span>{{ notice.body }}</span>
          <button @click="notice = null">关闭</button>
        </div>

        <section v-if="activeView === 'dashboard'" class="view-stack">
          <div class="toolbar-row">
            <button class="btn primary" :disabled="loadingOverview" @click="loadOverview(true)">
              <Icon name="database" />
              扫描缓存
            </button>
            <button class="btn secondary" @click="activeView = 'download'">
              <Icon name="download" />
              新建下载
            </button>
            <span v-if="overview && !overview.catalog_exists" class="hint-text">还没有 SQLite 索引，先扫描缓存。</span>
          </div>

          <section class="dashboard-strip">
            <div v-for="item in dashboardKeyStats" :key="item.label" class="dashboard-stat">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <em>{{ item.detail }}</em>
            </div>
          </section>

          <div class="asset-overview-grid">
            <article
              v-for="asset in assetOverviewCards"
              :key="asset.value"
              :class="['asset-summary-card', asset.tone]"
            >
              <div class="asset-card-head">
                <div class="asset-icon"><Icon :name="asset.icon" /></div>
                <div>
                  <span>缓存资产</span>
                  <strong>{{ asset.label }}</strong>
                </div>
                <em>{{ formatInt(asset.coveredTimeframeCount) }} / {{ formatInt(asset.totalTimeframeCount) }} 周期</em>
              </div>
              <div class="asset-main-metric">
                <strong>{{ formatInt(asset.symbolCount) }}</strong>
                <span>{{ formatInt(asset.cachedPeriodItems) }} / {{ formatInt(asset.totalPeriodItems) }} 周期项可用</span>
              </div>
              <div class="timeframe-strip">
                <div
                  v-for="period in asset.periods"
                  :key="period.timeframe"
                  :class="['timeframe-chip', { active: period.cachedCount > 0 }]"
                >
                  <span>{{ period.timeframe }}</span>
                  <strong>{{ formatInt(period.cachedCount) }} / {{ formatInt(period.totalCount) }}</strong>
                </div>
              </div>
            </article>
          </div>

          <Panel title="最近执行" subtitle="任务">
            <div v-if="latestTask" class="recent-task-card compact">
              <strong>{{ latestTask.status }}</strong>
              <span>{{ latestTask.id }}</span>
              <em>{{ latestTask.error || latestTask.finished_at || latestTask.started_at || latestTask.created_at }}</em>
            </div>
            <EmptyState v-else title="暂无任务" body="执行下载后这里展示最近一次任务状态。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'download'" class="content-grid form-grid">
          <Panel title="下载参数" subtitle="任务配置">
            <form class="task-form" @submit.prevent="previewPlan">
              <label class="span-full symbol-source-field">
                <div class="field-head">
                  <span>代码来源</span>
                  <div class="field-actions">
                    <button
                      class="mini-action"
                      type="button"
                      :disabled="loadingSymbolGroups"
                      @click="refreshShortcutGroup('index')"
                    >
                      <Icon name="refresh" />
                      {{ refreshingSymbolGroup === 'index' ? '刷新中' : '刷新指数' }}
                    </button>
                    <button
                      class="mini-action"
                      type="button"
                      :disabled="loadingSymbolGroups"
                      @click="refreshShortcutGroup('etf')"
                    >
                      <Icon name="refresh" />
                      {{ refreshingSymbolGroup === 'etf' ? '刷新中' : '刷新ETF' }}
                    </button>
                  </div>
                </div>
                <select v-model="selectedGroup" :disabled="loadingSymbolGroups" @change="applySymbolGroup">
                  <option value="custom">自定义</option>
                  <option v-for="group in config?.symbol_groups || []" :key="group.name" :value="group.name">
                    {{ group.name }} · {{ group.symbols.length }}只
                  </option>
                </select>
              </label>

              <div class="quick-update span-full">
                <div>
                  <strong>全资产更新</strong>
                  <span>按当前代码库合并股票、ETF、指数和板块，生成近 N 日任务。</span>
                </div>
                <label>
                  <span>近 N 日</span>
                  <input v-model.number="allAssetsLookbackDays" type="number" min="1" step="1" />
                </label>
                <button
                  class="btn secondary"
                  type="button"
                  :disabled="!allAssetSymbols.length"
                  @click="applyAllAssetsRecentUpdate"
                >
                  <Icon name="refresh" />
                  应用全资产
                </button>
              </div>

              <label>
                <span>周期</span>
                <select v-model="selectedTimeframe">
                  <option v-for="timeframe in config?.timeframes || []" :key="timeframe" :value="timeframe">
                    {{ timeframe }}
                  </option>
                </select>
              </label>

              <label class="span-full">
                <span>标的代码</span>
                <textarea v-model="symbolsText" rows="5" placeholder="000001.SZ, 600519.SH"></textarea>
              </label>

              <div class="inline-fields span-full">
                <label>
                  <span>开始</span>
                  <input v-model="settings.start" type="date" />
                </label>
                <label>
                  <span>结束</span>
                  <input v-model="settings.end" type="date" />
                </label>
              </div>
              <div class="date-shortcuts span-full" aria-label="日期快捷选项">
                <span>快捷</span>
                <button
                  v-for="shortcut in DATE_RANGE_SHORTCUTS"
                  :key="shortcut.key"
                  type="button"
                  :class="['date-shortcut', { active: isDateShortcutActive(settings, shortcut.key) }]"
                  @click="applyDateShortcut(settings, shortcut.key)"
                >
                  {{ shortcut.label }}
                </button>
              </div>

              <label>
                <span>执行方式</span>
                <select v-model="settings.mode">
                  <option value="smart">智能补齐</option>
                  <option value="force">强制刷新</option>
                </select>
              </label>

              <label>
                <span>批次大小</span>
                <input v-model.number="settings.batch_size" type="number" min="1" />
              </label>

              <label class="check-row span-full">
                <input v-model="settings.strict_after_update" type="checkbox" />
                <span>补齐后严格校验</span>
              </label>

              <label class="span-full">
                <span>行情根目录</span>
                <div class="path-control">
                  <input v-model="settings.data_root" type="text" />
                  <button class="btn secondary" type="button" :disabled="pickingDirectory !== ''" @click="pickDirectory('data_root')">
                    <Icon name="folder" />
                    {{ pickingDirectory === 'data_root' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>

              <label class="span-full">
                <span>TDX PYPlugins/user</span>
                <div class="path-control">
                  <input v-model="settings.tdx_path" type="text" />
                  <button class="btn secondary" type="button" :disabled="pickingDirectory !== ''" @click="pickDirectory('tdx_path')">
                    <Icon name="folder" />
                    {{ pickingDirectory === 'tdx_path' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>

              <div class="form-actions span-full">
                <button class="btn secondary" type="submit" :disabled="planning">
                  <Icon name="clipboard" />
                  预览计划
                </button>
                <button class="btn danger" type="button" :disabled="downloading" @click="startDownload">
                  <Icon name="download" />
                  执行下载
                </button>
              </div>
            </form>
          </Panel>

          <div class="view-stack">
            <Panel title="当前任务" subtitle="计划摘要">
              <div class="mini-grid">
                <MetricCard title="标的" :value="String(parsedSymbols.length)" detail="已解析" tone="blue" icon="key" />
                <MetricCard title="周期" :value="selectedTimeframe" detail="当前选择" tone="green" icon="clock" />
                <MetricCard title="待下载" :value="formatInt(planSummary.fetch_count)" detail="来自预览" tone="red" icon="download" />
                <MetricCard title="已可用" :value="formatInt(planSummary.cached_count)" detail="无需下载" tone="amber" icon="database" />
              </div>
            </Panel>

            <Panel title="下载计划" subtitle="最多显示 500 行">
              <DataTable :rows="displayPlanRows" :columns="planColumns" empty="点击“预览计划”后显示。" />
            </Panel>
          </div>
        </section>

        <section v-else-if="activeView === 'cache'" class="view-stack">
          <Panel title="本地缓存" subtitle="SQLite catalog">
            <div class="filter-row">
              <label>
                <span>筛选</span>
                <input v-model="cacheFilters.keyword" type="search" placeholder="代码或名称" />
              </label>
              <label>
                <span>资产</span>
                <select v-model="cacheFilters.assetType">
                  <option value="">全部资产</option>
                  <option v-for="item in uniqueAssetTypes" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>
              <label>
                <span>周期</span>
                <select v-model="cacheFilters.timeframe">
                  <option value="">全部周期</option>
                  <option v-for="item in uniqueCacheTimeframes" :key="item" :value="item">{{ item }}</option>
                </select>
              </label>
              <label>
                <span>状态</span>
                <select v-model="cacheFilters.status">
                  <option value="">全部状态</option>
                  <option v-for="item in uniqueCacheStatuses" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>
            </div>
            <div class="table-toolbar">
              <p class="table-caption">
                显示 {{ cachePageFirst }}-{{ cachePageEnd }} / 筛选 {{ filteredCacheRows.length }} / 总 {{ cacheRows.length }} 条
              </p>
              <div class="table-controls">
                <div class="page-size-group" aria-label="每页条数">
                  <span>每页</span>
                  <button
                    v-for="size in cachePageSizeOptions"
                    :key="size"
                    type="button"
                    :class="['page-size-button', { active: cachePagination.pageSize === size }]"
                    @click="setCachePageSize(size)"
                  >
                    {{ size }}
                  </button>
                </div>
                <div class="pagination-controls">
                  <button type="button" :disabled="cachePagination.page <= 1" @click="goCachePage(1)">首页</button>
                  <button type="button" :disabled="cachePagination.page <= 1" @click="goCachePage(cachePagination.page - 1)">上一页</button>
                  <span>{{ cachePagination.page }} / {{ cacheTotalPages }}</span>
                  <button
                    type="button"
                    :disabled="cachePagination.page >= cacheTotalPages"
                    @click="goCachePage(cachePagination.page + 1)"
                  >
                    下一页
                  </button>
                  <button
                    type="button"
                    :disabled="cachePagination.page >= cacheTotalPages"
                    @click="goCachePage(cacheTotalPages)"
                  >
                    末页
                  </button>
                </div>
              </div>
            </div>
            <DataTable :rows="displayCacheRows" :columns="cacheColumns" empty="暂无匹配缓存记录。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'research'" class="view-stack">
          <div class="research-tabs">
            <button
              v-for="tab in researchTabs"
              :key="tab.key"
              :class="['research-tab', { active: activeResearchTab === tab.key }]"
              @click="activeResearchTab = tab.key"
            >
              <Icon :name="tab.icon" />
              <span>{{ tab.label }}</span>
            </button>
          </div>

          <section v-if="activeResearchTab === 'history'" class="content-grid two">
            <Panel title="历史时序相似" subtitle="单标的">
              <form class="task-form" @submit.prevent="runHistorySearch">
                <label>
                  <span>标的代码</span>
                  <input v-model="historyForm.symbol" type="text" />
                </label>
                <div class="inline-fields span-full">
                  <label>
                    <span>开始日期</span>
                    <input v-model="historyForm.window_start" type="date" />
                  </label>
                  <label>
                    <span>截至日期</span>
                    <input v-model="historyForm.as_of" type="date" />
                  </label>
                </div>
                <div class="date-shortcuts span-full" aria-label="历史相似日期快捷选项">
                  <span>快捷</span>
                  <button
                    v-for="shortcut in DATE_RANGE_SHORTCUTS"
                    :key="shortcut.key"
                    type="button"
                    :class="['date-shortcut', { active: isHistoryDateShortcutActive(shortcut.key) }]"
                    @click="applyHistoryDateShortcut(shortcut.key)"
                  >
                    {{ shortcut.label }}
                  </button>
                </div>
                <label>
                  <span>窗口K数备用</span>
                  <input v-model.number="historyForm.window_size" type="number" min="2" />
                </label>
                <label>
                  <span>返回数量</span>
                  <input v-model.number="historyForm.top_n" type="number" min="1" />
                </label>
                <label>
                  <span>初筛候选</span>
                  <input v-model.number="historyForm.candidate_n" type="number" min="1" />
                </label>
                <label>
                  <span>排除近端K数</span>
                  <input v-model.number="historyForm.exclusion_bars" type="number" min="0" />
                </label>
                <label>
                  <span>样本间隔天数</span>
                  <input v-model.number="historyForm.nearby_gap_days" type="number" min="0" />
                </label>
                <label>
                  <span>前瞻K数</span>
                  <input v-model="historyForm.forward_windows" type="text" />
                </label>
                <div class="form-actions span-full">
                  <button class="btn primary" type="submit" :disabled="runningResearch === 'history'">
                    <Icon name="activity" />
                    开始搜索
                  </button>
                  <button class="btn secondary" type="button" :disabled="!historyResult" @click="saveResearchSnapshot('history')">
                    <Icon name="save" />
                    保存快照
                  </button>
                </div>
              </form>
              <div v-if="historyChartItems.length" class="research-kline-section">
                <div class="review-section-head">
                  <span>窗口K线</span>
                  <strong>{{ historyChartSummary }}</strong>
                </div>
                <div class="review-kline-grid">
                  <KlineChart v-for="item in historyChartItems" :key="`${item.symbol}-${item.label}`" :item="item" />
                </div>
              </div>
            </Panel>

            <Panel title="历史匹配结果" subtitle="按综合相似度排序">
              <DataTable :rows="displayHistoryRows" :columns="historyColumns" empty="暂无历史匹配结果。" />
              <div v-if="historyStatsRows.length" class="history-stats-block">
                <div class="history-stat-strip">
                  <div v-for="row in historyStatsRows" :key="row.label">
                    <span>{{ row.label }}</span>
                    <strong>{{ row.value }}</strong>
                    <em>{{ row.detail }}</em>
                  </div>
                </div>
                <DataTable
                  v-if="historyForwardStats.length"
                  :rows="historyForwardStats"
                  :columns="historyForwardStatColumns"
                  empty="暂无前瞻统计。"
                />
              </div>
            </Panel>
          </section>

          <section v-else-if="activeResearchTab === 'cross'" class="content-grid two">
            <Panel title="横截面相似" subtitle="同区间">
              <form class="task-form" @submit.prevent="runCrossSectionSearch">
                <label>
                  <span>目标标的</span>
                  <input v-model="crossForm.target_symbol" type="text" />
                </label>
                <label>
                  <span>返回数量</span>
                  <input v-model.number="crossForm.top_n" type="number" min="1" />
                </label>
                <div class="inline-fields span-full">
                  <label>
                    <span>开始</span>
                    <input v-model="crossForm.start" type="date" />
                  </label>
                  <label>
                    <span>结束</span>
                    <input v-model="crossForm.end" type="date" />
                  </label>
                </div>
                <div class="date-shortcuts span-full" aria-label="日期快捷选项">
                  <span>快捷</span>
                  <button
                    v-for="shortcut in DATE_RANGE_SHORTCUTS"
                    :key="shortcut.key"
                    type="button"
                    :class="['date-shortcut', { active: isDateShortcutActive(crossForm, shortcut.key) }]"
                    @click="applyDateShortcut(crossForm, shortcut.key)"
                  >
                    {{ shortcut.label }}
                  </button>
                </div>
                <label>
                  <span>日期容忍K数</span>
                  <input v-model.number="crossForm.date_tolerance_bars" type="number" min="0" />
                </label>
                <label>
                  <span>前瞻K数</span>
                  <input v-model="crossForm.forward_windows" type="text" />
                </label>
                <label class="span-full">
                  <span>候选标的</span>
                  <textarea v-model="crossForm.universe_symbols" rows="5"></textarea>
                </label>
                <div class="form-actions span-full">
                  <button class="btn primary" type="submit" :disabled="runningResearch === 'cross'">
                    <Icon name="layers" />
                    开始搜索
                  </button>
                  <button class="btn secondary" type="button" :disabled="!crossResult" @click="saveResearchSnapshot('cross')">
                    <Icon name="save" />
                    保存快照
                  </button>
                </div>
              </form>
              <div v-if="crossChartItems.length" class="research-kline-section">
                <div class="review-section-head">
                  <span>窗口K线</span>
                  <strong>{{ crossChartSummary }}</strong>
                </div>
                <div class="review-kline-grid">
                  <KlineChart v-for="item in crossChartItems" :key="`${item.symbol}-${item.label || item.rank}`" :item="item" />
                </div>
              </div>
            </Panel>

            <Panel title="横截面匹配结果" subtitle="日期容忍后择优">
              <DataTable :rows="displayCrossRows" :columns="crossColumns" empty="暂无横截面匹配结果。" />
            </Panel>
          </section>

          <section v-else class="content-grid two research-review-grid">
            <Panel title="多股复盘" subtitle="排序锐评">
              <form class="task-form" @submit.prevent="runReviewSearch">
                <div class="inline-fields span-full">
                  <label>
                    <span>开始</span>
                    <input v-model="reviewForm.start" type="date" />
                  </label>
                  <label>
                    <span>结束</span>
                    <input v-model="reviewForm.end" type="date" />
                  </label>
                </div>
                <div class="date-shortcuts span-full" aria-label="日期快捷选项">
                  <span>快捷</span>
                  <button
                    v-for="shortcut in DATE_RANGE_SHORTCUTS"
                    :key="shortcut.key"
                    type="button"
                    :class="['date-shortcut', { active: isDateShortcutActive(reviewForm, shortcut.key) }]"
                    @click="applyDateShortcut(reviewForm, shortcut.key)"
                  >
                    {{ shortcut.label }}
                  </button>
                </div>
                <label>
                  <span>最小波段幅度</span>
                  <input v-model.number="reviewForm.min_swing_return" type="number" min="0" step="0.01" />
                </label>
                <label>
                  <span>最小波段K数</span>
                  <input v-model.number="reviewForm.min_segment_bars" type="number" min="1" />
                </label>
                <label class="span-full">
                  <span>对标指数</span>
                  <input v-model="reviewForm.benchmark_symbol" type="text" placeholder="000300.SH" />
                </label>
                <label class="span-full review-symbol-field">
                  <div class="field-head">
                    <span>复盘标的</span>
                    <div class="field-actions">
                      <button class="mini-action" type="button" @click="openReviewSymbolPicker('etf')">
                        <Icon name="archive" />
                        选ETF
                      </button>
                      <button class="mini-action" type="button" @click="openReviewSymbolPicker('sector')">
                        <Icon name="layers" />
                        选板块
                      </button>
                    </div>
                  </div>
                  <textarea v-model="reviewForm.symbols" rows="5"></textarea>
                </label>
                <div class="form-actions span-full">
                  <button class="btn primary" type="submit" :disabled="runningResearch === 'review'">
                    <Icon name="clipboard" />
                    生成复盘
                  </button>
                  <button class="btn secondary" type="button" :disabled="!reviewResult" @click="saveResearchSnapshot('review')">
                    <Icon name="save" />
                    保存快照
                  </button>
                </div>
              </form>
              <div v-if="reviewChartItems.length" class="research-kline-section">
                <div class="review-section-head">
                  <span>窗口K线</span>
                  <strong>{{ reviewChartSummary }}</strong>
                </div>
                <div v-if="reviewResultStale" class="inline-warning">
                  参数已变更，点击“生成复盘”后刷新 K 线、排序和锐评。
                </div>
                <div class="review-kline-grid">
                  <KlineChart v-for="item in reviewChartItems" :key="item.symbol" :item="item" />
                </div>
              </div>
            </Panel>

            <div class="view-stack">
              <Panel title="排序锐评" subtitle="本地行情">
                <DataTable :rows="displayReviewRows" :columns="reviewColumns" empty="暂无复盘排序。" />
              </Panel>
              <Panel title="对标比较" subtitle="指数关系">
                <DataTable :rows="displayComparisonRows" :columns="comparisonColumns" empty="暂无对标比较。" />
              </Panel>
              <Panel title="关键波段" subtitle="首位标的">
                <DataTable :rows="displaySegmentRows" :columns="segmentColumns" empty="暂无关键波段。" />
              </Panel>
              <Panel title="复盘与锐评" subtitle="结构化输出">
                <div class="panel-actions">
                  <button class="btn secondary" type="button" :disabled="runningAiReview || !reviewResult?.ai?.messages?.length" @click="runAiReview">
                    <Icon name="activity" />
                    {{ aiConfigReady ? 'AI覆盖' : '本地规则' }}
                  </button>
                </div>
                <div v-if="reviewMarkdownBlocks.length || reviewScriptCards.length" class="review-output-stack">
                  <section v-if="reviewScriptCards.length" class="review-script-wrap">
                    <div class="review-script-title">逐股锐评卡片 · {{ reviewCardSourceLabel }}</div>
                    <div class="review-script-grid">
                      <article
                        v-for="card in reviewScriptCards"
                        :key="card.code"
                        :class="['review-script-card', reviewScriptGradeClass(card.grade)]"
                      >
                        <header class="review-script-head">
                          <div>
                            <h4>{{ card.title }}</h4>
                            <span>{{ card.code }} · {{ card.nature }}</span>
                          </div>
                          <b>{{ card.grade }}</b>
                        </header>
                        <div class="review-script-stats">
                          <span v-for="stat in card.stats" :key="stat.label">
                            {{ stat.label }} <strong>{{ stat.value }}</strong>
                          </span>
                        </div>
                        <section>
                          <span>一句话</span>
                          <p>{{ card.body }}</p>
                        </section>
                        <section>
                          <span>明日验证</span>
                          <p>{{ card.tomorrow }}</p>
                        </section>
                      </article>
                    </div>
                  </section>
                  <section v-if="reviewMarkdownBlocks.length" class="review-markdown-card">
                    <article
                      v-for="(block, index) in reviewMarkdownBlocks"
                      :key="index"
                      :class="['review-markdown-block', block.type]"
                    >
                      <template v-if="block.type === 'table'">
                        <div class="review-markdown-table">
                          <table>
                            <thead>
                              <tr>
                                <th v-for="head in block.headers" :key="head">{{ head }}</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
                                <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </template>
                      <template v-else>
                        <h4 v-if="block.title">{{ block.title }}</h4>
                        <p v-for="(line, lineIndex) in block.lines" :key="lineIndex">{{ line }}</p>
                      </template>
                    </article>
                  </section>
                </div>
                <EmptyState v-else title="暂无复盘输出" body="生成复盘后展示结构化复盘和逐股锐评卡片。" />
              </Panel>
            </div>
          </section>
        </section>

        <section v-else-if="activeView === 'tasks'" class="content-grid two">
          <Panel title="任务队列" subtitle="后台执行">
            <div class="panel-actions">
              <button class="btn secondary" :disabled="clearingTasks" @click="clearTaskHistory">
                <Icon name="trash" />
                清空历史
              </button>
            </div>
            <div v-if="tasks.length" class="task-list">
              <button
                v-for="task in tasks"
                :key="task.id"
                :class="['task-item', { active: selectedTaskId === task.id }]"
                @click="selectTask(task.id)"
              >
                <strong>{{ task.status }}</strong>
                <span>{{ task.id.slice(0, 12) }}</span>
                <em>{{ task.finished_at || task.started_at || task.created_at }}</em>
              </button>
            </div>
            <EmptyState v-else title="暂无任务" body="执行下载后任务会出现在这里。" />
          </Panel>

          <Panel title="过程记录" subtitle="事件流">
            <div v-if="selectedTask" class="task-detail-stack">
              <section class="event-window">
                <div class="task-section-head">
                  <strong>当前进度</strong>
                  <span>最新 {{ visibleTaskEvents.length }} / {{ selectedTaskEvents.length }} 条</span>
                </div>
                <div class="event-list compact">
                  <div v-for="event in visibleTaskEvents" :key="event.key" class="event-row">
                    <strong>{{ event.label }}</strong>
                    <span>{{ event.message }}</span>
                    <em>{{ event.time }}</em>
                  </div>
                </div>
              </section>
              <div v-if="selectedTask.error" class="error-box">{{ selectedTask.error }}</div>
              <section v-if="displayTaskEventRows.length" class="task-paged-section">
                <div class="table-toolbar">
                  <p class="table-caption">完整事件 {{ taskEventPageFirst }}-{{ taskEventPageEnd }} / {{ displayTaskEventRows.length }} 条</p>
                  <div class="table-controls">
                    <div class="page-size-group">
                      <span>每页</span>
                      <button
                        v-for="size in taskEventPageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: taskEventPagination.pageSize === size }]"
                        @click="setTaskEventPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button type="button" :disabled="taskEventPagination.page <= 1" @click="goTaskEventPage(1)">首页</button>
                      <button type="button" :disabled="taskEventPagination.page <= 1" @click="goTaskEventPage(taskEventPagination.page - 1)">上一页</button>
                      <span>{{ taskEventPagination.page }} / {{ taskEventTotalPages }}</span>
                      <button type="button" :disabled="taskEventPagination.page >= taskEventTotalPages" @click="goTaskEventPage(taskEventPagination.page + 1)">下一页</button>
                      <button type="button" :disabled="taskEventPagination.page >= taskEventTotalPages" @click="goTaskEventPage(taskEventTotalPages)">末页</button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedTaskEventRows" :columns="taskEventColumns" empty="暂无事件记录。" />
              </section>
              <section v-if="selectedTaskResultRows.length" class="task-paged-section">
                <div class="table-toolbar">
                  <p class="table-caption">写入结果 {{ taskResultPageFirst }}-{{ taskResultPageEnd }} / {{ selectedTaskResultRows.length }} 条</p>
                  <div class="table-controls">
                    <div class="page-size-group">
                      <span>每页</span>
                      <button
                        v-for="size in taskResultPageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: taskResultPagination.pageSize === size }]"
                        @click="setTaskResultPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button type="button" :disabled="taskResultPagination.page <= 1" @click="goTaskResultPage(1)">首页</button>
                      <button type="button" :disabled="taskResultPagination.page <= 1" @click="goTaskResultPage(taskResultPagination.page - 1)">上一页</button>
                      <span>{{ taskResultPagination.page }} / {{ taskResultTotalPages }}</span>
                      <button type="button" :disabled="taskResultPagination.page >= taskResultTotalPages" @click="goTaskResultPage(taskResultPagination.page + 1)">下一页</button>
                      <button type="button" :disabled="taskResultPagination.page >= taskResultTotalPages" @click="goTaskResultPage(taskResultTotalPages)">末页</button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="displayResultRows" :columns="resultColumns" empty="暂无写入结果。" />
              </section>
            </div>
            <EmptyState v-else title="未选择任务" body="左侧选择任务查看事件和结果。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'settings'" class="content-grid two">
          <Panel title="系统设置" subtitle="本地配置">
            <form class="task-form" @submit.prevent="saveSettings">
              <label class="span-full">
                <span>行情根目录</span>
                <div class="path-control">
                  <input v-model="settings.data_root" type="text" />
                  <button class="btn secondary" type="button" :disabled="pickingDirectory !== ''" @click="pickDirectory('data_root')">
                    <Icon name="folder" />
                    {{ pickingDirectory === 'data_root' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>
              <label class="span-full">
                <span>TDX PYPlugins/user</span>
                <div class="path-control">
                  <input v-model="settings.tdx_path" type="text" />
                  <button class="btn secondary" type="button" :disabled="pickingDirectory !== ''" @click="pickDirectory('tdx_path')">
                    <Icon name="folder" />
                    {{ pickingDirectory === 'tdx_path' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>
              <label>
                <span>复权</span>
                <select v-model="settings.adjust">
                  <option value="qfq">qfq</option>
                  <option value="hfq">hfq</option>
                  <option value="">不复权</option>
                </select>
              </label>
              <label>
                <span>默认批次</span>
                <input v-model.number="settings.batch_size" type="number" min="1" />
              </label>
              <label class="check-row span-full">
                <input v-model="settings.strict_after_update" type="checkbox" />
                <span>补齐后严格校验</span>
              </label>
              <div class="form-actions span-full">
                <button class="btn primary" type="submit">保存设置</button>
                <button class="btn secondary" type="button" @click="resetSettings">恢复默认</button>
              </div>
            </form>
          </Panel>

          <Panel title="AI 锐评设置" subtitle="输出参数">
            <form class="task-form ai-settings-form" @submit.prevent="saveSettings">
              <label class="span-full">
                <span>接口 URL</span>
                <input v-model="aiSettings.base_url" type="url" placeholder="https://api.openai.com/v1" />
              </label>
              <label class="span-full">
                <span>API Key</span>
                <input v-model="aiSettings.api_key" type="password" autocomplete="off" placeholder="保存到本机浏览器 localStorage" />
              </label>
              <label>
                <span>模型</span>
                <input v-model="aiSettings.model" type="text" placeholder="例如 deepseek-v4-flash" />
              </label>
              <label>
                <span>温度</span>
                <input v-model.number="aiSettings.temperature" type="number" min="0" max="2" step="0.1" />
              </label>
              <label class="span-full">
                <span>系统约束</span>
                <textarea v-model="aiPromptDraft.system" rows="8" placeholder="留空时使用系统默认提示词"></textarea>
              </label>
              <label class="span-full">
                <span>卡片任务提示</span>
                <textarea v-model="aiPromptDraft.user" rows="4"></textarea>
              </label>
              <label class="check-row span-full">
                <input v-model="aiPromptSaved" type="checkbox" />
                <span>启用自定义提示词</span>
              </label>
              <div class="ai-settings-note span-full">
                多股复盘生成 AI 覆盖时会读取这里保存的参数；证据 JSON 由当前复盘结果自动附加。
              </div>
              <div class="form-actions span-full">
                <button class="btn primary" type="submit">保存 AI 设置</button>
                <button class="btn secondary" type="button" @click="resetAiPromptSettings">恢复默认提示词</button>
              </div>
            </form>
          </Panel>

          <Panel title="运行状态" subtitle="API">
            <div class="kv-list">
              <div class="kv-row"><span>API</span><strong>http://127.0.0.1:8622</strong></div>
              <div class="kv-row"><span>运行链路</span><strong>{{ runtimeLabel }}</strong></div>
              <div class="kv-row"><span>索引文件</span><strong>{{ overview?.catalog_path || '未扫描' }}</strong></div>
              <div class="kv-row"><span>索引状态</span><strong>{{ overview?.catalog_exists ? '存在' : '未生成' }}</strong></div>
              <div class="kv-row"><span>缓存表格</span><strong>分页显示完整索引记录</strong></div>
            </div>
            <div class="timeframe-map">
              <div v-for="row in timeframeStorageRows" :key="row.timeframe">
                <span>{{ row.timeframe }}</span>
                <strong :title="row.path">{{ compactPath(row.path) }}</strong>
              </div>
            </div>
          </Panel>
        </section>

      </main>
    </div>

    <div v-if="reviewSymbolPickerOpen" class="modal-backdrop" @click.self="closeReviewSymbolPicker">
      <section class="asset-picker-modal" role="dialog" aria-modal="true" aria-labelledby="review-symbol-picker-title">
        <header class="asset-picker-head">
          <div>
            <h3 id="review-symbol-picker-title">选择复盘标的</h3>
            <p>{{ reviewSymbolPickerSourceSummary }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="closeReviewSymbolPicker">
            <Icon name="collapse" />
          </button>
        </header>

        <div class="asset-picker-tabs">
          <button
            v-for="tabItem in REVIEW_SYMBOL_PICKER_TABS"
            :key="tabItem.key"
            type="button"
            :class="['asset-picker-tab', { active: reviewSymbolPickerType === tabItem.key }]"
            @click="setReviewSymbolPickerType(tabItem.key)"
          >
            {{ tabItem.label }}
            <span>{{ reviewSymbolPickerCount(tabItem.key) }}</span>
          </button>
        </div>

        <div class="asset-picker-tools">
          <input v-model="reviewSymbolPickerKeyword" type="search" placeholder="搜索代码或名称" />
          <button class="btn secondary" type="button" @click="selectFilteredReviewSymbols">选当前结果</button>
          <button class="btn secondary" type="button" @click="selectAllReviewSymbols">全选{{ reviewSymbolPickerTypeLabel }}</button>
          <button class="btn secondary" type="button" @click="clearReviewSymbolSelection">清空</button>
        </div>

        <div class="asset-picker-summary">
          <span>显示 {{ formatInt(filteredReviewSymbolPickerRows.length) }} / {{ formatInt(reviewSymbolPickerRows.length) }} · {{ reviewSymbolPickerSortLabel }}</span>
          <strong>已选 {{ formatInt(reviewSymbolPickerSelection.length) }}</strong>
        </div>

        <div v-if="filteredReviewSymbolPickerRows.length" class="asset-picker-list">
          <label
            v-for="row in filteredReviewSymbolPickerRows"
            :key="row.symbol"
            :class="['asset-picker-row', { selected: isReviewSymbolSelected(row.symbol) }]"
          >
            <input type="checkbox" :checked="isReviewSymbolSelected(row.symbol)" @change="toggleReviewSymbol(row.symbol)" />
            <span>
              <strong>{{ row.symbol }}</strong>
              <em>{{ row.name || row.assetType || reviewSymbolPickerTypeLabel }}</em>
            </span>
          </label>
        </div>
        <div v-else class="asset-picker-empty">当前分类暂无可选标的。</div>

        <footer class="asset-picker-footer">
          <button class="btn secondary" type="button" @click="closeReviewSymbolPicker">取消</button>
          <button class="btn secondary" type="button" :disabled="!reviewSymbolPickerSelection.length" @click="applyReviewSymbolSelection('append')">
            追加选中
          </button>
          <button class="btn primary" type="button" :disabled="!reviewSymbolPickerSelection.length" @click="applyReviewSymbolSelection('replace')">
            替换标的
          </button>
        </footer>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import DataTable from './components/DataTable.vue'
import EmptyState from './components/EmptyState.vue'
import Icon from './components/Icon.vue'
import KlineChart from './components/KlineChart.vue'
import MetricCard from './components/MetricCard.vue'
import Panel from './components/Panel.vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

interface SymbolGroup {
  name: string
  symbols: string[]
}

interface ConfigPayload {
  defaults: Record<string, any>
  timeframes: string[]
  asset_types: Array<{ value: string; label: string }>
  symbol_groups: SymbolGroup[]
  runtime: string
}

interface TaskPayload {
  id: string
  kind: string
  status: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  events: Array<Record<string, any>>
  result: { summary: Record<string, any>; records: Array<Record<string, any>> } | null
  error: string | null
}

interface NoticePayload {
  type: 'success' | 'error' | 'info'
  title: string
  body: string
}

type DateShortcutKey = '20d' | '50d' | 'ytd' | '1y'

interface DateRangeFields {
  start: string
  end: string
}

type DirectoryField = 'data_root' | 'tdx_path'
type ResearchTabKey = 'history' | 'cross' | 'review'
type SymbolRefreshTarget = 'index' | 'etf'
type ReviewSymbolPickerType = 'etf' | 'sector'

interface ResearchSnapshot {
  id: string
  tab: ResearchTabKey
  title: string
  createdAt: string
  summary: string
  payload: Record<string, any>
  result: Record<string, any>
}

interface ReviewMarkdownBlock {
  type: 'table' | 'section' | 'paragraph'
  title: string
  lines: string[]
  headers: string[]
  rows: string[][]
}

interface ReviewScriptCard {
  code: string
  title: string
  grade: string
  nature: string
  body: string
  tomorrow: string
  stats: Array<{ label: string; value: string }>
}

const IMPORTANT_ASSET_TYPES = [
  { value: 'etf', label: 'ETF', tone: 'blue', icon: 'archive' },
  { value: 'stock', label: '个股', tone: 'green', icon: 'key' },
  { value: 'index', label: '指数', tone: 'indigo', icon: 'layers' }
]

const navItems = [
  { key: 'dashboard', label: '总览', title: 'TDX 数据运营工作台', description: '查看缓存资产、运行环境和最近任务。', icon: 'dashboard' },
  { key: 'download', label: '下载任务', title: '下载任务', description: '配置代码、周期、时间窗并在后台执行。', icon: 'download' },
  { key: 'cache', label: '缓存资产', title: '缓存资产', description: '查看 SQLite catalog 与本地 parquet 缓存。', icon: 'database' },
  { key: 'research', label: '研究工具', title: '研究工具', description: '基于本地 TDX 缓存做相似度搜索和多股复盘。', icon: 'layers' },
  { key: 'tasks', label: '执行记录', title: '执行记录', description: '查看后台任务状态、错误和写入结果。', icon: 'clipboard' },
  { key: 'settings', label: '系统设置', title: '系统设置', description: '配置默认路径、复权方式和运行参数。', icon: 'settings' }
]

const researchTabs: Array<{ key: ResearchTabKey; label: string; icon: string }> = [
  { key: 'history', label: '历史相似', icon: 'activity' },
  { key: 'cross', label: '横截面相似', icon: 'layers' },
  { key: 'review', label: '多股复盘', icon: 'clipboard' }
]

const SETTINGS_STORAGE_KEY = 'tdx-downloader-web-settings'
const RESEARCH_SNAPSHOT_STORAGE_KEY = 'tdx-downloader-research-snapshots'
const MAX_RESEARCH_SNAPSHOTS = 60
const CACHE_PAGE_SIZE_OPTIONS = [25, 50, 100]
const DEFAULT_ALL_ASSETS_LOOKBACK_DAYS = 20
const REVIEW_SYMBOL_PICKER_TABS: Array<{ key: ReviewSymbolPickerType; label: string }> = [
  { key: 'etf', label: 'ETF' },
  { key: 'sector', label: '板块指数' }
]
const DATE_RANGE_SHORTCUTS: Array<{ key: DateShortcutKey; label: string }> = [
  { key: '20d', label: '20日' },
  { key: '50d', label: '50日' },
  { key: 'ytd', label: 'YTD' },
  { key: '1y', label: '近一年' }
]
const TASK_EVENT_WINDOW_SIZE = 6
const TASK_EVENT_PAGE_SIZE_OPTIONS = [10, 25, 50]
const TASK_RESULT_PAGE_SIZE_OPTIONS = [25, 50, 100]
const STATUS_LABELS: Record<string, string> = {
  cached: '可用',
  missing_file: '缺文件',
  read_error: '读取失败',
  missing_columns: '缺字段',
  no_valid_rows: '无有效K线',
  ok: '通过',
  quality_error: '质量异常',
  no_window_data: '窗口无数据',
  coverage_gap: '覆盖缺口',
  ready: '准备完成',
  partial: '部分可用',
  empty: '无可用缓存',
  fetch: '待下载',
  fetched: '已下载'
}
const TIMEFRAME_DIR_NAMES: Record<string, string> = {
  '1d': 'daily',
  '1m': '1m',
  '5m': '5m',
  '15m': '15m',
  '30m': '30m',
  '60m': '60m'
}
const KNOWN_TIMEFRAME_DIRS = new Set(Object.values(TIMEFRAME_DIR_NAMES))
const sidebarCollapsed = ref(false)
const activeView = ref('dashboard')
const config = ref<ConfigPayload | null>(null)
const overview = ref<Record<string, any> | null>(null)
const tasks = ref<TaskPayload[]>([])
const selectedTaskId = ref('')
const selectedGroup = ref('核心样例')
const selectedTimeframe = ref('1d')
const researchTimeframe = ref('1d')
const allAssetsLookbackDays = ref(DEFAULT_ALL_ASSETS_LOOKBACK_DAYS)
const reviewSymbolPickerOpen = ref(false)
const reviewSymbolPickerType = ref<ReviewSymbolPickerType>('etf')
const reviewSymbolPickerKeyword = ref('')
const reviewSymbolPickerSelection = ref<string[]>([])
const symbolsText = ref('')
const planning = ref(false)
const downloading = ref(false)
const loadingOverview = ref(false)
const refreshingTopbar = ref(false)
const loadingSymbolGroups = ref(false)
const refreshingSymbolGroup = ref<SymbolRefreshTarget | ''>('')
const clearingTasks = ref(false)
const runningResearch = ref<ResearchTabKey | ''>('')
const runningAiReview = ref(false)
const activeResearchTab = ref<ResearchTabKey>('history')
const pickingDirectory = ref<DirectoryField | ''>('')
const planRows = ref<Array<Record<string, any>>>([])
const planSummary = ref<Record<string, any>>({})
const historyResult = ref<Record<string, any> | null>(null)
const crossResult = ref<Record<string, any> | null>(null)
const reviewResult = ref<Record<string, any> | null>(null)
const reviewResultSignature = ref('')
const aiReviewOutput = ref<Record<string, any> | null>(null)
const researchSnapshots = ref<ResearchSnapshot[]>([])
const notice = ref<NoticePayload | null>(null)
const cacheFilters = reactive({
  keyword: '',
  assetType: '',
  timeframe: '',
  status: ''
})
const cachePagination = reactive({
  page: 1,
  pageSize: 25
})
const taskEventPagination = reactive({
  page: 1,
  pageSize: TASK_EVENT_PAGE_SIZE_OPTIONS[0]
})
const taskResultPagination = reactive({
  page: 1,
  pageSize: TASK_RESULT_PAGE_SIZE_OPTIONS[0]
})

const settings = reactive({
  data_root: '/Volumes/ccOUT 1/tdx-data',
  adjust: 'qfq',
  tdx_path: '/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user',
  start: '',
  end: '',
  mode: 'smart',
  batch_size: 100,
  strict_after_update: true
})

const aiSettings = reactive({
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  model: '',
  temperature: 0.2
})
const aiPromptSaved = ref(false)
const aiPromptDraft = reactive({
  system: '',
  user: defaultAiUserPrompt()
})

const historyForm = reactive({
  symbol: '000001.SZ',
  window_start: offsetDateText(-20),
  as_of: todayText(),
  window_size: 20,
  candidate_n: 100,
  top_n: 10,
  exclusion_bars: 20,
  nearby_gap_days: 20,
  algorithm: 'baseline_price_feature',
  forward_windows: '5,20,60'
})

const crossForm = reactive({
  target_symbol: '000001.SZ',
  universe_symbols: '600519.SH\n300750.SZ\n601318.SH',
  start: offsetDateText(-20),
  end: todayText(),
  top_n: 20,
  date_tolerance_bars: 0,
  forward_windows: '3,5,10'
})

const reviewForm = reactive({
  symbols: '000001.SZ\n600519.SH\n300750.SZ\n601318.SH',
  start: offsetDateText(-20),
  end: todayText(),
  benchmark_symbol: '000300.SH',
  min_swing_return: 0.05,
  min_segment_bars: 3
})

const activeMeta = computed(() => navItems.find((item) => item.key === activeView.value) || navItems[0])
const activeResearchMeta = computed(() => researchTabs.find((item) => item.key === activeResearchTab.value) || researchTabs[0])
const summary = computed(() => overview.value?.summary || {})
const assetRows = computed(() => overview.value?.by_asset_type || [])
const timeframeRows = computed(() => overview.value?.by_timeframe || [])
const datasetRows = computed(() => overview.value?.by_dataset || [])
const cacheRows = computed(() => overview.value?.records || [])
const filteredCacheRows = computed(() => {
  const keyword = cacheFilters.keyword.trim().toLowerCase()
  return cacheRows.value.filter((row: Record<string, any>) => {
    const text = `${row.stock_code || ''} ${row.stock_name || ''}`.toLowerCase()
    return (
      (!keyword || text.includes(keyword)) &&
      (!cacheFilters.assetType || String(row.asset_type || '') === cacheFilters.assetType) &&
      (!cacheFilters.timeframe || String(row.timeframe || '') === cacheFilters.timeframe) &&
      (!cacheFilters.status || String(row.status || '') === cacheFilters.status)
    )
  })
})
const cacheSymbolMeta = computed(() => {
  const meta = new Map<string, { name: string; assetType: string }>()
  cacheRows.value.forEach((row: Record<string, any>) => {
    const symbol = String(row.stock_code || '').trim()
    if (!symbol || meta.has(symbol)) return
    meta.set(symbol, {
      name: String(row.stock_name || '').trim(),
      assetType: String(row.asset_type || '').trim()
    })
  })
  return meta
})
const cacheTotalPages = computed(() => Math.max(1, Math.ceil(filteredCacheRows.value.length / cachePagination.pageSize)))
const cachePageStartIndex = computed(() =>
  filteredCacheRows.value.length ? (cachePagination.page - 1) * cachePagination.pageSize : 0
)
const cachePageEnd = computed(() => Math.min(cachePageStartIndex.value + cachePagination.pageSize, filteredCacheRows.value.length))
const cachePageFirst = computed(() => (filteredCacheRows.value.length ? cachePageStartIndex.value + 1 : 0))
const pagedCacheRows = computed(() => filteredCacheRows.value.slice(cachePageStartIndex.value, cachePageEnd.value))
const displayCacheRows = computed(() => pagedCacheRows.value.map((row: Record<string, any>) => displayCacheRecord(row)))
const cachePageSizeOptions = CACHE_PAGE_SIZE_OPTIONS
const displayPlanRows = computed(() => planRows.value.map((row: Record<string, any>) => displayRecord(row)))
const displayResultRows = computed(() => pagedTaskResultRows.value.map((row: Record<string, any>) => displayRecord(row)))
const displayHistoryRows = computed(() =>
  (historyResult.value?.results || []).map((row: Record<string, any>) => displayResearchRecord(row))
)
const historySymbol = computed(() => historyResult.value?.summary?.symbol || historyForm.symbol)
const historyStockName = computed(() => String(historyResult.value?.summary?.stock_name || '').trim())
const historyDisplayName = computed(() => historyStockName.value || historySymbol.value)
const displayCrossRows = computed(() =>
  (crossResult.value?.results || []).map((row: Record<string, any>) => displayResearchRecord(row))
)
const displayReviewRows = computed(() =>
  (reviewResult.value?.ranking || []).map((row: Record<string, any>) => displayResearchRecord(row))
)
const displayComparisonRows = computed(() =>
  (reviewResult.value?.comparisons || []).map((row: Record<string, any>) => displayResearchRecord(row))
)
const displaySegmentRows = computed(() =>
  (reviewResult.value?.reviews?.[0]?.main_segments || []).map((row: Record<string, any>) => displayResearchRecord(row))
)
const historyChartItems = computed(() => {
  if (!historyResult.value) return []
  const symbol = historySymbol.value
  const items: Array<Record<string, any>> = []
  if (Array.isArray(historyResult.value.current_window) && historyResult.value.current_window.length) {
    items.push({
      symbol,
      name: historyDisplayName.value,
      label: '当前窗口',
      candles: historyResult.value.current_window,
      segments: [klineSegment(historyResult.value.current_window, '当前窗口')]
    })
  }
  const historicalWindows = historyResult.value.historical_windows || []
  const historicalChartWindows = historyResult.value.historical_chart_windows || []
  historicalWindows.slice(0, 5).forEach((candles: Array<Record<string, any>>, index: number) => {
    if (!candles.length) return
    items.push({
      symbol,
      name: historyDisplayName.value,
      label: `历史 #${index + 1}`,
      candles: historicalChartWindows[index]?.length ? historicalChartWindows[index] : candles,
      segments: [klineSegment(candles, '相似区间')]
    })
  })
  return items
})
const historyChartSummary = computed(() => {
  const count = Math.max(historyChartItems.value.length - 1, 0)
  const timeframe = historyResult.value?.summary?.timeframe || researchTimeframe.value
  const windowSize = historyResult.value?.summary?.window_size || historyForm.window_size
  const range = historyCurrentWindowRange.value
  const rangeText = range ? ` · ${range.start} 至 ${range.end}` : ''
  return historyChartItems.value.length ? `当前窗口 + ${count} 个历史匹配 · ${timeframe}${rangeText} · ${windowSize} 根K线` : ''
})
const historyCurrentWindowRange = computed(() => chartActualRange([{ candles: historyResult.value?.current_window || [] }]))
const historyStatsRows = computed(() => {
  if (!historyResult.value) return []
  const results = historyResult.value.results || []
  const first = results[0] || {}
  const currentWindow = historyResult.value.current_window || []
  const currentReturn = candleWindowReturn(currentWindow)
  const range = historyCurrentWindowRange.value
  return [
    {
      label: '当前标的',
      value: historyStockName.value ? `${historyStockName.value}` : historySymbol.value,
      detail: historyStockName.value ? historySymbol.value : '未解析名称'
    },
    {
      label: '当前窗口收益',
      value: formatPercentValue(currentReturn),
      detail: range ? `${range.start} 至 ${range.end}` : '-'
    },
    {
      label: '最高综合相似度',
      value: formatDecimalValue(first['综合相似度'], 4),
      detail: historyWindowLabel(first)
    },
    {
      label: '有效样本',
      value: `${formatInt(results.length)} / ${formatInt(historyResult.value.summary?.match_count)}`,
      detail: String(historyResult.value.summary?.algorithm || historyForm.algorithm)
    }
  ]
})
const historyForwardStats = computed(() => {
  const rows = historyResult.value?.results || []
  if (!rows.length) return []
  return historyForwardReturnKeys(rows).map((item) => {
    const values = rows.map((row: Record<string, any>) => Number(row[item.key])).filter((value: number) => Number.isFinite(value))
    const bestRow = rows.reduce((best: Record<string, any> | null, row: Record<string, any>) => {
      const value = Number(row[item.key])
      if (!Number.isFinite(value)) return best
      if (!best || value > Number(best[item.key])) return row
      return best
    }, null)
    return {
      '观察窗口': `后${item.horizon}根`,
      '样本数': formatInt(values.length),
      '平均收益': formatPercentValue(meanValue(values)),
      '中位收益': formatPercentValue(medianValue(values)),
      '胜率': formatPercentValue(values.length ? values.filter((value: number) => value > 0).length / values.length : NaN),
      '最好窗口': historyWindowLabel(bestRow || {}),
      '最好收益': formatPercentValue(bestRow ? bestRow[item.key] : NaN)
    }
  })
})
const crossChartItems = computed(() => {
  if (!crossResult.value) return []
  const items: Array<Record<string, any>> = []
  if (Array.isArray(crossResult.value.target_window) && crossResult.value.target_window.length) {
    items.push({
      symbol: crossResult.value.summary?.target_symbol || crossForm.target_symbol,
      name: crossResult.value.summary?.target_symbol || crossForm.target_symbol,
      label: '目标窗口',
      candles: crossResult.value.target_window
    })
  }
  const candidateWindows = crossResult.value.candidate_windows || []
  candidateWindows.slice(0, 5).forEach((row: Record<string, any>) => {
    if (!row.candles?.length) return
    items.push({
      symbol: row.symbol,
      name: row.symbol,
      rank: row.rank || '',
      candles: row.candles
    })
  })
  return items
})
const crossChartSummary = computed(() => {
  const count = Math.max(crossChartItems.value.length - 1, 0)
  const timeframe = crossResult.value?.summary?.timeframe || researchTimeframe.value
  return crossChartItems.value.length ? `目标窗口 + ${count} 个候选匹配 · ${timeframe} · ${crossForm.start} 至 ${crossForm.end}` : ''
})
const reviewChartItems = computed(() => {
  const rankingRows = reviewResult.value?.ranking || []
  const rankingBySymbol = new Map<string, Record<string, any>>(rankingRows.map((row: Record<string, any>) => [row['代码'], row]))
  return (reviewResult.value?.reviews || [])
    .filter((row: Record<string, any>) => Array.isArray(row.candles) && row.candles.length)
    .map((row: Record<string, any>) => {
      const ranking: Record<string, any> = rankingBySymbol.get(row.symbol) || {}
      return {
        symbol: row.symbol,
        name: ranking['股票'] || row.symbol,
        rank: ranking['排名'] || '',
        overview: row.overview || {},
        candles: row.candles || [],
        segments: row.main_segments || []
      }
    })
    .sort((left: Record<string, any>, right: Record<string, any>) => Number(left.rank || 9999) - Number(right.rank || 9999))
})
const reviewChartActualRange = computed(() => chartActualRange(reviewChartItems.value))
const reviewResultStale = computed(() => Boolean(reviewResult.value && reviewResultSignature.value !== reviewSearchSignature()))
const reviewChartSummary = computed(() => {
  const count = reviewChartItems.value.length
  const timeframe = reviewResult.value?.summary?.timeframe || researchTimeframe.value
  const requestedStart = reviewResult.value?.summary?.start || reviewForm.start
  const requestedEnd = reviewResult.value?.summary?.end || reviewForm.end
  const actual = reviewChartActualRange.value
  const parts = [`${count} 只`, timeframe, `请求 ${requestedStart} 至 ${requestedEnd}`]
  if (actual) parts.push(`实际K线 ${actual.start} 至 ${actual.end}`)
  if (reviewResultStale.value) parts.push('参数已变更')
  return count ? parts.join(' · ') : ''
})
const aiConfigReady = computed(() =>
  Boolean(aiSettings.base_url.trim() && aiSettings.api_key.trim() && aiSettings.model.trim())
)
const aiDefaultSystemPrompt = computed(() =>
  String((reviewResult.value?.ai?.messages || []).find((message: Record<string, string>) => message.role === 'system')?.content || '')
)
const reviewText = computed(() => String(reviewResult.value?.text?.review || ''))
const videoScriptText = computed(() => String(reviewResult.value?.text?.video_script || ''))
const reviewMarkdownBlocks = computed<ReviewMarkdownBlock[]>(() =>
  markdownBlocks(reviewText.value).filter((block) => !isInlineReviewBlock(block))
)
const localReviewScriptCards = computed<ReviewScriptCard[]>(() =>
  (reviewResult.value?.ranking || []).map((row: Record<string, any>) => {
    const code = String(row['代码'] || '')
    const stock = String(row['股票'] || '').trim()
    const grade = String(row['强弱等级'] || '-')
    return {
      code,
      title: stock && stock !== '-' ? `${stock}（${code}）` : code,
      grade,
      nature: String(row['当前性质'] || '-'),
      body: String(row['锐评结论'] || '-'),
      tomorrow: String(row['明日验证'] || '-'),
      stats: [
        { label: '收益', value: formatPercentValue(row['区间收益']) },
        { label: '回撤', value: formatPercentValue(row['最大回撤']) },
        { label: '超额', value: formatPercentValue(row['相对超额']) }
      ]
    }
  })
)
const aiReviewScriptCards = computed<ReviewScriptCard[]>(() =>
  (aiReviewOutput.value?.script_cards || []).map((card: Record<string, any>, index: number) => {
    const rankingRow = reviewResult.value?.ranking?.[index] || {}
    const code = String(card.code || card.symbol || rankingRow['代码'] || '')
    const title = String(card.title || rankingRow['股票'] || code || `AI卡片${index + 1}`)
    return {
      code,
      title,
      grade: String(card.grade || rankingRow['强弱等级'] || '-'),
      nature: String(card.nature || card.current_nature || rankingRow['当前性质'] || 'AI锐评'),
      body: String(card.body || card.review || card.summary || '-'),
      tomorrow: String(card.tomorrow_check || card.tomorrow || card.next_check || rankingRow['明日验证'] || '-'),
      stats: [
        { label: '来源', value: 'AI覆盖' },
        { label: '收益', value: formatPercentValue(rankingRow['区间收益']) },
        { label: '回撤', value: formatPercentValue(rankingRow['最大回撤']) }
      ]
    }
  })
)
const reviewScriptCards = computed<ReviewScriptCard[]>(() =>
  aiReviewScriptCards.value.length ? aiReviewScriptCards.value : localReviewScriptCards.value
)
const reviewCardSourceLabel = computed(() => (aiReviewScriptCards.value.length ? 'AI覆盖' : '本地规则'))
const activeResearchResult = computed(() => researchResultFor(activeResearchTab.value))
const activeResearchSnapshots = computed(() =>
  researchSnapshots.value.filter((snapshot) => snapshot.tab === activeResearchTab.value)
)
const uniqueCacheTimeframes = computed(() => uniqueStrings(cacheRows.value.map((row: Record<string, any>) => row.timeframe)))
const uniqueCacheStatuses = computed(() =>
  uniqueStrings(cacheRows.value.map((row: Record<string, any>) => row.status)).map((value) => ({
    value,
    label: STATUS_LABELS[value] || value
  }))
)
const uniqueAssetTypes = computed(() => {
  const labels = new Map((config.value?.asset_types || []).map((item: Record<string, string>) => [item.value, item.label]))
  return uniqueStrings(cacheRows.value.map((row: Record<string, any>) => row.asset_type)).map((value) => ({
    value,
    label: labels.get(value) || value
  }))
})
const runtimeLabel = computed(() => config.value?.runtime === 'parallels' ? 'Parallels' : 'Local')
const topbarRefreshing = computed(() => loadingOverview.value || refreshingTopbar.value)
const topbarRefreshTitle = computed(() => {
  if (activeView.value === 'cache') return '扫描缓存并更新索引'
  if (activeView.value === 'tasks') return '刷新任务进度'
  if (activeView.value === 'download') return '刷新任务和缓存状态'
  return '刷新当前页面数据'
})
const latestTask = computed(() => tasks.value[0])
const latestTaskText = computed(() => latestTask.value ? latestTask.value.status : '无')
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) || tasks.value[0] || null)
const selectedTaskEvents = computed(() =>
  (selectedTask.value?.events || []).map((event: Record<string, any>, index: number) => ({
    key: `${index}-${event.time || event.stage || event.label || ''}`,
    index: index + 1,
    label: String(event.label || event.stage || '-'),
    message: String(event.message || event.stage || '-'),
    time: formatDateTimeText(event.time)
  }))
)
const visibleTaskEvents = computed(() =>
  selectedTaskEvents.value.slice(Math.max(0, selectedTaskEvents.value.length - TASK_EVENT_WINDOW_SIZE))
)
const taskEventTotalPages = computed(() => Math.max(1, Math.ceil(selectedTaskEvents.value.length / taskEventPagination.pageSize)))
const taskEventPageStartIndex = computed(() =>
  selectedTaskEvents.value.length ? (taskEventPagination.page - 1) * taskEventPagination.pageSize : 0
)
const taskEventPageEnd = computed(() => Math.min(taskEventPageStartIndex.value + taskEventPagination.pageSize, selectedTaskEvents.value.length))
const taskEventPageFirst = computed(() => (selectedTaskEvents.value.length ? taskEventPageStartIndex.value + 1 : 0))
const displayTaskEventRows = computed(() =>
  selectedTaskEvents.value.map((event) => ({
    '序号': event.index,
    '阶段': event.label,
    '信息': event.message,
    '时间': event.time
  }))
)
const pagedTaskEventRows = computed(() => displayTaskEventRows.value.slice(taskEventPageStartIndex.value, taskEventPageEnd.value))
const taskEventPageSizeOptions = TASK_EVENT_PAGE_SIZE_OPTIONS
const selectedTaskResultRows = computed(() => selectedTask.value?.result?.records || [])
const taskResultTotalPages = computed(() => Math.max(1, Math.ceil(selectedTaskResultRows.value.length / taskResultPagination.pageSize)))
const taskResultPageStartIndex = computed(() =>
  selectedTaskResultRows.value.length ? (taskResultPagination.page - 1) * taskResultPagination.pageSize : 0
)
const taskResultPageEnd = computed(() =>
  Math.min(taskResultPageStartIndex.value + taskResultPagination.pageSize, selectedTaskResultRows.value.length)
)
const taskResultPageFirst = computed(() => (selectedTaskResultRows.value.length ? taskResultPageStartIndex.value + 1 : 0))
const pagedTaskResultRows = computed(() => selectedTaskResultRows.value.slice(taskResultPageStartIndex.value, taskResultPageEnd.value))
const taskResultPageSizeOptions = TASK_RESULT_PAGE_SIZE_OPTIONS
const parsedSymbols = computed(() => parseSymbols(symbolsText.value))
const allAssetSymbols = computed(() =>
  uniqueStringsInOrder((config.value?.symbol_groups || []).flatMap((group) => group.symbols))
)
const reviewSymbolPickerTypeLabel = computed(() =>
  REVIEW_SYMBOL_PICKER_TABS.find((item) => item.key === reviewSymbolPickerType.value)?.label || '标的'
)
const reviewSymbolPickerGroups = computed(() =>
  reviewSymbolGroupsForType(reviewSymbolPickerType.value)
)
const reviewSymbolPickerRows = computed(() =>
  uniqueStringsInOrder(reviewSymbolPickerGroups.value.flatMap((group) => group.symbols)).map((symbol) => {
    const meta = cacheSymbolMeta.value.get(symbol)
    return {
      symbol,
      name: meta?.name || '',
      assetType: meta?.assetType || ''
    }
  })
)
const filteredReviewSymbolPickerRows = computed(() => {
  const keyword = reviewSymbolPickerKeyword.value.trim().toLowerCase()
  if (!keyword) return reviewSymbolPickerRows.value
  return reviewSymbolPickerRows.value.filter((row) =>
    `${row.symbol} ${row.name} ${row.assetType}`.toLowerCase().includes(keyword)
  )
})
const reviewSymbolPickerSelectionSet = computed(() => new Set(reviewSymbolPickerSelection.value))
const reviewSymbolPickerSourceSummary = computed(() => {
  const names = reviewSymbolPickerGroups.value.map((group) => group.name).join(' / ') || reviewSymbolPickerTypeLabel.value
  return `${names} · ${formatInt(reviewSymbolPickerRows.value.length)} 只`
})
const reviewSymbolPickerSortLabel = computed(() => '近20K成交额降序')
const overviewTimeframes = computed(() =>
  sortTimeframes([
    ...timeframeRows.value.map((row: Record<string, any>) => row.timeframe),
    ...datasetRows.value.map((row: Record<string, any>) => row.timeframe)
  ])
)
const timeframeStorageRows = computed(() =>
  sortTimeframes(config.value?.timeframes || Object.keys(TIMEFRAME_DIR_NAMES)).map((timeframe) => ({
    timeframe,
    path: joinPath(settings.data_root, timeframeDirectoryName(timeframe))
  }))
)
const dashboardKeyStats = computed(() => [
  { label: '缓存标的', value: formatInt(summary.value.symbol_count), detail: `${formatInt(summary.value.asset_type_count)} 类资产` },
  {
    label: '可用周期项',
    value: `${formatInt(summary.value.data_inventory_cached_count)} / ${formatInt(summary.value.data_inventory_row_count)}`,
    detail: `${formatInt(summary.value.data_inventory_unavailable_count)} 缺口`
  },
  {
    label: 'K线总量',
    value: formatInt(summary.value.data_inventory_total_rows),
    detail: formatBytes(summary.value.data_inventory_total_file_size_bytes)
  },
  { label: '运行链路', value: runtimeLabel.value, detail: latestTaskText.value === '无' ? '暂无任务' : `最近 ${latestTaskText.value}` }
])
const assetOverviewCards = computed(() =>
  IMPORTANT_ASSET_TYPES.map((asset) => {
    const rows = datasetRows.value.filter((row: Record<string, any>) => row.asset_type === asset.value)
    const aggregate = assetRows.value.find((row: Record<string, any>) => row.asset_type === asset.value) || {}
    const periods = overviewTimeframes.value.map((timeframe) => {
      const timeframeDatasetRows = rows.filter((row: Record<string, any>) => row.timeframe === timeframe)
      const cachedCount = sumDatasetCount(timeframeDatasetRows, (row) => row.status === 'cached')
      const totalCount = sumDatasetCount(timeframeDatasetRows)
      return { timeframe, cachedCount, totalCount }
    })
    const symbolCount = Math.max(0, ...periods.map((period) => period.totalCount))
    const coveredTimeframeCount = periods.filter((period) => period.cachedCount > 0).length
    return {
      ...asset,
      symbolCount,
      rows: numberValue(aggregate.rows),
      periods,
      coveredTimeframeCount,
      totalTimeframeCount: periods.length,
      cachedPeriodItems: sumDatasetCount(rows, (row) => row.status === 'cached'),
      totalPeriodItems: sumDatasetCount(rows)
    }
  })
)

watch(
  () => [cacheFilters.keyword, cacheFilters.assetType, cacheFilters.timeframe, cacheFilters.status, cachePagination.pageSize],
  () => {
    cachePagination.page = 1
  }
)
watch(cacheTotalPages, () => {
  goCachePage(cachePagination.page)
})
watch(selectedTaskId, () => {
  taskEventPagination.page = 1
  taskResultPagination.page = 1
})
watch(taskEventTotalPages, () => {
  goTaskEventPage(taskEventPagination.page)
})
watch(taskResultTotalPages, () => {
  goTaskResultPage(taskResultPagination.page)
})

const planColumns = [
  { key: 'stock_code', label: '代码' },
  { key: 'timeframe', label: '周期' },
  { key: 'action', label: '动作' },
  { key: 'reason', label: '原因' },
  { key: 'missing_rows', label: '缺失K数' },
  { key: 'coverage_ratio', label: '覆盖率' }
]
const cacheColumns = [
  { key: 'stock_code', label: '代码' },
  { key: 'stock_name', label: '名称' },
  { key: 'asset_type', label: '资产' },
  { key: 'timeframe', label: '周期' },
  { key: 'adjust', label: '复权' },
  { key: 'status', label: '状态' },
  { key: 'rows', label: '行数' },
  { key: 'start_at', label: '开始' },
  { key: 'end_at', label: '结束' },
  { key: 'file_size_bytes', label: '大小' },
  { key: 'modified_at', label: '修改' },
  { key: 'path', label: '路径' },
  { key: 'message', label: '信息' }
]
const resultColumns = [
  { key: 'stock_code', label: '代码' },
  { key: 'timeframe', label: '周期' },
  { key: 'action', label: '动作' },
  { key: 'rows_written', label: '写入行' },
  { key: 'new_rows', label: '新增行' },
  { key: 'message', label: '信息' }
]
const taskEventColumns = [
  { key: '序号', label: '序号' },
  { key: '阶段', label: '阶段' },
  { key: '信息', label: '信息' },
  { key: '时间', label: '时间' }
]
const historyColumns = [
  { key: 'symbol', label: '代码' },
  { key: '股票', label: '股票' },
  { key: '窗口开始', label: '窗口开始' },
  { key: '窗口结束', label: '窗口结束' },
  { key: 'K线数量', label: 'K线' },
  { key: '综合相似度', label: '综合' },
  { key: '路径相似度', label: '路径' },
  { key: '区间收益', label: '收益' },
  { key: '最大回撤', label: '回撤' },
  { key: '后5根收益', label: '后5K' }
]
const historyForwardStatColumns = [
  { key: '观察窗口', label: '观察窗口' },
  { key: '样本数', label: '样本数' },
  { key: '平均收益', label: '平均收益' },
  { key: '中位收益', label: '中位收益' },
  { key: '胜率', label: '胜率' },
  { key: '最好窗口', label: '最好窗口' },
  { key: '最好收益', label: '最好收益' }
]
const crossColumns = [
  { key: 'symbol', label: '代码' },
  { key: '区间开始', label: '区间开始' },
  { key: '区间结束', label: '区间结束' },
  { key: '日期偏移', label: '偏移' },
  { key: '综合相似度', label: '综合' },
  { key: '路径相似度', label: '路径' },
  { key: '覆盖率', label: '覆盖' },
  { key: '区间收益', label: '收益' },
  { key: '后3根收益', label: '后3K' }
]
const reviewColumns = [
  { key: '排名', label: '排名' },
  { key: '代码', label: '代码' },
  { key: '股票', label: '股票' },
  { key: '强弱等级', label: '等级' },
  { key: '区间收益', label: '收益' },
  { key: '最大回撤', label: '回撤' },
  { key: '上涨K占比', label: '上涨K' },
  { key: '当前性质', label: '性质' },
  { key: '锐评结论', label: '结论' }
]
const comparisonColumns = [
  { key: '代码', label: '代码' },
  { key: '标的', label: '对标' },
  { key: '目标收益', label: '目标收益' },
  { key: '对比收益', label: '对比收益' },
  { key: '超额收益', label: '超额' },
  { key: '相关性', label: '相关' },
  { key: '波动关系', label: '关系' },
  { key: '强弱结论', label: '结论' }
]
const segmentColumns = [
  { key: '起点', label: '起点' },
  { key: '终点', label: '终点' },
  { key: '类型', label: '类型' },
  { key: 'K线数', label: 'K线' },
  { key: '区间收益', label: '收益' },
  { key: '最大回撤', label: '回撤' }
]

onMounted(async () => {
  restoreResearchSnapshots()
  await loadConfig()
  await Promise.all([loadOverview(false), loadTasks()])
  window.setInterval(() => {
    void loadTasks({ silent: true })
  }, 2500)
})

async function loadConfig() {
  try {
    config.value = await apiGet('/config')
    Object.assign(settings, config.value?.defaults || {})
    restoreSettings()
  } catch (error) {
    showError('配置加载失败', error)
    return
  }
  selectedTimeframe.value = config.value?.defaults?.timeframes?.[0] || '1d'
  researchTimeframe.value = selectedTimeframe.value
  const firstGroup = config.value?.symbol_groups?.[0]
  if (firstGroup) {
    selectedGroup.value = firstGroup.name
    symbolsText.value = firstGroup.symbols.join('\n')
  }
  void loadSymbolGroups(true)
}

async function loadSymbolGroups(preserveSelected: boolean, refreshTarget: SymbolRefreshTarget | '' = '') {
  loadingSymbolGroups.value = true
  const previousGroup = selectedGroup.value
  const previousSymbols = symbolsText.value
  let succeeded = false
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    const params = new URLSearchParams({
      data_root: settings.data_root,
      tdx_path: settings.tdx_path,
      adjust: settings.adjust
    })
    if (refreshTarget) params.set('target', refreshTarget)
    const data = await apiGet(`/symbol-groups?${params.toString()}`)
    if (config.value) config.value.symbol_groups = (data.groups || []).filter(isSymbolGroup)
    succeeded = true
  } catch (error) {
    showError('快捷代码加载失败', error)
  } finally {
    loadingSymbolGroups.value = false
  }
  if (!succeeded) return false
  if (preserveSelected && previousGroup === 'custom') return true
  const refreshed = config.value?.symbol_groups.find((item) => item.name === previousGroup)
  if (preserveSelected && refreshed) {
    symbolsText.value = refreshed.symbols.join('\n')
    return true
  }
  if (preserveSelected) {
    selectedGroup.value = 'custom'
    symbolsText.value = previousSymbols
    return true
  }
  const firstGroup = config.value?.symbol_groups?.[0]
  if (firstGroup) {
    selectedGroup.value = firstGroup.name
    symbolsText.value = firstGroup.symbols.join('\n')
  }
  return true
}

async function refreshShortcutGroup(target: SymbolRefreshTarget) {
  const targetGroup = target === 'index' ? '板块指数' : 'ETF列表'
  const targetLabel = target === 'index' ? '指数' : 'ETF'
  refreshingSymbolGroup.value = target
  try {
    const loaded = await loadSymbolGroups(true, target)
    if (!loaded) return
    const group = config.value?.symbol_groups.find((item) => item.name === targetGroup)
    if (!group || !group.symbols.length) {
      showNotice('info', `${targetLabel}列表为空`, `未从当前 TDX 路径读取到${targetLabel}列表，请检查 TDX PYPlugins/user 或代码表。`)
      return
    }
    selectedGroup.value = group.name
    symbolsText.value = group.symbols.join('\n')
    showNotice('success', `${targetLabel}列表已刷新`, `${group.name} 已读取 ${formatInt(group.symbols.length)} 只。`)
  } finally {
    refreshingSymbolGroup.value = ''
  }
}

async function loadOverview(refresh: boolean) {
  loadingOverview.value = true
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    const params = new URLSearchParams({
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      refresh: String(refresh)
    })
    overview.value = await apiGet(`/overview?${params.toString()}`)
    if (refresh) showNotice('success', '缓存扫描完成', 'SQLite 索引与缓存概览已刷新。')
    return true
  } catch (error) {
    showError(refresh ? '缓存扫描失败' : '缓存概览加载失败', error)
    return false
  } finally {
    loadingOverview.value = false
  }
}

async function refreshActiveView() {
  refreshingTopbar.value = true
  try {
    if (activeView.value === 'cache') {
      await loadOverview(true)
      return
    }
    if (activeView.value === 'tasks') {
      await loadTasks({ notify: true })
      return
    }
    if (activeView.value === 'download') {
      const [overviewOk, tasksOk] = await Promise.all([loadOverview(false), loadTasks({ silent: true })])
      if (overviewOk && tasksOk) showNotice('success', '状态已刷新', '下载任务进度和缓存概览已更新。')
      return
    }
    const [overviewOk, tasksOk] = await Promise.all([loadOverview(false), loadTasks({ silent: true })])
    if (overviewOk && tasksOk) showNotice('success', '页面已刷新', '概览和任务状态已更新。')
  } finally {
    refreshingTopbar.value = false
  }
}

async function previewPlan() {
  planning.value = true
  try {
    const data = await apiPost('/plan', payload())
    planSummary.value = data.summary || {}
    planRows.value = data.records || []
    showNotice('success', '计划已生成', `待下载 ${formatInt(planSummary.value.fetch_count)} 项，已可用 ${formatInt(planSummary.value.cached_count)} 项。`)
  } catch (error) {
    showError('预览计划失败', error)
  } finally {
    planning.value = false
  }
}

async function startDownload() {
  downloading.value = true
  try {
    const task = await apiPost('/download', payload())
    selectedTaskId.value = task.id
    activeView.value = 'tasks'
    await loadTasks()
    showNotice('info', '任务已提交', `后台任务 ${task.id.slice(0, 12)} 已进入队列。`)
  } catch (error) {
    showError('提交下载失败', error)
  } finally {
    downloading.value = false
  }
}

async function runHistorySearch() {
  runningResearch.value = 'history'
  try {
    historyResult.value = await apiPost('/research/history', {
      ...researchPayloadBase(),
      symbol: historyForm.symbol,
      window_start: historyForm.window_start || null,
      as_of: historyForm.as_of,
      window_size: Number(historyForm.window_size || 20),
      candidate_n: Number(historyForm.candidate_n || 100),
      top_n: Number(historyForm.top_n || 10),
      exclusion_bars: Number(historyForm.exclusion_bars || 0),
      nearby_gap_days: Number(historyForm.nearby_gap_days || 20),
      algorithm: historyForm.algorithm,
      forward_windows: parseNumberList(historyForm.forward_windows)
    })
    showNotice('success', '历史相似完成', `匹配 ${formatInt(historyResult.value?.summary?.match_count)} 个窗口。`)
  } catch (error) {
    showError('历史相似失败', error)
  } finally {
    runningResearch.value = ''
  }
}

async function runCrossSectionSearch() {
  runningResearch.value = 'cross'
  try {
    crossResult.value = await apiPost('/research/cross-section', {
      ...researchPayloadBase(),
      target_symbol: crossForm.target_symbol,
      universe_symbols: parseSymbols(crossForm.universe_symbols),
      start: crossForm.start,
      end: crossForm.end,
      top_n: Number(crossForm.top_n || 20),
      date_tolerance_bars: Number(crossForm.date_tolerance_bars || 0),
      forward_windows: parseNumberList(crossForm.forward_windows)
    })
    showNotice('success', '横截面搜索完成', `匹配 ${formatInt(crossResult.value?.summary?.match_count)} 个标的。`)
  } catch (error) {
    showError('横截面搜索失败', error)
  } finally {
    runningResearch.value = ''
  }
}

async function runReviewSearch() {
  runningResearch.value = 'review'
  try {
    reviewResult.value = await apiPost('/research/review', {
      ...researchPayloadBase(),
      symbols: parseSymbols(reviewForm.symbols),
      start: reviewForm.start,
      end: reviewForm.end,
      benchmark_symbol: reviewForm.benchmark_symbol,
      min_swing_return: Number(reviewForm.min_swing_return || 0),
      min_segment_bars: Number(reviewForm.min_segment_bars || 1)
    })
    reviewResultSignature.value = reviewSearchSignature()
    aiReviewOutput.value = null
    showNotice('success', '复盘已生成', `完成 ${formatInt(reviewResult.value?.summary?.ranked_count)} 个标的排序。`)
  } catch (error) {
    showError('复盘生成失败', error)
  } finally {
    runningResearch.value = ''
  }
}

async function runAiReview() {
  if (!reviewResult.value?.ai?.messages?.length) {
    showNotice('error', 'AI 证据缺失', '请先生成多股复盘。')
    return
  }
  if (!aiConfigReady.value) {
    aiReviewOutput.value = null
    showNotice('info', '使用本地规则锐评', '未填写完整 AI 接口参数，逐股锐评卡片由本地规则生成。')
    return
  }
  runningAiReview.value = true
  try {
    aiReviewOutput.value = await apiPost('/research/review-ai', {
      base_url: aiSettings.base_url.trim(),
      api_key: aiSettings.api_key.trim(),
      model: aiSettings.model.trim(),
      messages: reviewAiMessagesForRequest(),
      evidence: reviewResult.value.ai.evidence || {},
      temperature: Number(aiSettings.temperature ?? 0.2)
    })
    showNotice('success', 'AI 输出已生成', '模型返回已解析为复盘、分析和视频锐评。')
  } catch (error) {
    showError('AI 输出生成失败', error)
  } finally {
    runningAiReview.value = false
  }
}

function resetAiPromptSettings() {
  aiPromptDraft.system = ''
  aiPromptDraft.user = defaultAiUserPrompt()
  aiPromptSaved.value = false
  showNotice('info', '已恢复默认提示词', 'AI 覆盖将使用系统生成的默认 messages。')
}

function ensureAiPromptDraft() {
  if (!aiPromptDraft.system.trim()) aiPromptDraft.system = aiDefaultSystemPrompt.value
  if (!aiPromptDraft.user.trim()) aiPromptDraft.user = defaultAiUserPrompt()
}

function reviewAiMessagesForRequest() {
  if (!aiPromptSaved.value) return reviewResult.value?.ai?.messages || []
  const system = aiPromptDraft.system.trim() || aiDefaultSystemPrompt.value
  const userPrompt = aiPromptDraft.user.trim() || defaultAiUserPrompt()
  const evidence = JSON.stringify(reviewResult.value?.ai?.evidence || {}, null, 2)
  return [
    { role: 'system', content: system },
    { role: 'user', content: `${userPrompt}\n\n证据 JSON:\n${evidence}` },
  ]
}

function defaultAiUserPrompt() {
  return '请基于当前多股复盘证据生成逐股锐评卡片，保持 JSON 输出格式，重点强化排序理由、当前性质和明日验证。'
}

function saveActiveResearchSnapshot() {
  saveResearchSnapshot(activeResearchTab.value)
}

function saveResearchSnapshot(tab: ResearchTabKey) {
  const result = researchResultFor(tab)
  if (!result) {
    showNotice('info', '没有可保存结果', '先运行当前研究模块，再保存快照。')
    return
  }
  const snapshot: ResearchSnapshot = {
    id: `${tab}-${Date.now()}`,
    tab,
    title: researchSnapshotTitle(tab),
    createdAt: new Date().toLocaleString('zh-CN', { hour12: false }),
    summary: researchSnapshotSummary(tab, result),
    payload: researchSnapshotPayload(tab),
    result: cloneJson(result)
  }
  researchSnapshots.value = [snapshot, ...researchSnapshots.value].slice(0, MAX_RESEARCH_SNAPSHOTS)
  persistResearchSnapshots()
  showNotice('success', '快照已保存', `${activeResearchMetaFor(tab).label}结果已保存到本机浏览器。`)
}

function loadResearchSnapshot(snapshot: ResearchSnapshot) {
  activeResearchTab.value = snapshot.tab
  const base = snapshot.payload?.base || {}
  if (base.data_root) settings.data_root = normalizeDataRoot(String(base.data_root))
  if ('adjust' in base) settings.adjust = String(base.adjust || '')
  if (base.timeframe) researchTimeframe.value = String(base.timeframe)
  const form = snapshot.payload?.form || {}
  if (snapshot.tab === 'history') Object.assign(historyForm, form)
  if (snapshot.tab === 'cross') Object.assign(crossForm, form)
  if (snapshot.tab === 'review') Object.assign(reviewForm, form)
  setResearchResult(snapshot.tab, cloneJson(snapshot.result))
  if (snapshot.tab === 'review') reviewResultSignature.value = reviewSearchSignature()
  showNotice('success', '快照已载入', snapshot.title)
}

function deleteResearchSnapshot(snapshotId: string) {
  researchSnapshots.value = researchSnapshots.value.filter((snapshot) => snapshot.id !== snapshotId)
  persistResearchSnapshots()
  showNotice('info', '快照已删除', '本地研究快照列表已更新。')
}

async function loadTasks(options: { notify?: boolean; silent?: boolean } = {}) {
  try {
    const data = await apiGet('/tasks')
    tasks.value = data.tasks || []
    if (!selectedTaskId.value && tasks.value[0]) selectedTaskId.value = tasks.value[0].id
    if (options.notify) showNotice('success', '任务进度已刷新', '后台任务队列和过程记录已更新。')
    return true
  } catch (error) {
    if (!options.silent) showError('任务列表加载失败', error)
    return false
  }
}

async function clearTaskHistory() {
  clearingTasks.value = true
  try {
    const data = await apiDelete('/tasks')
    await loadTasks()
    if (!tasks.value.some((task) => task.id === selectedTaskId.value)) selectedTaskId.value = tasks.value[0]?.id || ''
    showNotice('success', '执行历史已清理', `已清理 ${formatInt(data.removed_count)} 条历史任务。`)
  } catch (error) {
    showError('清理任务失败', error)
  } finally {
    clearingTasks.value = false
  }
}

function selectTask(taskId: string) {
  selectedTaskId.value = taskId
}

async function pickDirectory(field: DirectoryField) {
  const labels: Record<DirectoryField, string> = {
    data_root: '行情根目录',
    tdx_path: 'TDX PYPlugins/user'
  }
  pickingDirectory.value = field
  try {
    const data = await apiPost('/pick-directory', {
      initial_directory: settings[field],
      title: `选择${labels[field]}`
    })
    if (!data.path || data.cancelled) return
    settings[field] = field === 'data_root' ? normalizeDataRoot(data.path) : data.path
    await loadSymbolGroups(true)
    showNotice('success', '目录已选择', `${labels[field]} 已更新。`)
  } catch (error) {
    showError('选择目录失败', error)
  } finally {
    pickingDirectory.value = ''
  }
}

function applySymbolGroup() {
  if (selectedGroup.value === 'custom') return
  const group = config.value?.symbol_groups.find((item) => item.name === selectedGroup.value)
  if (group) symbolsText.value = group.symbols.join('\n')
}

function applyAllAssetsRecentUpdate() {
  const days = Math.max(1, Math.trunc(Number(allAssetsLookbackDays.value) || DEFAULT_ALL_ASSETS_LOOKBACK_DAYS))
  allAssetsLookbackDays.value = days
  if (!allAssetSymbols.value.length) {
    showNotice('error', '全资产更新不可用', '当前代码库为空，请先刷新指数或 ETF 列表。')
    return
  }
  selectedGroup.value = 'custom'
  symbolsText.value = allAssetSymbols.value.join('\n')
  settings.start = offsetDateText(-days)
  settings.end = todayText()
  planRows.value = []
  planSummary.value = {}
  showNotice('success', '已应用全资产更新', `已载入 ${formatInt(allAssetSymbols.value.length)} 只资产，时间窗为近 ${days} 日。`)
}

function openReviewSymbolPicker(type: ReviewSymbolPickerType) {
  reviewSymbolPickerOpen.value = true
  reviewSymbolPickerType.value = type
  reviewSymbolPickerKeyword.value = ''
  prefillReviewSymbolSelection()
}

function closeReviewSymbolPicker() {
  reviewSymbolPickerOpen.value = false
}

function setReviewSymbolPickerType(type: ReviewSymbolPickerType) {
  reviewSymbolPickerType.value = type
  reviewSymbolPickerKeyword.value = ''
  prefillReviewSymbolSelection()
}

function reviewSymbolGroupsForType(type: ReviewSymbolPickerType) {
  const groups = config.value?.symbol_groups || []
  if (type === 'etf') return groups.filter((group) => group.name.toUpperCase().includes('ETF'))
  return groups.filter((group) => group.name.includes('板块指数'))
}

function reviewSymbolPickerCount(type: ReviewSymbolPickerType) {
  return formatInt(uniqueStringsInOrder(reviewSymbolGroupsForType(type).flatMap((group) => group.symbols)).length)
}

function prefillReviewSymbolSelection() {
  const current = new Set(parseSymbols(reviewForm.symbols))
  const currentGroupSymbols = reviewSymbolPickerRows.value.map((row) => row.symbol)
  const selected = currentGroupSymbols.filter((symbol) => current.has(symbol))
  reviewSymbolPickerSelection.value = selected.length ? selected : currentGroupSymbols
}

function isReviewSymbolSelected(symbol: string) {
  return reviewSymbolPickerSelectionSet.value.has(symbol)
}

function toggleReviewSymbol(symbol: string) {
  if (isReviewSymbolSelected(symbol)) {
    reviewSymbolPickerSelection.value = reviewSymbolPickerSelection.value.filter((item) => item !== symbol)
    return
  }
  reviewSymbolPickerSelection.value = uniqueStringsInOrder([...reviewSymbolPickerSelection.value, symbol])
}

function selectFilteredReviewSymbols() {
  reviewSymbolPickerSelection.value = uniqueStringsInOrder([
    ...reviewSymbolPickerSelection.value,
    ...filteredReviewSymbolPickerRows.value.map((row) => row.symbol)
  ])
}

function selectAllReviewSymbols() {
  reviewSymbolPickerSelection.value = reviewSymbolPickerRows.value.map((row) => row.symbol)
}

function clearReviewSymbolSelection() {
  reviewSymbolPickerSelection.value = []
}

function applyReviewSymbolSelection(mode: 'append' | 'replace') {
  const selected = reviewSymbolPickerSelection.value
  if (!selected.length) return
  const symbols = mode === 'append' ? uniqueStringsInOrder([...parseSymbols(reviewForm.symbols), ...selected]) : selected
  reviewForm.symbols = symbols.join('\n')
  reviewResult.value = null
  aiReviewOutput.value = null
  reviewResultSignature.value = ''
  closeReviewSymbolPicker()
  showNotice('success', '复盘标的已更新', `${mode === 'append' ? '追加' : '替换'} ${formatInt(selected.length)} 只${reviewSymbolPickerTypeLabel.value}。`)
}

function isSymbolGroup(value: any): value is SymbolGroup {
  return value && typeof value.name === 'string' && Array.isArray(value.symbols)
}

function payload() {
  settings.data_root = normalizeDataRoot(settings.data_root)
  return {
    ...settings,
    symbols: parsedSymbols.value,
    timeframes: [selectedTimeframe.value],
    batch_size: Number(settings.batch_size || 100)
  }
}

function researchPayloadBase() {
  settings.data_root = normalizeDataRoot(settings.data_root)
  return {
    data_root: settings.data_root,
    adjust: settings.adjust,
    timeframe: researchTimeframe.value
  }
}

function reviewSearchSignature() {
  return JSON.stringify({
    data_root: normalizeDataRoot(settings.data_root),
    adjust: settings.adjust,
    timeframe: researchTimeframe.value,
    symbols: parseSymbols(reviewForm.symbols),
    start: reviewForm.start,
    end: reviewForm.end,
    benchmark_symbol: reviewForm.benchmark_symbol,
    min_swing_return: Number(reviewForm.min_swing_return || 0),
    min_segment_bars: Number(reviewForm.min_segment_bars || 1)
  })
}

function researchSnapshotPayload(tab: ResearchTabKey) {
  const form = {
    history: { ...historyForm },
    cross: { ...crossForm },
    review: { ...reviewForm }
  }[tab]
  return {
    base: researchPayloadBase(),
    form: cloneJson(form)
  }
}

function researchSnapshotTitle(tab: ResearchTabKey) {
  if (tab === 'history') return `历史相似 · ${historyForm.symbol || '-'} · ${historyForm.window_start || '-'} 至 ${historyForm.as_of || '-'}`
  if (tab === 'cross') return `横截面相似 · ${crossForm.target_symbol || '-'} · ${crossForm.start || '-'} 至 ${crossForm.end || '-'}`
  const count = parseSymbols(reviewForm.symbols).length
  return `多股复盘 · ${formatInt(count)} 标的 · ${reviewForm.start || '-'} 至 ${reviewForm.end || '-'}`
}

function researchSnapshotSummary(tab: ResearchTabKey, result: Record<string, any>) {
  const payloadSummary = result.summary || {}
  if (tab === 'history') return `${formatInt(payloadSummary.match_count)} 个历史窗口 · ${payloadSummary.timeframe || researchTimeframe.value}`
  if (tab === 'cross') return `${formatInt(payloadSummary.match_count)} 个候选匹配 · ${payloadSummary.timeframe || researchTimeframe.value}`
  return `${formatInt(payloadSummary.ranked_count)} 个排序标的 · ${payloadSummary.timeframe || researchTimeframe.value}`
}

function researchResultFor(tab: ResearchTabKey) {
  if (tab === 'history') return historyResult.value
  if (tab === 'cross') return crossResult.value
  return reviewResult.value
}

function setResearchResult(tab: ResearchTabKey, result: Record<string, any>) {
  if (tab === 'history') historyResult.value = result
  if (tab === 'cross') crossResult.value = result
  if (tab === 'review') reviewResult.value = result
}

function activeResearchMetaFor(tab: ResearchTabKey) {
  return researchTabs.find((item) => item.key === tab) || researchTabs[0]
}

function restoreResearchSnapshots() {
  const raw = window.localStorage.getItem(RESEARCH_SNAPSHOT_STORAGE_KEY)
  if (!raw) return
  try {
    const parsed = JSON.parse(raw)
    researchSnapshots.value = Array.isArray(parsed) ? parsed.filter(isResearchSnapshot).slice(0, MAX_RESEARCH_SNAPSHOTS) : []
  } catch {
    window.localStorage.removeItem(RESEARCH_SNAPSHOT_STORAGE_KEY)
  }
}

function persistResearchSnapshots() {
  window.localStorage.setItem(RESEARCH_SNAPSHOT_STORAGE_KEY, JSON.stringify(researchSnapshots.value))
}

function isResearchSnapshot(value: any): value is ResearchSnapshot {
  return (
    value &&
    ['history', 'cross', 'review'].includes(value.tab) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    value.result &&
    typeof value.result === 'object'
  )
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

function saveSettings() {
  settings.data_root = normalizeDataRoot(settings.data_root)
  ensureAiPromptDraft()
  window.localStorage.setItem(
    SETTINGS_STORAGE_KEY,
    JSON.stringify({
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      batch_size: settings.batch_size,
      strict_after_update: settings.strict_after_update,
      ai: {
        base_url: aiSettings.base_url,
        api_key: aiSettings.api_key,
        model: aiSettings.model,
        temperature: aiSettings.temperature,
        prompt_enabled: aiPromptSaved.value,
        prompt_system: aiPromptDraft.system,
        prompt_user: aiPromptDraft.user
      }
    })
  )
  showNotice('success', '设置已保存', '下次打开控制台会自动使用当前路径、运行参数和 AI 锐评设置。')
}

function resetSettings() {
  window.localStorage.removeItem(SETTINGS_STORAGE_KEY)
  Object.assign(settings, config.value?.defaults || {})
  Object.assign(aiSettings, defaultAiSettings())
  aiPromptDraft.system = ''
  aiPromptDraft.user = defaultAiUserPrompt()
  aiPromptSaved.value = false
  settings.data_root = normalizeDataRoot(settings.data_root)
  selectedTimeframe.value = config.value?.defaults?.timeframes?.[0] || '1d'
  showNotice('info', '已恢复默认', '已恢复 API 提供的默认路径、运行参数和默认 AI 设置。')
}

function restoreSettings() {
  const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (saved.data_root) saved.data_root = normalizeDataRoot(saved.data_root)
    Object.assign(settings, {
      data_root: saved.data_root || settings.data_root,
      adjust: saved.adjust ?? settings.adjust,
      tdx_path: saved.tdx_path || settings.tdx_path,
      batch_size: saved.batch_size ?? settings.batch_size,
      strict_after_update: saved.strict_after_update ?? settings.strict_after_update
    })
    if (saved.ai && typeof saved.ai === 'object') {
      Object.assign(aiSettings, {
        base_url: saved.ai.base_url || aiSettings.base_url,
        api_key: saved.ai.api_key || '',
        model: saved.ai.model || '',
        temperature: saved.ai.temperature ?? aiSettings.temperature
      })
      aiPromptDraft.system = String(saved.ai.prompt_system || '')
      aiPromptDraft.user = String(saved.ai.prompt_user || defaultAiUserPrompt())
      aiPromptSaved.value = Boolean(saved.ai.prompt_enabled)
    }
  } catch {
    window.localStorage.removeItem(SETTINGS_STORAGE_KEY)
  }
}

function defaultAiSettings() {
  return {
    base_url: 'https://api.openai.com/v1',
    api_key: '',
    model: '',
    temperature: 0.2
  }
}

async function apiGet(path: string) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function apiDelete(path: string) {
  const response = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function apiPost(path: string, body: Record<string, any>) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

function parseSymbols(text: string) {
  return text.split(/[\s,;，、]+/).map((item) => item.trim()).filter(Boolean)
}

function parseNumberList(text: string) {
  const values = text
    .split(/[\s,;，、]+/)
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0)
  return values.length ? values : [5]
}

function chartActualRange(items: Array<Record<string, any>>) {
  const dates = items
    .flatMap((item) => (Array.isArray(item.candles) ? item.candles : []))
    .map((row: Record<string, any>) => String(row.date || '').slice(0, 10))
    .filter(Boolean)
    .sort()
  if (!dates.length) return null
  return { start: dates[0], end: dates[dates.length - 1] }
}

function candleWindowReturn(candles: Array<Record<string, any>>) {
  if (!candles.length) return NaN
  const first = Number(candles[0]?.close)
  const last = Number(candles[candles.length - 1]?.close)
  if (!Number.isFinite(first) || !Number.isFinite(last) || first === 0) return NaN
  return last / first - 1
}

function historyForwardReturnKeys(rows: Array<Record<string, any>>) {
  const byHorizon = new Map<number, string>()
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => {
      const match = /^t_plus_(\d+)_return$/.exec(key) || /^后(\d+)根收益$/.exec(key)
      const horizon = Number(match?.[1] || 0)
      if (!horizon) return
      if (!byHorizon.has(horizon) || key.startsWith('t_plus_')) byHorizon.set(horizon, key)
    })
  })
  return Array.from(byHorizon.entries())
    .map(([horizon, key]) => ({ key, horizon }))
    .sort((left, right) => left.horizon - right.horizon)
}

function historyWindowLabel(row: Record<string, any>) {
  const start = formatDateOnly(row['窗口开始'])
  const end = formatDateOnly(row['窗口结束'])
  return start && end ? `${start} 至 ${end}` : '-'
}

function klineSegment(candles: Array<Record<string, any>>, direction: string) {
  return {
    start: String(candles[0]?.date || '').slice(0, 10),
    end: String(candles[candles.length - 1]?.date || '').slice(0, 10),
    direction
  }
}

function todayText() {
  return formatDateText(new Date())
}

function offsetDateText(offsetDays: number) {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  return formatDateText(date)
}

function applyDateShortcut(target: DateRangeFields, key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  target.start = range.start
  target.end = range.end
}

function applyHistoryDateShortcut(key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  historyForm.window_start = range.start
  historyForm.as_of = range.end
}

function isDateShortcutActive(target: DateRangeFields, key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  return target.start === range.start && target.end === range.end
}

function isHistoryDateShortcutActive(key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  return historyForm.window_start === range.start && historyForm.as_of === range.end
}

function dateRangeForShortcut(key: DateShortcutKey): DateRangeFields {
  const end = todayText()
  if (key === '20d') return { start: offsetDateText(-20), end }
  if (key === '50d') return { start: offsetDateText(-50), end }
  if (key === 'ytd') return { start: `${new Date().getFullYear()}-01-01`, end }
  const start = new Date()
  start.setFullYear(start.getFullYear() - 1)
  return { start: formatDateText(start), end }
}

function formatDateText(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function compactPath(path: string) {
  if (!path) return '未设置'
  return path.length > 34 ? `${path.slice(0, 16)}...${path.slice(-14)}` : path
}

function normalizeDataRoot(path: string) {
  const text = String(path || '').trim().replace(/\/+$/, '')
  if (!text) return ''
  const parts = text.split('/')
  const last = parts[parts.length - 1]?.toLowerCase() || ''
  if (parts.length > 1 && KNOWN_TIMEFRAME_DIRS.has(last)) {
    return parts.slice(0, -1).join('/') || '/'
  }
  return text
}

function timeframeDirectoryName(timeframe: string) {
  return TIMEFRAME_DIR_NAMES[timeframe] || timeframe
}

function joinPath(root: string, child: string) {
  const normalizedRoot = normalizeDataRoot(root).replace(/\/+$/, '')
  return `${normalizedRoot}/${child}`.replace(/^\/\//, '/')
}

function formatInt(value: unknown) {
  const numberValue = Number(value || 0)
  return Number.isFinite(numberValue) ? Math.round(numberValue).toLocaleString() : '0'
}

function formatBytes(value: unknown) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

function numberValue(value: unknown) {
  const numberValue = Number(value || 0)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function uniqueStrings(values: unknown[]) {
  return Array.from(new Set(values.map((value) => String(value || '')).filter(Boolean))).sort()
}

function uniqueStringsInOrder(values: unknown[]) {
  const seen = new Set<string>()
  const output: string[] = []
  for (const value of values) {
    const item = String(value || '').trim()
    if (!item || seen.has(item)) continue
    seen.add(item)
    output.push(item)
  }
  return output
}

function sortTimeframes(values: unknown[]) {
  return uniqueStrings(values).sort((left, right) => timeframeRank(left) - timeframeRank(right) || left.localeCompare(right))
}

function timeframeRank(value: string) {
  const preferredOrder = ['1d', '1m', '5m', '15m', '30m', '60m']
  const preferredIndex = preferredOrder.indexOf(value)
  if (preferredIndex >= 0) return preferredIndex
  const match = /^(\d+)([md])$/.exec(value)
  if (!match) return Number.MAX_SAFE_INTEGER
  const count = Number(match[1])
  return match[2] === 'd' ? 1000 + count : 100 + count
}

function sumDatasetCount(rows: Array<Record<string, any>>, predicate: (row: Record<string, any>) => boolean = () => true) {
  return rows.filter(predicate).reduce((total, row) => total + numberValue(row.count), 0)
}

function displayRecord(row: Record<string, any>) {
  const labels = new Map((config.value?.asset_types || []).map((item: Record<string, string>) => [item.value, item.label]))
  return {
    ...row,
    asset_type: labels.get(String(row.asset_type || '')) || row.asset_type,
    status: STATUS_LABELS[String(row.status || '')] || row.status,
    action: STATUS_LABELS[String(row.action || '')] || row.action,
    reason: STATUS_LABELS[String(row.reason || '')] || row.reason,
    before_status: STATUS_LABELS[String(row.before_status || '')] || row.before_status,
    after_status: STATUS_LABELS[String(row.after_status || '')] || row.after_status
  }
}

function displayCacheRecord(row: Record<string, any>) {
  return {
    ...displayRecord(row),
    start_at: formatDateTimeText(row.start_at),
    end_at: formatDateTimeText(row.end_at),
    modified_at: formatDateTimeText(row.modified_at),
    file_size_bytes: formatBytes(row.file_size_bytes),
    path: row.path || '',
    message: row.message || ''
  }
}

function setCachePageSize(size: number) {
  cachePagination.pageSize = size
  cachePagination.page = 1
}

function goCachePage(page: number) {
  cachePagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), cacheTotalPages.value)
}

function setTaskEventPageSize(size: number) {
  taskEventPagination.pageSize = size
  taskEventPagination.page = 1
}

function goTaskEventPage(page: number) {
  taskEventPagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), taskEventTotalPages.value)
}

function setTaskResultPageSize(size: number) {
  taskResultPagination.pageSize = size
  taskResultPagination.page = 1
}

function goTaskResultPage(page: number) {
  taskResultPagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), taskResultTotalPages.value)
}

function formatDateTimeText(value: unknown) {
  if (value === null || value === undefined || value === '' || value === 'NaT') return ''
  const text = String(value)
  if (/^\d{4}-\d{2}-\d{2}T00:00:00/.test(text)) return text.slice(0, 10)
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return text.replace('T', ' ').replace(/\.\d+.*$/, '').slice(0, 16)
  return text
}

function formatDateOnly(value: unknown) {
  if (value === null || value === undefined || value === '' || value === 'NaT') return ''
  const text = String(value)
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10)
  return text
}

function displayResearchRecord(row: Record<string, any>) {
  const output: Record<string, any> = {}
  for (const [key, value] of Object.entries(row)) {
    output[key] = formatResearchValue(key, value)
  }
  return output
}

function formatResearchValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) return value.slice(0, 10)
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  if (key.includes('收益') || key.includes('回撤') || key.includes('占比') || key.includes('覆盖率')) {
    return `${(number * 100).toFixed(2)}%`
  }
  if (key.includes('相似度') || key.includes('距离') || key === '排序分') {
    return number.toFixed(4)
  }
  if (Number.isInteger(number)) return number.toLocaleString()
  return number.toFixed(2)
}

function formatPercentValue(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : '-'
}

function formatDecimalValue(value: unknown, digits = 2) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(digits) : '-'
}

function meanValue(values: number[]) {
  if (!values.length) return NaN
  return values.reduce((total, value) => total + value, 0) / values.length
}

function medianValue(values: number[]) {
  if (!values.length) return NaN
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  if (sorted.length % 2) return sorted[middle]
  return (sorted[middle - 1] + sorted[middle]) / 2
}

function markdownBlocks(text: string): ReviewMarkdownBlock[] {
  return text
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const lines = chunk.split('\n').map((line) => line.trim()).filter(Boolean)
      const tableLines = lines.filter((line) => line.startsWith('|'))
      if (tableLines.length) {
        const rows = tableLines.map(tableCells)
        const [headers = [], ...bodyRows] = rows.filter((cells) => !isMarkdownDividerRow(cells))
        return {
          type: 'table',
          title: '',
          lines: [],
          headers,
          rows: bodyRows
        }
      }
      return textBlock(lines)
    })
}

function textBlock(lines: string[]): ReviewMarkdownBlock {
  const cleaned = lines.map(cleanMarkdownLine).filter(Boolean)
  if (!cleaned.length) {
    return { type: 'paragraph', title: '', lines: [], headers: [], rows: [] }
  }
  const [firstLine, ...rest] = cleaned
  const titledLine = firstLine.match(/^(.+?)[:：]\s*(.*)$/)
  if (titledLine && rest.length === 0) {
    return {
      type: 'section',
      title: titledLine[1].trim(),
      lines: titledLine[2] ? [titledLine[2].trim()] : [],
      headers: [],
      rows: []
    }
  }
  if (rest.length) {
    return {
      type: 'section',
      title: firstLine.replace(/[:：]$/, ''),
      lines: rest,
      headers: [],
      rows: []
    }
  }
  return {
    type: 'paragraph',
    title: '',
    lines: [firstLine],
    headers: [],
    rows: []
  }
}

function cleanMarkdownLine(line: string) {
  return line
    .replace(/\*\*/g, '')
    .replace(/^[-*]\s+/, '• ')
    .trim()
}

function tableCells(line: string) {
  return line
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cleanMarkdownLine(cell))
}

function isMarkdownDividerRow(cells: string[]) {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s/g, '')))
}

function reviewScriptGradeClass(grade: string) {
  const gradeText = String(grade || '')
  const gradeMap: Record<string, string> = {
    '夯爆了': 'grade-s',
    '人上人': 'grade-a',
    '立棍单打': 'grade-b',
    '刷子': 'grade-c',
    '路边': 'grade-d',
    '混子': 'grade-d',
    NPC: 'grade-e',
    '拉完了': 'grade-f'
  }
  return gradeMap[gradeText] || 'grade-neutral'
}

function isInlineReviewBlock(block: ReviewMarkdownBlock) {
  if (block.title === '逐个锐评') return true
  return /（\d{6}\.(SH|SZ|BJ)）$/.test(block.title)
}

function showNotice(type: NoticePayload['type'], title: string, body: string) {
  notice.value = { type, title, body }
}

function showError(title: string, error: unknown) {
  showNotice('error', title, extractErrorMessage(error))
}

function extractErrorMessage(error: unknown) {
  if (error instanceof Error) {
    try {
      const parsed = JSON.parse(error.message)
      return parsed.detail || parsed.message || error.message
    } catch {
      return error.message
    }
  }
  return String(error)
}
</script>
