<template>
  <div :class="['app-shell', chartThemeClass, chartDensityClass]">
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
          <button class="resize-reset-button" type="button" title="还原卡片尺寸" @click="resetResizableCards">
            还原卡片尺寸
          </button>
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

        <section class="ai-command-shell" aria-label="大模型命令框">
          <div class="ai-command-head">
            <div>
              <strong>大模型命令框</strong>
              <span>{{ aiCommandScopeLabel }}</span>
            </div>
            <em>{{ aiConfigReady ? `模型 ${aiSettings.model}` : '未配置模型时使用本地规则规划' }}</em>
          </div>
          <form class="ai-command-form" @submit.prevent="runAiCommand">
            <textarea
              v-model="aiCommandForm.text"
              rows="2"
              placeholder="例如：帮我选择所有创业板股票；把风险参数调保守；基准60日涨幅设为12%"
            ></textarea>
            <button class="btn primary" type="submit" :disabled="runningAiCommand || !aiCommandForm.text.trim()">
              <Icon name="sparkles" />
              {{ runningAiCommand ? '解析中' : '解析并应用' }}
            </button>
          </form>
          <div v-if="aiCommandResult" class="ai-command-result">
            <strong>{{ aiCommandResult.summary }}</strong>
            <span v-for="item in aiCommandResult.patches || []" :key="`${item.target}-${item.label}`">{{ item.summary || item.label }}</span>
            <em v-for="item in aiCommandResult.warnings || []" :key="item">{{ item }}</em>
          </div>
        </section>

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
            <div v-for="item in dashboardKeyStats" :key="item.label" class="dashboard-stat" data-resizable-card>
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
              data-resizable-card
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
            <div v-if="latestTask" class="recent-task-card compact" data-resizable-card>
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
                  <span>按当前代码库合并股票、ETF、指数和板块，生成近 N 个交易日任务。</span>
                </div>
                <label>
                  <span>近 N 交易日</span>
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

              <div class="span-full timeframe-picker">
                <div class="field-head">
                  <span>周期</span>
                  <div class="field-actions">
                    <button class="mini-action" type="button" @click="selectAllDownloadTimeframes">全周期</button>
                    <button class="mini-action" type="button" @click="selectDefaultDownloadTimeframe">默认</button>
                  </div>
                </div>
                <div class="timeframe-options">
                  <label
                    v-for="timeframe in downloadTimeframeOptions"
                    :key="timeframe"
                    :class="['timeframe-option', { selected: isDownloadTimeframeSelected(timeframe) }]"
                  >
                    <input
                      type="checkbox"
                      :checked="isDownloadTimeframeSelected(timeframe)"
                      @change="toggleDownloadTimeframe(timeframe)"
                    />
                    <span>{{ timeframe }}</span>
                  </label>
                </div>
              </div>

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
                <MetricCard title="周期" :value="downloadTimeframeSummary" detail="已选择" tone="green" icon="clock" />
                <MetricCard title="待下载" :value="formatInt(planSummary.fetch_count)" detail="来自预览" tone="red" icon="download" />
                <MetricCard title="已可用" :value="formatInt(planSummary.cached_count)" detail="无需下载" tone="amber" icon="database" />
              </div>
            </Panel>

            <Panel title="下载计划" subtitle="翻页查看">
              <div v-if="planRows.length" class="table-toolbar">
                <p class="table-caption">显示 {{ planPageFirst }}-{{ planPageEnd }} / {{ planRows.length }} 条</p>
                <div class="table-controls">
                  <div class="page-size-group">
                    <span>每页</span>
                    <button
                      v-for="size in planPageSizeOptions"
                      :key="size"
                      type="button"
                      :class="['page-size-button', { active: planPagination.pageSize === size }]"
                      @click="setPlanPageSize(size)"
                    >
                      {{ size }}
                    </button>
                  </div>
                  <div class="pagination-controls">
                    <button type="button" :disabled="planPagination.page <= 1" @click="goPlanPage(1)">首页</button>
                    <button type="button" :disabled="planPagination.page <= 1" @click="goPlanPage(planPagination.page - 1)">上一页</button>
                    <span>{{ planPagination.page }} / {{ planTotalPages }}</span>
                    <button type="button" :disabled="planPagination.page >= planTotalPages" @click="goPlanPage(planPagination.page + 1)">下一页</button>
                    <button type="button" :disabled="planPagination.page >= planTotalPages" @click="goPlanPage(planTotalPages)">末页</button>
                  </div>
                </div>
              </div>
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
            <Panel title="横截面相似" :subtitle="crossSearchModeLabel">
              <form class="task-form" @submit.prevent="runCrossSectionSearch">
                <label>
                  <span>目标标的</span>
                  <input v-model="crossForm.target_symbol" type="text" />
                </label>
                <label>
                  <span>搜索方式</span>
                  <select v-model="crossForm.search_mode">
                    <option value="same_date">同区间</option>
                    <option value="traversal">指定区间</option>
                  </select>
                </label>
                <label>
                  <span>返回数量</span>
                  <input v-model.number="crossForm.top_n" type="number" min="1" />
                </label>
                <div class="field-cluster span-full">
                  <div class="field-cluster-head">
                    <strong>目标锚定区间</strong>
                    <span>用于建立目标走势</span>
                  </div>
                  <div class="inline-fields">
                    <label>
                      <span>目标开始</span>
                      <input v-model="crossForm.start" type="date" />
                    </label>
                    <label>
                      <span>目标结束</span>
                      <input v-model="crossForm.end" type="date" />
                    </label>
                  </div>
                  <div class="date-shortcuts" aria-label="目标日期快捷选项">
                    <span>目标快捷</span>
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
                </div>
                <div class="field-cluster span-full" :class="{ muted: crossForm.search_mode !== 'traversal' }">
                  <div class="field-cluster-head">
                    <strong>候选搜索区间</strong>
                    <span>{{ crossForm.search_mode === 'traversal' ? '约束候选窗口起始范围' : '同区间模式下使用目标区间与日期容忍' }}</span>
                  </div>
                  <div class="inline-fields">
                    <label>
                      <span>候选开始</span>
                      <input v-model="crossForm.traversal_start" type="date" :disabled="crossForm.search_mode !== 'traversal'" />
                    </label>
                    <label>
                      <span>候选结束</span>
                      <input v-model="crossForm.traversal_end" type="date" :disabled="crossForm.search_mode !== 'traversal'" />
                    </label>
                  </div>
                  <div class="date-shortcuts" aria-label="候选日期快捷选项">
                    <span>候选快捷</span>
                    <button
                      v-for="shortcut in DATE_RANGE_SHORTCUTS"
                      :key="shortcut.key"
                      type="button"
                      :disabled="crossForm.search_mode !== 'traversal'"
                      :class="['date-shortcut', { active: isCandidateDateShortcutActive(shortcut.key) }]"
                      @click="applyCandidateDateShortcut(shortcut.key)"
                    >
                      {{ shortcut.label }}
                    </button>
                  </div>
                </div>
                <label v-if="crossForm.search_mode === 'same_date'">
                  <span>日期容忍K数</span>
                  <input v-model.number="crossForm.date_tolerance_bars" type="number" min="0" />
                </label>
                <label v-else>
                  <span>邻近排除K数</span>
                  <input v-model.number="crossForm.exclusion_bars" type="number" min="0" />
                </label>
                <label>
                  <span>前瞻K数</span>
                  <input v-model="crossForm.forward_windows" type="text" />
                </label>
                <label class="span-full">
                  <div class="field-head">
                    <span>候选标的</span>
                    <div class="field-actions">
                      <button class="mini-action" type="button" @click="setCrossUniverseFromAssetType('etf')">
                        <Icon name="archive" />
                        所有ETF
                      </button>
                      <button class="mini-action" type="button" @click="setCrossUniverseFromAssetType('stock')">
                        <Icon name="key" />
                        所有个股
                      </button>
                      <button class="mini-action" type="button" @click="setCrossUniverseFromAssetType('index')">
                        <Icon name="layers" />
                        所有指数
                      </button>
                    </div>
                  </div>
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

          <section v-else-if="activeResearchTab === 'etf'" class="view-stack etf-tracker-view">
            <Panel class="etf-control-surface" title="场内 ETF 跟踪" subtitle="分类行情 / 同类合并">
              <form class="task-form etf-tracker-form" @submit.prevent="runEtfTrackerReview">
                <label>
                  <span>类别</span>
                  <select v-model="etfTrackerForm.category">
                    <option v-for="category in ETF_TRACKER_CATEGORY_OPTIONS" :key="category.value" :value="category.value">
                      {{ category.label }}
                    </option>
                  </select>
                </label>
                <label>
                  <span>类型</span>
                  <select v-model="etfTrackerForm.type">
                    <option value="">全部类型</option>
                    <option value="股票型">股票型</option>
                    <option value="其他型">其他型</option>
                  </select>
                </label>
                <label>
                  <span>跟踪指数</span>
                  <select v-model="etfTrackerForm.tracking_index">
                    <option value="">全部指数</option>
                    <option v-for="indexName in etfTrackingIndexOptions" :key="indexName" :value="indexName">
                      {{ indexName }}
                    </option>
                  </select>
                </label>
                <label>
                  <span>搜索</span>
                  <input v-model="etfTrackerForm.keyword" type="search" placeholder="代码、名称或指数" />
                </label>
                <label class="review-ai-toggle">
                  <input v-model="etfTrackerForm.merge_similar" type="checkbox" />
                  <span>合并同类ETF</span>
                  <em>同类取成交额最大</em>
                </label>
                <label>
                  <span>复盘数量</span>
                  <input v-model.number="etfTrackerForm.top_n" type="number" min="1" max="200" />
                </label>
                <div class="inline-fields span-full">
                  <label>
                    <span>开始</span>
                    <input v-model="etfTrackerForm.start" type="date" />
                  </label>
                  <label>
                    <span>结束</span>
                    <input v-model="etfTrackerForm.end" type="date" />
                  </label>
                  <label>
                    <span>对标指数</span>
                    <input v-model="etfTrackerForm.benchmark_symbol" type="text" placeholder="000300.SH" />
                  </label>
                </div>
                <div class="date-shortcuts span-full" aria-label="ETF日期快捷选项">
                  <span>快捷</span>
                  <button
                    v-for="shortcut in DATE_RANGE_SHORTCUTS"
                    :key="shortcut.key"
                    type="button"
                    :class="['date-shortcut', { active: isDateShortcutActive(etfTrackerForm, shortcut.key) }]"
                    @click="applyDateShortcut(etfTrackerForm, shortcut.key)"
                  >
                    {{ shortcut.label }}
                  </button>
                </div>
                <div class="etf-cache-strip span-full" aria-label="ETF缓存状态">
                  <span class="etf-cache-title">缓存状态</span>
                  <div
                    v-for="item in etfCacheStatusCards"
                    :key="item.label"
                    :class="['etf-cache-pill', item.tone]"
                  >
                    <strong>{{ item.label }}</strong>
                    <em>{{ item.detail }}</em>
                    <b>{{ item.value }}</b>
                  </div>
                  <button class="mini-action" type="button" @click="clearEtfClientCache">清理ETF缓存</button>
                </div>
                <label>
                  <span>最小波段幅度</span>
                  <input v-model.number="etfTrackerForm.min_swing_return" type="number" min="0" step="0.01" />
                </label>
                <label>
                  <span>最小波段K数</span>
                  <input v-model.number="etfTrackerForm.min_segment_bars" type="number" min="1" />
	                </label>
	                <div class="form-actions span-full">
	                  <button class="btn secondary" type="button" :disabled="loadingEtfTracking" @click="loadEtfTracking(true)">
	                    <Icon name="refresh" />
	                    {{ loadingEtfTracking ? '读取中' : '刷新TDX ETF接口' }}
	                  </button>
                    <button class="btn secondary" type="button" :disabled="loadingEtfReturns" @click="loadEtfReturns(true)">
                      <Icon name="refresh" />
                      {{ loadingEtfReturns ? '计算中' : '刷新收益率' }}
                    </button>
	                  <button class="btn primary" type="submit" :disabled="runningResearch === 'etf' || !etfTrackerReviewSymbols.length">
	                    <Icon name="activity" />
	                    生成 ETF 趋势对比
                  </button>
                  <button class="btn secondary" type="button" :disabled="!etfTrackerReviewSymbols.length" @click="loadEtfTrackerSymbolsToReview">
                    <Icon name="clipboard" />
                    载入多股复盘
                  </button>
                </div>
              </form>
            </Panel>

            <section class="dashboard-strip etf-tracker-strip etf-soft-band">
              <div v-for="item in etfTrackerSummaryCards" :key="item.label" class="dashboard-stat" data-resizable-card>
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <em>{{ item.detail }}</em>
              </div>
            </section>

            <section class="etf-candidate-row etf-result-surface">
              <Panel class="etf-candidate-panel etf-candidate-wide-panel" title="ETF 候选池" subtitle="筛选结果">
                <div v-if="etfTrackerDisplayRows.length" class="table-toolbar etf-candidate-toolbar">
                  <p class="table-caption">
                    显示 {{ etfTrackerPageFirst }}-{{ etfTrackerPageEnd }} / {{ etfTrackerDisplayRows.length }} 条
                  </p>
                  <div class="table-controls">
                    <div class="page-size-group" aria-label="ETF候选池每页条数">
                      <span>每页</span>
                      <button
                        v-for="size in etfTrackerPageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: etfTrackerPagination.pageSize === size }]"
                        @click="setEtfTrackerPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button type="button" :disabled="etfTrackerPagination.page <= 1" @click="goEtfTrackerPage(1)">首页</button>
                      <button type="button" :disabled="etfTrackerPagination.page <= 1" @click="goEtfTrackerPage(etfTrackerPagination.page - 1)">上一页</button>
                      <span>{{ etfTrackerPagination.page }} / {{ etfTrackerTotalPages }}</span>
                      <button type="button" :disabled="etfTrackerPagination.page >= etfTrackerTotalPages" @click="goEtfTrackerPage(etfTrackerPagination.page + 1)">下一页</button>
                      <button type="button" :disabled="etfTrackerPagination.page >= etfTrackerTotalPages" @click="goEtfTrackerPage(etfTrackerTotalPages)">末页</button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="displayEtfTrackerRows" :columns="etfTrackerColumns" empty="暂无匹配 ETF。" />
              </Panel>
            </section>

            <section class="content-grid two etf-tracker-grid etf-insight-surface">
              <Panel class="etf-insight-panel" title="ETF趋势对比" subtitle="复盘排序">
                <div v-if="etfTrackerTrendCards.length" class="etf-trend-stack">
                  <article v-for="card in etfTrackerTrendCards" :key="String(card['代码'])" class="etf-trend-card" data-resizable-card>
                    <div>
                      <strong>{{ card['名称'] }}</strong>
                      <span>{{ card['代码'] }} · {{ card['跟踪指数'] }}</span>
                    </div>
                    <b>{{ card['等级'] }}</b>
                    <div class="etf-trend-meter">
                      <i :style="{ width: trendMeterWidth(card['区间收益']) }"></i>
                    </div>
                    <em>{{ card['趋势表达'] }}</em>
                  </article>
                </div>
                <EmptyState v-else title="暂无趋势对比" body="筛选 ETF 后生成趋势对比。" />
              </Panel>
            </section>

            <Panel title="ETF 排序明细" subtitle="强化比较与筛选">
              <DataTable :rows="etfTrackerReviewRows" :columns="etfTrackerReviewColumns" empty="生成 ETF 趋势对比后显示排序。" />
            </Panel>

            <div v-if="etfTrackerResultActive && reviewChartItems.length" class="research-kline-section">
              <div class="review-section-head">
                <span>ETF趋势K线</span>
                <strong>{{ reviewChartSummary }}</strong>
              </div>
              <div class="review-kline-grid">
                <KlineChart v-for="item in reviewChartItems" :key="`etf-${item.symbol}`" :item="item" />
              </div>
            </div>
          </section>

          <section v-else-if="activeResearchTab === 'regime'" class="view-stack market-regime-view">
            <section class="content-grid two market-regime-grid">
              <Panel title="市场风险偏好" subtitle="Market Regime Research">
                <form class="task-form" @submit.prevent="runMarketRegimeResearch">
                  <label>
                    <span>基准指数</span>
                    <input v-model="regimeForm.benchmark_symbol" type="text" />
                  </label>
                  <label>
                    <span>前瞻窗口</span>
                    <input v-model="regimeForm.forward_windows" type="text" />
                  </label>
                  <div class="inline-fields span-full">
                    <label>
                      <span>开始</span>
                      <input v-model="regimeForm.start" type="date" />
                    </label>
                    <label>
                      <span>结束</span>
                      <input v-model="regimeForm.end" type="date" />
                    </label>
                  </div>
                  <div class="date-shortcuts span-full" aria-label="市场风险偏好日期快捷选项">
                    <span>快捷</span>
                    <button
                      v-for="shortcut in DATE_RANGE_SHORTCUTS"
                      :key="shortcut.key"
                      type="button"
                      :class="['date-shortcut', { active: isDateShortcutActive(regimeForm, shortcut.key) }]"
                      @click="applyDateShortcut(regimeForm, shortcut.key)"
                    >
                      {{ shortcut.label }}
                    </button>
                  </div>
                  <div class="regime-method-note span-full">
                    <strong>参数口径</strong>
                    <span>先判断基准是否处于“上涨后回撤”，再看个股回调是否充分、是否转强，最后用市场宽度、高流动性破位和现金偏好确认风险阶段。</span>
                  </div>
                  <div class="regime-preset-panel span-full">
                    <div class="regime-preset-head">
                      <div>
                        <strong>参数预设</strong>
                        <span>百分比直接填 8、-6、60 这种界面数值；保守更早提示风险，弹性更少误报。</span>
                      </div>
                      <div class="regime-preset-actions" aria-label="市场风险偏好参数预设">
                        <button
                          v-for="preset in REGIME_PARAMETER_PRESETS"
                          :key="preset.key"
                          type="button"
                          :class="['regime-preset-button', { active: regimeActivePresetKey === preset.key }]"
                          @click="applyRegimeParameterPreset(preset.key)"
                        >
                          <span>{{ preset.label }}</span>
                          <em>{{ preset.detail }}</em>
                        </button>
                      </div>
                    </div>
                    <div class="regime-guide-grid">
                      <span v-for="item in regimeParameterGuideCards" :key="item.label">
                        <b>{{ item.label }}</b>
                        <em>{{ item.detail }}</em>
                      </span>
                    </div>
                  </div>
                  <label>
                    <span>基准60日涨幅</span>
                    <div class="percent-input">
                      <input v-model.number="regimeForm.benchmark_rally_60_threshold" type="number" step="0.5" />
                      <b>%</b>
                    </div>
                    <em class="field-hint">达到该涨幅后，才进入“上涨后回撤”观察口径。</em>
                  </label>
                  <label>
                    <span>基准20日回撤</span>
                    <div class="percent-input">
                      <input v-model.number="regimeForm.benchmark_pullback_20_threshold" type="number" max="0" step="0.5" />
                      <b>%</b>
                    </div>
                    <em class="field-hint">基准从20日高点回撤到该幅度，判为调整。</em>
                  </label>
                  <label>
                    <span>20日回撤阈值</span>
                    <div class="percent-input">
                      <input v-model.number="regimeForm.pullback_20_threshold" type="number" max="0" step="0.5" />
                      <b>%</b>
                    </div>
                    <em class="field-hint">个股短线回调是否充分的判定线。</em>
                  </label>
                  <label>
                    <span>60日回撤阈值</span>
                    <div class="percent-input">
                      <input v-model.number="regimeForm.pullback_60_threshold" type="number" max="0" step="0.5" />
                      <b>%</b>
                    </div>
                    <em class="field-hint">个股中期回调是否充分的判定线。</em>
                  </label>
                  <details class="regime-advanced-options span-full">
                    <summary>
                      <strong>高级参数</strong>
                      <span>分层、压力信号与阶段阈值，百分比参数直接填百分数</span>
                    </summary>
                    <div class="regime-param-grid">
                      <label>
                        <span>高流动性分位</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.liquidity_high_percentile" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                        <em class="field-hint">成交额分位高于该值，归入高流动性层。</em>
                      </label>
                      <label>
                        <span>中盘起始分位</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.liquidity_mid_percentile" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>低流动性分位</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.liquidity_low_percentile" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>高波动分位</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.volatility_high_percentile" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                        <em class="field-hint">HV20 分位高于该值，归入高波资产。</em>
                      </label>
                      <label>
                        <span>低波动分位</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.volatility_low_percentile" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>高位回撤阈值</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.high_position_drawdown_threshold" type="number" max="0" step="0.5" />
                          <b>%</b>
                        </div>
                        <em class="field-hint">距离250日高点回撤小于该值，仍视为高位。</em>
                      </label>
                      <label>
                        <span>高位涨幅分位</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.high_position_return_percentile" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>领涨5日阈值</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.leader_return_5d_threshold" type="number" step="0.5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>压力破位阈值</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.stress_ma20_break_threshold" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                        <em class="field-hint">层内跌破 MA20 的资产占比达到该值，压力上升。</em>
                      </label>
                      <label>
                        <span>压力收益阈值</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.stress_return_5d_threshold" type="number" step="0.5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>现金压力分</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.cash_stress_score_threshold" type="number" min="0" max="100" step="1" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>现金偏好阈值</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.cash_preference_proxy_threshold" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                        <em class="field-hint">现金偏好代理达到该值，判为明显防守。</em>
                      </label>
                      <label>
                        <span>扩张宽度</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.risk_expansion_breadth_threshold" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>收缩宽度</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.risk_contraction_breadth_threshold" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>释放后段宽度</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.risk_release_breadth_threshold" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                        <em class="field-hint">市场宽度低于该值且高流动性破位，进入释放后段。</em>
                      </label>
                      <label>
                        <span>高流动性抛售</span>
                        <div class="percent-input">
                          <input v-model.number="regimeForm.high_liquidity_selloff_threshold" type="number" min="0" max="100" step="5" />
                          <b>%</b>
                        </div>
                      </label>
                      <label>
                        <span>集中度TopN</span>
                        <input v-model.number="regimeForm.concentration_top_n" type="number" min="1" max="500" step="1" />
                      </label>
                      <label>
                        <span>日报交易日数</span>
                        <input v-model.number="regimeForm.daily_report_days" type="number" min="1" max="120" step="1" />
                      </label>
                      <label>
                        <span>回流候选数</span>
                        <input v-model.number="regimeForm.flow_candidate_limit" type="number" min="1" max="200" step="1" />
                      </label>
                      <label>
                        <span>时间线交易日数</span>
                        <input v-model.number="regimeForm.risk_timeline_days" type="number" min="5" max="180" step="1" />
                      </label>
                    </div>
                  </details>
                  <div class="field-cluster span-full">
                    <div class="field-cluster-head">
                      <strong>研究宇宙</strong>
                      <span>优先使用通达信板块，可叠加 ETF 或全A；手动标的作为补充。</span>
                    </div>
                    <div class="timeframe-options regime-universe-options">
                      <label
                        v-for="option in regimeUniverseOptions"
                        :key="option.name"
                        :class="['timeframe-option', { selected: regimeForm.universe_groups.includes(option.name), muted: option.disabled }]"
                      >
                        <input v-model="regimeForm.universe_groups" type="checkbox" :value="option.name" :disabled="option.disabled" />
                        <span>{{ option.label }} · {{ formatInt(option.count) }}</span>
                      </label>
                    </div>
                    <div class="regime-universe-summary">
                      <span>当前候选约 {{ formatInt(selectedRegimeUniverseCount) }} 只</span>
                      <button class="mini-action" type="button" @click="regimeForm.symbols = ''">清空手动标的</button>
                    </div>
                  </div>
                  <label class="span-full">
                    <span>手动补充标的</span>
                    <textarea v-model="regimeForm.symbols" rows="5" placeholder="可补充行业、ETF、板块或个股代码；留空则只使用所选研究宇宙"></textarea>
                  </label>
                  <div class="form-actions span-full">
                    <button class="btn primary" type="submit" :disabled="runningResearch === 'regime'">
                      <Icon name="activity" />
                      运行研究
                    </button>
                    <button class="btn secondary" type="button" :disabled="!regimeResult" @click="saveActiveResearchSnapshot">
                      <Icon name="save" />
                      保存快照
                    </button>
                    <button class="btn secondary" type="button" :disabled="!regimeResult" @click="downloadMarketRegimeJson">
                      <Icon name="download" />
                      导出JSON
                    </button>
                  </div>
                </form>
              </Panel>

              <Panel class="market-regime-score-panel" title="Risk Appetite Index" subtitle="市场状态">
                <div class="regime-score-card" data-resizable-card>
                  <span>{{ regimeResult?.risk_appetite?.phase || '等待研究' }}</span>
                  <strong>{{ formatDecimalValue(regimeResult?.risk_appetite?.score, 1) }}</strong>
                  <em>{{ regimeResult ? '风险偏好指数' : '运行后显示综合状态' }}</em>
                </div>
                <div class="regime-state-grid">
                  <div v-for="item in regimeStateCards" :key="item.label">
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                    <em>{{ item.detail }}</em>
                  </div>
                </div>
                <div class="regime-summary-grid" aria-label="市场风险偏好摘要">
                  <article v-for="item in regimeSummaryCards" :key="item.label" class="regime-summary-card">
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                    <em>{{ item.detail }}</em>
                  </article>
                </div>
              </Panel>
            </section>

            <Panel class="market-regime-answer-panel" title="核心结论" subtitle="阶段、流向、补跌、因子优势">
              <div v-if="regimeAnswerCards.length" class="regime-answer-card-grid">
                <article v-for="item in regimeAnswerCards" :key="item.question" :class="['regime-answer-card', item.tone]">
                  <span>{{ item.question }}</span>
                  <strong>{{ item.answer }}</strong>
                  <em>{{ item.detail }}</em>
                </article>
              </div>
              <EmptyState v-else title="等待研究" body="运行后显示核心问题答案。" />
            </Panel>

            <div class="research-tabs regime-section-tabs" aria-label="市场风险偏好功能页签">
              <button
                v-for="tab in regimeSectionTabs"
                :key="tab.key"
                type="button"
                :class="['research-tab', { active: activeRegimeSectionTab === tab.key }]"
                @click="activeRegimeSectionTab = tab.key"
              >
                <Icon :name="tab.icon" />
                {{ tab.label }}
              </button>
            </div>

            <section v-if="activeRegimeSectionTab === 'overview'" class="content-grid two market-regime-result-grid regime-visual-grid">
              <Panel title="RAI 趋势" subtitle="0-100 风险偏好综合分">
                <div v-if="regimeRaiChartPoints.length" class="regime-rai-chart" aria-label="风险偏好指数趋势">
                  <div class="regime-rai-meaning">
                    <div class="regime-rai-definition">
                      <span>RAI 0-100</span>
                      <strong>{{ activeRegimeRaiPoint ? formatDecimalValue(activeRegimeRaiPoint.score, 1) : '-' }}</strong>
                      <em>{{ activeRegimeRaiPoint?.phase || '未运行' }} · 越低代表现金偏好与风险释放越强</em>
                    </div>
                    <div class="regime-rai-scale">
                      <span v-for="item in regimeRaiScaleCards" :key="item.label" :class="item.tone">
                        <b>{{ item.label }}</b>
                        <strong>{{ item.value }}</strong>
                        <em>{{ item.detail }}</em>
                      </span>
                    </div>
                  </div>
                  <div class="regime-chart-head">
                    <span v-for="item in regimeRaiLatestBadges" :key="item.label">
                      {{ item.label }} <strong>{{ item.value }}</strong>
                    </span>
                  </div>
                  <div v-if="regimeRaiWindowAvailable" class="regime-rai-timeline">
                    <span>{{ regimeRaiWindowLabel }}</span>
                    <input
                      type="range"
                      min="0"
                      :max="regimeRaiWindowMaxStart"
                      :value="regimeRaiWindowStartValue"
                      aria-label="拖动选择 RAI 时间窗口"
                      @input="onRegimeRaiWindowInput"
                    />
                    <em>拖动时间轴</em>
                  </div>
                  <svg class="regime-rai-svg" viewBox="0 0 640 190" role="img" aria-label="RAI趋势图">
                    <rect class="regime-rai-zone positive" x="24" y="24" width="592" height="50" />
                    <rect class="regime-rai-zone neutral" x="24" y="74" width="592" height="44" />
                    <rect class="regime-rai-zone negative" x="24" y="118" width="592" height="50" />
                    <line class="regime-threshold high" x1="24" x2="616" y1="74" y2="74" />
                    <line class="regime-threshold low" x1="24" x2="616" y1="118" y2="118" />
                    <text x="28" y="68">65</text>
                    <text x="28" y="112">35</text>
                    <text class="regime-zone-label" x="574" y="50">扩张</text>
                    <text class="regime-zone-label" x="574" y="98">修复</text>
                    <text class="regime-zone-label" x="574" y="146">收缩</text>
                    <line
                      v-if="activeRegimeRaiPoint"
                      class="regime-rai-active-line"
                      :x1="activeRegimeRaiPoint.x"
                      :x2="activeRegimeRaiPoint.x"
                      y1="24"
                      y2="168"
                    />
                    <polyline class="regime-rai-line" :points="regimeRaiLinePoints" />
                    <circle
                      v-for="point in regimeRaiChartPoints"
                      :key="point.key"
                      :class="['regime-rai-dot', point.tone, { active: activeRegimeRaiPoint?.key === point.key }]"
                      :cx="point.x"
                      :cy="point.y"
                      :r="activeRegimeRaiPoint?.key === point.key ? 3.1 : 1.8"
                      role="button"
                      tabindex="0"
                      @click="setActiveRegimeRaiPoint(point)"
                      @focus="setActiveRegimeRaiPoint(point)"
                      @pointerenter="setActiveRegimeRaiPoint(point)"
                      @keyup.enter="setActiveRegimeRaiPoint(point)"
                      @keyup.space.prevent="setActiveRegimeRaiPoint(point)"
                    >
                      <title>{{ point.title }}</title>
                    </circle>
                  </svg>
                  <div class="regime-chart-axis">
                    <span>{{ regimeRaiAxisLabels[0] || '-' }}</span>
                    <span>{{ regimeRaiAxisLabels[1] || '-' }}</span>
                    <span>{{ regimeRaiAxisLabels[2] || '-' }}</span>
                  </div>
                  <div v-if="activeRegimeRaiPoint" class="regime-rai-active-card" :class="activeRegimeRaiPoint.tone">
                    <div class="regime-rai-active-summary">
                      <span>{{ formatDateOnly(activeRegimeRaiPoint.date) }}</span>
                      <strong>{{ activeRegimeRaiPoint.phase || '-' }}</strong>
                      <em>RAI {{ formatDecimalValue(activeRegimeRaiPoint.score, 1) }}</em>
                    </div>
                    <div class="regime-rai-driver-list" aria-label="RAI驱动指标">
                      <article v-for="item in regimeRaiDrivers" :key="item.label" class="regime-rai-driver">
                        <span>{{ item.label }}</span>
                        <strong>{{ item.value }}</strong>
                        <em>{{ item.detail }}</em>
                      </article>
                    </div>
                  </div>
                </div>
                <EmptyState v-else title="等待研究" body="运行后显示风险偏好指数趋势。" />
              </Panel>

              <Panel title="风险释放路径图" subtitle="谁先承压，压力是否向后扩散">
                <div v-if="regimeRiskHeatmapRows.length" class="regime-risk-heatmap" aria-label="风险释放路径压力矩阵">
                  <div class="regime-heatmap-guide">
                    <div>
                      <strong>{{ regimeRiskReleaseNarrative }}</strong>
                      <span>读法：从左到右看时间推进；从上到下看压力是否按高波资产、高位资产、高流动性资产、现金偏好代理扩散。</span>
                    </div>
                    <div class="regime-heatmap-legend" aria-label="压力强度图例">
                      <span><i class="low"></i>观察</span>
                      <span><i class="mid"></i>升温</span>
                      <span><i class="high"></i>高压</span>
                      <span><i class="trigger"></i>触发边框</span>
                    </div>
                  </div>
                  <div class="regime-heatmap-status">
                    <span v-for="item in regimeRiskReleaseSummary" :key="item.label">
                      {{ item.label }} <strong>{{ item.value }}</strong>
                      <em>{{ item.detail }}</em>
                    </span>
                  </div>
                  <div class="regime-heatmap-frame">
                    <div class="regime-heatmap-axis" :style="regimeHeatmapAxisStyle">
                      <span class="regime-heatmap-corner">层级</span>
                      <template v-for="row in regimeRiskHeatmapRows" :key="`axis-${row.layer}`">
                        <strong class="regime-heatmap-layer">
                          <span>{{ row.layer }}</span>
                          <em>{{ row.description }}</em>
                        </strong>
                      </template>
                    </div>
                    <div class="regime-heatmap-scroll">
                      <div class="regime-heatmap-grid" :style="regimeHeatmapGridStyle">
                        <span
                          v-for="item in regimeRiskTimelineDateHeaders"
                          :key="`date-${item.date}`"
                          :class="['regime-heatmap-date', { muted: !item.show }]"
                          :title="item.date"
                        >
                          {{ item.show ? shortDateLabel(item.date) : '' }}
                        </span>
                        <template v-for="row in regimeRiskHeatmapRows" :key="row.layer">
                          <span
                            v-for="cell in row.cells"
                            :key="cell.key"
                            class="regime-heatmap-cell"
                            :class="{ active: cell.stress_signal }"
                            :style="riskHeatmapCellStyle(cell)"
                            :title="cell.title"
                          >
                            <strong>{{ heatmapScoreLabel(cell.stress_score) }}</strong>
                            <em>{{ cell.label }}</em>
                          </span>
                        </template>
                      </div>
                    </div>
                  </div>
                </div>
                <EmptyState v-else title="等待研究" body="运行后显示风险释放层级时间线。" />
              </Panel>
            </section>

            <section v-else-if="activeRegimeSectionTab === 'daily'" class="view-stack market-regime-tab-panel">
              <Panel class="market-regime-daily-panel" title="每日市场状态报告" subtitle="风险阶段与资金迁移">
                <div v-if="regimeResult" class="regime-daily-stack">
                  <div class="regime-daily-grid">
                    <article v-for="item in regimeDailyReportCards" :key="item.label" class="regime-daily-card">
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                      <em>{{ item.detail }}</em>
                    </article>
                  </div>
                  <div class="regime-answer-grid">
                    <div>
                      <span>资金流出</span>
                      <strong>{{ regimeResult.daily_report?.answers?.funds_leaving || '-' }}</strong>
                    </div>
                    <div>
                      <span>资金流入</span>
                      <strong>{{ regimeResult.daily_report?.answers?.funds_entering || '-' }}</strong>
                    </div>
                    <div>
                      <span>高流动性补跌</span>
                      <strong>{{ regimeResult.daily_report?.answers?.high_liquidity_selloff ? '已触发' : '未触发' }}</strong>
                    </div>
                    <div>
                      <span>更接近</span>
                      <strong>{{ regimeResult.daily_report?.answers?.closer_to || '-' }}</strong>
                    </div>
                  </div>
                  <div v-if="displayRegimeDailyEvidenceCards.length" class="regime-evidence-grid" aria-label="日报证据">
                    <article
                      v-for="item in displayRegimeDailyEvidenceCards"
                      :key="item.metric"
                      :class="['regime-evidence-card', item.tone]"
                    >
                      <span>{{ item.metric }}</span>
                      <strong>{{ item.value }}</strong>
                      <em>{{ item.detail }}</em>
                    </article>
                  </div>
                  <EmptyState v-else title="暂无日报证据" body="运行结果未返回日报证据指标。" />
                  <div v-if="regimeDailyCaveats.length" class="regime-caveats">
                    <span v-for="item in regimeDailyCaveats" :key="item">{{ item }}</span>
                  </div>
                </div>
                <EmptyState v-else title="等待研究" body="运行后生成每日市场状态报告。" />
              </Panel>

              <Panel title="最近日报序列" subtitle="阶段、流向与压力变化">
                <PaginatedDataTable
                  :rows="displayRegimeDailyHistoryRows"
                  :columns="regimeDailyHistoryColumns"
                  empty="运行研究后显示最近交易日的市场状态序列。"
                  aria-label="最近日报序列"
                />
              </Panel>
            </section>

            <section v-else-if="activeRegimeSectionTab === 'flow'" class="content-grid two market-regime-result-grid">
              <Panel title="RAI 组成拆解" subtitle="高位、中盘、高流动性与市场宽度">
                <PaginatedDataTable
                  :rows="displayRegimeComponentRows"
                  :columns="regimeComponentColumns"
                  empty="运行研究后显示风险偏好指数构成。"
                  aria-label="RAI组成拆解"
                />
              </Panel>
              <Panel title="波动率 × 流动性" subtitle="资金迁移">
                <PaginatedDataTable
                  :rows="displayRegimeMigrationRows"
                  :columns="regimeMigrationColumns"
                  empty="运行研究后显示高波动、高位、高流动性资产迁移状态。"
                  aria-label="波动率流动性"
                />
              </Panel>
              <Panel title="风险释放顺序" subtitle="高波 → 高位 → 高流动性 → 现金">
                <PaginatedDataTable
                  :rows="displayRegimeSequenceRows"
                  :columns="regimeSequenceColumns"
                  empty="运行研究后显示风险释放阶段的触发顺序。"
                  aria-label="风险释放顺序"
                />
              </Panel>
              <Panel title="高流动性补跌" subtitle="未来 5/10/20 日">
                <PaginatedDataTable
                  :rows="displayRegimeHighLiquidityBreakRows"
                  :columns="regimeHighLiquidityBreakColumns"
                  empty="运行研究后显示高流动性资产跌破趋势后的前瞻表现。"
                  aria-label="高流动性补跌"
                />
              </Panel>
              <Panel title="市场缩圈" subtitle="上涨资产、成交额集中度、领涨数量">
                <div v-if="displayRegimeMarketScopeRows.length" class="table-toolbar regime-market-scope-toolbar">
                  <p class="table-caption">
                    显示 {{ regimeMarketScopePageFirst }}-{{ regimeMarketScopePageEnd }} / {{ displayRegimeMarketScopeRows.length }} 条
                  </p>
                  <div class="table-controls">
                    <div class="page-size-group" aria-label="市场缩圈每页条数">
                      <span>每页</span>
                      <button
                        v-for="size in regimeMarketScopePageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: regimeMarketScopePagination.pageSize === size }]"
                        @click="setRegimeMarketScopePageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button type="button" :disabled="regimeMarketScopePagination.page <= 1" @click="goRegimeMarketScopePage(1)">首页</button>
                      <button
                        type="button"
                        :disabled="regimeMarketScopePagination.page <= 1"
                        @click="goRegimeMarketScopePage(regimeMarketScopePagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span>{{ regimeMarketScopePagination.page }} / {{ regimeMarketScopeTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="regimeMarketScopePagination.page >= regimeMarketScopeTotalPages"
                        @click="goRegimeMarketScopePage(regimeMarketScopePagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="regimeMarketScopePagination.page >= regimeMarketScopeTotalPages"
                        @click="goRegimeMarketScopePage(regimeMarketScopeTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedRegimeMarketScopeRows" :columns="regimeMarketScopeColumns" empty="运行研究后显示最近市场扩散与缩圈过程。" />
              </Panel>
            </section>

            <section v-else-if="activeRegimeSectionTab === 'asset'" class="view-stack market-regime-tab-panel">
              <Panel title="资金回流候选" subtitle="回调、转强、相对强度与流动性排序">
                <div v-if="displayRegimeFlowCandidateRows.length" class="table-toolbar regime-flow-toolbar">
                  <p class="table-caption">
                    显示 {{ regimeFlowCandidatePageFirst }}-{{ regimeFlowCandidatePageEnd }} / {{ displayRegimeFlowCandidateRows.length }} 条
                  </p>
                  <div class="table-controls">
                    <div class="page-size-group" aria-label="资金回流候选每页条数">
                      <span>每页</span>
                      <button
                        v-for="size in regimeFlowCandidatePageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: regimeFlowCandidatePagination.pageSize === size }]"
                        @click="setRegimeFlowCandidatePageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button type="button" :disabled="regimeFlowCandidatePagination.page <= 1" @click="goRegimeFlowCandidatePage(1)">首页</button>
                      <button type="button" :disabled="regimeFlowCandidatePagination.page <= 1" @click="goRegimeFlowCandidatePage(regimeFlowCandidatePagination.page - 1)">上一页</button>
                      <span>{{ regimeFlowCandidatePagination.page }} / {{ regimeFlowCandidateTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="regimeFlowCandidatePagination.page >= regimeFlowCandidateTotalPages"
                        @click="goRegimeFlowCandidatePage(regimeFlowCandidatePagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="regimeFlowCandidatePagination.page >= regimeFlowCandidateTotalPages"
                        @click="goRegimeFlowCandidatePage(regimeFlowCandidateTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedRegimeFlowCandidateRows" :columns="regimeFlowCandidateColumns" empty="运行研究后显示资产级资金回流候选。" />
              </Panel>
              <Panel title="资金迁移资产明细" subtitle="趋势、波动率、流动性">
                <PaginatedDataTable
                  :rows="displayRegimeAssetRows"
                  :columns="regimeAssetColumns"
                  empty="运行研究后显示资产级状态。"
                  aria-label="资金迁移资产明细"
                />
              </Panel>
            </section>

            <section v-else-if="activeRegimeSectionTab === 'factor'" class="content-grid two market-regime-result-grid">
              <Panel title="基准调整阶段" subtitle="上涨后回撤样本口径">
                <PaginatedDataTable
                  :rows="displayRegimeBenchmarkRows"
                  :columns="regimeBenchmarkColumns"
                  empty="运行研究后显示基准阶段。"
                  aria-label="基准调整阶段"
                />
              </Panel>
              <Panel title="调整阶段因子优势" subtitle="A组相对全市场基准">
                <PaginatedDataTable
                  :rows="displayRegimeAdjustmentFactorAdvantageRows"
                  :columns="regimeFactorAdvantageColumns"
                  empty="当前区间没有满足基准上涨后调整的样本。"
                  aria-label="调整阶段因子优势"
                />
              </Panel>
              <Panel title="调整阶段回测明细" subtitle="基准上涨后回撤">
                <PaginatedDataTable
                  :rows="displayRegimeAdjustmentFactorRows"
                  :columns="regimeFactorColumns"
                  empty="当前区间没有满足基准上涨后调整的分组样本。"
                  aria-label="调整阶段回测明细"
                />
              </Panel>
              <Panel title="全样本因子优势" subtitle="A组相对全市场基准">
                <PaginatedDataTable
                  :rows="displayRegimeFactorAdvantageRows"
                  :columns="regimeFactorAdvantageColumns"
                  empty="运行研究后显示A组相对基准的统计优势。"
                  aria-label="全样本因子优势"
                />
              </Panel>
              <Panel title="回调充分 + 转强" subtitle="因子回测报告">
                <PaginatedDataTable
                  :rows="displayRegimeFactorRows"
                  :columns="regimeFactorColumns"
                  empty="运行研究后显示分组收益、胜率和超额收益。"
                  aria-label="回调充分转强"
                />
              </Panel>
            </section>
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
                <label class="review-ai-toggle">
                  <input v-model="reviewForm.enable_ai_review" type="checkbox" />
                  <span>启用 AI 锐评</span>
                  <em>{{ aiConfigReady ? '使用系统设置中的 AI 接口' : '未配置时输出本地默认锐评' }}</em>
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
                  <button class="btn secondary" type="button" :disabled="runningAiReview || !reviewResult?.ai?.messages?.length" @click="runAiReview()">
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
                          data-resizable-card
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
              <section v-if="selectedTaskQualityIssues.length" class="task-paged-section quality-issue-list">
                <div class="table-toolbar">
                  <p class="table-caption">质量门禁 {{ taskQualityIssuePageFirst }}-{{ taskQualityIssuePageEnd }} / {{ selectedTaskQualityIssues.length }} 条</p>
                  <div class="table-controls">
                    <div class="page-size-group">
                      <span>每页</span>
                      <button
                        v-for="size in taskQualityIssuePageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: taskQualityIssuePagination.pageSize === size }]"
                        @click="setTaskQualityIssuePageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button type="button" :disabled="taskQualityIssuePagination.page <= 1" @click="goTaskQualityIssuePage(1)">首页</button>
                      <button type="button" :disabled="taskQualityIssuePagination.page <= 1" @click="goTaskQualityIssuePage(taskQualityIssuePagination.page - 1)">上一页</button>
                      <span>{{ taskQualityIssuePagination.page }} / {{ taskQualityIssueTotalPages }}</span>
                      <button type="button" :disabled="taskQualityIssuePagination.page >= taskQualityIssueTotalPages" @click="goTaskQualityIssuePage(taskQualityIssuePagination.page + 1)">下一页</button>
                      <button type="button" :disabled="taskQualityIssuePagination.page >= taskQualityIssueTotalPages" @click="goTaskQualityIssuePage(taskQualityIssueTotalPages)">末页</button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedTaskQualityIssueRows" :columns="taskQualityIssueColumns" empty="暂无质量门禁明细。" />
              </section>
              <div v-else-if="selectedTask.error" class="error-box">{{ selectedTask.error }}</div>
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

        <section v-else-if="activeView === 'ai'" class="view-stack ai-workbench-view">
          <section class="content-grid two">
            <Panel title="AI 模块" subtitle="Stock Data Interface">
              <form class="task-form ai-workbench-form" @submit.prevent="runAiWorkbench">
                <label class="span-full">
                  <div class="field-head">
                    <span>导入 Skill / 系统提示词</span>
                    <div class="field-actions">
                      <label class="mini-action skill-file-action">
                        <Icon name="folder" />
                        导入文本
                        <input type="file" accept=".md,.txt,text/markdown,text/plain" @change="importAiSkillPrompt" />
                      </label>
                      <button class="mini-action" type="button" @click="aiWorkbenchForm.skill_prompt = ''">清空</button>
                    </div>
                  </div>
                  <textarea v-model="aiWorkbenchForm.skill_prompt" rows="6" placeholder="粘贴你的 skill、研究框架或输出约束。"></textarea>
                </label>
                <label class="span-full">
                  <span>用户任务</span>
                  <textarea v-model="aiWorkbenchForm.prompt" rows="4" placeholder="例如：用我的框架判断这批股票的强弱、风险点和下一步观察项。"></textarea>
                </label>
                <label class="span-full">
                  <span>股票代码</span>
                  <textarea v-model="aiWorkbenchForm.symbols" rows="4" placeholder="000001.SZ&#10;300750.SZ"></textarea>
                </label>
                <div class="inline-fields span-full">
                  <label>
                    <span>开始</span>
                    <input v-model="aiWorkbenchForm.start" type="date" />
                  </label>
                  <label>
                    <span>结束</span>
                    <input v-model="aiWorkbenchForm.end" type="date" />
                  </label>
                  <label>
                    <span>周期</span>
                    <select v-model="aiWorkbenchForm.timeframe">
                      <option v-for="timeframe in config?.timeframes || ['1d']" :key="timeframe" :value="timeframe">{{ timeframe }}</option>
                    </select>
                  </label>
                </div>
                <label>
                  <span>最大数据行</span>
                  <input v-model.number="aiWorkbenchForm.max_rows" type="number" min="20" max="1000" step="20" />
                </label>
                <label>
                  <span>最大标的数</span>
                  <input v-model.number="aiWorkbenchForm.max_symbols" type="number" min="1" max="50" />
                </label>
                <div class="form-actions span-full">
                  <button class="btn primary" type="submit" :disabled="runningAiWorkbench || !aiConfigReady">
                    <Icon name="sparkles" />
                    {{ runningAiWorkbench ? '运行中' : '调用 AI' }}
                  </button>
                  <button class="btn secondary" type="button" @click="aiWorkbenchForm.symbols = reviewForm.symbols || symbolsText">
                    载入当前标的
                  </button>
                </div>
                <div class="ai-settings-note span-full">
                  只会把当前选择的本地行情 JSON 发给模型；不开放任意代码执行或外部交易操作。
                </div>
              </form>
            </Panel>

            <Panel title="统一图表设置" subtitle="全局显示偏好">
              <form class="task-form chart-settings-form" @submit.prevent="saveSettings">
                <label>
                  <span>色彩风格</span>
                  <select v-model="chartSettings.theme">
                    <option value="clean">清爽</option>
                    <option value="contrast">高对比</option>
                  </select>
                </label>
                <label>
                  <span>图表密度</span>
                  <select v-model="chartSettings.density">
                    <option value="comfortable">舒展</option>
                    <option value="compact">紧凑</option>
                  </select>
                </label>
                <label class="check-row span-full">
                  <input v-model="chartSettings.show_context" type="checkbox" />
                  <span>显示图表上下文说明</span>
                </label>
                <div class="chart-setting-preview span-full">
                  <span>当前风格</span>
                  <strong>{{ chartSettings.theme === 'contrast' ? '高对比' : '清爽' }} · {{ chartSettings.density === 'compact' ? '紧凑' : '舒展' }}</strong>
                  <em>设置会同步影响页面图表与结果卡片间距。</em>
                </div>
                <div class="form-actions span-full">
                  <button class="btn primary" type="submit">保存图表设置</button>
                </div>
              </form>
            </Panel>
          </section>

          <Panel title="AI 输出" subtitle="模型结果与数据上下文">
            <div v-if="aiWorkbenchResult" class="ai-workbench-output">
              <article>
                <span>模型输出</span>
                <pre>{{ aiWorkbenchResult.content }}</pre>
                <em>{{ aiWorkbenchResult.disclaimer }}</em>
              </article>
              <DataTable :rows="aiWorkbenchLatestRows" :columns="aiWorkbenchLatestColumns" empty="暂无最新指标。" />
              <DataTable :rows="aiWorkbenchRecordRows" :columns="aiWorkbenchRecordColumns" empty="暂无行情上下文。" />
            </div>
            <EmptyState v-else title="等待 AI 任务" body="配置股票数据和提示词后调用模型。" />
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
              <label class="span-full">
                <span>Fuyao API Key</span>
                <input v-model="fuyaoSettings.api_key" type="password" autocomplete="off" placeholder="用于同花顺交易日历，保存到本机浏览器 localStorage" />
              </label>
              <div class="form-actions span-full">
                <button class="btn primary" type="submit">保存设置</button>
                <button class="btn secondary" type="button" @click="resetSettings">恢复默认</button>
              </div>
            </form>
          </Panel>

          <Panel title="AI 设置" subtitle="命令框 / 锐评 / AI 模块">
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
                大模型命令框、AI 模块和多股复盘 AI 覆盖都会读取这里保存的参数；具体证据由各模块自动附加。
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
          <select v-model="reviewSymbolPickerCategory" aria-label="复盘标的分类">
            <option v-for="item in reviewSymbolPickerCategoryOptions" :key="item.value" :value="item.value">
              {{ item.label }} · {{ formatInt(item.count) }}
            </option>
          </select>
          <input v-model="reviewSymbolPickerKeyword" type="search" placeholder="搜索代码或名称" />
          <button class="btn secondary" type="button" @click="selectFilteredReviewSymbols">选当前结果</button>
          <button class="btn secondary" type="button" @click="selectAllReviewSymbols">全选当前分类</button>
          <button class="btn secondary" type="button" @click="clearReviewSymbolSelection">清空</button>
        </div>

        <div class="asset-picker-summary">
          <span>
            显示 {{ formatInt(reviewSymbolPickerVisibleRows.length) }} / 筛选 {{ formatInt(filteredReviewSymbolPickerRows.length) }}
            / 分类 {{ formatInt(categoryFilteredReviewSymbolPickerRows.length) }} / 总 {{ formatInt(reviewSymbolPickerRows.length) }}
            <template v-if="filteredReviewSymbolPickerRows.length > reviewSymbolPickerVisibleRows.length">
              · 已限制渲染前 {{ formatInt(REVIEW_SYMBOL_PICKER_VISIBLE_LIMIT) }}
            </template>
            · {{ reviewSymbolPickerSortLabel }}
          </span>
          <strong>已选 {{ formatInt(reviewSymbolPickerSelection.length) }}</strong>
        </div>

        <div v-if="filteredReviewSymbolPickerRows.length" class="asset-picker-list">
          <label
            v-for="row in reviewSymbolPickerVisibleRows"
            :key="row.symbol"
            :class="['asset-picker-row', { selected: isReviewSymbolSelected(row.symbol) }]"
          >
            <input type="checkbox" :checked="isReviewSymbolSelected(row.symbol)" @change="toggleReviewSymbol(row.symbol)" />
            <span>
              <strong>{{ row.symbol }}</strong>
              <em>{{ row.name || row.assetType || reviewSymbolPickerTypeLabel }} · {{ row.categoryLabel }}</em>
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
import PaginatedDataTable from './components/PaginatedDataTable.vue'
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
  symbol_names?: Record<string, string>
  integrations?: Record<string, any>
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

interface TaskQualityIssue {
  index: number
  symbol: string
  timeframe: string
  status: string
  status_label: string
  message: string
}

type DateShortcutKey = '20d' | '50d' | 'ytd' | '1y'
type RegimeParameterPresetKey = 'balanced' | 'defensive' | 'elastic'

interface DateRangeFields {
  start: string
  end: string
}

type DirectoryField = 'data_root' | 'tdx_path'
type ResearchTabKey = 'history' | 'cross' | 'review' | 'etf' | 'regime'
type RegimeSectionTabKey = 'overview' | 'daily' | 'flow' | 'factor' | 'asset'
type SymbolRefreshTarget = 'index' | 'etf'
type ReviewSymbolPickerType = 'etf' | 'sector'
type AssetShortcutType = 'etf' | 'stock' | 'index'
type EtfClientCacheSource = 'empty' | 'client' | 'memory' | 'disk' | 'network' | 'cleared'

interface EtfClientCacheState {
  source: EtfClientCacheSource
  saved_at: number
  record_count: number
}

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
  { key: 'ai', label: 'AI 工作台', title: 'AI 工作台', description: '把本地股票数据交给用户提示词和大模型。', icon: 'sparkles' },
  { key: 'tasks', label: '执行记录', title: '执行记录', description: '查看后台任务状态、错误和写入结果。', icon: 'clipboard' },
  { key: 'settings', label: '系统设置', title: '系统设置', description: '配置默认路径、复权方式和运行参数。', icon: 'settings' }
]

const researchTabs: Array<{ key: ResearchTabKey; label: string; icon: string }> = [
  { key: 'history', label: '历史相似', icon: 'activity' },
  { key: 'cross', label: '横截面相似', icon: 'layers' },
  { key: 'review', label: '多股复盘', icon: 'clipboard' },
  { key: 'etf', label: '场内ETF跟踪', icon: 'archive' },
  { key: 'regime', label: '市场风险偏好', icon: 'activity' }
]

const regimeSectionTabs: Array<{ key: RegimeSectionTabKey; label: string; icon: string }> = [
  { key: 'overview', label: '总览图形', icon: 'activity' },
  { key: 'daily', label: '日报', icon: 'clipboard' },
  { key: 'flow', label: '风险释放', icon: 'layers' },
  { key: 'factor', label: '因子回测', icon: 'database' },
  { key: 'asset', label: '资产明细', icon: 'archive' }
]

const SETTINGS_STORAGE_KEY = 'tdx-downloader-web-settings'
const RESEARCH_SNAPSHOT_STORAGE_KEY = 'tdx-downloader-research-snapshots'
const ETF_TRACKING_CACHE_STORAGE_KEY = 'tdx-downloader-etf-tracking-cache'
const ETF_RETURNS_CACHE_STORAGE_KEY = 'tdx-downloader-etf-returns-cache'
const ETF_TRACKING_CLIENT_CACHE_TTL_MS = 24 * 60 * 60 * 1000
const ETF_RETURNS_CLIENT_CACHE_TTL_MS = 12 * 60 * 60 * 1000
const MAX_RESEARCH_SNAPSHOTS = 60
const CACHE_PAGE_SIZE_OPTIONS = [25, 50, 100]
const PLAN_PAGE_SIZE_OPTIONS = [25, 50, 100]
const ETF_TRACKER_PAGE_SIZE_OPTIONS = [25, 50, 100]
const REGIME_FLOW_CANDIDATE_PAGE_SIZE_OPTIONS = [10, 20, 30]
const REGIME_MARKET_SCOPE_PAGE_SIZE_OPTIONS = [10, 15, 30]
const REGIME_RAI_WINDOW_SIZE = 60
const REGIME_PERCENT_FIELD_KEYS = [
  'benchmark_rally_60_threshold',
  'benchmark_pullback_20_threshold',
  'pullback_20_threshold',
  'pullback_60_threshold',
  'liquidity_high_percentile',
  'liquidity_mid_percentile',
  'liquidity_low_percentile',
  'volatility_high_percentile',
  'volatility_low_percentile',
  'high_position_drawdown_threshold',
  'high_position_return_percentile',
  'leader_return_5d_threshold',
  'stress_ma20_break_threshold',
  'stress_return_5d_threshold',
  'cash_stress_score_threshold',
  'cash_preference_proxy_threshold',
  'risk_expansion_breadth_threshold',
  'risk_contraction_breadth_threshold',
  'risk_release_breadth_threshold',
  'high_liquidity_selloff_threshold'
] as const
const REGIME_PARAMETER_PRESETS: Array<{
  key: RegimeParameterPresetKey
  label: string
  detail: string
  values: Record<(typeof REGIME_PERCENT_FIELD_KEYS)[number], number>
}> = [
  {
    key: 'balanced',
    label: '标准',
    detail: '默认研究口径',
    values: {
      benchmark_rally_60_threshold: 8,
      benchmark_pullback_20_threshold: -3,
      pullback_20_threshold: -6,
      pullback_60_threshold: -10,
      liquidity_high_percentile: 80,
      liquidity_mid_percentile: 35,
      liquidity_low_percentile: 20,
      volatility_high_percentile: 80,
      volatility_low_percentile: 20,
      high_position_drawdown_threshold: -10,
      high_position_return_percentile: 80,
      leader_return_5d_threshold: 3,
      stress_ma20_break_threshold: 60,
      stress_return_5d_threshold: 0,
      cash_stress_score_threshold: 62,
      cash_preference_proxy_threshold: 60,
      risk_expansion_breadth_threshold: 60,
      risk_contraction_breadth_threshold: 40,
      risk_release_breadth_threshold: 45,
      high_liquidity_selloff_threshold: 60
    }
  },
  {
    key: 'defensive',
    label: '保守',
    detail: '更早识别退潮',
    values: {
      benchmark_rally_60_threshold: 6,
      benchmark_pullback_20_threshold: -2.5,
      pullback_20_threshold: -5,
      pullback_60_threshold: -8,
      liquidity_high_percentile: 75,
      liquidity_mid_percentile: 35,
      liquidity_low_percentile: 20,
      volatility_high_percentile: 75,
      volatility_low_percentile: 20,
      high_position_drawdown_threshold: -8,
      high_position_return_percentile: 75,
      leader_return_5d_threshold: 2,
      stress_ma20_break_threshold: 55,
      stress_return_5d_threshold: -1,
      cash_stress_score_threshold: 58,
      cash_preference_proxy_threshold: 55,
      risk_expansion_breadth_threshold: 65,
      risk_contraction_breadth_threshold: 45,
      risk_release_breadth_threshold: 50,
      high_liquidity_selloff_threshold: 55
    }
  },
  {
    key: 'elastic',
    label: '弹性',
    detail: '减少短噪声误报',
    values: {
      benchmark_rally_60_threshold: 10,
      benchmark_pullback_20_threshold: -4,
      pullback_20_threshold: -8,
      pullback_60_threshold: -12,
      liquidity_high_percentile: 85,
      liquidity_mid_percentile: 40,
      liquidity_low_percentile: 20,
      volatility_high_percentile: 85,
      volatility_low_percentile: 20,
      high_position_drawdown_threshold: -12,
      high_position_return_percentile: 85,
      leader_return_5d_threshold: 4,
      stress_ma20_break_threshold: 65,
      stress_return_5d_threshold: 1,
      cash_stress_score_threshold: 66,
      cash_preference_proxy_threshold: 65,
      risk_expansion_breadth_threshold: 55,
      risk_contraction_breadth_threshold: 35,
      risk_release_breadth_threshold: 40,
      high_liquidity_selloff_threshold: 65
    }
  }
]
const RISK_RELEASE_LAYER_DESCRIPTIONS: Record<string, string> = {
  '高波资产': '弹性资产先承压',
  '高位资产': '拥挤交易退潮',
  '高流动性资产': '权重补跌确认',
  '现金偏好代理': '防守情绪抬升'
}
const DEFAULT_ALL_ASSETS_LOOKBACK_DAYS = 20
const REVIEW_SYMBOL_PICKER_VISIBLE_LIMIT = 240
const REVIEW_SYMBOL_PICKER_TABS: Array<{ key: ReviewSymbolPickerType; label: string }> = [
  { key: 'etf', label: 'ETF' },
  { key: 'sector', label: '板块指数' }
]
const ETF_REVIEW_SYMBOL_CATEGORIES = [
  { value: 'equity_etf', label: '股票型ETF' },
  { value: 'bond_money_etf', label: '债券/货币ETF' },
  { value: 'commodity_cross_reit', label: '商品/跨境/REIT' },
  { value: 'tdx_special', label: '通达信ETF指数' },
  { value: 'lof_other_fund', label: 'LOF/其他基金' },
  { value: 'all', label: '全部ETF/基金' }
]
const SECTOR_REVIEW_SYMBOL_CATEGORIES = [
  { value: 'industry_l1', label: '行业一级' },
  { value: 'industry_l2', label: '行业二级' },
  { value: 'tdx_special', label: '通达信特色/昨日涨停' },
  { value: 'bond_fund', label: '债券/基金' },
  { value: 'all', label: '全部板块指数' }
]
const TDX_LEVEL_ONE_INDUSTRY_NAMES = new Set([
  '煤炭',
  '电力',
  '石油',
  '钢铁',
  '有色',
  '化纤',
  '化工',
  '建材',
  '造纸',
  '矿物制品',
  '日用化工',
  '农林牧渔',
  '纺织服饰',
  '食品饮料',
  '酿酒',
  '家用电器',
  '汽车类',
  '医疗保健',
  '家居用品',
  '医药',
  '商业连锁',
  '传媒娱乐',
  '酒店餐饮',
  '航空',
  '船舶',
  '运输设备',
  '通用机械',
  '电气设备',
  '电信运营',
  '公共交通',
  '水务',
  '供气供热',
  '环境保护',
  '运输服务',
  '银行',
  '证券',
  '保险',
  '多元金融',
  '建筑',
  '房地产',
  'IT设备',
  '通信设备',
  '半导体',
  '元器件',
  '软件服务',
  '互联网',
  '综合类'
])
const DATE_RANGE_SHORTCUTS: Array<{ key: DateShortcutKey; label: string }> = [
  { key: '20d', label: '20交易日' },
  { key: '50d', label: '50交易日' },
  { key: 'ytd', label: 'YTD' },
  { key: '1y', label: '近一年' }
]
const ETF_TRACKER_CATEGORY_OPTIONS = [
  { value: 'all', label: '全部ETF' },
  { value: 'industry', label: '行业指数类' },
  { value: 'theme', label: '主题类' },
  { value: 'broad', label: '宽基类' },
  { value: 'bond', label: '债类' },
  { value: 'other', label: '其他类' }
]
const ETF_TRACKING_INDEX_SYMBOLS = ['000016.SH', '000300.SH', '000905.SH', '000852.SH', '399006.SZ', '000688.SH']
const TASK_EVENT_WINDOW_SIZE = 6
const TASK_EVENT_PAGE_SIZE_OPTIONS = [10, 25, 50]
const TASK_RESULT_PAGE_SIZE_OPTIONS = [25, 50, 100]
const TASK_QUALITY_PAGE_SIZE_OPTIONS = [25, 50, 100]
const RISK_RELEASE_LAYER_ORDER = ['高波资产', '高位资产', '高流动性资产', '现金偏好代理']
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
const selectedTimeframes = ref<string[]>(['1d'])
const researchTimeframe = ref('1d')
const allAssetsLookbackDays = ref(DEFAULT_ALL_ASSETS_LOOKBACK_DAYS)
const reviewSymbolPickerOpen = ref(false)
const reviewSymbolPickerType = ref<ReviewSymbolPickerType>('etf')
const reviewSymbolPickerCategory = ref(defaultReviewSymbolCategory('etf'))
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
const loadingEtfTracking = ref(false)
const loadingEtfReturns = ref(false)
const loadingTradingCalendar = ref(false)
const runningResearch = ref<ResearchTabKey | ''>('')
const runningAiReview = ref(false)
const runningAiCommand = ref(false)
const runningAiWorkbench = ref(false)
const activeResearchTab = ref<ResearchTabKey>('history')
const activeRegimeSectionTab = ref<RegimeSectionTabKey>('overview')
const pickingDirectory = ref<DirectoryField | ''>('')
const planRows = ref<Array<Record<string, any>>>([])
const planSummary = ref<Record<string, any>>({})
const historyResult = ref<Record<string, any> | null>(null)
const crossResult = ref<Record<string, any> | null>(null)
const reviewResult = ref<Record<string, any> | null>(null)
const regimeResult = ref<Record<string, any> | null>(null)
const activeRegimeRaiKey = ref('')
const regimeRaiWindowStart = ref(-1)
const reviewResultSignature = ref('')
const etfTrackerResultSignature = ref('')
const etfTrackingRows = ref<Array<Record<string, any>>>([])
const etfReturnRows = ref<Array<Record<string, any>>>([])
const etfTrackingCacheState = reactive<EtfClientCacheState>({ source: 'empty', saved_at: 0, record_count: 0 })
const etfReturnsCacheState = reactive<EtfClientCacheState>({ source: 'empty', saved_at: 0, record_count: 0 })
const tradingCalendarDays = ref<string[]>([])
const aiReviewOutput = ref<Record<string, any> | null>(null)
const aiCommandResult = ref<Record<string, any> | null>(null)
const aiWorkbenchResult = ref<Record<string, any> | null>(null)
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
const planPagination = reactive({
  page: 1,
  pageSize: PLAN_PAGE_SIZE_OPTIONS[0]
})
const taskEventPagination = reactive({
  page: 1,
  pageSize: TASK_EVENT_PAGE_SIZE_OPTIONS[0]
})
const taskResultPagination = reactive({
  page: 1,
  pageSize: TASK_RESULT_PAGE_SIZE_OPTIONS[0]
})
const taskQualityIssuePagination = reactive({
  page: 1,
  pageSize: TASK_QUALITY_PAGE_SIZE_OPTIONS[0]
})
const etfTrackerPagination = reactive({
  page: 1,
  pageSize: ETF_TRACKER_PAGE_SIZE_OPTIONS[0]
})
const regimeFlowCandidatePagination = reactive({
  page: 1,
  pageSize: REGIME_FLOW_CANDIDATE_PAGE_SIZE_OPTIONS[0]
})
const regimeMarketScopePagination = reactive({
  page: 1,
  pageSize: REGIME_MARKET_SCOPE_PAGE_SIZE_OPTIONS[1]
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
const fuyaoSettings = reactive({
  api_key: ''
})
const aiPromptSaved = ref(false)
const aiPromptDraft = reactive({
  system: '',
  user: defaultAiUserPrompt()
})
const aiCommandForm = reactive({
  text: ''
})
const aiWorkbenchForm = reactive({
  symbols: '000001.SZ\n300750.SZ',
  start: tradingLookbackStartText(60),
  end: todayText(),
  timeframe: '1d',
  skill_prompt: '',
  prompt: '请基于这些本地行情数据，输出强弱判断、风险点和下一步观察项。',
  max_symbols: 20,
  max_rows: 240
})
const chartSettings = reactive({
  theme: 'clean',
  density: 'comfortable',
  show_context: true
})

const historyForm = reactive({
  symbol: '000001.SZ',
  window_start: tradingLookbackStartText(20),
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
  start: tradingLookbackStartText(20),
  end: todayText(),
  search_mode: 'same_date',
  traversal_start: offsetDateText(-365),
  traversal_end: todayText(),
  top_n: 20,
  date_tolerance_bars: 0,
  exclusion_bars: 0,
  forward_windows: '3,5,10'
})

const reviewForm = reactive({
  symbols: '000001.SZ\n600519.SH\n300750.SZ\n601318.SH',
  start: tradingLookbackStartText(20),
  end: todayText(),
  benchmark_symbol: '000300.SH',
  min_swing_return: 0.05,
  min_segment_bars: 3,
  enable_ai_review: false
})

const etfTrackerForm = reactive({
  category: 'all',
  type: '',
  tracking_index: '',
  keyword: '',
  merge_similar: false,
  start: tradingLookbackStartText(20),
  end: todayText(),
  benchmark_symbol: '000300.SH',
  top_n: 30,
  min_swing_return: 0.04,
  min_segment_bars: 3
})

const regimeForm = reactive({
  benchmark_symbol: '000300.SH',
  symbols: '',
  universe_groups: ['板块指数'],
  start: tradingLookbackStartText(120),
  end: todayText(),
  forward_windows: '3,5,10',
  benchmark_rally_60_threshold: 8,
  benchmark_pullback_20_threshold: -3,
  pullback_20_threshold: -6,
  pullback_60_threshold: -10,
  liquidity_high_percentile: 80,
  liquidity_mid_percentile: 35,
  liquidity_low_percentile: 20,
  volatility_high_percentile: 80,
  volatility_low_percentile: 20,
  high_position_drawdown_threshold: -10,
  high_position_return_percentile: 80,
  leader_return_5d_threshold: 3,
  stress_ma20_break_threshold: 60,
  stress_return_5d_threshold: 0,
  cash_stress_score_threshold: 62,
  cash_preference_proxy_threshold: 60,
  risk_expansion_breadth_threshold: 60,
  risk_contraction_breadth_threshold: 40,
  risk_release_breadth_threshold: 45,
  high_liquidity_selloff_threshold: 60,
  concentration_top_n: 20,
  daily_report_days: 20,
  flow_candidate_limit: 30,
  risk_timeline_days: 60
})

const regimeParameterGuideCards = [
  { label: '1. 基准环境', detail: '基准先有 60 日上涨，再出现 20 日回撤，才进入调整样本。' },
  { label: '2. 个股回调', detail: '20 日和 60 日回撤用于判断回调是否充分。' },
  { label: '3. 压力层级', detail: '高波、高位、高流动性依次承压，代表风险释放扩散。' },
  { label: '4. 阶段确认', detail: '宽度、现金偏好和高流动性破位共同决定 RAI 阶段。' }
]
const regimeActivePresetKey = computed(() => {
  const matched = REGIME_PARAMETER_PRESETS.find((preset) =>
    REGIME_PERCENT_FIELD_KEYS.every((field) => Math.abs(Number((regimeForm as Record<string, any>)[field]) - preset.values[field]) < 0.0001)
  )
  return matched?.key || ''
})

const activeMeta = computed(() => navItems.find((item) => item.key === activeView.value) || navItems[0])
const activeResearchMeta = computed(() => researchTabs.find((item) => item.key === activeResearchTab.value) || researchTabs[0])
const crossSearchModeLabel = computed(() => (crossForm.search_mode === 'traversal' ? '指定区间' : '同区间'))
const summary = computed(() => overview.value?.summary || {})
const assetRows = computed(() => overview.value?.by_asset_type || [])
const timeframeRows = computed(() => overview.value?.by_timeframe || [])
const datasetRows = computed(() => overview.value?.by_dataset || [])
const cacheRows = computed(() => overview.value?.records || [])
const overviewRecordCount = computed(() => numberValue(overview.value?.record_count))
const overviewRecordsLoaded = computed(() =>
  Boolean(overview.value) && (cacheRows.value.length > 0 || overviewRecordCount.value === 0)
)
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
    const symbol = normalizeSymbol(String(row.stock_code || ''))
    if (!symbol || meta.has(symbol)) return
    meta.set(symbol, {
      name: String(row.stock_name || '').trim(),
      assetType: String(row.asset_type || '').trim()
    })
  })
  return meta
})
const cacheRecordsBySymbol = computed(() => {
  const records = new Map<string, Array<Record<string, any>>>()
  cacheRows.value.forEach((row: Record<string, any>) => {
    const symbol = normalizeSymbol(String(row.stock_code || ''))
    if (!symbol) return
    const rows = records.get(symbol) || []
    rows.push(row)
    records.set(symbol, rows)
  })
  return records
})
const cacheSymbolsByAssetType = computed(() => {
  const grouped = new Map<string, Set<string>>()
  cacheRows.value.forEach((row: Record<string, any>) => {
    const type = String(row.asset_type || '').trim()
    const symbol = normalizeSymbol(String(row.stock_code || ''))
    if (!type || !symbol) return
    const symbols = grouped.get(type) || new Set<string>()
    symbols.add(symbol)
    grouped.set(type, symbols)
  })
  return new Map(Array.from(grouped.entries()).map(([type, symbols]) => [type, Array.from(symbols)]))
})
const symbolNameMap = computed(() => {
  const names = new Map<string, string>()
  Object.entries(config.value?.symbol_names || {}).forEach(([symbol, name]) => {
    const normalized = normalizeSymbol(symbol)
    const label = String(name || '').trim()
    if (normalized && label) names.set(normalized, label)
  })
  return names
})
const etfTrackingMetaBySymbol = computed(() => {
  const meta = new Map<string, Record<string, any>>()
  etfTrackingRows.value.forEach((row: Record<string, any>) => {
    const symbol = normalizeSymbol(String(row.stock_code || ''))
    if (!symbol || meta.has(symbol)) return
    const trackingSymbol = normalizeSymbol(String(row.tracking_symbol || ''))
    meta.set(symbol, {
      ...row,
      stock_code: symbol,
      tracking_symbol: trackingSymbol,
      stock_name: String(row.stock_name || '').trim(),
      tracking_name: String(row.tracking_name || '').trim()
    })
  })
  return meta
})
const etfReturnMetaBySymbol = computed(() => {
  const meta = new Map<string, Record<string, any>>()
  etfReturnRows.value.forEach((row: Record<string, any>) => {
    const symbol = normalizeSymbol(String(row.symbol || row.stock_code || ''))
    if (!symbol || meta.has(symbol)) return
    meta.set(symbol, row)
  })
  return meta
})
const etfTrackerUniverseRows = computed(() => {
  const symbols = uniqueStringsInOrder([
    ...etfTrackingRows.value.map((row: Record<string, any>) => normalizeSymbol(String(row.stock_code || ''))),
    ...groupSymbolsForAssetType('etf'),
    ...cacheSymbolsForAssetType('etf')
  ])
  return symbols.map((symbol) => {
    const tdxMeta = etfTrackingMetaBySymbol.value.get(symbol)
    const meta = cacheSymbolMeta.value.get(symbol)
    const name = String(tdxMeta?.stock_name || symbolNameMap.value.get(symbol) || meta?.name || '').trim()
    const trackingIndex = tdxMeta ? etfTrackingDisplayLabel(tdxMeta) : etfTrackingIndexLabel(name, symbol)
    const cacheRecord = cacheRecordForSymbol(symbol, researchTimeframe.value)
    const returnMeta = etfReturnMetaBySymbol.value.get(symbol)
    const category = etfTrackerCategory(symbol, name, trackingIndex)
    return {
      symbol,
      name,
      type: tdxMeta ? '股票型' : etfFundType(name, trackingIndex),
      category,
      categoryLabel: etfTrackerCategoryLabel(category),
      tracking_index: trackingIndex,
      status: STATUS_LABELS[String(cacheRecord?.status || '')] || cacheRecord?.status || '未扫描',
      source: tdxMeta ? 'TDX接口' : '代码表/缓存',
      now_price: returnMeta?.close ?? tdxMeta?.now_price,
      iopv: tdxMeta?.iopv,
      market_value: tdxMeta?.market_value,
      amount: returnMeta?.amount,
      return_1d: returnMeta?.return_1d,
      return_5d: returnMeta?.return_5d,
      return_20d: returnMeta?.return_20d,
      return_50d: returnMeta?.return_50d,
      return_ytd: returnMeta?.return_ytd,
      rows: numberValue(cacheRecord?.rows),
      end_at: formatDateTimeText(returnMeta?.latest_date || cacheRecord?.end_at)
    }
  })
})
const etfTrackingIndexOptions = computed(() =>
  uniqueStringsInOrder(etfTrackerUniverseRows.value.map((row) => row.tracking_index)).filter(Boolean)
)
const filteredEtfTrackerRows = computed(() => {
  const keyword = etfTrackerForm.keyword.trim().toLowerCase()
  return etfTrackerUniverseRows.value.filter((row) => {
    const text = `${row.symbol} ${row.name} ${row.type} ${row.categoryLabel} ${row.tracking_index}`.toLowerCase()
    return (
      (etfTrackerForm.category === 'all' || row.category === etfTrackerForm.category) &&
      (!etfTrackerForm.type || row.type === etfTrackerForm.type) &&
      (!etfTrackerForm.tracking_index || row.tracking_index === etfTrackerForm.tracking_index) &&
      (!keyword || text.includes(keyword))
    )
  })
})
const etfTrackerDisplayRows = computed(() =>
  etfTrackerForm.merge_similar ? mergeSimilarEtfRows(filteredEtfTrackerRows.value) : filteredEtfTrackerRows.value
)
const etfTrackerReviewSymbols = computed(() =>
  etfTrackerDisplayRows.value.slice(0, Math.max(1, Number(etfTrackerForm.top_n || 30))).map((row) => row.symbol)
)
const etfTrackerTotalPages = computed(() => Math.max(1, Math.ceil(etfTrackerDisplayRows.value.length / etfTrackerPagination.pageSize)))
const etfTrackerPageStartIndex = computed(() =>
  etfTrackerDisplayRows.value.length ? (etfTrackerPagination.page - 1) * etfTrackerPagination.pageSize : 0
)
const etfTrackerPageEnd = computed(() =>
  Math.min(etfTrackerPageStartIndex.value + etfTrackerPagination.pageSize, etfTrackerDisplayRows.value.length)
)
const etfTrackerPageFirst = computed(() => (etfTrackerDisplayRows.value.length ? etfTrackerPageStartIndex.value + 1 : 0))
const pagedEtfTrackerRows = computed(() => etfTrackerDisplayRows.value.slice(etfTrackerPageStartIndex.value, etfTrackerPageEnd.value))
const displayEtfTrackerRows = computed(() =>
  pagedEtfTrackerRows.value.map((row) => ({
    '代码': row.symbol,
    '名称': row.name || '-',
    '类别': row.categoryLabel,
    '类型': row.type,
    '跟踪指数': row.tracking_index,
    '最新价': formatDecimalValue(row.now_price, 3),
    '当日': formatPercentValue(row.return_1d),
    '近5日': formatPercentValue(row.return_5d),
    '近20日': formatPercentValue(row.return_20d),
    '近50日': formatPercentValue(row.return_50d),
    'YTD': formatPercentValue(row.return_ytd),
    '成交额': formatAmountValue(row.amount),
    'IOPV': formatDecimalValue(row.iopv, 3),
    '规模': formatDecimalValue(row.market_value, 1),
    '数据来源': row.source,
    '缓存状态': row.status,
    'K线行数': formatInt(row.rows),
    '最近日期': row.end_at || '-'
  }))
)
const etfTrackerPageSizeOptions = ETF_TRACKER_PAGE_SIZE_OPTIONS
const etfTrackerResultActive = computed(() =>
  Boolean(reviewResult.value && etfTrackerResultSignature.value === etfTrackerSearchSignature())
)
const etfTrackerReviewRows = computed(() => {
  if (!etfTrackerResultActive.value) return []
  const metaBySymbol = new Map(etfTrackerUniverseRows.value.map((row) => [row.symbol, row]))
  return (reviewResult.value?.ranking || []).map((row: Record<string, any>) => {
    const symbol = String(row['代码'] || '')
    const meta = metaBySymbol.get(symbol)
    return {
      '排名': row['排名'],
      '代码': symbol,
      '名称': row['股票'] || meta?.name || '-',
      '类型': meta?.type || '-',
      '跟踪指数': meta?.tracking_index || '-',
      '等级': row['强弱等级'],
      '区间收益': formatResearchValue('区间收益', row['区间收益']),
      '超额收益': formatResearchValue('超额收益', row['相对超额']),
      '最大回撤': formatResearchValue('最大回撤', row['最大回撤']),
      '趋势表达': `${row['强弱等级'] || '-'} · ${row['当前性质'] || '-'}`
    }
  })
})
const etfTrackerTrendCards = computed(() => etfTrackerReviewRows.value.slice(0, 6))
const etfTrackerSummaryCards = computed(() => [
  { label: 'ETF池', value: formatInt(etfTrackerUniverseRows.value.length), detail: `${researchTimeframe.value} · ${settings.adjust || '不复权'}` },
  { label: '筛选结果', value: formatInt(filteredEtfTrackerRows.value.length), detail: etfTrackerFilterSummary() },
  { label: '展示ETF', value: formatInt(etfTrackerDisplayRows.value.length), detail: etfTrackerForm.merge_similar ? '同类取成交额最大' : '全量展示' },
  { label: '复盘数量', value: formatInt(etfTrackerReviewSymbols.value.length), detail: `上限 ${formatInt(etfTrackerForm.top_n)}` },
  { label: '对标指数', value: etfTrackerForm.benchmark_symbol || '-', detail: `${etfTrackerForm.start} 至 ${etfTrackerForm.end}` }
])
const etfCacheStatusCards = computed(() => [
  {
    label: 'TDX接口',
    value: formatInt(etfTrackingCacheState.record_count || etfTrackingRows.value.length),
    detail: etfCacheStatusText(etfTrackingCacheState, loadingEtfTracking.value),
    tone: etfCacheTone(etfTrackingCacheState, loadingEtfTracking.value)
  },
  {
    label: '收益计算',
    value: formatInt(etfReturnsCacheState.record_count || etfReturnRows.value.length),
    detail: etfCacheStatusText(etfReturnsCacheState, loadingEtfReturns.value),
    tone: etfCacheTone(etfReturnsCacheState, loadingEtfReturns.value)
  }
])
const regimeSummaryCards = computed(() => {
  const summary = regimeResult.value?.summary || {}
  const appetite = regimeResult.value?.risk_appetite || {}
  const sequence = regimeResult.value?.risk_release_sequence || {}
  return [
    { label: 'Risk Appetite Index', value: formatDecimalValue(appetite.score, 1), detail: String(appetite.phase || '未运行') },
    { label: '研究资产', value: formatInt(summary.asset_count), detail: `${summary.benchmark_symbol || regimeForm.benchmark_symbol} · ${summary.timeframe || researchTimeframe.value}` },
    { label: '市场宽度', value: formatPercentValue(appetite.breadth_ma20), detail: '站上 MA20 比例' },
    { label: '高流动性破位', value: formatPercentValue(appetite.high_liquidity_break_ratio), detail: '高流动性资产跌破 MA20' },
    { label: '现金偏好代理', value: formatPercentValue(appetite.cash_preference_proxy), detail: `集中度 ${formatPercentValue(appetite.amount_concentration)}` },
    { label: '释放顺序', value: formatPercentValue(sequence.sequence_score), detail: String(sequence.current_stage || '未触发') }
  ]
})
const regimeStateCards = computed(() => {
  const state = regimeResult.value?.state_report || {}
  return [
    { label: '趋势状态', value: formatPercentValue(state.trend?.breadth_ma20), detail: `MA60 ${formatPercentValue(state.trend?.breadth_ma60)}` },
    { label: '波动率状态', value: formatPercentValue(state.volatility?.median_hv20), detail: `ATR/Close ${formatPercentValue(state.volatility?.median_atr20_close)}` },
    { label: '流动性状态', value: formatAmountValue(state.liquidity?.median_amount20), detail: `Top20占比 ${formatPercentValue(state.liquidity?.top20_amount_share)}` }
  ]
})
const regimeUniverseOptions = computed(() =>
  ['板块指数', 'ETF列表', '全A股票'].map((name) => {
    const group = config.value?.symbol_groups.find((item) => item.name === name)
    return {
      name,
      label: name === '板块指数' ? '通达信板块' : name.replace('列表', ''),
      count: group?.symbols.length || 0,
      disabled: !group?.symbols.length
    }
  })
)
const activeRegimeUniverseGroups = computed(() =>
  regimeForm.universe_groups.filter((name) => {
    const group = config.value?.symbol_groups.find((item) => item.name === name)
    return Boolean(group?.symbols.length)
  })
)
const selectedRegimeUniverseCount = computed(() =>
  regimeForm.universe_groups.reduce((total, name) => {
    const group = config.value?.symbol_groups.find((item) => item.name === name)
    return total + (group?.symbols.length || 0)
  }, parseSymbols(regimeForm.symbols).length)
)
const regimeDailyReportCards = computed(() => {
  const report = regimeResult.value?.daily_report || {}
  const flow = report.flow || {}
  return [
    { label: '报告日期', value: formatDateOnly(report.as_of) || '-', detail: report.title || '未生成' },
    { label: '风险阶段', value: report.phase || '-', detail: `RAI ${formatDecimalValue(report.score, 1)}` },
    { label: '趋势', value: report.trend_status || '-', detail: `模式 ${flow.market_mode || '-'}` },
    { label: '波动率', value: report.volatility_status || '-', detail: `流动性 ${report.liquidity_status || '-'}` }
  ]
})
const regimeAnswerCards = computed(() =>
  (regimeResult.value?.answer_cards || []).map((row: Record<string, any>) => ({
    question: row.question || '-',
    answer: row.answer || '-',
    detail: row.detail || '-',
    tone: row.tone || 'neutral'
  }))
)
const regimeRaiTrendRows = computed(() => {
  const rows = regimeResult.value?.risk_appetite_series || regimeResult.value?.daily_report_history || []
  return rows.map((row: Record<string, any>) => ({
    date: row.date || row.as_of,
    score: numberValue(row.score),
    phase: String(row.phase || ''),
    breadth_ma20: row.breadth_ma20,
    high_liquidity_break_ratio: row.high_liquidity_break_ratio,
    cash_preference_proxy: row.cash_preference_proxy,
    short_momentum: row.short_momentum,
    amount_concentration: row.amount_concentration
  })).filter((row: Record<string, any>) => row.date)
})
const regimeRaiWindowSize = computed(() => Math.min(REGIME_RAI_WINDOW_SIZE, regimeRaiTrendRows.value.length))
const regimeRaiWindowMaxStart = computed(() => Math.max(0, regimeRaiTrendRows.value.length - regimeRaiWindowSize.value))
const regimeRaiWindowStartValue = computed(() => {
  if (regimeRaiWindowStart.value < 0) return regimeRaiWindowMaxStart.value
  return Math.min(Math.max(0, regimeRaiWindowStart.value), regimeRaiWindowMaxStart.value)
})
const visibleRegimeRaiTrendRows = computed(() => {
  const start = regimeRaiWindowStartValue.value
  return regimeRaiTrendRows.value.slice(start, start + regimeRaiWindowSize.value)
})
const regimeRaiWindowAvailable = computed(() => regimeRaiTrendRows.value.length > regimeRaiWindowSize.value)
const regimeRaiWindowLabel = computed(() => {
  const rows = visibleRegimeRaiTrendRows.value
  if (!rows.length) return '-'
  return `${formatDateOnly(rows[0].date)} 至 ${formatDateOnly(rows[rows.length - 1].date)}`
})
const regimeRaiChartPoints = computed(() => {
  const rows = visibleRegimeRaiTrendRows.value
  const width = 592
  const height = 144
  const left = 24
  const top = 24
  return rows.map((row: Record<string, any>, index: number) => {
    const x = left + (rows.length <= 1 ? width / 2 : (index / (rows.length - 1)) * width)
    const score = Math.max(0, Math.min(100, numberValue(row.score)))
    const y = top + ((100 - score) / 100) * height
    return {
      key: `${formatDateOnly(row.date)}-${index}`,
      x,
      y,
      score,
      phase: row.phase,
      date: row.date,
      breadth_ma20: row.breadth_ma20,
      high_liquidity_break_ratio: row.high_liquidity_break_ratio,
      cash_preference_proxy: row.cash_preference_proxy,
      short_momentum: row.short_momentum,
      amount_concentration: row.amount_concentration,
      tone: regimePhaseTone(row.phase),
      title: `${formatDateOnly(row.date)} · RAI ${formatDecimalValue(score, 1)} · ${row.phase || '-'}`
    }
  })
})
const regimeRaiLinePoints = computed(() => regimeRaiChartPoints.value.map((point: Record<string, any>) => `${point.x},${point.y}`).join(' '))
const activeRegimeRaiPoint = computed(() => {
  const points = regimeRaiChartPoints.value
  if (!points.length) return null
  return points.find((point: Record<string, any>) => point.key === activeRegimeRaiKey.value) || points[points.length - 1]
})
const regimeRaiDrivers = computed(() => {
  const point = activeRegimeRaiPoint.value || {}
  return [
    { label: 'MA20宽度', value: formatPercentValue(point.breadth_ma20), detail: '站上MA20资产占比，低于35%偏弱' },
    { label: '5日动量', value: formatPercentValue(point.short_momentum), detail: '资产池近5日表现，负值代表回撤' },
    { label: '高流动性破位', value: formatPercentValue(point.high_liquidity_break_ratio), detail: '高成交资产跌破MA20占比' },
    { label: '现金偏好', value: formatPercentValue(point.cash_preference_proxy), detail: '防守/现金代理强度，高位偏避险' },
    { label: '成交集中度', value: formatPercentValue(point.amount_concentration), detail: '成交额向少数资产集中程度' }
  ]
})
const regimeRaiScaleCards = [
  { label: '65-100', value: '风险偏好扩张', detail: '宽度扩散、资金回流', tone: 'positive' },
  { label: '35-65', value: '震荡修复', detail: '风险与修复并存', tone: 'neutral' },
  { label: '0-35', value: '收缩/释放', detail: '现金偏好、权重破位', tone: 'negative' }
]
const regimeRaiAxisLabels = computed(() => {
  const rows = visibleRegimeRaiTrendRows.value
  if (!rows.length) return []
  const middle = rows[Math.floor((rows.length - 1) / 2)]
  return [formatDateOnly(rows[0].date), formatDateOnly(middle.date), formatDateOnly(rows[rows.length - 1].date)]
})
const regimeRaiLatestBadges = computed(() => {
  const latest = regimeRaiTrendRows.value[regimeRaiTrendRows.value.length - 1] || {}
  return [
    { label: '最新', value: formatDecimalValue(latest.score, 1) },
    { label: 'MA20宽度', value: formatPercentValue(latest.breadth_ma20) },
    { label: '现金偏好', value: formatPercentValue(latest.cash_preference_proxy) }
  ]
})
function setActiveRegimeRaiPoint(point: Record<string, any>) {
  activeRegimeRaiKey.value = String(point.key || '')
}

function onRegimeRaiWindowInput(event: Event) {
  const input = event.target as HTMLInputElement | null
  regimeRaiWindowStart.value = Number(input?.value || 0)
}

function displaySymbolName(symbol: unknown) {
  const normalized = normalizeSymbol(String(symbol || ''))
  if (!normalized) return '-'
  const etfMeta = etfTrackingMetaBySymbol.value.get(normalized)
  return symbolNameMap.value.get(normalized) || cacheSymbolMeta.value.get(normalized)?.name || etfMeta?.stock_name || '-'
}

const regimeRiskTimelineRows = computed(() =>
  (regimeResult.value?.risk_release_timeline || []).map((row: Record<string, any>) => ({
    date: formatDateOnly(row.date),
    layer: String(row.layer || ''),
    layer_order: numberValue(row.layer_order),
    asset_count: numberValue(row.asset_count),
    return_5d: row.return_5d,
    ma20_break_ratio: row.ma20_break_ratio,
    amount_share: row.amount_share,
    stress_score: numberValue(row.stress_score),
    stress_signal: Boolean(row.stress_signal),
    stress_level: String(row.stress_level || '')
  })).filter((row: Record<string, any>) => row.date && row.layer)
)
const regimeRiskTimelineDates = computed(() =>
  uniqueStringsInOrder(regimeRiskTimelineRows.value.map((row: Record<string, any>) => row.date)).sort().reverse()
)
const latestRegimeRiskTimelineDate = computed(() => regimeRiskTimelineDates.value[0] || '')
const latestRegimeRiskTriggerLayers = computed(() =>
  regimeRiskTimelineRows.value
    .filter((row: Record<string, any>) => row.date === latestRegimeRiskTimelineDate.value && row.stress_signal)
    .map((row: Record<string, any>) => row.layer)
)
const regimeRiskTimelineDateHeaders = computed(() => {
  const dates = regimeRiskTimelineDates.value
  const lastIndex = dates.length - 1
  return dates.map((date, index) => ({
    date,
    show: dates.length <= 14 || index === 0 || index === lastIndex || index % 5 === 0
  }))
})
const regimeRiskReleaseSummary = computed(() => {
  const sequence = regimeResult.value?.risk_release_sequence || {}
  const triggeredLayers = latestRegimeRiskTriggerLayers.value
  return [
    {
      label: '最新日期',
      value: shortDateLabel(latestRegimeRiskTimelineDate.value),
      detail: '时间线最左侧'
    },
    {
      label: '触发层级',
      value: triggeredLayers.length ? `${triggeredLayers.length}层` : '0层',
      detail: triggeredLayers.length ? triggeredLayers.join('、') : '未触发释放信号'
    },
    {
      label: '顺序吻合',
      value: formatPercentValue(sequence.sequence_score),
      detail: '越高越接近标准释放路径'
    },
    {
      label: '当前阶段',
      value: String(sequence.current_stage || '未触发'),
      detail: '最新压力所在层级'
    }
  ]
})
const regimeRiskReleaseNarrative = computed(() => {
  const latestDate = latestRegimeRiskTimelineDate.value
  const layers = latestRegimeRiskTriggerLayers.value
  if (!latestDate) return '运行后显示风险释放路径。'
  if (!layers.length) return `${shortDateLabel(latestDate)} 未触发释放层级，主要观察压力是否继续升温。`
  return `${shortDateLabel(latestDate)} 已触发：${layers.join('、')}。`
})
const regimeRiskHeatmapRows = computed(() => {
  const rowsByKey = new Map(regimeRiskTimelineRows.value.map((row: Record<string, any>) => [`${row.layer}-${row.date}`, row]))
  const layers = uniqueStringsInOrder([
    ...RISK_RELEASE_LAYER_ORDER,
    ...regimeRiskTimelineRows.value.map((row: Record<string, any>) => row.layer)
  ]).filter((layer) => regimeRiskTimelineRows.value.some((row: Record<string, any>) => row.layer === layer))
  return layers.map((layer) => ({
    layer,
    description: RISK_RELEASE_LAYER_DESCRIPTIONS[layer] || '压力层级',
    cells: regimeRiskTimelineDates.value.map((date) => {
      const row: Record<string, any> = rowsByKey.get(`${layer}-${date}`) || {}
      const stressScore = numberValue(row.stress_score)
      return {
        key: `${layer}-${date}`,
        date,
        layer,
        stress_score: stressScore,
        stress_signal: Boolean(row.stress_signal),
        stress_level: String(row.stress_level || ''),
        label: riskHeatmapStatusLabel(Boolean(row.stress_signal), stressScore),
        title: `${date} · ${layer} · 压力 ${formatPercentValue(stressScore)} · 跌破MA20 ${formatPercentValue(row.ma20_break_ratio)} · 近5日 ${formatPercentValue(row.return_5d)} · 成交额占比 ${formatPercentValue(row.amount_share)}`
      }
    })
  }))
})
const regimeHeatmapRowTemplate = computed(() => `18px repeat(${Math.max(1, regimeRiskHeatmapRows.value.length)}, 38px)`)
const regimeHeatmapAxisStyle = computed(() => ({
  gridTemplateRows: regimeHeatmapRowTemplate.value
}))
const regimeHeatmapGridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${Math.max(1, regimeRiskTimelineDates.value.length)}, 56px)`,
  gridTemplateRows: regimeHeatmapRowTemplate.value
}))
const displayRegimeDailyEvidenceCards = computed(() =>
  (regimeResult.value?.daily_report?.evidence || []).map((row: Record<string, any>) => {
    const metric = String(row.metric || '-')
    return {
      metric,
      value: metric.includes('数量') ? formatInt(row.value) : formatPercentValue(row.value),
      detail: dailyEvidenceDetail(metric),
      tone: dailyEvidenceTone(metric)
    }
  })
)
const displayRegimeDailyHistoryRows = computed(() =>
  (regimeResult.value?.daily_report_history || []).map((row: Record<string, any>) => ({
    '日期': formatDateOnly(row.as_of),
    'RAI': formatDecimalValue(row.score, 1),
    '阶段': row.phase,
    '趋势': row.trend_status,
    '波动率': row.volatility_status,
    '流动性': row.liquidity_status,
    '流出': row.funds_leaving,
    '流入': row.funds_entering,
    '高流动性抛售': row.high_liquidity_selloff ? '是' : '否',
    '更接近': row.closer_to,
    '释放阶段': row.current_release_stage,
    'MA20宽度': formatPercentValue(row.breadth_ma20),
    '高流动性破位': formatPercentValue(row.high_liquidity_break_ratio),
    '现金偏好': formatPercentValue(row.cash_preference_proxy),
    '成交额集中度': formatPercentValue(row.amount_concentration)
  }))
)
const displayRegimeComponentRows = computed(() =>
  (regimeResult.value?.risk_appetite_components || []).map((row: Record<string, any>) => ({
    '组成': row.component,
    '信号': row.signal,
    '资产数': formatInt(row.asset_count),
    '分项分': formatDecimalValue(row.score, 1),
    '贡献': formatDecimalValue(row.contribution, 1),
    '近5日收益': formatPercentValue(row.return_5d),
    '跌破MA20': formatPercentValue(row.ma20_break_ratio),
    '成交额占比': formatPercentValue(row.amount_share),
    '阈值': row.threshold === null || row.threshold === undefined ? '-' : formatPercentValue(row.threshold)
  }))
)
const displayRegimeFlowCandidateRows = computed(() =>
  (regimeResult.value?.flow_candidates || []).map((row: Record<string, any>) => ({
    '排名': formatInt(row.rank),
    '代码': row.stock_code,
    '名称': displaySymbolName(row.stock_code),
    '评分': formatDecimalValue(row.score, 1),
    '分组': String(row.group || '').replace('回调充分+转强', '回调充分 + 转强').replace('回调充分+未转强', '回调充分 + 未转强'),
    '资产池': row.asset_pool,
    '理由': row.reason,
    '近5日': formatPercentValue(row.ret_5),
    '近20日': formatPercentValue(row.ret_20),
    '20日回撤': formatPercentValue(row.drawdown_20),
    '60日回撤': formatPercentValue(row.drawdown_60),
    'RS20': formatPercentValue(row.rs20),
    'RS排名': formatPercentValue(row.rs_rank),
    '成交额分位': formatPercentValue(row.amount_percentile),
    '成交收缩': formatPercentValue(row.amount_contraction),
    'MA20': row.above_ma20 ? '上方' : '下方',
    '转强': row.turn_strong ? '是' : '否',
    '回调充分': row.pullback_sufficient ? '是' : '否',
    '高位': row.high_position_signal ? '是' : '否',
    '高流动性': row.high_liquidity_signal ? '是' : '否'
  }))
)
const regimeFlowCandidateTotalPages = computed(() =>
  Math.max(1, Math.ceil(displayRegimeFlowCandidateRows.value.length / regimeFlowCandidatePagination.pageSize))
)
const regimeFlowCandidatePageStartIndex = computed(() =>
  displayRegimeFlowCandidateRows.value.length
    ? (regimeFlowCandidatePagination.page - 1) * regimeFlowCandidatePagination.pageSize
    : 0
)
const regimeFlowCandidatePageEnd = computed(() =>
  Math.min(regimeFlowCandidatePageStartIndex.value + regimeFlowCandidatePagination.pageSize, displayRegimeFlowCandidateRows.value.length)
)
const regimeFlowCandidatePageFirst = computed(() =>
  displayRegimeFlowCandidateRows.value.length ? regimeFlowCandidatePageStartIndex.value + 1 : 0
)
const pagedRegimeFlowCandidateRows = computed(() =>
  displayRegimeFlowCandidateRows.value.slice(regimeFlowCandidatePageStartIndex.value, regimeFlowCandidatePageEnd.value)
)
const regimeFlowCandidatePageSizeOptions = REGIME_FLOW_CANDIDATE_PAGE_SIZE_OPTIONS
const regimeDailyCaveats = computed(() =>
  (regimeResult.value?.daily_report?.caveats || []).map((item: unknown) => String(item || '').trim()).filter(Boolean)
)
const displayRegimeBenchmarkRows = computed(() => {
  const row = regimeResult.value?.benchmark_regime
  if (!row) return []
  return [
    {
      '基准': row.benchmark_symbol || regimeForm.benchmark_symbol,
      '日期': formatDateOnly(row.as_of),
      '阶段': row.stage || '-',
      '当前调整': row.is_adjustment_stage ? '是' : '否',
      '60日涨幅': formatPercentValue(row.ret_60),
      '20日回撤': formatPercentValue(row.drawdown_20),
      '样本数': formatInt(row.sample_count),
      '调整样本': formatInt(row.adjustment_sample_count),
      '调整占比': formatPercentValue(row.adjustment_ratio),
      '涨幅阈值': formatPercentValue(row.rally_60_threshold),
      '回撤阈值': formatPercentValue(row.pullback_20_threshold)
    }
  ]
})
const displayRegimeAdjustmentFactorAdvantageRows = computed(() =>
  (regimeResult.value?.adjustment_factor_advantage?.by_window || []).map((row: Record<string, any>) => ({
    '窗口': row.window,
    'A组样本': formatInt(row.a_sample_count),
    '基准样本': formatInt(row.market_sample_count),
    'A组平均收益': formatPercentValue(row.a_mean_return),
    '基准平均收益': formatPercentValue(row.market_mean_return),
    '相对基准': formatPercentValue(row.excess_vs_market),
    'A组胜率': formatPercentValue(row.a_win_rate),
    '相对指数': formatPercentValue(row.benchmark_excess_return),
    '是否占优': row.advantage ? '是' : '否'
  }))
)
const displayRegimeAdjustmentFactorRows = computed(() =>
  (regimeResult.value?.adjustment_factor_backtest || []).map((row: Record<string, any>) => ({
    '分组': String(row.group || '').replace('回调充分+转强', '回调充分 + 转强').replace('回调充分+未转强', '回调充分 + 未转强'),
    '窗口': row.window,
    '样本数': formatInt(row.sample_count),
    '平均收益': formatPercentValue(row.mean_return),
    '胜率': formatPercentValue(row.win_rate),
    '超额收益': formatPercentValue(row.excess_return)
  }))
)
const displayRegimeFactorAdvantageRows = computed(() =>
  (regimeResult.value?.factor_advantage?.by_window || []).map((row: Record<string, any>) => ({
    '窗口': row.window,
    'A组样本': formatInt(row.a_sample_count),
    '基准样本': formatInt(row.market_sample_count),
    'A组平均收益': formatPercentValue(row.a_mean_return),
    '基准平均收益': formatPercentValue(row.market_mean_return),
    '相对基准': formatPercentValue(row.excess_vs_market),
    'A组胜率': formatPercentValue(row.a_win_rate),
    '相对指数': formatPercentValue(row.benchmark_excess_return),
    '是否占优': row.advantage ? '是' : '否'
  }))
)
const displayRegimeFactorRows = computed(() =>
  (regimeResult.value?.factor_backtest || []).map((row: Record<string, any>) => ({
    '分组': String(row.group || '').replace('回调充分+转强', '回调充分 + 转强').replace('回调充分+未转强', '回调充分 + 未转强'),
    '窗口': row.window,
    '样本数': formatInt(row.sample_count),
    '平均收益': formatPercentValue(row.mean_return),
    '胜率': formatPercentValue(row.win_rate),
    '超额收益': formatPercentValue(row.excess_return)
  }))
)
const displayRegimeMigrationRows = computed(() =>
  (regimeResult.value?.migration_layers || []).map((row: Record<string, any>) => ({
    '层级': row.layer,
    '资产数': formatInt(row.asset_count),
    '近5日收益': formatPercentValue(row.return_5d),
    '跌破MA20': formatPercentValue(row.ma20_break_ratio),
    '成交额占比': formatPercentValue(row.amount_share)
  }))
)
const displayRegimeSequenceRows = computed(() =>
  (regimeResult.value?.risk_release_sequence?.layers || []).map((row: Record<string, any>) => ({
    '阶段': row.layer,
    '首次触发': formatDateOnly(row.first_stress_date) || '-',
    '领先/滞后天数': row.lead_lag_days ?? '-',
    '当前触发': row.current_stress ? '是' : '否',
    '资产数': formatInt(row.asset_count),
    '近5日收益': formatPercentValue(row.return_5d),
    '跌破MA20': formatPercentValue(row.ma20_break_ratio),
    '压力分': formatPercentValue(row.stress_score)
  }))
)
const displayRegimeHighLiquidityBreakRows = computed(() =>
  (regimeResult.value?.high_liquidity_break_study || []).map((row: Record<string, any>) => ({
    '窗口': row.window,
    '事件数': formatInt(row.event_count),
    '事件资产收益': formatPercentValue(row.event_asset_mean_return),
    '全市场收益': formatPercentValue(row.market_mean_return),
    '基准收益': formatPercentValue(row.benchmark_mean_return),
    '基准胜率': formatPercentValue(row.benchmark_win_rate),
    '事件宽度': formatPercentValue(row.breadth_ma20_at_event)
  }))
)
const displayRegimeMarketScopeRows = computed(() =>
  (regimeResult.value?.market_scope?.series || []).map((row: Record<string, any>) => ({
    '日期': formatDateOnly(row.date),
    '资产数': formatInt(row.asset_count),
    '上涨资产': formatInt(row.rising_count),
    '上涨占比': formatPercentValue(row.rising_ratio),
    '领涨资产': formatInt(row.leader_count),
    '领涨占比': formatPercentValue(row.leader_ratio),
    'MA20宽度': formatPercentValue(row.breadth_ma20),
    '成交额集中度': formatPercentValue(row.top20_amount_share),
    '近5日中位收益': formatPercentValue(row.median_return_5d)
  }))
)
const regimeMarketScopeTotalPages = computed(() =>
  Math.max(1, Math.ceil(displayRegimeMarketScopeRows.value.length / regimeMarketScopePagination.pageSize))
)
const regimeMarketScopePageStartIndex = computed(() =>
  displayRegimeMarketScopeRows.value.length ? (regimeMarketScopePagination.page - 1) * regimeMarketScopePagination.pageSize : 0
)
const regimeMarketScopePageEnd = computed(() =>
  Math.min(regimeMarketScopePageStartIndex.value + regimeMarketScopePagination.pageSize, displayRegimeMarketScopeRows.value.length)
)
const regimeMarketScopePageFirst = computed(() =>
  displayRegimeMarketScopeRows.value.length ? regimeMarketScopePageStartIndex.value + 1 : 0
)
const pagedRegimeMarketScopeRows = computed(() =>
  displayRegimeMarketScopeRows.value.slice(regimeMarketScopePageStartIndex.value, regimeMarketScopePageEnd.value)
)
const regimeMarketScopePageSizeOptions = REGIME_MARKET_SCOPE_PAGE_SIZE_OPTIONS
const displayRegimeAssetRows = computed(() =>
  (regimeResult.value?.asset_rows || []).map((row: Record<string, any>) => ({
    '代码': row.stock_code,
    '分组': String(row.group || '').replace('回调充分+转强', '回调充分 + 转强').replace('回调充分+未转强', '回调充分 + 未转强'),
    '资产池': row.asset_pool,
    '日期': formatDateOnly(row.date),
    '20日回撤': formatPercentValue(row.drawdown_20),
    '60日回撤': formatPercentValue(row.drawdown_60),
    'RS20': formatPercentValue(row.rs20),
    'RS排名': formatPercentValue(row.rs_rank),
    '近5日': formatPercentValue(row.ret_5),
    '近20日': formatPercentValue(row.ret_20),
    '近120日': formatPercentValue(row.ret_120),
    'HV20': formatPercentValue(row.hv20),
    'HV60': formatPercentValue(row.hv60),
    'ATR20/Close': formatPercentValue(row.atr20_close),
    '20日成交额': formatAmountValue(row.amount20),
    '60日成交额': formatAmountValue(row.amount60),
    '成交额排名': formatDecimalValue(row.amount_rank, 0),
    '成交额分位': formatPercentValue(row.amount_percentile),
    '波动桶': row.volatility_bucket,
    '流动性桶': row.liquidity_bucket,
    '位置桶': row.position_bucket,
    '高位信号': row.high_position_signal ? '是' : '否',
    '高流动性': row.high_liquidity_signal ? '是' : '否',
    'MA20': row.above_ma20 ? '上方' : '下方',
    'MA60': row.above_ma60 ? '上方' : '下方'
  }))
)
const cacheTotalPages = computed(() => Math.max(1, Math.ceil(filteredCacheRows.value.length / cachePagination.pageSize)))
const cachePageStartIndex = computed(() =>
  filteredCacheRows.value.length ? (cachePagination.page - 1) * cachePagination.pageSize : 0
)
const cachePageEnd = computed(() => Math.min(cachePageStartIndex.value + cachePagination.pageSize, filteredCacheRows.value.length))
const cachePageFirst = computed(() => (filteredCacheRows.value.length ? cachePageStartIndex.value + 1 : 0))
const pagedCacheRows = computed(() => filteredCacheRows.value.slice(cachePageStartIndex.value, cachePageEnd.value))
const displayCacheRows = computed(() => pagedCacheRows.value.map((row: Record<string, any>) => displayCacheRecord(row)))
const cachePageSizeOptions = CACHE_PAGE_SIZE_OPTIONS
const planTotalPages = computed(() => Math.max(1, Math.ceil(planRows.value.length / planPagination.pageSize)))
const planPageStartIndex = computed(() => (planRows.value.length ? (planPagination.page - 1) * planPagination.pageSize : 0))
const planPageEnd = computed(() => Math.min(planPageStartIndex.value + planPagination.pageSize, planRows.value.length))
const planPageFirst = computed(() => (planRows.value.length ? planPageStartIndex.value + 1 : 0))
const pagedPlanRows = computed(() => planRows.value.slice(planPageStartIndex.value, planPageEnd.value))
const displayPlanRows = computed(() => pagedPlanRows.value.map((row: Record<string, any>) => displayRecord(row)))
const planPageSizeOptions = PLAN_PAGE_SIZE_OPTIONS
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
    const targetCandles = Array.isArray(crossResult.value.target_chart_window) && crossResult.value.target_chart_window.length
      ? crossResult.value.target_chart_window
      : crossResult.value.target_window
    items.push({
      symbol: crossResult.value.summary?.target_symbol || crossForm.target_symbol,
      name: crossResult.value.summary?.stock_name || crossResult.value.summary?.target_symbol || crossForm.target_symbol,
      label: '目标窗口',
      candles: targetCandles,
      segments: crossResult.value.target_segments || [klineSegment(crossResult.value.target_window, '对标窗口')]
    })
  }
  const candidateWindows = crossResult.value.candidate_windows || []
  candidateWindows.slice(0, 5).forEach((row: Record<string, any>) => {
    if (!row.candles?.length) return
    items.push({
      symbol: row.symbol,
      name: row.name || row['股票'] || row.symbol,
      rank: row.rank || '',
      candles: row.chart_candles || row.candles,
      segments: row.segments || [klineSegment(row.candles, '对标窗口')]
    })
  })
  return items
})
const crossChartSummary = computed(() => {
  const count = Math.max(crossChartItems.value.length - 1, 0)
  const summary = crossResult.value?.summary || {}
  const timeframe = summary.timeframe || researchTimeframe.value
  if (!crossChartItems.value.length) return ''
  if (summary.search_mode === 'traversal') {
    return `目标窗口 + ${count} 个候选匹配 · ${timeframe} · 目标 ${formatDateTimeText(summary.target_start || summary.start)} 至 ${formatDateTimeText(summary.target_end || summary.end)} · 候选 ${formatDateTimeText(summary.candidate_start || summary.traversal_start)} 至 ${formatDateTimeText(summary.candidate_end || summary.traversal_end)}`
  }
  return `目标窗口 + ${count} 个候选匹配 · ${timeframe} · 目标 ${formatDateTimeText(summary.target_start || summary.start || crossForm.start)} 至 ${formatDateTimeText(summary.target_end || summary.end || crossForm.end)}`
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
const aiCommandScopeLabel = computed(() => {
  if (activeView.value !== 'research') return `作用于：${activeMeta.value.title}`
  return `作用于：研究工具 / ${activeResearchMeta.value.label}`
})
const chartThemeClass = computed(() => `chart-theme-${chartSettings.theme === 'contrast' ? 'contrast' : 'clean'}`)
const chartDensityClass = computed(() => `chart-density-${chartSettings.density === 'compact' ? 'compact' : 'comfortable'}`)
const aiDefaultSystemPrompt = computed(() =>
  String((reviewResult.value?.ai?.messages || []).find((message: Record<string, string>) => message.role === 'system')?.content || '')
)
const aiWorkbenchLatestRows = computed(() =>
  (aiWorkbenchResult.value?.data_context?.latest || []).map((row: Record<string, any>) => ({
    '代码': row.symbol,
    '名称': row.name || displaySymbolName(row.symbol),
    '日期': formatDateOnly(row.date),
    '收盘': formatDecimalValue(row.close, 2),
    '区间收益': formatPercentValue(row.return),
    '行数': formatInt(row.rows)
  }))
)
const aiWorkbenchRecordRows = computed(() =>
  (aiWorkbenchResult.value?.data_context?.records || []).slice(0, 80).map((row: Record<string, any>) => ({
    '日期': formatDateOnly(row.date),
    '代码': row.stock_code,
    '开': formatDecimalValue(row.open, 2),
    '高': formatDecimalValue(row.high, 2),
    '低': formatDecimalValue(row.low, 2),
    '收': formatDecimalValue(row.close, 2),
    '成交额': formatAmountValue(row.amount)
  }))
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
const selectedTaskQualityIssues = computed(() => parseQualityGateIssues(selectedTask.value?.error || ''))
const taskQualityIssueTotalPages = computed(() =>
  Math.max(1, Math.ceil(selectedTaskQualityIssues.value.length / taskQualityIssuePagination.pageSize))
)
const taskQualityIssuePageStartIndex = computed(() =>
  selectedTaskQualityIssues.value.length ? (taskQualityIssuePagination.page - 1) * taskQualityIssuePagination.pageSize : 0
)
const taskQualityIssuePageEnd = computed(() =>
  Math.min(taskQualityIssuePageStartIndex.value + taskQualityIssuePagination.pageSize, selectedTaskQualityIssues.value.length)
)
const taskQualityIssuePageFirst = computed(() =>
  selectedTaskQualityIssues.value.length ? taskQualityIssuePageStartIndex.value + 1 : 0
)
const pagedTaskQualityIssueRows = computed(() =>
  selectedTaskQualityIssues.value.slice(taskQualityIssuePageStartIndex.value, taskQualityIssuePageEnd.value).map((issue) => ({
    '序号': issue.index,
    '代码': issue.symbol,
    '周期': issue.timeframe,
    '状态': issue.status_label,
    '信息': issue.message
  }))
)
const taskQualityIssuePageSizeOptions = TASK_QUALITY_PAGE_SIZE_OPTIONS
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
const downloadTimeframeOptions = computed(() => sortTimeframes(config.value?.timeframes || Object.keys(TIMEFRAME_DIR_NAMES)))
const selectedDownloadTimeframes = computed(() => normalizeDownloadTimeframes(selectedTimeframes.value))
const downloadTimeframeSummary = computed(() => {
  const selected = selectedDownloadTimeframes.value
  if (!selected.length) return '未选择'
  if (selected.length === downloadTimeframeOptions.value.length) return `全周期 ${selected.length}`
  return selected.join(' / ')
})
const reviewSymbolPickerTypeLabel = computed(() =>
  REVIEW_SYMBOL_PICKER_TABS.find((item) => item.key === reviewSymbolPickerType.value)?.label || '标的'
)
const reviewSymbolPickerGroups = computed(() =>
  reviewSymbolGroupsForType(reviewSymbolPickerType.value)
)
const reviewSymbolPickerRows = computed(() =>
  uniqueStringsInOrder(reviewSymbolPickerGroups.value.flatMap((group) => group.symbols)).map((symbol) => {
    const meta = cacheSymbolMeta.value.get(symbol)
    const name = symbolNameMap.value.get(symbol) || meta?.name || ''
    const assetType = meta?.assetType || ''
    const category = reviewSymbolCategory(reviewSymbolPickerType.value, symbol, name, assetType)
    return {
      symbol,
      name,
      assetType,
      category,
      categoryLabel: reviewSymbolCategoryLabel(reviewSymbolPickerType.value, category)
    }
  })
)
const reviewSymbolPickerCategoryOptions = computed(() => {
  const definitions = reviewSymbolCategoryDefinitions(reviewSymbolPickerType.value)
  const counts = new Map<string, number>()
  reviewSymbolPickerRows.value.forEach((row) => {
    counts.set(row.category, (counts.get(row.category) || 0) + 1)
    counts.set('all', (counts.get('all') || 0) + 1)
  })
  return definitions.map((item) => ({
    ...item,
    count: counts.get(item.value) || 0
  }))
})
const categoryFilteredReviewSymbolPickerRows = computed(() => {
  const category = reviewSymbolPickerCategory.value || defaultReviewSymbolCategory(reviewSymbolPickerType.value)
  if (category === 'all') return reviewSymbolPickerRows.value
  return reviewSymbolPickerRows.value.filter((row) => row.category === category)
})
const filteredReviewSymbolPickerRows = computed(() => {
  const keyword = reviewSymbolPickerKeyword.value.trim().toLowerCase()
  if (!keyword) return categoryFilteredReviewSymbolPickerRows.value
  return categoryFilteredReviewSymbolPickerRows.value.filter((row) =>
    `${row.symbol} ${row.name} ${row.assetType} ${row.categoryLabel}`.toLowerCase().includes(keyword)
  )
})
const reviewSymbolPickerVisibleRows = computed(() =>
  filteredReviewSymbolPickerRows.value.slice(0, REVIEW_SYMBOL_PICKER_VISIBLE_LIMIT)
)
const reviewSymbolPickerSelectionSet = computed(() => new Set(reviewSymbolPickerSelection.value))
const reviewSymbolPickerSourceSummary = computed(() => {
  const names = reviewSymbolPickerGroups.value.map((group) => group.name).join(' / ') || reviewSymbolPickerTypeLabel.value
  const category =
    reviewSymbolPickerCategoryOptions.value.find((item) => item.value === reviewSymbolPickerCategory.value) ||
    reviewSymbolPickerCategoryOptions.value[0]
  return `${names} · ${category?.label || '全部'} ${formatInt(category?.count || 0)} / ${formatInt(reviewSymbolPickerRows.value.length)} 只`
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
watch(
  () => [
    etfTrackerForm.category,
    etfTrackerForm.type,
    etfTrackerForm.tracking_index,
    etfTrackerForm.keyword,
    etfTrackerForm.merge_similar,
    etfTrackerPagination.pageSize
  ],
  () => {
    etfTrackerPagination.page = 1
  }
)
watch(cacheTotalPages, () => {
  goCachePage(cachePagination.page)
})
watch(etfTrackerTotalPages, () => {
  goEtfTrackerPage(etfTrackerPagination.page)
})
watch(regimeFlowCandidateTotalPages, () => {
  goRegimeFlowCandidatePage(regimeFlowCandidatePagination.page)
})
watch(regimeMarketScopeTotalPages, () => {
  goRegimeMarketScopePage(regimeMarketScopePagination.page)
})
watch(planTotalPages, () => {
  goPlanPage(planPagination.page)
})
watch(selectedTaskId, () => {
  taskEventPagination.page = 1
  taskResultPagination.page = 1
  taskQualityIssuePagination.page = 1
})
watch(taskEventTotalPages, () => {
  goTaskEventPage(taskEventPagination.page)
})
watch(taskResultTotalPages, () => {
  goTaskResultPage(taskResultPagination.page)
})
watch(taskQualityIssueTotalPages, () => {
  goTaskQualityIssuePage(taskQualityIssuePagination.page)
})
watch(activeView, (view) => {
  if (view === 'cache' && !overviewRecordsLoaded.value && !loadingOverview.value) {
    void loadOverview(false, { includeRecords: true })
  }
  if (view === 'research' && activeResearchTab.value === 'etf') ensureEtfTrackingLoaded()
  normalizeResizableCardWidths()
})
watch(activeResearchTab, (tab) => {
  if (tab === 'etf') ensureEtfTrackingLoaded()
  normalizeResizableCardWidths()
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
const taskQualityIssueColumns = [
  { key: '序号', label: '序号' },
  { key: '代码', label: '代码' },
  { key: '周期', label: '周期' },
  { key: '状态', label: '状态' },
  { key: '信息', label: '信息' }
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
  { key: '股票', label: '名称' },
  { key: '区间开始', label: '区间开始' },
  { key: '区间结束', label: '区间结束' },
  { key: '日期偏移', label: '偏移' },
  { key: '遍历偏移', label: '遍历' },
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
const etfTrackerColumns = [
  { key: '代码', label: '代码' },
  { key: '名称', label: '名称' },
  { key: '类别', label: '类别' },
  { key: '类型', label: '类型' },
  { key: '最新价', label: '最新价' },
  { key: '当日', label: '当日' },
  { key: '近5日', label: '近5日' },
  { key: '近20日', label: '近20日' },
  { key: '近50日', label: '近50日' },
  { key: 'YTD', label: 'YTD' },
  { key: '成交额', label: '成交额' },
  { key: 'IOPV', label: 'IOPV' },
  { key: '规模', label: '规模' },
  { key: '数据来源', label: '来源' },
  { key: '缓存状态', label: '缓存' },
  { key: 'K线行数', label: 'K线' },
  { key: '最近日期', label: '最近日期' },
  { key: '跟踪指数', label: '跟踪指数' }
]
const etfTrackerReviewColumns = [
  { key: '排名', label: '排名' },
  { key: '代码', label: '代码' },
  { key: '名称', label: '名称' },
  { key: '类型', label: '类型' },
  { key: '等级', label: '等级' },
  { key: '区间收益', label: '收益' },
  { key: '超额收益', label: '超额' },
  { key: '最大回撤', label: '回撤' },
  { key: '趋势表达', label: '趋势表达' },
  { key: '跟踪指数', label: '跟踪指数' }
]
const regimeFactorAdvantageColumns = [
  { key: '窗口', label: '窗口' },
  { key: 'A组样本', label: 'A组样本' },
  { key: '基准样本', label: '基准样本' },
  { key: 'A组平均收益', label: 'A组平均收益' },
  { key: '基准平均收益', label: '基准平均收益' },
  { key: '相对基准', label: '相对基准' },
  { key: 'A组胜率', label: 'A组胜率' },
  { key: '相对指数', label: '相对指数' },
  { key: '是否占优', label: '是否占优' }
]
const regimeBenchmarkColumns = [
  { key: '基准', label: '基准' },
  { key: '日期', label: '日期' },
  { key: '阶段', label: '阶段' },
  { key: '当前调整', label: '当前调整' },
  { key: '60日涨幅', label: '60日涨幅' },
  { key: '20日回撤', label: '20日回撤' },
  { key: '样本数', label: '样本数' },
  { key: '调整样本', label: '调整样本' },
  { key: '调整占比', label: '调整占比' },
  { key: '涨幅阈值', label: '涨幅阈值' },
  { key: '回撤阈值', label: '回撤阈值' }
]
const regimeFactorColumns = [
  { key: '分组', label: '分组' },
  { key: '窗口', label: '窗口' },
  { key: '样本数', label: '样本数' },
  { key: '平均收益', label: '平均收益' },
  { key: '胜率', label: '胜率' },
  { key: '超额收益', label: '超额收益' }
]
const regimeMigrationColumns = [
  { key: '层级', label: '层级' },
  { key: '资产数', label: '资产数' },
  { key: '近5日收益', label: '近5日收益' },
  { key: '跌破MA20', label: '跌破MA20' },
  { key: '成交额占比', label: '成交额占比' }
]
const regimeSequenceColumns = [
  { key: '阶段', label: '阶段' },
  { key: '首次触发', label: '首次触发' },
  { key: '领先/滞后天数', label: '领先/滞后' },
  { key: '当前触发', label: '当前触发' },
  { key: '资产数', label: '资产数' },
  { key: '近5日收益', label: '近5日收益' },
  { key: '跌破MA20', label: '跌破MA20' },
  { key: '压力分', label: '压力分' }
]
const regimeHighLiquidityBreakColumns = [
  { key: '窗口', label: '窗口' },
  { key: '事件数', label: '事件数' },
  { key: '事件资产收益', label: '事件资产收益' },
  { key: '全市场收益', label: '全市场收益' },
  { key: '基准收益', label: '基准收益' },
  { key: '基准胜率', label: '基准胜率' },
  { key: '事件宽度', label: '事件宽度' }
]
const regimeDailyHistoryColumns = [
  { key: '日期', label: '日期' },
  { key: 'RAI', label: 'RAI' },
  { key: '阶段', label: '阶段' },
  { key: '趋势', label: '趋势' },
  { key: '波动率', label: '波动率' },
  { key: '流动性', label: '流动性' },
  { key: '流出', label: '流出' },
  { key: '流入', label: '流入' },
  { key: '高流动性抛售', label: '高流动性抛售' },
  { key: '更接近', label: '更接近' },
  { key: '释放阶段', label: '释放阶段' },
  { key: 'MA20宽度', label: 'MA20宽度' },
  { key: '高流动性破位', label: '高流动性破位' },
  { key: '现金偏好', label: '现金偏好' },
  { key: '成交额集中度', label: '成交额集中度' }
]
const regimeComponentColumns = [
  { key: '组成', label: '组成' },
  { key: '信号', label: '信号' },
  { key: '资产数', label: '资产数' },
  { key: '分项分', label: '分项分' },
  { key: '贡献', label: '贡献' },
  { key: '近5日收益', label: '近5日收益' },
  { key: '跌破MA20', label: '跌破MA20' },
  { key: '成交额占比', label: '成交额占比' },
  { key: '阈值', label: '阈值' }
]
const regimeFlowCandidateColumns = [
  { key: '排名', label: '排名' },
  { key: '代码', label: '代码' },
  { key: '名称', label: '名称' },
  { key: '评分', label: '评分' },
  { key: '分组', label: '分组' },
  { key: '资产池', label: '资产池' },
  { key: '理由', label: '理由' },
  { key: '近5日', label: '近5日' },
  { key: '近20日', label: '近20日' },
  { key: '20日回撤', label: '20日回撤' },
  { key: '60日回撤', label: '60日回撤' },
  { key: 'RS20', label: 'RS20' },
  { key: 'RS排名', label: 'RS排名' },
  { key: '成交额分位', label: '成交额分位' },
  { key: '成交收缩', label: '成交收缩' },
  { key: 'MA20', label: 'MA20' },
  { key: '转强', label: '转强' },
  { key: '回调充分', label: '回调充分' },
  { key: '高位', label: '高位' },
  { key: '高流动性', label: '高流动性' }
]
const regimeMarketScopeColumns = [
  { key: '日期', label: '日期' },
  { key: '资产数', label: '资产数' },
  { key: '上涨资产', label: '上涨资产' },
  { key: '上涨占比', label: '上涨占比' },
  { key: '领涨资产', label: '领涨资产' },
  { key: '领涨占比', label: '领涨占比' },
  { key: 'MA20宽度', label: 'MA20宽度' },
  { key: '成交额集中度', label: '成交额集中度' },
  { key: '近5日中位收益', label: '近5日中位收益' }
]
const regimeAssetColumns = [
  { key: '代码', label: '代码' },
  { key: '分组', label: '分组' },
  { key: '资产池', label: '资产池' },
  { key: '日期', label: '日期' },
  { key: '20日回撤', label: '20日回撤' },
  { key: '60日回撤', label: '60日回撤' },
  { key: 'RS20', label: 'RS20' },
  { key: 'RS排名', label: 'RS排名' },
  { key: '近5日', label: '近5日' },
  { key: '近20日', label: '近20日' },
  { key: '近120日', label: '近120日' },
  { key: 'HV20', label: 'HV20' },
  { key: 'HV60', label: 'HV60' },
  { key: 'ATR20/Close', label: 'ATR20/Close' },
  { key: '20日成交额', label: '20日成交额' },
  { key: '60日成交额', label: '60日成交额' },
  { key: '成交额排名', label: '成交额排名' },
  { key: '成交额分位', label: '成交额分位' },
  { key: '波动桶', label: '波动桶' },
  { key: '流动性桶', label: '流动性桶' },
  { key: '位置桶', label: '位置桶' },
  { key: '高位信号', label: '高位信号' },
  { key: '高流动性', label: '高流动性' },
  { key: 'MA20', label: 'MA20' },
  { key: 'MA60', label: 'MA60' }
]
const aiWorkbenchLatestColumns = [
  { key: '代码', label: '代码' },
  { key: '名称', label: '名称' },
  { key: '日期', label: '日期' },
  { key: '收盘', label: '收盘' },
  { key: '区间收益', label: '区间收益' },
  { key: '行数', label: '行数' }
]
const aiWorkbenchRecordColumns = [
  { key: '日期', label: '日期' },
  { key: '代码', label: '代码' },
  { key: '开', label: '开' },
  { key: '高', label: '高' },
  { key: '低', label: '低' },
  { key: '收', label: '收' },
  { key: '成交额', label: '成交额' }
]

onMounted(async () => {
  restoreResearchSnapshots()
  await loadConfig()
  void loadTradingCalendar()
  await Promise.all([loadOverview(false, { includeRecords: false }), loadTasks()])
  normalizeResizableCardWidths()
  window.setInterval(() => {
    void loadTasks({ silent: true })
  }, 2500)
})

async function loadConfig() {
  try {
    config.value = await apiGet('/config')
    Object.assign(settings, config.value?.defaults || {})
    selectedTimeframes.value = normalizeDownloadTimeframes(config.value?.defaults?.timeframes || ['1d'])
    researchTimeframe.value = selectedDownloadTimeframes.value[0] || '1d'
    restoreSettings()
  } catch (error) {
    showError('配置加载失败', error)
    return
  }
  researchTimeframe.value = selectedDownloadTimeframes.value[0] || researchTimeframe.value
  const firstGroup = config.value?.symbol_groups?.[0]
  if (firstGroup) {
    selectedGroup.value = firstGroup.name
    symbolsText.value = firstGroup.symbols.join('\n')
  }
  void loadSymbolGroups(true)
}

async function loadTradingCalendar() {
  if (!fuyaoCalendarAvailable()) return false
  if (loadingTradingCalendar.value) return false
  loadingTradingCalendar.value = true
  try {
    const data = await apiGet('/trading-calendar', { headers: fuyaoApiHeaders() })
    const days = Array.isArray(data.days) ? data.days : []
    tradingCalendarDays.value = uniqueStringsInOrder(days).filter(isDateText).sort()
    return true
  } catch (error) {
    showError('交易日历加载失败', error)
    return false
  } finally {
    loadingTradingCalendar.value = false
  }
}

async function loadSymbolGroups(preserveSelected: boolean, refreshTarget: SymbolRefreshTarget | '' = '') {
  loadingSymbolGroups.value = true
  const previousGroup = selectedGroup.value
  const previousSymbols = symbolsText.value
  let succeeded = false
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    settings.tdx_path = normalizeTdxPath(settings.tdx_path)
    const params = new URLSearchParams({
      data_root: settings.data_root,
      tdx_path: settings.tdx_path,
      adjust: settings.adjust
    })
    if (refreshTarget) params.set('target', refreshTarget)
    const data = await apiGet(`/symbol-groups?${params.toString()}`)
    if (config.value) {
      config.value.symbol_groups = (data.groups || []).filter(isSymbolGroup)
      config.value.symbol_names = {
        ...(config.value.symbol_names || {}),
        ...(data.symbol_names || {})
      }
    }
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

function ensureEtfTrackingLoaded() {
  const needsOverviewRecords = !overviewRecordsLoaded.value
  if (needsOverviewRecords && !loadingOverview.value) {
    void loadOverview(false, { includeRecords: true })
  }
  if (!dynamicSymbolGroupAvailable('ETF列表') && !loadingSymbolGroups.value) {
    void loadSymbolGroups(true, 'etf')
  }
  if (!etfTrackingRows.value.length && !loadingEtfTracking.value) {
    void loadEtfTracking(false, { preferCache: true })
  }
  if (etfTrackingRows.value.length && !etfReturnRows.value.length && !loadingEtfReturns.value) {
    void loadEtfReturns(false, { preferCache: true })
  }
}

async function loadEtfTracking(notify = false, options: { preferCache?: boolean } = {}) {
  if (loadingEtfTracking.value) return false
  loadingEtfTracking.value = true
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    settings.tdx_path = normalizeTdxPath(settings.tdx_path)
    const cacheKey = etfTrackingClientCacheKey()
    if (options.preferCache) {
      const cached = restoreEtfClientCache(ETF_TRACKING_CACHE_STORAGE_KEY, cacheKey, ETF_TRACKING_CLIENT_CACHE_TTL_MS)
      if (cached) {
        etfTrackingRows.value = cached.records
        updateEtfCacheState(etfTrackingCacheState, 'client', cached.record_count, cached.saved_at)
        if (etfTrackingRows.value.length || overviewRecordsLoaded.value || dynamicSymbolGroupAvailable('ETF列表')) {
          void loadEtfReturns(false, { preferCache: true })
        }
        return true
      }
    }
    const params = new URLSearchParams({
      data_root: settings.data_root,
      tdx_path: settings.tdx_path
    })
    etfTrackingIndexSymbols().forEach((symbol) => params.append('index_symbols', symbol))
    const data = await apiGet(`/etf-tracking?${params.toString()}`)
    const records = Array.isArray(data.records) ? data.records : []
    etfTrackingRows.value = records
    writeEtfClientCache(ETF_TRACKING_CACHE_STORAGE_KEY, cacheKey, records)
    updateEtfCacheState(etfTrackingCacheState, etfApiCacheSource(data.cache), records.length, Date.now())
    if (etfTrackingRows.value.length || overviewRecordsLoaded.value || dynamicSymbolGroupAvailable('ETF列表')) {
      void loadEtfReturns(false, { preferCache: true })
    }
    if (notify) showNotice('success', 'TDX ETF接口已刷新', `读取 ${formatInt(data.record_count)} 条指数跟踪 ETF 记录。`)
    return true
  } catch (error) {
    showError('TDX ETF接口加载失败', error)
    return false
  } finally {
    loadingEtfTracking.value = false
  }
}

async function loadEtfReturns(notify = false, options: { preferCache?: boolean } = {}) {
  if (loadingEtfReturns.value) return false
  const symbols = etfTrackerReturnSymbols()
  if (!symbols.length) return false
  loadingEtfReturns.value = true
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    const end = latestTradingDayText()
    const cacheKey = etfReturnsClientCacheKey(symbols, end)
    if (options.preferCache) {
      const cached = restoreEtfClientCache(ETF_RETURNS_CACHE_STORAGE_KEY, cacheKey, ETF_RETURNS_CLIENT_CACHE_TTL_MS)
      if (cached) {
        etfReturnRows.value = cached.records
        updateEtfCacheState(etfReturnsCacheState, 'client', cached.record_count, cached.saved_at)
        return true
      }
    }
    const data = await apiPost('/etf-returns', {
      data_root: settings.data_root,
      adjust: settings.adjust,
      symbols,
      end
    })
    const records = Array.isArray(data.records) ? data.records : []
    etfReturnRows.value = records
    writeEtfClientCache(ETF_RETURNS_CACHE_STORAGE_KEY, cacheKey, records)
    updateEtfCacheState(etfReturnsCacheState, etfApiCacheSource(data.cache), records.length, Date.now())
    if (notify) showNotice('success', 'ETF收益率已刷新', `基于本地日线缓存计算 ${formatInt(data.record_count)} 条。`)
    return true
  } catch (error) {
    showError('ETF收益率加载失败', error)
    return false
  } finally {
    loadingEtfReturns.value = false
  }
}

function restoreEtfClientCache(storageKey: string, cacheKey: string, ttlMs: number) {
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return null
    const payload = JSON.parse(raw) as Record<string, any>
    const savedAt = Number(payload.saved_at || 0)
    if (payload.key !== cacheKey || !Array.isArray(payload.records) || !savedAt) return null
    if (Date.now() - savedAt > ttlMs) {
      window.localStorage.removeItem(storageKey)
      return null
    }
    return {
      records: payload.records as Array<Record<string, any>>,
      saved_at: savedAt,
      record_count: Number(payload.record_count || payload.records.length || 0)
    }
  } catch {
    window.localStorage.removeItem(storageKey)
    return null
  }
}

function writeEtfClientCache(storageKey: string, cacheKey: string, records: Array<Record<string, any>>) {
  window.localStorage.setItem(
    storageKey,
    JSON.stringify({
      key: cacheKey,
      saved_at: Date.now(),
      record_count: records.length,
      records
    })
  )
}

function clearEtfClientCache() {
  window.localStorage.removeItem(ETF_TRACKING_CACHE_STORAGE_KEY)
  window.localStorage.removeItem(ETF_RETURNS_CACHE_STORAGE_KEY)
  updateEtfCacheState(etfTrackingCacheState, 'cleared', etfTrackingRows.value.length, 0)
  updateEtfCacheState(etfReturnsCacheState, 'cleared', etfReturnRows.value.length, 0)
  showNotice('success', 'ETF缓存已清理', '已清理浏览器本地 ETF 接口和收益缓存；下次刷新会重新读取。')
}

function updateEtfCacheState(
  state: EtfClientCacheState,
  source: EtfClientCacheSource,
  recordCount: number,
  savedAt: number
) {
  state.source = source
  state.record_count = recordCount
  state.saved_at = savedAt
}

function etfApiCacheSource(cache: Record<string, any> | null | undefined): EtfClientCacheSource {
  if (!cache?.hit) return 'network'
  return cache?.scope === 'disk' ? 'disk' : 'memory'
}

function etfTrackingClientCacheKey() {
  return JSON.stringify({
    kind: 'tracking',
    data_root: normalizeDataRoot(settings.data_root),
    tdx_path: normalizeTdxPath(settings.tdx_path),
    index_symbols: etfTrackingIndexSymbols()
  })
}

function etfReturnsClientCacheKey(symbols: string[], end: string) {
  return JSON.stringify({
    kind: 'returns',
    data_root: normalizeDataRoot(settings.data_root),
    adjust: settings.adjust,
    end,
    symbols
  })
}

function etfCacheStatusText(state: EtfClientCacheState, loading: boolean) {
  if (loading) return '刷新中'
  if (state.source === 'client') return `本地缓存 · ${etfCacheTimeText(state.saved_at)}`
  if (state.source === 'memory') return `接口缓存 · ${etfCacheTimeText(state.saved_at)}`
  if (state.source === 'disk') return `磁盘缓存 · ${etfCacheTimeText(state.saved_at)}`
  if (state.source === 'network') return `刚刷新 · ${etfCacheTimeText(state.saved_at)}`
  if (state.source === 'cleared') return '已清理'
  return '未缓存'
}

function etfCacheTone(state: EtfClientCacheState, loading: boolean) {
  if (loading) return 'loading'
  return state.source
}

function etfCacheTimeText(savedAt: number) {
  if (!savedAt) return '-'
  return formatDateTimeText(new Date(savedAt).toISOString())
}

function etfTrackerReturnSymbols() {
  return uniqueStringsInOrder([
    ...etfTrackingRows.value.map((row: Record<string, any>) => normalizeSymbol(String(row.stock_code || ''))),
    ...groupSymbolsForAssetType('etf'),
    ...cacheSymbolsForAssetType('etf')
  ])
}

function etfTrackingIndexSymbols() {
  return uniqueStringsInOrder([...ETF_TRACKING_INDEX_SYMBOLS, etfTrackerForm.benchmark_symbol].map((symbol) => normalizeSymbol(symbol)))
}

function dynamicSymbolGroupAvailable(name: string) {
  return Boolean(config.value?.symbol_groups.some((group) => group.name === name && group.symbols.length > 0))
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

async function loadOverview(refresh: boolean, options: { includeRecords?: boolean } = {}) {
  loadingOverview.value = true
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    settings.tdx_path = normalizeTdxPath(settings.tdx_path)
    const includeRecords = options.includeRecords ?? activeView.value === 'cache'
    const params = new URLSearchParams({
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      refresh: String(refresh),
      include_records: String(includeRecords)
    })
    overview.value = await apiGet(`/overview?${params.toString()}`)
    if (includeRecords && activeView.value === 'research' && activeResearchTab.value === 'etf') {
      void loadEtfReturns(false, { preferCache: true })
    }
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
      await loadOverview(true, { includeRecords: true })
      return
    }
    if (activeView.value === 'tasks') {
      await loadTasks({ notify: true })
      return
    }
    if (activeView.value === 'download') {
      const [overviewOk, tasksOk] = await Promise.all([loadOverview(false, { includeRecords: false }), loadTasks({ silent: true })])
      if (overviewOk && tasksOk) showNotice('success', '状态已刷新', '下载任务进度和缓存概览已更新。')
      return
    }
    const [overviewOk, tasksOk] = await Promise.all([loadOverview(false, { includeRecords: activeView.value === 'cache' }), loadTasks({ silent: true })])
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
    planPagination.page = 1
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
      search_mode: crossForm.search_mode,
      traversal_start: crossForm.traversal_start,
      traversal_end: crossForm.traversal_end,
      top_n: Number(crossForm.top_n || 20),
      date_tolerance_bars: Number(crossForm.date_tolerance_bars || 0),
      exclusion_bars: Number(crossForm.exclusion_bars || 0),
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
    etfTrackerResultSignature.value = ''
    if (reviewForm.enable_ai_review) await runAiReview({ fallbackToLocal: true })
    else aiReviewOutput.value = null
    showNotice('success', '复盘已生成', `完成 ${formatInt(reviewResult.value?.summary?.ranked_count)} 个标的排序。`)
  } catch (error) {
    showError('复盘生成失败', error)
  } finally {
    runningResearch.value = ''
  }
}

async function runEtfTrackerReview() {
  const selected = etfTrackerReviewSymbols.value
  if (!selected.length) {
    showNotice('error', 'ETF筛选为空', '请调整类型、跟踪指数或关键词。')
    return
  }
  runningResearch.value = 'etf'
  try {
    reviewForm.symbols = selected.join('\n')
    reviewForm.start = etfTrackerForm.start
    reviewForm.end = etfTrackerForm.end
    reviewForm.benchmark_symbol = etfTrackerForm.benchmark_symbol
    reviewForm.min_swing_return = Number(etfTrackerForm.min_swing_return || 0)
    reviewForm.min_segment_bars = Number(etfTrackerForm.min_segment_bars || 1)
    reviewResult.value = await apiPost('/research/review', {
      ...researchPayloadBase(),
      symbols: selected,
      start: etfTrackerForm.start,
      end: etfTrackerForm.end,
      benchmark_symbol: etfTrackerForm.benchmark_symbol,
      min_swing_return: Number(etfTrackerForm.min_swing_return || 0),
      min_segment_bars: Number(etfTrackerForm.min_segment_bars || 1)
    })
    reviewResultSignature.value = reviewSearchSignature()
    etfTrackerResultSignature.value = etfTrackerSearchSignature()
    aiReviewOutput.value = null
    showNotice('success', 'ETF趋势对比已生成', `筛选 ${formatInt(filteredEtfTrackerRows.value.length)} 只，复盘 ${formatInt(selected.length)} 只。`)
  } catch (error) {
    showError('ETF趋势对比失败', error)
  } finally {
    runningResearch.value = ''
  }
}

async function runMarketRegimeResearch() {
  runningResearch.value = 'regime'
  try {
    regimeResult.value = await apiPost('/research/market-regime', {
      ...researchPayloadBase(),
      timeframe: '1d',
      tdx_path: settings.tdx_path,
      benchmark_symbol: regimeForm.benchmark_symbol,
      symbols: parseSymbols(regimeForm.symbols),
      universe_groups: activeRegimeUniverseGroups.value,
      start: regimeForm.start,
      end: regimeForm.end,
      forward_windows: parseNumberList(regimeForm.forward_windows),
      benchmark_rally_60_threshold: percentOrDefault(regimeForm.benchmark_rally_60_threshold, 8),
      benchmark_pullback_20_threshold: percentOrDefault(regimeForm.benchmark_pullback_20_threshold, -3),
      pullback_20_threshold: percentOrDefault(regimeForm.pullback_20_threshold, -6),
      pullback_60_threshold: percentOrDefault(regimeForm.pullback_60_threshold, -10),
      liquidity_high_percentile: percentOrDefault(regimeForm.liquidity_high_percentile, 80),
      liquidity_mid_percentile: percentOrDefault(regimeForm.liquidity_mid_percentile, 35),
      liquidity_low_percentile: percentOrDefault(regimeForm.liquidity_low_percentile, 20),
      volatility_high_percentile: percentOrDefault(regimeForm.volatility_high_percentile, 80),
      volatility_low_percentile: percentOrDefault(regimeForm.volatility_low_percentile, 20),
      high_position_drawdown_threshold: percentOrDefault(regimeForm.high_position_drawdown_threshold, -10),
      high_position_return_percentile: percentOrDefault(regimeForm.high_position_return_percentile, 80),
      leader_return_5d_threshold: percentOrDefault(regimeForm.leader_return_5d_threshold, 3),
      stress_ma20_break_threshold: percentOrDefault(regimeForm.stress_ma20_break_threshold, 60),
      stress_return_5d_threshold: percentOrDefault(regimeForm.stress_return_5d_threshold, 0),
      cash_stress_score_threshold: percentOrDefault(regimeForm.cash_stress_score_threshold, 62),
      cash_preference_proxy_threshold: percentOrDefault(regimeForm.cash_preference_proxy_threshold, 60),
      risk_expansion_breadth_threshold: percentOrDefault(regimeForm.risk_expansion_breadth_threshold, 60),
      risk_contraction_breadth_threshold: percentOrDefault(regimeForm.risk_contraction_breadth_threshold, 40),
      risk_release_breadth_threshold: percentOrDefault(regimeForm.risk_release_breadth_threshold, 45),
      high_liquidity_selloff_threshold: percentOrDefault(regimeForm.high_liquidity_selloff_threshold, 60),
      concentration_top_n: numberOrDefault(regimeForm.concentration_top_n, 20),
      daily_report_days: numberOrDefault(regimeForm.daily_report_days, 20),
      flow_candidate_limit: numberOrDefault(regimeForm.flow_candidate_limit, 30),
      risk_timeline_days: numberOrDefault(regimeForm.risk_timeline_days, 60)
    })
    regimeFlowCandidatePagination.page = 1
    regimeMarketScopePagination.page = 1
    activeRegimeSectionTab.value = 'overview'
    activeRegimeRaiKey.value = ''
    regimeRaiWindowStart.value = -1
    const phase = regimeResult.value?.risk_appetite?.phase || '已生成'
    showNotice('success', '市场风险偏好研究完成', `${phase} · ${formatInt(regimeResult.value?.summary?.asset_count)} 个资产。`)
  } catch (error) {
    showError('市场风险偏好研究失败', error)
  } finally {
    runningResearch.value = ''
  }
}

async function runAiCommand() {
  if (!aiCommandForm.text.trim()) return
  runningAiCommand.value = true
  try {
    const result = await apiPost('/ai/command', {
      ...researchPayloadBase(),
      tdx_path: settings.tdx_path,
      text: aiCommandForm.text,
      current_view: activeView.value,
      research_tab: activeResearchTab.value,
      base_url: aiSettings.base_url.trim(),
      api_key: aiSettings.api_key.trim(),
      model: aiSettings.model.trim(),
      temperature: Number(aiSettings.temperature ?? 0)
    })
    aiCommandResult.value = result
    applyAiCommandResult(result)
    showNotice('success', 'AI 命令已应用', result.summary || '已根据命令更新参数。')
  } catch (error) {
    showError('AI 命令失败', error)
  } finally {
    runningAiCommand.value = false
  }
}

function applyAiCommandResult(result: Record<string, any>) {
  ;(result.patches || []).forEach((patch: Record<string, any>) => applyAiCommandPatch(patch))
}

function applyAiCommandPatch(patch: Record<string, any>) {
  const target = String(patch.target || '')
  const value = patch.value
  if (target === 'activeView') {
    const nextView = String(value || '')
    if (navItems.some((item) => item.key === nextView)) activeView.value = nextView
    return
  }
  if (target === 'symbolsText') {
    symbolsText.value = String(value || '')
    activeView.value = 'download'
    selectedGroup.value = 'custom'
    return
  }
  if (target === 'cacheFilters.keyword') {
    cacheFilters.keyword = String(value || '').split(/\s+/)[0] || ''
    activeView.value = 'cache'
    return
  }
  if (target === 'crossForm.universe_symbols') {
    crossForm.universe_symbols = String(value || '')
    activeView.value = 'research'
    activeResearchTab.value = 'cross'
    return
  }
  if (target === 'reviewForm.symbols') {
    reviewForm.symbols = String(value || '')
    activeView.value = 'research'
    activeResearchTab.value = 'review'
    return
  }
  if (target === 'regimeForm.symbols') {
    regimeForm.symbols = String(value || '')
    activeView.value = 'research'
    activeResearchTab.value = 'regime'
    return
  }
  if (target === 'selectedTimeframes') {
    selectedTimeframes.value = normalizeDownloadTimeframes(Array.isArray(value) ? value : [String(value || '1d')])
    activeView.value = 'download'
    clearPlanPreview()
    return
  }
  if (target === 'researchTimeframe') {
    researchTimeframe.value = String(value || '1d')
    activeView.value = 'research'
    return
  }
  if (target.endsWith('.date_shortcut')) {
    applyAiDateShortcut(target, String(value || ''))
    return
  }
  const applied = applyAiFormFieldPatch(target, value)
  if (applied && target.startsWith('regimeForm.')) {
    activeView.value = 'research'
    activeResearchTab.value = 'regime'
  }
}

function applyAiFormFieldPatch(target: string, value: unknown) {
  const forms: Record<string, Record<string, any>> = {
    settings: settings as Record<string, any>,
    cacheFilters: cacheFilters as Record<string, any>,
    historyForm: historyForm as Record<string, any>,
    crossForm: crossForm as Record<string, any>,
    reviewForm: reviewForm as Record<string, any>,
    etfTrackerForm: etfTrackerForm as Record<string, any>,
    regimeForm: regimeForm as Record<string, any>,
    aiWorkbenchForm: aiWorkbenchForm as Record<string, any>
  }
  const [formName, field] = target.split('.', 2)
  const form = forms[formName]
  if (!form || !field || !(field in form)) return false
  form[field] = value
  if (formName === 'cacheFilters') activeView.value = 'cache'
  if (formName === 'settings') {
    activeView.value = ['mode', 'batch_size', 'start', 'end'].includes(field) ? 'download' : 'settings'
  }
  if (formName === 'historyForm') {
    activeView.value = 'research'
    activeResearchTab.value = 'history'
  }
  if (formName === 'crossForm') {
    activeView.value = 'research'
    activeResearchTab.value = 'cross'
  }
  if (formName === 'reviewForm') {
    activeView.value = 'research'
    activeResearchTab.value = 'review'
  }
  if (formName === 'etfTrackerForm') {
    activeView.value = 'research'
    activeResearchTab.value = 'etf'
  }
  if (formName === 'aiWorkbenchForm') activeView.value = 'ai'
  return true
}

function applyAiDateShortcut(target: string, key: string) {
  if (!['20d', '50d', 'ytd', '1y'].includes(key)) return
  const shortcut = key as DateShortcutKey
  if (target === 'settings.date_shortcut') {
    applyDateShortcut(settings, shortcut)
    activeView.value = 'download'
    return
  }
  if (target === 'historyForm.date_shortcut') {
    applyHistoryDateShortcut(shortcut)
    activeView.value = 'research'
    activeResearchTab.value = 'history'
    return
  }
  if (target === 'crossForm.date_shortcut') {
    applyDateShortcut(crossForm, shortcut)
    activeView.value = 'research'
    activeResearchTab.value = 'cross'
    return
  }
  if (target === 'reviewForm.date_shortcut') {
    applyDateShortcut(reviewForm, shortcut)
    activeView.value = 'research'
    activeResearchTab.value = 'review'
    return
  }
  if (target === 'etfForm.date_shortcut') {
    applyDateShortcut(etfTrackerForm, shortcut)
    activeView.value = 'research'
    activeResearchTab.value = 'etf'
    return
  }
  if (target === 'regimeForm.date_shortcut') {
    applyDateShortcut(regimeForm, shortcut)
    activeView.value = 'research'
    activeResearchTab.value = 'regime'
    return
  }
  if (target === 'aiWorkbenchForm.date_shortcut') {
    applyDateShortcut(aiWorkbenchForm, shortcut)
    activeView.value = 'ai'
  }
}

async function runAiWorkbench() {
  if (!aiConfigReady.value) {
    showNotice('error', 'AI 接口未配置', '请先在系统设置里填写接口 URL、API Key 和模型。')
    return
  }
  runningAiWorkbench.value = true
  try {
    aiWorkbenchResult.value = await apiPost('/ai/stock-agent', {
      ...researchPayloadBase(),
      timeframe: aiWorkbenchForm.timeframe,
      base_url: aiSettings.base_url.trim(),
      api_key: aiSettings.api_key.trim(),
      model: aiSettings.model.trim(),
      prompt: aiWorkbenchForm.prompt,
      skill_prompt: aiWorkbenchForm.skill_prompt,
      symbols: parseSymbols(aiWorkbenchForm.symbols),
      start: aiWorkbenchForm.start,
      end: aiWorkbenchForm.end,
      temperature: Number(aiSettings.temperature ?? 0.2),
      max_symbols: numberOrDefault(aiWorkbenchForm.max_symbols, 20),
      max_rows: numberOrDefault(aiWorkbenchForm.max_rows, 240)
    })
    showNotice('success', 'AI 模块已生成', '模型已读取受限本地行情上下文并返回结果。')
  } catch (error) {
    showError('AI 模块运行失败', error)
  } finally {
    runningAiWorkbench.value = false
  }
}

async function importAiSkillPrompt(event: Event) {
  const input = event.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (!file) return
  try {
    const text = await file.text()
    if (text.length > 200000) {
      showNotice('error', 'Skill 文件过大', '请导入 200,000 字符以内的 Markdown 或纯文本。')
      return
    }
    aiWorkbenchForm.skill_prompt = text
    showNotice('success', 'Skill 已导入', `${file.name} 已载入 AI 模块提示词。`)
  } catch (error) {
    showError('Skill 导入失败', error)
  } finally {
    if (input) input.value = ''
  }
}

function downloadMarketRegimeJson() {
  if (!regimeResult.value) {
    showNotice('info', '没有可导出结果', '先运行市场风险偏好研究。')
    return
  }
  const date = formatDateOnly(regimeResult.value.summary?.as_of) || regimeForm.end || todayText()
  downloadJson(`market-regime-${date}.json`, regimeResult.value)
}

function loadEtfTrackerSymbolsToReview() {
  const selected = etfTrackerReviewSymbols.value
  if (!selected.length) {
    showNotice('error', 'ETF筛选为空', '请调整类型、跟踪指数或关键词。')
    return
  }
  reviewForm.symbols = selected.join('\n')
  reviewForm.start = etfTrackerForm.start
  reviewForm.end = etfTrackerForm.end
  reviewForm.benchmark_symbol = etfTrackerForm.benchmark_symbol
  reviewForm.min_swing_return = Number(etfTrackerForm.min_swing_return || 0)
  reviewForm.min_segment_bars = Number(etfTrackerForm.min_segment_bars || 1)
  activeResearchTab.value = 'review'
  reviewResult.value = null
  aiReviewOutput.value = null
  reviewResultSignature.value = ''
  etfTrackerResultSignature.value = ''
  showNotice('success', '已载入多股复盘', `已写入 ${formatInt(selected.length)} 只 ETF。`)
}

async function runAiReview(options: { fallbackToLocal?: boolean } = {}) {
  if (!reviewResult.value?.ai?.messages?.length) {
    showNotice('error', 'AI 证据缺失', '请先生成多股复盘。')
    return
  }
  if (!aiConfigReady.value) {
    aiReviewOutput.value = null
    if (options.fallbackToLocal) {
      showNotice('info', '使用本地规则锐评', 'AI 接口参数未配置完整，本次输出本地默认锐评。')
    } else {
      showNotice('info', '使用本地规则锐评', '未填写完整 AI 接口参数，逐股锐评卡片由本地规则生成。')
    }
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
    if (options.fallbackToLocal) aiReviewOutput.value = null
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
  if (snapshot.tab === 'etf') Object.assign(etfTrackerForm, form)
  if (snapshot.tab === 'regime') {
    Object.assign(regimeForm, form)
    normalizeRegimePercentFields()
  }
  setResearchResult(snapshot.tab, cloneJson(snapshot.result))
  if (snapshot.tab === 'review') reviewResultSignature.value = reviewSearchSignature()
  if (snapshot.tab === 'etf') {
    etfTrackerResultSignature.value = etfTrackerSearchSignature()
    reviewResultSignature.value = ''
  }
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
    settings[field] = field === 'data_root' ? normalizeDataRoot(data.path) : normalizeTdxPath(data.path)
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
  settings.start = tradingLookbackStartText(days)
  settings.end = latestTradingDayText()
  planRows.value = []
  planSummary.value = {}
  showNotice('success', '已应用全资产更新', `已载入 ${formatInt(allAssetSymbols.value.length)} 只资产，时间窗为近 ${days} 个交易日。`)
}

function normalizeDownloadTimeframes(values: unknown[]) {
  const options = downloadTimeframeOptions.value
  const allowed = new Set(options)
  const normalized = uniqueStringsInOrder(values).filter((timeframe) => allowed.has(timeframe))
  if (normalized.length) return normalized
  const fallback = String(config.value?.defaults?.timeframes?.[0] || '1d')
  return options.includes(fallback) ? [fallback] : options.slice(0, 1)
}

function isDownloadTimeframeSelected(timeframe: string) {
  return selectedDownloadTimeframes.value.includes(timeframe)
}

function clearPlanPreview() {
  planRows.value = []
  planSummary.value = {}
  planPagination.page = 1
}

function toggleDownloadTimeframe(timeframe: string) {
  const current = selectedDownloadTimeframes.value
  let selected = current.filter((item) => item !== timeframe)
  if (current.includes(timeframe)) {
    selectedTimeframes.value = normalizeDownloadTimeframes(selected)
  } else {
    const defaultSelection = normalizeDownloadTimeframes(config.value?.defaults?.timeframes || ['1d'])
    const replacingDefault =
      current.length === defaultSelection.length &&
      defaultSelection.every((item) => current.includes(item)) &&
      !defaultSelection.includes(timeframe)
    if (replacingDefault) selected = []
    selectedTimeframes.value = normalizeDownloadTimeframes([timeframe, ...selected])
  }
  clearPlanPreview()
}

function selectAllDownloadTimeframes() {
  selectedTimeframes.value = [...downloadTimeframeOptions.value]
  clearPlanPreview()
}

function selectDefaultDownloadTimeframe() {
  selectedTimeframes.value = normalizeDownloadTimeframes(config.value?.defaults?.timeframes || ['1d'])
  clearPlanPreview()
}

function cacheSymbolsForAssetType(type: AssetShortcutType) {
  return cacheSymbolsByAssetType.value.get(type) || []
}

function cacheRecordForSymbol(symbol: string, timeframe: string) {
  const normalized = normalizeSymbol(symbol)
  const rows = (cacheRecordsBySymbol.value.get(normalized) || []).filter(
    (row: Record<string, any>) => String(row.asset_type || '') === 'etf'
  )
  return rows.find((row: Record<string, any>) => String(row.timeframe || '') === timeframe) || rows[0] || null
}

function etfTrackingDisplayLabel(row: Record<string, any>) {
  const name = String(row.tracking_name || '').trim()
  const symbol = normalizeSymbol(String(row.tracking_symbol || ''))
  if (name && symbol) return `${name}（${symbol}）`
  return name || symbol || 'TDX跟踪指数'
}

function etfTrackingIndexLabel(name: string, symbol: string) {
  const source = String(name || '').trim()
  if (!source) return symbol
  const beforeEtf = source.split(/ETF|LOF|基金|联接|增强/i)[0].trim()
  const cleaned = beforeEtf
    .replace(/^(华夏|易方达|南方|华泰柏瑞|华泰柏|嘉实|博时|广发|富国|招商|鹏华|汇添富|国泰|银华|景顺长城|工银瑞信|天弘)/, '')
    .replace(/(交易型开放式指数证券投资基金|交易型开放式指数基金|指数证券投资基金|指数基金)$/g, '')
    .trim()
  return cleaned || beforeEtf || source.replace(/ETF.*$/i, '').trim() || symbol
}

function etfFundType(name: string, trackingIndex: string) {
  const text = `${name} ${trackingIndex}`.toUpperCase()
  if (/债|国债|政金债|信用债|转债|短融|货币|现金|黄金|商品|原油|豆粕|有色|能源化工|REIT|REITS/.test(text)) {
    return '其他型'
  }
  return '股票型'
}

function etfTrackerCategory(symbol: string, name: string, trackingIndex: string) {
  const normalized = normalizeSymbol(symbol)
  const code = normalized.split('.')[0] || ''
  const text = `${normalized} ${name} ${trackingIndex}`.toUpperCase()
  if (code.startsWith('511') || code.startsWith('551') || /债|国债|政金债|信用债|公司债|可转债|转债|短融|货币|现金|日利|添益/.test(text)) {
    return 'bond'
  }
  if (/沪深300|中证A?500|中证1000|中证2000|中证800|上证50|上证180|科创50|创业板50|创业板指|深证100|深证成指|MSCI|A50/.test(text)) {
    return 'broad'
  }
  if (/半导体|芯片|证券|银行|保险|医药|医疗|消费|军工|煤炭|有色|钢铁|电力|汽车|家电|食品|饮料|白酒|酿酒|化工|建材|传媒|通信|软件|互联网|房地产|建筑|运输|农业|养殖|畜牧|稀土|机械|电气|物流|旅游|环保/.test(text)) {
    return 'industry'
  }
  if (/人工智能|AI|CPO|机器人|低空|算力|云计算|数据中心|信创|新能源|光伏|储能|电池|创新药|碳中和|ESG|央企|国企|红利|高股息|价值|成长|龙头|一带一路|数字经济|专精特新/.test(text)) {
    return 'theme'
  }
  return 'other'
}

function etfTrackerCategoryLabel(category: string) {
  return ETF_TRACKER_CATEGORY_OPTIONS.find((item) => item.value === category)?.label || '其他类'
}

function mergeSimilarEtfRows(rows: Array<Record<string, any>>) {
  const merged = new Map<string, Record<string, any>>()
  rows.forEach((row) => {
    const key = similarEtfKey(row)
    const current = merged.get(key)
    merged.set(key, current ? largestAmountEtfRow(current, row) : row)
  })
  return Array.from(merged.values())
}

function largestAmountEtfRow(left: Record<string, any>, right: Record<string, any>) {
  const leftAmount = numberValue(left.amount)
  const rightAmount = numberValue(right.amount)
  if (rightAmount > leftAmount) return right
  if (rightAmount === leftAmount && numberValue(right.market_value) > numberValue(left.market_value)) return right
  return left
}

function similarEtfKey(row: Record<string, any>) {
  const category = String(row.category || 'other')
  const trackingIndex = normalizeSimilarEtfName(String(row.tracking_index || row.name || row.symbol || ''))
  return `${category}:${trackingIndex || row.symbol}`
}

function normalizeSimilarEtfName(value: string) {
  return value
    .replace(/[（(][0-9A-Z.]+[）)]/g, '')
    .replace(/ETF|LOF|基金|联接|增强|发起式|交易型开放式指数证券投资基金|交易型开放式指数基金/gi, '')
    .replace(/华夏|易方达|南方|华泰柏瑞|华泰柏|嘉实|博时|广发|富国|招商|鹏华|汇添富|国泰|银华|景顺长城|工银瑞信|天弘|平安|兴业|建信|大成|华安|华宝|申万菱信|海富通|永赢|摩根|华富|浦银安盛/g, '')
    .replace(/\s+/g, '')
    .trim()
}

function groupSymbolsForAssetType(type: AssetShortcutType) {
  const groups = config.value?.symbol_groups || []
  if (type === 'etf') {
    return uniqueStringsInOrder(groups.filter((group) => group.name.toUpperCase().includes('ETF')).flatMap((group) => group.symbols))
  }
  if (type === 'stock') {
    return uniqueStringsInOrder(groups.filter((group) => group.name.includes('全A股票')).flatMap((group) => group.symbols))
  }
  return uniqueStringsInOrder(groups.filter((group) => group.name.includes('指数')).flatMap((group) => group.symbols))
}

function symbolsForAssetType(type: AssetShortcutType) {
  const cacheSymbols = cacheSymbolsForAssetType(type)
  return cacheSymbols.length ? cacheSymbols : groupSymbolsForAssetType(type)
}

function setCrossUniverseFromAssetType(type: AssetShortcutType) {
  const symbols = symbolsForAssetType(type)
  const labels: Record<AssetShortcutType, string> = { etf: 'ETF', stock: '个股', index: '指数' }
  if (!symbols.length) {
    showNotice('error', `${labels[type]}候选为空`, '当前配置没有可用标的，请先刷新指数或 ETF 列表。')
    return
  }
  crossForm.universe_symbols = symbols.join('\n')
  showNotice('success', '候选标的已更新', `已填入 ${formatInt(symbols.length)} 个${labels[type]}候选。`)
}

function openReviewSymbolPicker(type: ReviewSymbolPickerType) {
  reviewSymbolPickerOpen.value = true
  reviewSymbolPickerType.value = type
  reviewSymbolPickerCategory.value = defaultReviewSymbolCategory(type)
  reviewSymbolPickerKeyword.value = ''
  prefillReviewSymbolSelection()
}

function closeReviewSymbolPicker() {
  reviewSymbolPickerOpen.value = false
}

function setReviewSymbolPickerType(type: ReviewSymbolPickerType) {
  reviewSymbolPickerType.value = type
  reviewSymbolPickerCategory.value = defaultReviewSymbolCategory(type)
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

function reviewSymbolCategoryDefinitions(type: ReviewSymbolPickerType) {
  return type === 'etf' ? ETF_REVIEW_SYMBOL_CATEGORIES : SECTOR_REVIEW_SYMBOL_CATEGORIES
}

function defaultReviewSymbolCategory(type: ReviewSymbolPickerType) {
  return type === 'etf' ? 'equity_etf' : 'industry_l1'
}

function reviewSymbolCategoryLabel(type: ReviewSymbolPickerType, category: string) {
  return reviewSymbolCategoryDefinitions(type).find((item) => item.value === category)?.label || '其他'
}

function reviewSymbolCategory(type: ReviewSymbolPickerType, symbol: string, name: string, assetType = '') {
  return type === 'etf' ? etfReviewCategory(symbol, name, assetType) : sectorReviewCategory(symbol, name, assetType)
}

function etfReviewCategory(symbol: string, name: string, assetType = '') {
  const normalized = normalizeSymbol(symbol)
  const code = normalized.split('.')[0] || ''
  const text = `${normalized} ${name} ${assetType}`.toUpperCase()
  if (normalized.startsWith('880')) return 'tdx_special'
  if (code.startsWith('511') || code.startsWith('551')) return 'bond_money_etf'
  if (/债基|债|国债|政金债|信用债|公司债|可转债|转债|短融|货币|现金|日利|添益/.test(text)) {
    return 'bond_money_etf'
  }
  if (
    code.startsWith('513') ||
    /黄金|商品|原油|豆粕|能源化工|REIT|REITS|纳指|标普|恒生|港股|香港|中韩|韩国|日经|德国|法国|印度|海外|QDII|中概|跨境|美股|美国|亚太/.test(text)
  ) {
    return 'commodity_cross_reit'
  }
  if (/ETF/.test(text) || /^1[5-6]\d{4}\./.test(normalized) || /^5[1-9]\d{4}\./.test(normalized)) {
    return 'equity_etf'
  }
  return 'lof_other_fund'
}

function sectorReviewCategory(symbol: string, name: string, assetType = '') {
  const normalized = normalizeSymbol(symbol)
  const code = normalized.split('.')[0] || ''
  const cleanedName = String(name || '').replace(/\s+/g, '')
  const text = `${normalized} ${name} ${assetType}`.toUpperCase()
  if (/债|转债|国债|信用|货币|现金|基金|回购/.test(text)) return 'bond_fund'
  if (isTdxSpecialSectorIndex(text)) return 'tdx_special'
  if (/^880[34]\d{2}$/.test(code)) {
    if (TDX_LEVEL_ONE_INDUSTRY_NAMES.has(cleanedName)) return 'industry_l1'
    return 'industry_l2'
  }
  return 'tdx_special'
}

function isTdxSpecialSectorIndex(text: string) {
  return /TDX|昨日|昨|涨停|涨跌家数|停板|停牌|连板|近期|最近|情绪|热股|强势|弱势|异动|重仓|社保|北上|QFII|陆股通|持股|增仓|减仓|独门|绩优|亏损|预升|预亏|高管|解禁|减持|增持|控制权|股权|融资|融券|破净|低价|高价|市盈|质押|ST|含H股|专精特新|主板|北证|全Ａ|总市值|流通市值|平均股价|成交均价|活筹|等权|中位|均价|地域|板块/.test(text)
}

function prefillReviewSymbolSelection() {
  const current = new Set(parseSymbols(reviewForm.symbols))
  const currentGroupSymbols = categoryFilteredReviewSymbolPickerRows.value.map((row) => row.symbol)
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
  reviewSymbolPickerSelection.value = categoryFilteredReviewSymbolPickerRows.value.map((row) => row.symbol)
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
  settings.tdx_path = normalizeTdxPath(settings.tdx_path)
  return {
    ...settings,
    symbols: parsedSymbols.value,
    timeframes: selectedDownloadTimeframes.value,
    batch_size: Number(settings.batch_size || 100)
  }
}

function researchPayloadBase() {
  settings.data_root = normalizeDataRoot(settings.data_root)
  settings.tdx_path = normalizeTdxPath(settings.tdx_path)
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

function etfTrackerSearchSignature() {
  return JSON.stringify({
    data_root: normalizeDataRoot(settings.data_root),
    adjust: settings.adjust,
    timeframe: researchTimeframe.value,
    category: etfTrackerForm.category,
    type: etfTrackerForm.type,
    tracking_index: etfTrackerForm.tracking_index,
    keyword: etfTrackerForm.keyword.trim(),
    merge_similar: etfTrackerForm.merge_similar,
    symbols: etfTrackerReviewSymbols.value,
    start: etfTrackerForm.start,
    end: etfTrackerForm.end,
    benchmark_symbol: etfTrackerForm.benchmark_symbol,
    min_swing_return: Number(etfTrackerForm.min_swing_return || 0),
    min_segment_bars: Number(etfTrackerForm.min_segment_bars || 1),
    top_n: Number(etfTrackerForm.top_n || 30)
  })
}

function etfTrackerFilterSummary() {
  const categoryLabel =
    ETF_TRACKER_CATEGORY_OPTIONS.find((item) => item.value === etfTrackerForm.category)?.label || '全部ETF'
  const parts = [
    categoryLabel,
    etfTrackerForm.type || '全部类型',
    etfTrackerForm.tracking_index || '全部指数',
    etfTrackerForm.merge_similar ? '合并同类' : '不合并'
  ]
  const keyword = etfTrackerForm.keyword.trim()
  if (keyword) parts.push(`关键词 ${keyword}`)
  return parts.join(' · ')
}

function researchSnapshotPayload(tab: ResearchTabKey) {
  const form = {
    history: { ...historyForm },
    cross: { ...crossForm },
    review: { ...reviewForm },
    etf: { ...etfTrackerForm },
    regime: { ...regimeForm }
  }[tab]
  return {
    base: researchPayloadBase(),
    form: cloneJson(form)
  }
}

function researchSnapshotTitle(tab: ResearchTabKey) {
  if (tab === 'history') return `历史相似 · ${historyForm.symbol || '-'} · ${historyForm.window_start || '-'} 至 ${historyForm.as_of || '-'}`
  if (tab === 'cross') return `横截面相似 · ${crossForm.target_symbol || '-'} · ${crossForm.start || '-'} 至 ${crossForm.end || '-'}`
  if (tab === 'etf') return `场内ETF跟踪 · ${etfTrackerFilterSummary()} · ${etfTrackerForm.start || '-'} 至 ${etfTrackerForm.end || '-'}`
  if (tab === 'regime') return `市场风险偏好 · ${regimeForm.benchmark_symbol || '-'} · ${regimeForm.start || '-'} 至 ${regimeForm.end || '-'}`
  const count = parseSymbols(reviewForm.symbols).length
  return `多股复盘 · ${formatInt(count)} 标的 · ${reviewForm.start || '-'} 至 ${reviewForm.end || '-'}`
}

function researchSnapshotSummary(tab: ResearchTabKey, result: Record<string, any>) {
  const payloadSummary = result.summary || {}
  if (tab === 'history') return `${formatInt(payloadSummary.match_count)} 个历史窗口 · ${payloadSummary.timeframe || researchTimeframe.value}`
  if (tab === 'cross') return `${formatInt(payloadSummary.match_count)} 个候选匹配 · ${payloadSummary.timeframe || researchTimeframe.value}`
  if (tab === 'etf') return `${formatInt(payloadSummary.ranked_count)} 只ETF排序 · ${payloadSummary.timeframe || researchTimeframe.value}`
  if (tab === 'regime') {
    const appetite = result.risk_appetite || {}
    return `${String(appetite.phase || '-')} · RAI ${formatDecimalValue(appetite.score, 1)} · ${formatInt(payloadSummary.asset_count)} 资产`
  }
  return `${formatInt(payloadSummary.ranked_count)} 个排序标的 · ${payloadSummary.timeframe || researchTimeframe.value}`
}

function researchResultFor(tab: ResearchTabKey) {
  if (tab === 'history') return historyResult.value
  if (tab === 'cross') return crossResult.value
  if (tab === 'regime') return regimeResult.value
  return reviewResult.value
}

function setResearchResult(tab: ResearchTabKey, result: Record<string, any>) {
  if (tab === 'history') historyResult.value = result
  if (tab === 'cross') crossResult.value = result
  if (tab === 'regime') regimeResult.value = result
  if (tab === 'review' || tab === 'etf') reviewResult.value = result
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
    ['history', 'cross', 'review', 'etf', 'regime'].includes(value.tab) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    value.result &&
    typeof value.result === 'object'
  )
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

function downloadJson(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function saveSettings() {
  settings.data_root = normalizeDataRoot(settings.data_root)
  settings.tdx_path = normalizeTdxPath(settings.tdx_path)
  ensureAiPromptDraft()
  window.localStorage.setItem(
    SETTINGS_STORAGE_KEY,
    JSON.stringify({
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      timeframes: selectedDownloadTimeframes.value,
      batch_size: settings.batch_size,
      strict_after_update: settings.strict_after_update,
      fuyao: {
        api_key: fuyaoSettings.api_key
      },
      ai: {
        base_url: aiSettings.base_url,
        api_key: aiSettings.api_key,
        model: aiSettings.model,
        temperature: aiSettings.temperature,
        prompt_enabled: aiPromptSaved.value,
        prompt_system: aiPromptDraft.system,
        prompt_user: aiPromptDraft.user
      },
      chart: {
        theme: chartSettings.theme,
        density: chartSettings.density,
        show_context: chartSettings.show_context
      }
    })
  )
  showNotice('success', '设置已保存', '下次打开控制台会自动使用当前路径、运行参数和 AI 锐评设置。')
}

function resetSettings() {
  window.localStorage.removeItem(SETTINGS_STORAGE_KEY)
  Object.assign(settings, config.value?.defaults || {})
  Object.assign(aiSettings, defaultAiSettings())
  Object.assign(fuyaoSettings, defaultFuyaoSettings())
  Object.assign(chartSettings, defaultChartSettings())
  aiPromptDraft.system = ''
  aiPromptDraft.user = defaultAiUserPrompt()
  aiPromptSaved.value = false
  settings.data_root = normalizeDataRoot(settings.data_root)
  selectedTimeframes.value = normalizeDownloadTimeframes(config.value?.defaults?.timeframes || ['1d'])
  researchTimeframe.value = selectedDownloadTimeframes.value[0] || '1d'
  planRows.value = []
  planSummary.value = {}
  showNotice('info', '已恢复默认', '已恢复 API 提供的默认路径、运行参数和默认 AI 设置。')
}

function resetResizableCards() {
  clearResizableCardInlineSize(true)
  document.body.classList.add('card-resize-resetting')
  window.requestAnimationFrame(() => {
    document.body.classList.remove('card-resize-resetting')
  })
  showNotice('info', '已还原卡片尺寸', '全部可缩放卡片已恢复自适应布局。')
}

function normalizeResizableCardWidths() {
  window.requestAnimationFrame(() => {
    clearResizableCardInlineSize(false)
  })
}

function clearResizableCardInlineSize(includeHeight: boolean) {
  document.querySelectorAll<HTMLElement>('[data-resizable-card]').forEach((element) => {
    element.style.width = ''
    element.style.minWidth = ''
    element.style.maxWidth = ''
    if (includeHeight) {
      element.style.height = ''
      element.style.minHeight = ''
      element.style.maxHeight = ''
    }
  })
}

function restoreSettings() {
  const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (saved.data_root) saved.data_root = normalizeDataRoot(saved.data_root)
    if (saved.tdx_path) saved.tdx_path = normalizeTdxPath(saved.tdx_path)
    Object.assign(settings, {
      data_root: saved.data_root || settings.data_root,
      adjust: saved.adjust ?? settings.adjust,
      tdx_path: saved.tdx_path || settings.tdx_path,
      batch_size: saved.batch_size ?? settings.batch_size,
      strict_after_update: saved.strict_after_update ?? settings.strict_after_update
    })
    if (Array.isArray(saved.timeframes)) {
      selectedTimeframes.value = normalizeDownloadTimeframes(saved.timeframes)
    } else if (typeof saved.timeframe === 'string') {
      selectedTimeframes.value = normalizeDownloadTimeframes([saved.timeframe])
    }
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
    if (saved.fuyao && typeof saved.fuyao === 'object') {
      fuyaoSettings.api_key = saved.fuyao.api_key || ''
    }
    if (saved.chart && typeof saved.chart === 'object') {
      Object.assign(chartSettings, {
        theme: saved.chart.theme || chartSettings.theme,
        density: saved.chart.density || chartSettings.density,
        show_context: saved.chart.show_context ?? chartSettings.show_context
      })
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

function defaultFuyaoSettings() {
  return {
    api_key: ''
  }
}

function defaultChartSettings() {
  return {
    theme: 'clean',
    density: 'comfortable',
    show_context: true
  }
}

function fuyaoApiHeaders(): Record<string, string> {
  const apiKey = fuyaoSettings.api_key.trim()
  return apiKey ? { 'x-fuyao-api-key': apiKey } : {}
}

function fuyaoCalendarAvailable() {
  return Boolean(fuyaoSettings.api_key.trim() || config.value?.integrations?.fuyao_calendar?.configured)
}

async function apiGet(path: string, options: { headers?: Record<string, string> } = {}) {
  const response = await fetch(`${API_BASE}${path}`, { headers: options.headers || {} })
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

function normalizeSymbol(value: string) {
  const text = String(value || '').trim().toUpperCase().replace('_', '.')
  if (!text) return ''
  if (text.includes('.')) {
    const [code, exchange] = text.split('.', 2)
    const digits = code.replace(/\D/g, '').padStart(6, '0')
    const suffix = (exchange || '').slice(0, 2)
    return digits && ['SH', 'SZ', 'BJ'].includes(suffix) ? `${digits}.${suffix}` : ''
  }
  const digits = text.replace(/\D/g, '').slice(-6).padStart(6, '0')
  if (!digits) return ''
  if (/^(600|601|603|605|688|689)/.test(digits)) return `${digits}.SH`
  if (/^(430|830|831|832|833|834|835|836|837|838|839|920)/.test(digits)) return `${digits}.BJ`
  return `${digits}.SZ`
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

function tradingLookbackStartText(dayCount: number) {
  const count = Math.max(1, Math.trunc(Number(dayCount) || 1))
  const calendarDays = tradingCalendarDays.value.filter((day) => day <= latestTradingDayText()).sort()
  if (calendarDays.length) {
    return calendarDays[Math.max(0, calendarDays.length - count)]
  }
  const date = previousOrCurrentTradingDate(new Date())
  let remaining = count - 1
  while (remaining > 0) {
    date.setDate(date.getDate() - 1)
    if (isTradingWeekday(date)) remaining -= 1
  }
  return formatDateText(date)
}

function latestTradingDayText() {
  const today = todayText()
  const calendarDays = tradingCalendarDays.value.filter((day) => day <= today).sort()
  if (calendarDays.length) return calendarDays[calendarDays.length - 1]
  return formatDateText(previousOrCurrentTradingDate(new Date()))
}

function isDateText(value: unknown) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))
}

function previousOrCurrentTradingDate(value: Date) {
  const date = new Date(value)
  while (!isTradingWeekday(date)) {
    date.setDate(date.getDate() - 1)
  }
  return date
}

function isTradingWeekday(value: Date) {
  const day = value.getDay()
  return day !== 0 && day !== 6
}

function applyDateShortcut(target: DateRangeFields, key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  target.start = range.start
  target.end = range.end
}

function applyCandidateDateShortcut(key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  crossForm.traversal_start = range.start
  crossForm.traversal_end = range.end
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

function isCandidateDateShortcutActive(key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  return crossForm.traversal_start === range.start && crossForm.traversal_end === range.end
}

function isHistoryDateShortcutActive(key: DateShortcutKey) {
  const range = dateRangeForShortcut(key)
  return historyForm.window_start === range.start && historyForm.as_of === range.end
}

function dateRangeForShortcut(key: DateShortcutKey): DateRangeFields {
  const end = latestTradingDayText()
  if (key === '20d') return { start: tradingLookbackStartText(20), end }
  if (key === '50d') return { start: tradingLookbackStartText(50), end }
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

function shortDateLabel(value: unknown) {
  const text = formatDateOnly(value)
  return text ? text.slice(5) : '-'
}

function regimePhaseTone(phase: unknown) {
  const text = String(phase || '')
  if (text.includes('扩张') || text.includes('主升')) return 'positive'
  if (text.includes('释放') || text.includes('收缩')) return 'negative'
  return 'neutral'
}

function dailyEvidenceDetail(metric: string) {
  if (metric.includes('MA20')) return '短期宽度'
  if (metric.includes('MA60')) return '中期宽度'
  if (metric.includes('跌破')) return '高流动性压力'
  if (metric.includes('集中')) return '成交缩圈'
  if (metric.includes('数量')) return '回流候选'
  return '日报证据'
}

function dailyEvidenceTone(metric: string) {
  if (metric.includes('跌破')) return 'negative'
  if (metric.includes('数量')) return 'positive'
  if (metric.includes('集中')) return 'warning'
  return 'neutral'
}

function heatmapScoreLabel(value: unknown) {
  const score = Math.max(0, Math.min(1, Number(value)))
  return Number.isFinite(score) ? `${Math.round(score * 100)}%` : '-'
}

function riskHeatmapStatusLabel(triggered: boolean, value: unknown) {
  if (triggered) return '触发'
  const score = Math.max(0, Math.min(1, Number(value)))
  if (!Number.isFinite(score)) return '-'
  if (score >= 0.66) return '高压'
  if (score >= 0.38) return '升温'
  return '观察'
}

function riskHeatmapCellStyle(cell: Record<string, any>) {
  const score = Math.max(0, Math.min(1, numberValue(cell.stress_score)))
  const hue = 174 - score * 152
  const alpha = 0.2 + score * 0.7
  return {
    backgroundColor: `hsla(${hue}, 72%, 45%, ${alpha})`,
    borderColor: cell.stress_signal ? 'rgba(190, 18, 60, 0.88)' : 'rgba(16, 24, 40, 0.08)',
    color: score >= 0.58 ? '#ffffff' : '#14333a'
  }
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

function normalizeTdxPath(path: string) {
  const text = String(path || '').trim().replace(/[\\/]+$/, '')
  if (!text) return ''
  const separator = text.includes('\\') && !text.includes('/') ? '\\' : '/'
  const parts = text.split(/[\\/]+/)
  const last = parts[parts.length - 1]?.toLowerCase() || ''
  if (last === 'user' || last === 'sys') return text
  if (last === 'pyplugins') return `${text}${separator}user`
  if (last.includes('new_tdx64') || last.includes('newtdx64') || last.includes('new_tdx')) {
    return `${text}${separator}PYPlugins${separator}user`
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

function formatAmountValue(value: unknown) {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '-'
  if (Math.abs(amount) >= 100000000) return `${(amount / 100000000).toFixed(2)}亿`
  if (Math.abs(amount) >= 10000) return `${(amount / 10000).toFixed(1)}万`
  return amount.toFixed(0)
}

function numberValue(value: unknown) {
  const numberValue = Number(value || 0)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function numberOrDefault(value: unknown, fallback: number) {
  if (value === '' || value === null || value === undefined) return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function percentOrDefault(value: unknown, fallbackPercent: number) {
  if (value === '' || value === null || value === undefined) return fallbackPercent / 100
  const parsed = Number(String(value).trim().replace(/%$/, ''))
  return Number.isFinite(parsed) ? parsed / 100 : fallbackPercent / 100
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

function setPlanPageSize(size: number) {
  planPagination.pageSize = size
  planPagination.page = 1
}

function goPlanPage(page: number) {
  planPagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), planTotalPages.value)
}

function setEtfTrackerPageSize(size: number) {
  etfTrackerPagination.pageSize = size
  etfTrackerPagination.page = 1
}

function goEtfTrackerPage(page: number) {
  etfTrackerPagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), etfTrackerTotalPages.value)
}

function setRegimeFlowCandidatePageSize(size: number) {
  regimeFlowCandidatePagination.pageSize = size
  regimeFlowCandidatePagination.page = 1
}

function goRegimeFlowCandidatePage(page: number) {
  regimeFlowCandidatePagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), regimeFlowCandidateTotalPages.value)
}

function setRegimeMarketScopePageSize(size: number) {
  regimeMarketScopePagination.pageSize = size
  regimeMarketScopePagination.page = 1
}

function goRegimeMarketScopePage(page: number) {
  regimeMarketScopePagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), regimeMarketScopeTotalPages.value)
}

function applyRegimeParameterPreset(key: RegimeParameterPresetKey) {
  const preset = REGIME_PARAMETER_PRESETS.find((item) => item.key === key)
  if (!preset) return
  for (const [field, value] of Object.entries(preset.values)) {
    ;(regimeForm as Record<string, any>)[field] = value
  }
  showNotice('info', '风险偏好参数已切换', `${preset.label}：${preset.detail}`)
}

function normalizeRegimePercentFields() {
  for (const field of REGIME_PERCENT_FIELD_KEYS) {
    const current = (regimeForm as Record<string, any>)[field]
    const normalized = normalizeLegacyPercentInput(field, current)
    if (normalized !== current) {
      ;(regimeForm as Record<string, any>)[field] = normalized
    }
  }
}

function normalizeLegacyPercentInput(field: string, value: unknown) {
  if (!REGIME_PERCENT_FIELD_KEYS.includes(field as (typeof REGIME_PERCENT_FIELD_KEYS)[number])) return value
  const number = Number(value)
  if (!Number.isFinite(number) || number === 0) return value
  const defaultPercent = REGIME_PARAMETER_PRESETS[0]?.values[field as (typeof REGIME_PERCENT_FIELD_KEYS)[number]]
  if (!Number.isFinite(defaultPercent)) return value
  const defaultRatio = defaultPercent / 100
  if (Math.abs(number - defaultRatio) < 0.000001) return defaultPercent
  return value
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

function setTaskQualityIssuePageSize(size: number) {
  taskQualityIssuePagination.pageSize = size
  taskQualityIssuePagination.page = 1
}

function goTaskQualityIssuePage(page: number) {
  taskQualityIssuePagination.page = Math.min(Math.max(1, Math.trunc(page || 1)), taskQualityIssueTotalPages.value)
}

function parseQualityGateIssues(errorText: unknown): TaskQualityIssue[] {
  const text = String(errorText || '')
  if (!text.includes('质量门禁')) return []
  const issues: TaskQualityIssue[] = []
  const pattern = /(\d{6}\.(?:SH|SZ|BJ))\/([A-Za-z0-9]+)=([a-z_]+)\((.*?)\)(?=\s*[;；]|\s*$)/g
  let match = pattern.exec(text)
  while (match) {
    const status = match[3]
    issues.push({
      index: issues.length + 1,
      symbol: match[1],
      timeframe: match[2],
      status,
      status_label: STATUS_LABELS[status] || status,
      message: match[4] || '-'
    })
    match = pattern.exec(text)
  }
  return issues
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

function trendMeterWidth(value: unknown) {
  const number = Number(String(value || '').replace('%', ''))
  if (!Number.isFinite(number)) return '12%'
  return `${Math.min(100, Math.max(8, 50 + number * 2))}%`
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
