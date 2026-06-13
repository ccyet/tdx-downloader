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
          type="button"
          :aria-label="item.label"
          :aria-current="activeView === item.key ? 'page' : undefined"
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
            <button
              class="btn secondary"
              type="button"
              :disabled="activeResearchSnapshotDisabled"
              :title="activeResearchSnapshotDisabledReason || '保存当前工作台结果到本机快照'"
              @click="saveActiveResearchSnapshot"
            >
              <Icon name="save" />
              保存当前结果
            </button>
            <span
              v-if="activeResearchSnapshotDisabledReason"
              class="action-status inline warning side-action-status"
            >
              <i></i>
              {{ activeResearchSnapshotDisabledReason }}
            </span>
          </div>
          <div v-if="activeResearchSnapshots.length" class="side-snapshot-list">
            <article
              v-for="snapshot in activeResearchSnapshots"
              :key="snapshot.id"
              :class="[
                'side-snapshot-row',
                { confirming: confirmingResearchSnapshotDeleteId === snapshot.id || confirmingResearchSnapshotLoadId === snapshot.id }
              ]"
            >
              <button
                type="button"
                :disabled="confirmingResearchSnapshotDeleteId === snapshot.id || confirmingResearchSnapshotLoadId === snapshot.id"
                :title="confirmingResearchSnapshotDeleteId === snapshot.id ? '请先确认或取消删除' : confirmingResearchSnapshotLoadId === snapshot.id ? '请先确认或取消载入' : '载入快照前需要确认'"
                @click="requestLoadResearchSnapshot(snapshot)"
              >
                <strong>{{ snapshot.title }}</strong>
                <span>{{ snapshot.summary }}</span>
              </button>
              <div v-if="confirmingResearchSnapshotLoadId === snapshot.id" class="side-snapshot-confirm">
                <button class="mini-action" type="button" title="取消载入快照" @click="cancelLoadResearchSnapshot">
                  取消
                </button>
                <button class="mini-action danger" type="button" title="确认载入该研究快照" @click="confirmLoadResearchSnapshot(snapshot)">
                  载入
                </button>
              </div>
              <div v-else-if="confirmingResearchSnapshotDeleteId === snapshot.id" class="side-snapshot-confirm">
                <button class="mini-action" type="button" title="取消删除快照" @click="cancelDeleteResearchSnapshot">
                  取消
                </button>
                <button class="mini-action danger" type="button" title="确认删除该本地快照" @click="confirmDeleteResearchSnapshot(snapshot.id)">
                  删除
                </button>
              </div>
              <button
                v-else
                class="icon-button danger"
                type="button"
                title="删除快照前需要确认"
                aria-label="删除快照前需要确认"
                @click="requestDeleteResearchSnapshot(snapshot.id)"
              >
                <Icon name="trash" />
              </button>
            </article>
          </div>
          <p v-else class="side-empty">暂无当前模块快照。</p>
        </details>
      </div>

      <div class="sidebar-footer">
        <button
          class="nav-button"
          type="button"
          :aria-label="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
          :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
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
          <div class="resize-reset-actions" :class="{ confirming: confirmingResetResizableCards }">
            <template v-if="confirmingResetResizableCards">
              <button class="resize-reset-button" type="button" title="取消还原卡片尺寸" @click="cancelResetResizableCards">
                取消
              </button>
              <button class="resize-reset-button danger" type="button" title="确认还原全部卡片尺寸" @click="confirmResetResizableCards">
                确认还原
              </button>
            </template>
            <button v-else class="resize-reset-button" type="button" title="还原前需要确认" @click="requestResetResizableCards">
              还原卡片尺寸
            </button>
          </div>
          <template v-if="confirmingTopbarRefresh">
            <button class="resize-reset-button" type="button" title="取消刷新当前页面" @click="cancelTopbarRefresh">
              取消
            </button>
            <button class="resize-reset-button danger" type="button" :title="topbarRefreshConfirmText" @click="confirmTopbarRefresh">
              确认刷新
            </button>
          </template>
          <button
            v-else
            class="icon-button"
            type="button"
            :disabled="topbarRefreshing"
            :title="`${topbarRefreshTitle}前需要确认`"
            :aria-label="`${topbarRefreshTitle}前需要确认`"
            @click="requestTopbarRefresh"
          >
            <Icon name="refresh" />
          </button>
          <span v-if="topbarRefreshing" class="action-status inline busy">
            <i></i>
            {{ topbarRefreshStatusText }}
          </span>
          <span v-else-if="confirmingTopbarRefresh" class="action-status inline warning">
            <i></i>
            {{ topbarRefreshConfirmText }}
          </span>
          <div class="avatar">TD</div>
        </div>
      </header>

      <main :class="{ 'ai-main': activeView === 'ai' }">
        <div
          v-if="notice"
          :class="['notice-bar', notice.type]"
          :role="noticeRole(notice)"
          :aria-live="noticeAriaLive(notice)"
        >
          <strong>{{ notice.title }}</strong>
          <span>{{ notice.body }}</span>
          <button type="button" title="关闭当前提示" @click="notice = null">关闭</button>
        </div>

        <section v-if="activeView !== 'ai'" class="ai-command-shell" aria-label="大模型命令框">
          <div class="ai-command-head">
            <div>
              <strong>大模型命令框</strong>
              <span>{{ aiCommandScopeLabel }}</span>
            </div>
            <em>{{ aiConfigReady ? `模型 ${aiSettings.model}` : '未配置模型时使用本地规则规划' }}</em>
          </div>
          <form class="ai-command-form" @submit.prevent="requestRunAiCommand">
            <textarea
              v-model="aiCommandForm.text"
              rows="2"
              aria-label="大模型命令内容"
              placeholder="例如：帮我选择所有创业板股票；把风险参数调保守；基准60日涨幅设为12%"
              @input="handleAiCommandInput"
            ></textarea>
            <button
              v-if="!confirmingRunAiCommand"
              class="btn primary"
              type="submit"
              :disabled="aiCommandDisabled"
              :title="aiCommandDisabledReason || '解析命令前需要确认'"
            >
              <Icon name="sparkles" />
              {{ runningAiCommand ? '解析中' : '解析命令' }}
            </button>
            <template v-else>
              <button class="btn secondary" type="button" title="取消解析当前 AI 命令" @click="cancelRunAiCommand">
                取消
              </button>
              <button
                class="btn danger"
                type="button"
                :disabled="aiCommandDisabled"
                :title="aiCommandDisabledReason || aiCommandRunConfirmText"
                @click="confirmRunAiCommand"
              >
                确认解析
              </button>
            </template>
          </form>
          <div class="action-status" :class="{ busy: runningAiCommand, warning: confirmingRunAiCommand, muted: !runningAiCommand && !aiCommandResult && !confirmingRunAiCommand }">
            <i></i>
            <span>{{ aiCommandStatusText }}</span>
          </div>
          <div v-if="aiCommandResult" class="ai-command-result" :class="{ warning: aiCommandHasWarnings || aiCommandResultState === 'pending' }">
            <strong>{{ aiCommandResult.summary }}</strong>
            <span v-for="item in aiCommandResult.patches || []" :key="`${item.target}-${item.label}`">{{ item.summary || item.label }}</span>
            <em v-for="item in aiCommandResult.warnings || []" :key="item">{{ item }}</em>
          </div>
          <div v-if="aiCommandResultState === 'pending'" class="ai-command-actions">
            <button class="mini-action" type="button" title="取消应用当前 AI 命令结果" @click="cancelAiCommandApply">
              取消
            </button>
            <button
              class="mini-action danger"
              type="button"
              :disabled="aiCommandApplyDisabled"
              :title="aiCommandApplyDisabledReason || aiCommandApplyConfirmText"
              @click="confirmAiCommandApply"
            >
              确认应用
            </button>
          </div>
        </section>

        <section v-if="activeView === 'dashboard'" class="view-stack">
          <div class="toolbar-row">
            <button
              v-if="!confirmingOverviewRefresh"
              class="btn primary"
              type="button"
              :disabled="overviewRefreshDisabled"
              :title="overviewRefreshDisabledReason || '扫描缓存前需要确认'"
              @click="requestOverviewRefresh"
            >
              <Icon name="database" />
              {{ loadingOverview ? '扫描中' : '扫描缓存' }}
            </button>
            <template v-else>
              <button class="btn secondary" type="button" title="取消扫描缓存" @click="cancelOverviewRefresh">
                取消
              </button>
              <button
                class="btn danger"
                type="button"
                :disabled="overviewRefreshDisabled"
                :title="overviewRefreshDisabledReason || overviewRefreshConfirmText"
                @click="confirmOverviewRefresh"
              >
                确认扫描
              </button>
            </template>
            <button class="btn secondary" type="button" @click="activeView = 'download'">
              <Icon name="download" />
              新建下载
            </button>
            <span v-if="confirmingOverviewRefresh" class="action-status inline warning">
              <i></i>
              {{ overviewRefreshConfirmText }}
            </span>
            <span v-else-if="overviewRefreshDisabledReason" class="action-status inline busy">
              <i></i>
              {{ overviewRefreshDisabledReason }}
            </span>
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
              <div class="recent-task-main">
                <strong>{{ taskStatusLabel(latestTask.status) }}</strong>
                <span>{{ latestTask.id }}</span>
              </div>
              <div v-if="latestTaskProgress" class="task-progress-strip compact" :aria-label="latestTaskProgress.ariaLabel">
                <span :class="['task-progress-dot', latestTaskProgress.statusClass]"></span>
                <div class="task-progress-track slim" aria-hidden="true">
                  <span :style="{ width: latestTaskProgress.barWidth }"></span>
                </div>
                <em>{{ latestTaskProgress.percentText }}</em>
              </div>
              <div v-if="taskHasControls(latestTask)" class="task-control-actions latest-task-actions" aria-label="最近任务控制">
                <button
                  class="mini-action"
                  type="button"
                  :disabled="!taskCanPause(latestTask) || taskControlBusy(latestTask)"
                  :title="taskPauseTitle(latestTask)"
                  @click="controlTask(latestTask, 'pause')"
                >
                  暂停
                </button>
                <button
                  class="mini-action"
                  type="button"
                  :disabled="!taskCanResume(latestTask) || taskControlBusy(latestTask)"
                  :title="taskResumeTitle(latestTask)"
                  @click="controlTask(latestTask, 'resume')"
                >
                  继续
                </button>
                <button
                  class="mini-action danger"
                  type="button"
                  :disabled="!taskCanCancel(latestTask) || taskControlBusy(latestTask)"
                  :title="taskCancelTitle(latestTask)"
                  @click="controlTask(latestTask, 'cancel')"
                >
                  终止
                </button>
              </div>
              <em>{{ latestTask.error || latestTask.finished_at || latestTask.started_at || latestTask.created_at }}</em>
            </div>
            <EmptyState v-else title="暂无任务" body="执行下载后这里展示最近一次任务状态。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'download'" class="content-grid form-grid">
          <Panel title="下载参数" subtitle="任务配置">
            <form class="task-form" @submit.prevent="requestPreviewPlan">
              <label class="span-full symbol-source-field">
                <div class="field-head">
                  <span>代码来源</span>
                  <div class="field-actions">
                    <template v-if="pendingSymbolRefreshTarget === 'index' || pendingSymbolRefreshTarget === 'etf'">
                      <button class="mini-action" type="button" title="取消刷新代码表" @click="cancelSymbolGroupRefresh">取消</button>
                      <button
                        class="mini-action danger"
                        type="button"
                        :disabled="pendingSymbolRefreshDisabled"
                        :title="pendingSymbolRefreshDisabledReason || pendingSymbolRefreshConfirmText"
                        @click="confirmSymbolGroupRefresh"
                      >
                        确认刷新
                      </button>
                    </template>
                    <template v-else>
                      <button
                        class="mini-action"
                        type="button"
                        :disabled="symbolGroupRefreshDisabled"
                        :title="symbolGroupRefreshDisabledReason || '刷新指数前需要确认'"
                        @click="requestSymbolGroupRefresh('index')"
                      >
                        <Icon name="refresh" />
                        {{ refreshingSymbolGroup === 'index' ? '刷新中' : '刷新指数' }}
                      </button>
                      <button
                        class="mini-action"
                        type="button"
                        :disabled="symbolGroupRefreshDisabled"
                        :title="symbolGroupRefreshDisabledReason || '刷新 ETF 前需要确认'"
                        @click="requestSymbolGroupRefresh('etf')"
                      >
                        <Icon name="refresh" />
                        {{ refreshingSymbolGroup === 'etf' ? '刷新中' : '刷新ETF' }}
                      </button>
                    </template>
                  </div>
                </div>
                <span v-if="pendingSymbolRefreshTarget === 'index' || pendingSymbolRefreshTarget === 'etf'" class="action-status inline warning symbol-refresh-status">
                  <i></i>
                  {{ pendingSymbolRefreshConfirmText }}
                </span>
                <select
                  :value="pendingDownloadSymbolGroup || selectedGroup"
                  :disabled="loadingSymbolGroups || Boolean(pendingDownloadSymbolGroup)"
                  @change="requestApplySymbolGroup"
                >
                  <option value="custom">自定义</option>
                  <option v-for="group in config?.symbol_groups || []" :key="group.name" :value="group.name">
                    {{ group.name }} · {{ group.symbols.length }}只
                  </option>
                </select>
                <div v-if="pendingDownloadSymbolGroup" class="symbol-group-confirm-row">
                  <span class="action-status inline warning">
                    <i></i>
                    {{ downloadSymbolGroupConfirmText }}
                  </span>
                  <button class="mini-action" type="button" title="取消应用代码来源" @click="cancelApplySymbolGroup">
                    取消
                  </button>
                  <button
                    class="mini-action danger"
                    type="button"
                    :disabled="downloadSymbolGroupConfirmDisabled"
                    :title="downloadSymbolGroupConfirmDisabledReason || downloadSymbolGroupConfirmText"
                    @click="confirmApplySymbolGroup"
                  >
                    确认应用
                  </button>
                </div>
              </label>

              <div class="quick-update span-full">
                <div>
                  <strong>全资产更新</strong>
                  <span>按当前代码库合并股票、ETF、指数和板块，生成近 N 个交易日任务。</span>
                </div>
                <label>
                  <span>近 N 交易日</span>
                  <input
                    v-model.number="allAssetsLookbackDays"
                    type="number"
                    min="1"
                    step="1"
                    :disabled="confirmingAllAssetsUpdate"
                  />
                </label>
                <div class="quick-update-actions">
                  <button
                    v-show="!confirmingAllAssetsUpdate"
                    class="btn secondary quick-update-primary"
                    type="button"
                    :disabled="allAssetsUpdateDisabled"
                    :title="allAssetsUpdateDisabledReason || '应用全资产前需要确认'"
                    @click="requestAllAssetsRecentUpdate"
                  >
                    <Icon name="refresh" />
                    应用全资产
                  </button>
                  <button
                    v-show="confirmingAllAssetsUpdate"
                    class="btn secondary"
                    type="button"
                    title="取消应用全资产"
                    @click="cancelAllAssetsRecentUpdate"
                  >
                    取消
                  </button>
                  <button
                    v-show="confirmingAllAssetsUpdate"
                    class="btn danger"
                    type="button"
                    :disabled="allAssetsUpdateDisabled"
                    :title="allAssetsUpdateDisabledReason || allAssetsUpdateConfirmText"
                    @click="confirmAllAssetsRecentUpdate"
                  >
                    确认应用
                  </button>
                </div>
                <span v-if="confirmingAllAssetsUpdate" class="action-status inline warning quick-update-status">
                  <i></i>
                  {{ allAssetsUpdateConfirmText }}
                </span>
              </div>

              <div class="span-full timeframe-picker">
                <div class="field-head">
                  <span>周期</span>
                  <div class="field-actions">
                    <template v-if="pendingDownloadTimeframeAction">
                      <button class="mini-action" type="button" title="取消下载周期快捷修改" @click="cancelDownloadTimeframeAction">取消</button>
                      <button
                        class="mini-action danger"
                        type="button"
                        :disabled="downloadTimeframePendingDisabled"
                        :title="downloadTimeframePendingDisabledReason || downloadTimeframePendingText"
                        @click="confirmDownloadTimeframeAction"
                      >
                        确认应用
                      </button>
                    </template>
                    <template v-else>
                      <button class="mini-action" type="button" title="选择全周期前需要确认" @click="requestDownloadTimeframeAction('all')">全周期</button>
                      <button class="mini-action" type="button" title="恢复默认周期前需要确认" @click="requestDownloadTimeframeAction('default')">默认</button>
                    </template>
                  </div>
                </div>
                <span v-if="pendingDownloadTimeframeAction" class="action-status inline warning timeframe-confirm-status">
                  <i></i>
                  {{ downloadTimeframePendingText }}
                </span>
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
                <textarea v-model="symbolsText" rows="5" placeholder="000001.SZ, 600519.SH" @input="handleDownloadSymbolsInput"></textarea>
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
                <template v-if="pendingDownloadDateShortcut">
                  <button class="date-shortcut" type="button" title="取消日期快捷修改" @click="cancelDownloadDateShortcut">取消</button>
                  <button
                    class="date-shortcut danger"
                    type="button"
                    :disabled="downloadDateShortcutPendingDisabled"
                    :title="downloadDateShortcutPendingDisabledReason || downloadDateShortcutPendingText"
                    @click="confirmDownloadDateShortcut"
                  >
                    确认应用
                  </button>
                </template>
                <template v-else>
                  <button
                    v-for="shortcut in DATE_RANGE_SHORTCUTS"
                    :key="shortcut.key"
                    type="button"
                    :class="['date-shortcut', { active: isDateShortcutActive(settings, shortcut.key) }]"
                    :aria-pressed="isDateShortcutActive(settings, shortcut.key)"
                    title="应用日期快捷前需要确认"
                    @click="requestDownloadDateShortcut(shortcut.key)"
                  >
                    {{ shortcut.label }}
                  </button>
                </template>
                <span v-if="pendingDownloadDateShortcut" class="action-status inline warning download-date-shortcut-status">
                  <i></i>
                  {{ downloadDateShortcutPendingText }}
                </span>
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
                  <button
                    class="btn secondary"
                    type="button"
                    :disabled="directoryPickDisabled"
                    :title="directoryPickTitle('data_root')"
                    @click="pickDirectory('data_root')"
                  >
                    <Icon name="folder" />
                    {{ pickingDirectory === 'data_root' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>

              <label class="span-full">
                <span>TDX PYPlugins 或根目录</span>
                <div class="path-control">
                  <input v-model="settings.tdx_path" type="text" />
                  <button
                    class="btn secondary"
                    type="button"
                    :disabled="directoryPickDisabled"
                    :title="directoryPickTitle('tdx_path')"
                    @click="pickDirectory('tdx_path')"
                  >
                    <Icon name="folder" />
                    {{ pickingDirectory === 'tdx_path' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>

              <div class="action-readiness span-full" :class="{ warning: Boolean(downloadActionWarning) }">
                <strong>{{ downloadActionReady ? '可预览下载计划' : '请先补齐参数' }}</strong>
                <span>{{ downloadActionStatusText }}</span>
              </div>

              <div class="form-actions span-full">
                <template v-if="confirmingPreviewPlan">
                  <button class="btn secondary" type="button" title="取消预览下载计划" @click="cancelPreviewPlan">取消</button>
                  <button
                    class="btn danger"
                    type="button"
                    :disabled="previewPlanDisabled"
                    :title="previewPlanDisabledReason || previewPlanConfirmText"
                    @click="confirmPreviewPlan"
                  >
                    确认预览
                  </button>
                </template>
                <button
                  v-else
                  class="btn secondary"
                  type="submit"
                  :disabled="previewPlanDisabled"
                  :title="previewPlanDisabledReason || '预览下载计划前需要确认'"
                >
                  <Icon name="clipboard" />
                  {{ planning ? '生成计划中' : '预览计划' }}
                </button>
                <template v-if="confirmingStartDownload">
                  <button class="btn secondary" type="button" :disabled="downloading" title="取消执行下载" @click="cancelStartDownload">
                    取消
                  </button>
                  <button class="btn danger" type="button" :disabled="startDownloadDisabled" :title="startDownloadDisabledReason || startDownloadConfirmTitle" @click="confirmStartDownload">
                    <Icon name="download" />
                    {{ downloading ? '提交中' : '确认执行' }}
                  </button>
                </template>
                <button v-else class="btn danger" type="button" :disabled="startDownloadDisabled" :title="startDownloadDisabledReason || startDownloadRequestTitle" @click="requestStartDownload">
                  <Icon name="download" />
                  执行下载
                </button>
                <span v-if="planning || downloading" class="action-status inline busy">
                  <i></i>
                  {{ downloadBusyStatusText }}
                </span>
                <span v-else-if="confirmingPreviewPlan" class="action-status inline warning">
                  <i></i>
                  {{ previewPlanConfirmText }}
                </span>
                <span v-else-if="confirmingStartDownload" class="action-status inline warning download-confirm-status">
                  <i></i>
                  {{ startDownloadConfirmStatusText }}
                </span>
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
                      :aria-pressed="planPagination.pageSize === size"
                      :title="pageSizeButtonTitle(size, planPagination.pageSize, '下载计划')"
                      @click="setPlanPageSize(size)"
                    >
                      {{ size }}
                    </button>
                  </div>
                  <div class="pagination-controls">
                    <button
                      type="button"
                      :disabled="paginationActionDisabled('first', planPagination.page, planTotalPages)"
                      :aria-disabled="paginationActionDisabled('first', planPagination.page, planTotalPages)"
                      :aria-label="paginationActionTitle('first', planPagination.page, planTotalPages, '下载计划')"
                      :title="paginationActionTitle('first', planPagination.page, planTotalPages, '下载计划')"
                      @click="goPlanPage(1)"
                    >
                      首页
                    </button>
                    <button
                      type="button"
                      :disabled="paginationActionDisabled('prev', planPagination.page, planTotalPages)"
                      :aria-disabled="paginationActionDisabled('prev', planPagination.page, planTotalPages)"
                      :aria-label="paginationActionTitle('prev', planPagination.page, planTotalPages, '下载计划')"
                      :title="paginationActionTitle('prev', planPagination.page, planTotalPages, '下载计划')"
                      @click="goPlanPage(planPagination.page - 1)"
                    >
                      上一页
                    </button>
                    <span class="pagination-status" aria-live="polite">{{ planPagination.page }} / {{ planTotalPages }}</span>
                    <button
                      type="button"
                      :disabled="paginationActionDisabled('next', planPagination.page, planTotalPages)"
                      :aria-disabled="paginationActionDisabled('next', planPagination.page, planTotalPages)"
                      :aria-label="paginationActionTitle('next', planPagination.page, planTotalPages, '下载计划')"
                      :title="paginationActionTitle('next', planPagination.page, planTotalPages, '下载计划')"
                      @click="goPlanPage(planPagination.page + 1)"
                    >
                      下一页
                    </button>
                    <button
                      type="button"
                      :disabled="paginationActionDisabled('last', planPagination.page, planTotalPages)"
                      :aria-disabled="paginationActionDisabled('last', planPagination.page, planTotalPages)"
                      :aria-label="paginationActionTitle('last', planPagination.page, planTotalPages, '下载计划')"
                      :title="paginationActionTitle('last', planPagination.page, planTotalPages, '下载计划')"
                      @click="goPlanPage(planTotalPages)"
                    >
                      末页
                    </button>
                  </div>
                </div>
              </div>
              <DataTable
                :rows="displayPlanRows"
                :columns="planColumns"
                aria-label="下载计划"
                empty="点击“预览计划”后显示。"
                empty-body="系统会按当前标的、周期和交易日窗口计算本地数据缺口。"
                :loading="planning"
                loading-title="正在生成下载计划"
                loading-text="正在比较任务交易日和本地缓存交易日，请稍候。"
              />
            </Panel>
          </div>
        </section>

        <section v-else-if="activeView === 'cache'" class="view-stack">
          <section class="content-grid two">
            <Panel title="股票数据表" subtitle="K线 + 指标列">
              <form class="task-form" @submit.prevent="requestLoadPriceTable">
                <label>
                  <span>股票代码</span>
                  <input v-model="priceTableForm.symbols" type="text" placeholder="000001.SZ,300750.SZ" />
                </label>
                <label>
                  <span>周期</span>
                  <select v-model="priceTableForm.timeframe">
                    <option v-for="timeframe in config?.timeframes || ['1d']" :key="timeframe" :value="timeframe">{{ timeframe }}</option>
                  </select>
                </label>
                <label>
                  <span>开始</span>
                  <input v-model="priceTableForm.start" type="date" />
                </label>
                <label>
                  <span>结束</span>
                  <input v-model="priceTableForm.end" type="date" />
                </label>
                <label class="span-full">
                  <span>指标列</span>
                  <div class="indicator-chip-row">
                    <button
                      v-for="formula in indicatorFormulaRows"
                      :key="formula.formula_id"
                      type="button"
                      :class="['indicator-chip', { active: isIndicatorSelected(formula.formula_id) }]"
                      @click="togglePriceIndicator(formula.formula_id)"
                    >
                      {{ formula.name || formula.formula_id }}
                    </button>
                  </div>
                </label>
                <div class="form-actions span-full">
                  <template v-if="confirmingLoadPriceTable">
                    <button class="btn secondary" type="button" title="取消读取股票数据表" @click="cancelLoadPriceTable">取消</button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="priceTableActionDisabled"
                      :title="priceTableActionDisabledReason || priceTableLoadConfirmText"
                      @click="confirmLoadPriceTable"
                    >
                      确认读取
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn primary"
                    type="submit"
                    :disabled="priceTableActionDisabled"
                    :title="priceTableActionDisabledReason || '读取股票数据表前需要确认'"
                  >
                    <Icon name="database" />
                    {{ loadingPriceTable ? '读取中' : '读取数据表' }}
                  </button>
                  <template v-if="confirmingPriceTableCommonIndicators">
                    <button class="btn secondary" type="button" title="取消应用常用均线" @click="cancelPriceTableCommonIndicators">取消</button>
                    <button class="btn danger" type="button" :title="priceTableCommonIndicatorsConfirmText" @click="confirmPriceTableCommonIndicators">
                      确认均线
                    </button>
                  </template>
                  <button v-else class="btn secondary" type="button" title="应用常用均线前需要确认" @click="requestPriceTableCommonIndicators">
                    常用均线
                  </button>
                </div>
                <div class="action-readiness span-full" :class="{ warning: Boolean((priceTableActionDisabledReason && !loadingPriceTable) || confirmingLoadPriceTable || confirmingPriceTableCommonIndicators) }">
                  <strong>{{ loadingPriceTable ? '读取中' : confirmingLoadPriceTable ? '待确认' : confirmingPriceTableCommonIndicators ? '待确认' : priceTableActionDisabledReason ? '待补充' : '可读取' }}</strong>
                  <span>{{ confirmingLoadPriceTable ? priceTableLoadConfirmText : confirmingPriceTableCommonIndicators ? priceTableCommonIndicatorsConfirmText : priceTableActionStatusText }}</span>
                </div>
              </form>
            </Panel>

            <Panel title="指标公式" subtitle="导入 / 映射 / 计算">
              <form class="task-form" @submit.prevent="requestImportIndicatorFormula">
                <label>
                  <span>公式前缀</span>
                  <input v-model="indicatorImportForm.formula_id_prefix" type="text" placeholder="可选" :disabled="confirmingImportIndicatorFormula" />
                </label>
                <label>
                  <span>映射资产</span>
                  <select v-model="indicatorMappingForm.asset_type" :disabled="confirmingImportIndicatorFormula">
                    <option value="">全部资产</option>
                    <option value="stock">个股</option>
                    <option value="etf">ETF</option>
                    <option value="index">指数</option>
                  </select>
                </label>
                <label class="span-full">
                  <span>通达信公式文本</span>
                  <textarea v-model="indicatorImportForm.text" rows="5" placeholder="例如：M20:MA(CLOSE,20);" :disabled="confirmingImportIndicatorFormula"></textarea>
                </label>
                <div class="form-actions span-full">
                  <template v-if="confirmingImportIndicatorFormula">
                    <button class="btn secondary" type="button" title="取消导入指标公式" @click="cancelImportIndicatorFormula">取消</button>
                    <button class="btn danger" type="button" :disabled="indicatorImportDisabled" :title="indicatorImportDisabledReason || indicatorImportConfirmText" @click="confirmImportIndicatorFormula">
                      确认导入
                    </button>
                  </template>
                  <template v-else-if="confirmingMapSelectedIndicators">
                    <button class="btn secondary" type="button" title="取消绑定选中指标" @click="cancelMapSelectedIndicators">取消</button>
                    <button class="btn danger" type="button" :disabled="indicatorMappingDisabled" :title="indicatorMappingDisabledReason || indicatorMappingConfirmText" @click="confirmMapSelectedIndicators">
                      确认绑定
                    </button>
                  </template>
                  <template v-else-if="confirmingComputeSelectedIndicators">
                    <button class="btn secondary" type="button" title="取消计算选中指标" @click="cancelComputeSelectedIndicators">取消</button>
                    <button class="btn danger" type="button" :disabled="indicatorComputeDisabled" :title="indicatorComputeDisabledReason || indicatorComputeConfirmText" @click="confirmComputeSelectedIndicators">
                      确认计算
                    </button>
                  </template>
                  <button v-else class="btn primary" type="submit" :disabled="indicatorImportDisabled" :title="indicatorImportDisabledReason || '导入公式前需要确认'">
                    <Icon name="download" />
                    {{ importingIndicatorFormula ? '导入中' : '导入公式' }}
                  </button>
                  <button
                    v-if="!indicatorConfirmingAction"
                    class="btn secondary"
                    type="button"
                    :disabled="indicatorMappingDisabled"
                    :title="indicatorMappingDisabledReason || '绑定选中指标前需要确认'"
                    @click="requestMapSelectedIndicators"
                  >
                    <Icon name="layers" />
                    {{ mappingIndicators ? '绑定中' : '绑定选中指标' }}
                  </button>
                  <button
                    v-if="!indicatorConfirmingAction"
                    class="btn secondary"
                    type="button"
                    :disabled="indicatorComputeDisabled"
                    :title="indicatorComputeDisabledReason || '计算选中指标前需要确认'"
                    @click="requestComputeSelectedIndicators"
                  >
                    <Icon name="activity" />
                    {{ computingIndicators ? '计算中' : '计算选中指标' }}
                  </button>
                </div>
                <div class="action-readiness span-full" :class="{ warning: Boolean(indicatorActionWarning) || Boolean(indicatorConfirmingAction) }">
                  <strong>{{ indicatorActionStateLabel }}</strong>
                  <span>{{ indicatorConfirmingActionText || indicatorActionStatusText }}</span>
                </div>
              </form>
            </Panel>
          </section>

          <Panel title="股票数据明细" :subtitle="priceTableSummary">
            <DataTable
              :rows="displayPriceTableRows"
              :columns="priceTableColumns"
              aria-label="股票数据明细"
              empty="读取股票数据表后显示。"
              empty-body="填写代码与日期后读取；如选择指标，会同步展示指标列。"
              :loading="loadingPriceTable"
              loading-title="正在读取股票数据表"
              loading-text="正在读取 K 线、补算缺失指标并刷新表格。"
            />
          </Panel>

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
                    :aria-pressed="cachePagination.pageSize === size"
                    :title="pageSizeButtonTitle(size, cachePagination.pageSize, '缓存资产')"
                    @click="setCachePageSize(size)"
                  >
                    {{ size }}
                  </button>
                </div>
                <div class="pagination-controls">
                  <button
                    type="button"
                    :disabled="paginationActionDisabled('first', cachePagination.page, cacheTotalPages)"
                    :aria-disabled="paginationActionDisabled('first', cachePagination.page, cacheTotalPages)"
                    :aria-label="paginationActionTitle('first', cachePagination.page, cacheTotalPages, '缓存资产')"
                    :title="paginationActionTitle('first', cachePagination.page, cacheTotalPages, '缓存资产')"
                    @click="goCachePage(1)"
                  >
                    首页
                  </button>
                  <button
                    type="button"
                    :disabled="paginationActionDisabled('prev', cachePagination.page, cacheTotalPages)"
                    :aria-disabled="paginationActionDisabled('prev', cachePagination.page, cacheTotalPages)"
                    :aria-label="paginationActionTitle('prev', cachePagination.page, cacheTotalPages, '缓存资产')"
                    :title="paginationActionTitle('prev', cachePagination.page, cacheTotalPages, '缓存资产')"
                    @click="goCachePage(cachePagination.page - 1)"
                  >
                    上一页
                  </button>
                  <span class="pagination-status" aria-live="polite">{{ cachePagination.page }} / {{ cacheTotalPages }}</span>
                  <button
                    type="button"
                    :disabled="paginationActionDisabled('next', cachePagination.page, cacheTotalPages)"
                    :aria-disabled="paginationActionDisabled('next', cachePagination.page, cacheTotalPages)"
                    :aria-label="paginationActionTitle('next', cachePagination.page, cacheTotalPages, '缓存资产')"
                    :title="paginationActionTitle('next', cachePagination.page, cacheTotalPages, '缓存资产')"
                    @click="goCachePage(cachePagination.page + 1)"
                  >
                    下一页
                  </button>
                  <button
                    type="button"
                    :disabled="paginationActionDisabled('last', cachePagination.page, cacheTotalPages)"
                    :aria-disabled="paginationActionDisabled('last', cachePagination.page, cacheTotalPages)"
                    :aria-label="paginationActionTitle('last', cachePagination.page, cacheTotalPages, '缓存资产')"
                    :title="paginationActionTitle('last', cachePagination.page, cacheTotalPages, '缓存资产')"
                    @click="goCachePage(cacheTotalPages)"
                  >
                    末页
                  </button>
                </div>
              </div>
            </div>
            <DataTable :rows="displayCacheRows" :columns="cacheColumns" aria-label="本地缓存资产" empty="暂无匹配缓存记录。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'research'" class="view-stack">
          <div class="research-tabs" role="tablist" aria-label="研究工具页签">
            <button
              v-for="tab in researchTabs"
              :key="tab.key"
              type="button"
              :class="['research-tab', { active: activeResearchTab === tab.key }]"
              role="tab"
              :id="researchTabId(tab.key)"
              :aria-selected="activeResearchTab === tab.key"
              :aria-controls="researchPanelId(tab.key)"
              :tabindex="activeResearchTab === tab.key ? 0 : -1"
              :title="`切换到${tab.label}`"
              @click="activeResearchTab = tab.key"
              @keydown="handleResearchTabKeydown($event, tab.key)"
            >
              <Icon :name="tab.icon" />
              <span>{{ tab.label }}</span>
            </button>
          </div>

          <section
            v-if="activeResearchTab === 'history'"
            :id="researchPanelId('history')"
            class="content-grid two"
            role="tabpanel"
            :aria-labelledby="researchTabId('history')"
          >
            <Panel title="历史时序相似" subtitle="单标的">
              <form class="task-form" @submit.prevent="requestRunHistorySearch">
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
                  <template v-if="pendingResearchDateShortcut?.target === 'history'">
                    <button class="date-shortcut" type="button" title="取消历史相似日期快捷修改" @click="cancelResearchDateShortcut">取消</button>
                    <button class="date-shortcut danger" type="button" :title="researchDateShortcutPendingText" @click="confirmResearchDateShortcut">
                      确认应用
                    </button>
                  </template>
                  <template v-else>
                    <button
                      v-for="shortcut in DATE_RANGE_SHORTCUTS"
                      :key="shortcut.key"
                      type="button"
                      :class="['date-shortcut', { active: isHistoryDateShortcutActive(shortcut.key) }]"
                      :aria-pressed="isHistoryDateShortcutActive(shortcut.key)"
                      title="应用历史相似日期快捷前需要确认"
                      @click="requestResearchDateShortcut('history', shortcut.key)"
                    >
                      {{ shortcut.label }}
                    </button>
                  </template>
                  <span v-if="pendingResearchDateShortcut?.target === 'history'" class="action-status inline warning research-date-shortcut-status">
                    <i></i>
                    {{ researchDateShortcutPendingText }}
                  </span>
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
                  <template v-if="confirmingRunHistorySearch">
                    <button class="btn secondary" type="button" title="取消历史相似搜索" @click="cancelRunHistorySearch">
                      取消
                    </button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="researchActionDisabled('history')"
                      :title="researchActionDisabledReason('history') || historySearchConfirmText"
                      @click="confirmRunHistorySearch"
                    >
                      确认搜索
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn primary"
                    type="submit"
                    :disabled="researchActionDisabled('history')"
                    :title="researchActionDisabledReason('history') || '开始历史相似搜索前需要确认'"
                  >
                    <Icon name="activity" />
                    {{ runningResearch === 'history' ? '搜索中' : '开始搜索' }}
                  </button>
                  <button class="btn secondary" type="button" :disabled="resultActionDisabled('history')" :title="resultActionDisabledReason('history') || '保存当前历史相似结果到本机快照'" @click="saveResearchSnapshot('history')">
                    <Icon name="save" />
                    保存快照
                  </button>
                  <span v-if="runningResearch === 'history'" class="action-status inline busy">
                    <i></i>
                    {{ researchBusyStatusText }}
                  </span>
                  <span v-else-if="confirmingRunHistorySearch" class="action-status inline warning">
                    <i></i>
                    {{ historySearchConfirmText }}
                  </span>
                  <span v-else-if="resultActionDisabledReason('history')" class="action-status inline warning">
                    <i></i>
                    {{ resultActionDisabledReason('history') }}
                  </span>
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
              <DataTable :rows="displayHistoryRows" :columns="historyColumns" aria-label="历史匹配结果" empty="暂无历史匹配结果。" />
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
                  aria-label="历史前瞻统计"
                  empty="暂无前瞻统计。"
                />
              </div>
            </Panel>
          </section>

          <section
            v-else-if="activeResearchTab === 'cross'"
            :id="researchPanelId('cross')"
            class="content-grid two"
            role="tabpanel"
            :aria-labelledby="researchTabId('cross')"
          >
            <Panel title="横截面相似" :subtitle="crossSearchModeLabel">
              <form class="task-form" @submit.prevent="requestRunCrossSectionSearch">
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
                    <template v-if="pendingResearchDateShortcut?.target === 'crossTarget'">
                      <button class="date-shortcut" type="button" title="取消目标日期快捷修改" @click="cancelResearchDateShortcut">取消</button>
                      <button class="date-shortcut danger" type="button" :title="researchDateShortcutPendingText" @click="confirmResearchDateShortcut">
                        确认应用
                      </button>
                    </template>
                    <template v-else>
                      <button
                        v-for="shortcut in DATE_RANGE_SHORTCUTS"
                        :key="shortcut.key"
                        type="button"
                        :class="['date-shortcut', { active: isDateShortcutActive(crossForm, shortcut.key) }]"
                        :aria-pressed="isDateShortcutActive(crossForm, shortcut.key)"
                        title="应用目标日期快捷前需要确认"
                        @click="requestResearchDateShortcut('crossTarget', shortcut.key)"
                      >
                        {{ shortcut.label }}
                      </button>
                    </template>
                    <span v-if="pendingResearchDateShortcut?.target === 'crossTarget'" class="action-status inline warning research-date-shortcut-status">
                      <i></i>
                      {{ researchDateShortcutPendingText }}
                    </span>
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
                      <input
                        v-model="crossForm.traversal_start"
                        type="date"
                        :disabled="Boolean(crossCandidateRangeDisabledReason)"
                        :title="crossCandidateRangeDisabledReason || '设置候选搜索起始日期'"
                      />
                    </label>
                    <label>
                      <span>候选结束</span>
                      <input
                        v-model="crossForm.traversal_end"
                        type="date"
                        :disabled="Boolean(crossCandidateRangeDisabledReason)"
                        :title="crossCandidateRangeDisabledReason || '设置候选搜索结束日期'"
                      />
                    </label>
                  </div>
                  <div class="date-shortcuts" aria-label="候选日期快捷选项">
                    <span>候选快捷</span>
                    <template v-if="pendingResearchDateShortcut?.target === 'crossCandidate'">
                      <button class="date-shortcut" type="button" title="取消候选日期快捷修改" @click="cancelResearchDateShortcut">取消</button>
                      <button class="date-shortcut danger" type="button" :title="researchDateShortcutPendingText" @click="confirmResearchDateShortcut">
                        确认应用
                      </button>
                    </template>
                    <template v-else>
                      <button
                        v-for="shortcut in DATE_RANGE_SHORTCUTS"
                        :key="shortcut.key"
                        type="button"
                        :disabled="Boolean(crossCandidateRangeDisabledReason)"
                        :class="['date-shortcut', { active: isCandidateDateShortcutActive(shortcut.key) }]"
                        :aria-pressed="isCandidateDateShortcutActive(shortcut.key)"
                        :title="crossCandidateRangeDisabledReason || '应用候选日期快捷前需要确认'"
                        @click="requestResearchDateShortcut('crossCandidate', shortcut.key)"
                      >
                        {{ shortcut.label }}
                      </button>
                    </template>
                    <span v-if="crossCandidateRangeDisabledReason" class="action-status inline muted research-date-shortcut-status">
                      <i></i>
                      {{ crossCandidateRangeDisabledReason }}
                    </span>
                    <span v-if="pendingResearchDateShortcut?.target === 'crossCandidate'" class="action-status inline warning research-date-shortcut-status">
                      <i></i>
                      {{ researchDateShortcutPendingText }}
                    </span>
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
                    <div class="field-actions" :class="{ confirming: Boolean(pendingCrossUniverseAction) }">
                      <template v-if="pendingCrossUniverseAction">
                        <button class="mini-action" type="button" title="取消候选标的覆盖" @click="cancelCrossUniverseAction">
                          取消
                        </button>
                        <button
                          class="mini-action danger"
                          type="button"
                          :disabled="crossUniversePendingDisabled"
                          :title="crossUniversePendingDisabledReason || crossUniversePendingStatusText"
                          @click="confirmCrossUniverseAction"
                        >
                          确认{{ crossUniversePendingActionLabel }}
                        </button>
                      </template>
                      <template v-else>
                        <button class="mini-action" type="button" title="填入所有 ETF 前需要确认" @click="requestCrossUniverseFromAssetType('etf')">
                          <Icon name="archive" />
                          所有ETF
                        </button>
                        <button class="mini-action" type="button" title="填入所有个股前需要确认" @click="requestCrossUniverseFromAssetType('stock')">
                          <Icon name="key" />
                          所有个股
                        </button>
                        <button class="mini-action" type="button" title="填入所有指数前需要确认" @click="requestCrossUniverseFromAssetType('index')">
                          <Icon name="layers" />
                          所有指数
                        </button>
                      </template>
                    </div>
                  </div>
                  <span v-if="pendingCrossUniverseAction" class="action-status inline warning cross-universe-status">
                    <i></i>
                    {{ crossUniversePendingStatusText }}
                  </span>
                  <textarea v-model="crossForm.universe_symbols" rows="5" @input="cancelCrossUniverseAction"></textarea>
                </label>
                <div class="form-actions span-full">
                  <template v-if="confirmingRunCrossSearch">
                    <button class="btn secondary" type="button" title="取消横截面相似搜索" @click="cancelRunCrossSectionSearch">
                      取消
                    </button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="researchActionDisabled('cross')"
                      :title="researchActionDisabledReason('cross') || crossSearchConfirmText"
                      @click="confirmRunCrossSectionSearch"
                    >
                      确认搜索
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn primary"
                    type="submit"
                    :disabled="researchActionDisabled('cross')"
                    :title="researchActionDisabledReason('cross') || '开始横截面相似搜索前需要确认'"
                  >
                    <Icon name="layers" />
                    {{ runningResearch === 'cross' ? '搜索中' : '开始搜索' }}
                  </button>
                  <button class="btn secondary" type="button" :disabled="resultActionDisabled('cross')" :title="resultActionDisabledReason('cross') || '保存当前横截面搜索结果到本机快照'" @click="saveResearchSnapshot('cross')">
                    <Icon name="save" />
                    保存快照
                  </button>
                  <span v-if="runningResearch === 'cross'" class="action-status inline busy">
                    <i></i>
                    {{ researchBusyStatusText }}
                  </span>
                  <span v-else-if="confirmingRunCrossSearch" class="action-status inline warning">
                    <i></i>
                    {{ crossSearchConfirmText }}
                  </span>
                  <span v-else-if="resultActionDisabledReason('cross')" class="action-status inline warning">
                    <i></i>
                    {{ resultActionDisabledReason('cross') }}
                  </span>
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
              <DataTable :rows="displayCrossRows" :columns="crossColumns" aria-label="横截面匹配结果" empty="暂无横截面匹配结果。" />
            </Panel>
          </section>

          <section
            v-else-if="activeResearchTab === 'etf'"
            :id="researchPanelId('etf')"
            class="view-stack etf-tracker-view"
            role="tabpanel"
            :aria-labelledby="researchTabId('etf')"
          >
            <Panel class="etf-control-surface" title="场内 ETF 跟踪" subtitle="分类行情 / 同类合并">
              <form class="task-form etf-tracker-form" @submit.prevent="requestRunEtfTrackerReview">
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
                  <template v-if="pendingResearchDateShortcut?.target === 'etf'">
                    <button class="date-shortcut" type="button" title="取消 ETF 日期快捷修改" @click="cancelResearchDateShortcut">取消</button>
                    <button class="date-shortcut danger" type="button" :title="researchDateShortcutPendingText" @click="confirmResearchDateShortcut">
                      确认应用
                    </button>
                  </template>
                  <template v-else>
                    <button
                      v-for="shortcut in DATE_RANGE_SHORTCUTS"
                      :key="shortcut.key"
                      type="button"
                      :class="['date-shortcut', { active: isDateShortcutActive(etfTrackerForm, shortcut.key) }]"
                      :aria-pressed="isDateShortcutActive(etfTrackerForm, shortcut.key)"
                      title="应用 ETF 日期快捷前需要确认"
                      @click="requestResearchDateShortcut('etf', shortcut.key)"
                    >
                      {{ shortcut.label }}
                    </button>
                  </template>
                  <span v-if="pendingResearchDateShortcut?.target === 'etf'" class="action-status inline warning research-date-shortcut-status">
                    <i></i>
                    {{ researchDateShortcutPendingText }}
                  </span>
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
                  <div class="etf-cache-actions" :class="{ confirming: confirmingClearEtfCache }">
                    <template v-if="confirmingClearEtfCache">
                      <span class="etf-cache-confirm-text">清理后下次刷新会重新读取 ETF 接口与收益缓存。</span>
                      <button class="mini-action" type="button" title="取消清理 ETF 缓存" @click="cancelClearEtfClientCache">取消</button>
                      <button class="mini-action danger" type="button" title="确认清理浏览器本地 ETF 缓存" @click="confirmClearEtfClientCache">确认清理</button>
                    </template>
                    <button v-else class="mini-action" type="button" title="清理前需要确认" @click="requestClearEtfClientCache">清理ETF缓存</button>
                  </div>
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
                  <template v-if="pendingEtfRefreshAction">
                    <button class="btn secondary" type="button" title="取消刷新 ETF 数据" @click="cancelEtfRefreshAction">
                      取消
                    </button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="pendingEtfRefreshDisabled"
                      :title="pendingEtfRefreshDisabledReason || pendingEtfRefreshConfirmText"
                      @click="confirmEtfRefreshAction"
                    >
                      确认刷新
                    </button>
                  </template>
	                  <template v-else>
                    <button
                        class="btn secondary"
                        type="button"
                        :disabled="etfTrackingRefreshDisabled"
                        :title="etfTrackingRefreshDisabledReason || '刷新 TDX ETF 接口前需要确认'"
                        @click="requestEtfRefreshAction('tracking')"
                      >
	                      <Icon name="refresh" />
	                      {{ loadingEtfTracking ? '读取中' : '刷新TDX ETF接口' }}
	                    </button>
                      <button
                        class="btn secondary"
                        type="button"
                        :disabled="etfReturnsRefreshDisabled"
                        :title="etfReturnsRefreshDisabledReason || '刷新 ETF 收益率前需要确认'"
                        @click="requestEtfRefreshAction('returns')"
                      >
                        <Icon name="refresh" />
                        {{ loadingEtfReturns ? '计算中' : '刷新收益率' }}
                      </button>
                    </template>
                  <template v-if="confirmingRunEtfTrackerReview">
                    <button class="btn secondary" type="button" title="取消生成 ETF 趋势对比" @click="cancelRunEtfTrackerReview">
                      取消
                    </button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="etfTrackerActionDisabled"
                      :title="etfTrackerActionDisabledReason || etfTrackerReviewConfirmText"
                      @click="confirmRunEtfTrackerReview"
                    >
                      确认生成
                    </button>
                  </template>
	                  <button
                    v-else
                    class="btn primary"
                    type="submit"
                    :disabled="etfTrackerActionDisabled"
                    :title="etfTrackerActionDisabledReason || '生成 ETF 趋势对比前需要确认'"
                  >
	                    <Icon name="activity" />
	                    {{ runningResearch === 'etf' ? '生成中' : '生成 ETF 趋势对比' }}
                  </button>
                  <template v-if="confirmingLoadEtfReview">
                    <button class="btn secondary" type="button" title="取消载入多股复盘" @click="cancelLoadEtfTrackerSymbolsToReview">取消</button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="etfLoadReviewDisabled"
                      :title="etfLoadReviewDisabledReason || etfLoadReviewConfirmText"
                      @click="confirmLoadEtfTrackerSymbolsToReview"
                    >
                      确认载入
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn secondary"
                    type="button"
                    :disabled="etfLoadReviewDisabled"
                    :title="etfLoadReviewDisabledReason || '载入多股复盘前需要确认'"
                    @click="requestLoadEtfTrackerSymbolsToReview"
                  >
                    <Icon name="clipboard" />
                    载入多股复盘
                  </button>
                  <span v-if="runningResearch === 'etf'" class="action-status inline busy">
                    <i></i>
                    {{ researchBusyStatusText }}
                  </span>
                  <span v-else-if="pendingEtfRefreshAction" class="action-status inline warning">
                    <i></i>
                    {{ pendingEtfRefreshConfirmText }}
                  </span>
                  <span v-else-if="confirmingRunEtfTrackerReview" class="action-status inline warning">
                    <i></i>
                    {{ etfTrackerReviewConfirmText }}
                  </span>
                  <span v-else-if="confirmingLoadEtfReview" class="action-status inline warning">
                    <i></i>
                    {{ etfLoadReviewConfirmText }}
                  </span>
                  <span v-else-if="etfLoadReviewDisabledReason" class="action-status inline warning">
                    <i></i>
                    {{ etfLoadReviewDisabledReason }}
                  </span>
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
                        :aria-pressed="etfTrackerPagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, etfTrackerPagination.pageSize, 'ETF候选池')"
                        @click="setEtfTrackerPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-label="paginationActionTitle('first', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        :title="paginationActionTitle('first', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        @click="goEtfTrackerPage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-label="paginationActionTitle('prev', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        :title="paginationActionTitle('prev', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        @click="goEtfTrackerPage(etfTrackerPagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ etfTrackerPagination.page }} / {{ etfTrackerTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-label="paginationActionTitle('next', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        :title="paginationActionTitle('next', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        @click="goEtfTrackerPage(etfTrackerPagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', etfTrackerPagination.page, etfTrackerTotalPages)"
                        :aria-label="paginationActionTitle('last', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        :title="paginationActionTitle('last', etfTrackerPagination.page, etfTrackerTotalPages, 'ETF候选池')"
                        @click="goEtfTrackerPage(etfTrackerTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="displayEtfTrackerRows" :columns="etfTrackerColumns" aria-label="ETF候选池" empty="暂无匹配 ETF。" />
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
              <DataTable :rows="etfTrackerReviewRows" :columns="etfTrackerReviewColumns" aria-label="ETF排序明细" empty="生成 ETF 趋势对比后显示排序。" />
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

          <section
            v-else-if="activeResearchTab === 'regime'"
            :id="researchPanelId('regime')"
            class="view-stack market-regime-view"
            role="tabpanel"
            :aria-labelledby="researchTabId('regime')"
          >
            <section class="content-grid two market-regime-grid">
              <Panel title="市场风险偏好" subtitle="Market Regime Research">
                <form class="task-form" @submit.prevent="requestRunMarketRegimeResearch">
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
                    <template v-if="pendingResearchDateShortcut?.target === 'regime'">
                      <button class="date-shortcut" type="button" title="取消市场风偏日期快捷修改" @click="cancelResearchDateShortcut">取消</button>
                      <button class="date-shortcut danger" type="button" :title="researchDateShortcutPendingText" @click="confirmResearchDateShortcut">
                        确认应用
                      </button>
                    </template>
                    <template v-else>
                      <button
                        v-for="shortcut in DATE_RANGE_SHORTCUTS"
                        :key="shortcut.key"
                        type="button"
                        :class="['date-shortcut', { active: isDateShortcutActive(regimeForm, shortcut.key) }]"
                        :aria-pressed="isDateShortcutActive(regimeForm, shortcut.key)"
                        title="应用市场风偏日期快捷前需要确认"
                        @click="requestResearchDateShortcut('regime', shortcut.key)"
                      >
                        {{ shortcut.label }}
                      </button>
                    </template>
                    <span v-if="pendingResearchDateShortcut?.target === 'regime'" class="action-status inline warning research-date-shortcut-status">
                      <i></i>
                      {{ researchDateShortcutPendingText }}
                    </span>
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
                          :class="[
                            'regime-preset-button',
                            { active: regimeActivePresetKey === preset.key, pending: pendingRegimePresetKey === preset.key }
                          ]"
                          :aria-pressed="regimeActivePresetKey === preset.key"
                          :disabled="Boolean(pendingRegimePresetKey)"
                          :title="pendingRegimePresetKey ? '请先确认或取消当前参数预设' : '应用参数预设前需要确认'"
                          @click="requestRegimeParameterPreset(preset.key)"
                        >
                          <span>{{ preset.label }}</span>
                          <em>{{ preset.detail }}</em>
                        </button>
                      </div>
                    </div>
                    <div v-if="pendingRegimePresetKey" class="regime-preset-confirm">
                      <span class="action-status inline warning">
                        <i></i>
                        {{ regimePresetConfirmText }}
                      </span>
                      <button class="mini-action" type="button" title="取消应用风险偏好参数预设" @click="cancelRegimeParameterPreset">
                        取消
                      </button>
                      <button
                        class="mini-action danger"
                        type="button"
                        :disabled="regimePresetConfirmDisabled"
                        :title="regimePresetConfirmDisabledReason || regimePresetConfirmText"
                        @click="confirmRegimeParameterPreset"
                      >
                        确认应用
                      </button>
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
                      <label v-for="item in REGIME_ADVANCED_PARAMETERS" :key="item.key" class="regime-param-item">
                        <span class="regime-param-label">
                          <span>{{ item.label }}</span>
                          <button class="hint-popover-trigger" type="button" :aria-label="`${item.label}说明`">
                            ?
                            <span class="hint-popover" role="tooltip">{{ item.hint }}</span>
                          </button>
                        </span>
                        <div v-if="item.unit === '%'" class="percent-input compact">
                          <input v-model.number="regimeForm[item.key]" type="number" :min="item.min" :max="item.max" :step="item.step" />
                          <b>%</b>
                        </div>
                        <input
                          v-else
                          v-model.number="regimeForm[item.key]"
                          class="compact-number-input"
                          type="number"
                          :min="item.min"
                          :max="item.max"
                          :step="item.step"
                        />
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
                      <template v-if="confirmingClearRegimeManualSymbols">
                        <em>{{ regimeManualSymbolsClearConfirmText }}</em>
                        <button class="mini-action" type="button" title="取消清空手动标的" @click="cancelClearRegimeManualSymbols">取消</button>
                        <button class="mini-action danger" type="button" :title="regimeManualSymbolsClearConfirmText" @click="confirmClearRegimeManualSymbols">确认清空</button>
                      </template>
                      <button
                        v-else
                        class="mini-action"
                        type="button"
                        :disabled="regimeManualSymbolsClearDisabled"
                        :title="regimeManualSymbolsClearDisabledReason || '清空手动补充标的前需要确认'"
                        @click="requestClearRegimeManualSymbols"
                      >
                        清空手动标的
                      </button>
                    </div>
                  </div>
                  <label class="span-full">
                    <span>手动补充标的</span>
                    <textarea v-model="regimeForm.symbols" rows="5" placeholder="可补充行业、ETF、板块或个股代码；留空则只使用所选研究宇宙"></textarea>
                  </label>
                  <div class="form-actions span-full">
                    <template v-if="confirmingRunRegimeResearch">
                      <button class="btn secondary" type="button" title="取消运行市场风险偏好研究" @click="cancelRunMarketRegimeResearch">
                        取消
                      </button>
                      <button
                        class="btn danger"
                        type="button"
                        :disabled="researchActionDisabled('regime')"
                        :title="researchActionDisabledReason('regime') || regimeResearchConfirmText"
                        @click="confirmRunMarketRegimeResearch"
                      >
                        确认运行
                      </button>
                    </template>
                    <button
                      v-else
                      class="btn primary"
                      type="submit"
                      :disabled="researchActionDisabled('regime')"
                      :title="researchActionDisabledReason('regime') || '运行市场风险偏好研究前需要确认'"
                    >
                      <Icon name="activity" />
                      {{ runningResearch === 'regime' ? '研究中' : '运行研究' }}
                    </button>
                    <button class="btn secondary" type="button" :disabled="resultActionDisabled('regime')" :title="resultActionDisabledReason('regime') || '保存当前市场风险偏好结果到本机快照'" @click="saveActiveResearchSnapshot">
                      <Icon name="save" />
                      保存快照
                    </button>
                    <template v-if="confirmingRegimeExport">
                      <button class="btn secondary" type="button" title="取消导出市场风偏 JSON" @click="cancelMarketRegimeJsonExport">
                        取消
                      </button>
                      <button class="btn danger" type="button" :disabled="regimeExportDisabled" :title="regimeExportDisabledReason || regimeExportConfirmText" @click="confirmMarketRegimeJsonExport">
                        <Icon name="download" />
                        确认导出
                      </button>
                    </template>
                    <button v-else class="btn secondary" type="button" :disabled="regimeExportDisabled" :title="regimeExportDisabledReason || '导出当前市场风险偏好研究 JSON 前需要确认'" @click="requestMarketRegimeJsonExport">
                      <Icon name="download" />
                      导出JSON
                    </button>
                    <span v-if="runningResearch === 'regime'" class="action-status inline busy">
                      <i></i>
                      {{ researchBusyStatusText }}
                    </span>
                    <span v-else-if="confirmingRunRegimeResearch" class="action-status inline warning">
                      <i></i>
                      {{ regimeResearchConfirmText }}
                    </span>
                    <span v-else-if="confirmingRegimeExport" class="action-status inline warning">
                      <i></i>
                      {{ regimeExportConfirmText }}
                    </span>
                    <span v-else-if="resultActionDisabledReason('regime')" class="action-status inline warning">
                      <i></i>
                      {{ resultActionDisabledReason('regime') }}
                    </span>
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

            <div class="research-tabs regime-section-tabs" role="tablist" aria-label="市场风险偏好功能页签">
              <button
                v-for="tab in regimeSectionTabs"
                :key="tab.key"
                type="button"
                :class="['research-tab', { active: activeRegimeSectionTab === tab.key }]"
                role="tab"
                :id="regimeSectionTabId(tab.key)"
                :aria-selected="activeRegimeSectionTab === tab.key"
                :aria-controls="regimeSectionPanelId(tab.key)"
                :tabindex="activeRegimeSectionTab === tab.key ? 0 : -1"
                :title="`切换到${tab.label}`"
                @click="activeRegimeSectionTab = tab.key"
                @keydown="handleRegimeSectionTabKeydown($event, tab.key)"
              >
                <Icon :name="tab.icon" />
                {{ tab.label }}
              </button>
            </div>

            <section
              v-if="activeRegimeSectionTab === 'overview'"
              :id="regimeSectionPanelId('overview')"
              class="content-grid two market-regime-result-grid regime-visual-grid"
              role="tabpanel"
              :aria-labelledby="regimeSectionTabId('overview')"
            >
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
                      :aria-label="point.title"
                      :aria-pressed="activeRegimeRaiPoint?.key === point.key"
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

            <section
              v-else-if="activeRegimeSectionTab === 'daily'"
              :id="regimeSectionPanelId('daily')"
              class="view-stack market-regime-tab-panel"
              role="tabpanel"
              :aria-labelledby="regimeSectionTabId('daily')"
            >
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

            <section
              v-else-if="activeRegimeSectionTab === 'flow'"
              :id="regimeSectionPanelId('flow')"
              class="content-grid two market-regime-result-grid"
              role="tabpanel"
              :aria-labelledby="regimeSectionTabId('flow')"
            >
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
                        :aria-pressed="regimeMarketScopePagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, regimeMarketScopePagination.pageSize, '市场缩圈')"
                        @click="setRegimeMarketScopePageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-label="paginationActionTitle('first', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        :title="paginationActionTitle('first', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        @click="goRegimeMarketScopePage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-label="paginationActionTitle('prev', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        :title="paginationActionTitle('prev', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        @click="goRegimeMarketScopePage(regimeMarketScopePagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ regimeMarketScopePagination.page }} / {{ regimeMarketScopeTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-label="paginationActionTitle('next', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        :title="paginationActionTitle('next', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        @click="goRegimeMarketScopePage(regimeMarketScopePagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', regimeMarketScopePagination.page, regimeMarketScopeTotalPages)"
                        :aria-label="paginationActionTitle('last', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        :title="paginationActionTitle('last', regimeMarketScopePagination.page, regimeMarketScopeTotalPages, '市场缩圈')"
                        @click="goRegimeMarketScopePage(regimeMarketScopeTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedRegimeMarketScopeRows" :columns="regimeMarketScopeColumns" aria-label="市场缩圈" empty="运行研究后显示最近市场扩散与缩圈过程。" />
              </Panel>
            </section>

            <section
              v-else-if="activeRegimeSectionTab === 'asset'"
              :id="regimeSectionPanelId('asset')"
              class="view-stack market-regime-tab-panel"
              role="tabpanel"
              :aria-labelledby="regimeSectionTabId('asset')"
            >
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
                        :aria-pressed="regimeFlowCandidatePagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, regimeFlowCandidatePagination.pageSize, '资金回流候选')"
                        @click="setRegimeFlowCandidatePageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-label="paginationActionTitle('first', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        :title="paginationActionTitle('first', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        @click="goRegimeFlowCandidatePage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-label="paginationActionTitle('prev', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        :title="paginationActionTitle('prev', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        @click="goRegimeFlowCandidatePage(regimeFlowCandidatePagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ regimeFlowCandidatePagination.page }} / {{ regimeFlowCandidateTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-label="paginationActionTitle('next', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        :title="paginationActionTitle('next', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        @click="goRegimeFlowCandidatePage(regimeFlowCandidatePagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages)"
                        :aria-label="paginationActionTitle('last', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        :title="paginationActionTitle('last', regimeFlowCandidatePagination.page, regimeFlowCandidateTotalPages, '资金回流候选')"
                        @click="goRegimeFlowCandidatePage(regimeFlowCandidateTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedRegimeFlowCandidateRows" :columns="regimeFlowCandidateColumns" aria-label="资金回流候选" empty="运行研究后显示资产级资金回流候选。" />
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

            <section
              v-else-if="activeRegimeSectionTab === 'factor'"
              :id="regimeSectionPanelId('factor')"
              class="content-grid two market-regime-result-grid"
              role="tabpanel"
              :aria-labelledby="regimeSectionTabId('factor')"
            >
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

          <section
            v-else
            :id="researchPanelId('review')"
            class="content-grid two research-review-grid"
            role="tabpanel"
            :aria-labelledby="researchTabId('review')"
          >
            <Panel title="多股复盘" subtitle="排序锐评">
              <form class="task-form" @submit.prevent="requestRunReviewSearch">
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
                  <template v-if="pendingResearchDateShortcut?.target === 'review'">
                    <button class="date-shortcut" type="button" title="取消复盘日期快捷修改" @click="cancelResearchDateShortcut">取消</button>
                    <button class="date-shortcut danger" type="button" :title="researchDateShortcutPendingText" @click="confirmResearchDateShortcut">
                      确认应用
                    </button>
                  </template>
                  <template v-else>
                    <button
                      v-for="shortcut in DATE_RANGE_SHORTCUTS"
                      :key="shortcut.key"
                      type="button"
                      :class="['date-shortcut', { active: isDateShortcutActive(reviewForm, shortcut.key) }]"
                      :aria-pressed="isDateShortcutActive(reviewForm, shortcut.key)"
                      title="应用复盘日期快捷前需要确认"
                      @click="requestResearchDateShortcut('review', shortcut.key)"
                    >
                      {{ shortcut.label }}
                    </button>
                  </template>
                  <span v-if="pendingResearchDateShortcut?.target === 'review'" class="action-status inline warning research-date-shortcut-status">
                    <i></i>
                    {{ researchDateShortcutPendingText }}
                  </span>
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
                  <template v-if="confirmingRunReviewSearch">
                    <button class="btn secondary" type="button" title="取消生成多股复盘" @click="cancelRunReviewSearch">
                      取消
                    </button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="researchActionDisabled('review')"
                      :title="researchActionDisabledReason('review') || reviewSearchConfirmText"
                      @click="confirmRunReviewSearch"
                    >
                      确认生成
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn primary"
                    type="submit"
                    :disabled="researchActionDisabled('review')"
                    :title="researchActionDisabledReason('review') || '生成多股复盘前需要确认'"
                  >
                    <Icon name="clipboard" />
                    {{ runningResearch === 'review' ? '生成中' : '生成复盘' }}
                  </button>
                  <button class="btn secondary" type="button" :disabled="resultActionDisabled('review')" :title="resultActionDisabledReason('review') || '保存当前多股复盘结果到本机快照'" @click="saveResearchSnapshot('review')">
                    <Icon name="save" />
                    保存快照
                  </button>
                  <span v-if="runningResearch === 'review'" class="action-status inline busy">
                    <i></i>
                    {{ researchBusyStatusText }}
                  </span>
                  <span v-else-if="confirmingRunReviewSearch" class="action-status inline warning">
                    <i></i>
                    {{ reviewSearchConfirmText }}
                  </span>
                  <span v-else-if="resultActionDisabledReason('review')" class="action-status inline warning">
                    <i></i>
                    {{ resultActionDisabledReason('review') }}
                  </span>
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
                <DataTable :rows="displayReviewRows" :columns="reviewColumns" aria-label="复盘排序" empty="暂无复盘排序。" />
              </Panel>
              <Panel title="对标比较" subtitle="指数关系">
                <DataTable :rows="displayComparisonRows" :columns="comparisonColumns" aria-label="对标比较" empty="暂无对标比较。" />
              </Panel>
              <Panel title="关键波段" subtitle="首位标的">
                <DataTable :rows="displaySegmentRows" :columns="segmentColumns" aria-label="关键波段" empty="暂无关键波段。" />
              </Panel>
              <Panel title="复盘与锐评" subtitle="结构化输出">
                <div class="panel-actions">
                  <template v-if="confirmingRunAiReview">
                    <button class="btn secondary" type="button" title="取消 AI 覆盖" @click="cancelRunAiReview">取消</button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="reviewAiActionDisabled"
                      :title="reviewAiActionDisabledReason || reviewAiConfirmText"
                      @click="confirmRunAiReview"
                    >
                      确认覆盖
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn secondary"
                    type="button"
                    :disabled="reviewAiActionDisabled"
                    :title="reviewAiActionDisabledReason || 'AI 覆盖复盘前需要确认'"
                    @click="requestRunAiReview"
                  >
                    <Icon name="activity" />
                    {{ runningAiReview ? '生成中' : aiConfigReady ? 'AI覆盖' : '本地规则' }}
                  </button>
                  <span class="action-status inline" :class="{ busy: runningAiReview, warning: Boolean((reviewAiActionDisabledReason && !runningAiReview) || confirmingRunAiReview) }">
                    <i></i>
                    {{ reviewAiActionStatusText }}
                  </span>
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
                          <table aria-label="多股复盘结构化表格">
                            <caption class="sr-only">多股复盘结构化表格</caption>
                            <thead>
                              <tr>
                                <th v-for="head in block.headers" :key="head" scope="col">{{ head }}</th>
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
                      <template v-else-if="block.type === 'code'">
                        <pre class="review-markdown-code"><code>{{ block.lines.join('\n') }}</code></pre>
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
            <div class="panel-actions task-clear-actions" :class="{ confirming: confirmingClearTasks }">
              <template v-if="confirmingClearTasks">
                <span class="action-status inline warning">
                  <i></i>
                  {{ clearTasksConfirmStatusText }}
                </span>
                <button
                  class="btn secondary"
                  type="button"
                  :disabled="clearTasksCancelDisabled"
                  :title="clearTasksCancelDisabledReason || '取消清空任务历史'"
                  @click="cancelClearTaskHistory"
                >
                  取消
                </button>
                <button
                  class="btn danger"
                  type="button"
                  :disabled="clearTasksConfirmDisabled"
                  :title="clearTasksConfirmDisabledReason || clearTasksConfirmTitle"
                  @click="confirmClearTaskHistory"
                >
                  <Icon name="trash" />
                  {{ clearingTasks ? '清理中' : '确认清空' }}
                </button>
              </template>
              <button
                v-else
                class="btn secondary"
                type="button"
                :disabled="clearTasksDisabled"
                :title="clearTasksDisabledReason || '清空当前后台任务历史记录'"
                @click="requestClearTaskHistory"
              >
                <Icon name="trash" />
                清空历史
              </button>
            </div>
            <div v-if="tasks.length" class="task-list">
              <article
                v-for="task in tasks"
                :key="task.id"
                :class="['task-item', { active: selectedTaskId === task.id }]"
              >
                <button
                  class="task-item-main"
                  type="button"
                  :aria-pressed="selectedTaskId === task.id"
                  :title="selectedTaskId === task.id ? '当前任务' : '查看任务详情'"
                  @click="selectTask(task.id)"
                >
                  <strong>{{ taskStatusLabel(task.status) }}</strong>
                  <span>{{ task.id.slice(0, 12) }}</span>
                  <em>{{ task.finished_at || task.started_at || task.created_at }}</em>
                </button>
                <div v-if="taskHasControls(task)" class="task-control-actions" aria-label="任务控制">
                  <button
                    class="mini-action"
                    type="button"
                    :disabled="!taskCanPause(task) || taskControlBusy(task)"
                    :title="taskPauseTitle(task)"
                    @click="controlTask(task, 'pause')"
                  >
                    暂停
                  </button>
                  <button
                    class="mini-action"
                    type="button"
                    :disabled="!taskCanResume(task) || taskControlBusy(task)"
                    :title="taskResumeTitle(task)"
                    @click="controlTask(task, 'resume')"
                  >
                    继续
                  </button>
                  <button
                    class="mini-action danger"
                    type="button"
                    :disabled="!taskCanCancel(task) || taskControlBusy(task)"
                    :title="taskCancelTitle(task)"
                    @click="controlTask(task, 'cancel')"
                  >
                    终止
                  </button>
                </div>
              </article>
            </div>
            <EmptyState v-else title="暂无任务" body="执行下载后任务会出现在这里。" />
          </Panel>

          <Panel title="过程记录" subtitle="事件流">
            <div v-if="selectedTask" class="task-detail-stack">
              <section class="event-window">
                <div class="task-section-head">
                  <strong>当前进度</strong>
                  <span>{{ selectedTaskControlText }} · 主动汇报 {{ visibleTaskEvents.length }} / {{ selectedTaskEvents.length }} 条</span>
                </div>
                <div v-if="selectedTaskProgress" class="task-progress-card" :aria-label="selectedTaskProgress.ariaLabel">
                  <div class="task-progress-card-head">
                    <strong>{{ selectedTaskProgress.title }}</strong>
                    <span>{{ selectedTaskProgress.percentText }}</span>
                  </div>
                  <div class="task-progress-track" aria-hidden="true">
                    <span :style="{ width: selectedTaskProgress.barWidth }"></span>
                  </div>
                  <div class="task-progress-meta">
                    <span>{{ selectedTaskProgress.detail }}</span>
                    <em>{{ selectedTaskProgress.time }}</em>
                  </div>
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
                        :aria-pressed="taskQualityIssuePagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, taskQualityIssuePagination.pageSize, '质量门禁明细')"
                        @click="setTaskQualityIssuePageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-label="paginationActionTitle('first', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        :title="paginationActionTitle('first', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        @click="goTaskQualityIssuePage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-label="paginationActionTitle('prev', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        :title="paginationActionTitle('prev', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        @click="goTaskQualityIssuePage(taskQualityIssuePagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ taskQualityIssuePagination.page }} / {{ taskQualityIssueTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-label="paginationActionTitle('next', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        :title="paginationActionTitle('next', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        @click="goTaskQualityIssuePage(taskQualityIssuePagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', taskQualityIssuePagination.page, taskQualityIssueTotalPages)"
                        :aria-label="paginationActionTitle('last', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        :title="paginationActionTitle('last', taskQualityIssuePagination.page, taskQualityIssueTotalPages, '质量门禁明细')"
                        @click="goTaskQualityIssuePage(taskQualityIssueTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedTaskQualityIssueRows" :columns="taskQualityIssueColumns" aria-label="质量门禁明细" empty="暂无质量门禁明细。" />
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
                        :aria-pressed="taskEventPagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, taskEventPagination.pageSize, '任务事件')"
                        @click="setTaskEventPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', taskEventPagination.page, taskEventTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', taskEventPagination.page, taskEventTotalPages)"
                        :aria-label="paginationActionTitle('first', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        :title="paginationActionTitle('first', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        @click="goTaskEventPage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', taskEventPagination.page, taskEventTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', taskEventPagination.page, taskEventTotalPages)"
                        :aria-label="paginationActionTitle('prev', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        :title="paginationActionTitle('prev', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        @click="goTaskEventPage(taskEventPagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ taskEventPagination.page }} / {{ taskEventTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', taskEventPagination.page, taskEventTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', taskEventPagination.page, taskEventTotalPages)"
                        :aria-label="paginationActionTitle('next', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        :title="paginationActionTitle('next', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        @click="goTaskEventPage(taskEventPagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', taskEventPagination.page, taskEventTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', taskEventPagination.page, taskEventTotalPages)"
                        :aria-label="paginationActionTitle('last', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        :title="paginationActionTitle('last', taskEventPagination.page, taskEventTotalPages, '任务事件')"
                        @click="goTaskEventPage(taskEventTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="pagedTaskEventRows" :columns="taskEventColumns" aria-label="任务事件记录" empty="暂无事件记录。" />
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
                        :aria-pressed="taskResultPagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, taskResultPagination.pageSize, '写入结果')"
                        @click="setTaskResultPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', taskResultPagination.page, taskResultTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', taskResultPagination.page, taskResultTotalPages)"
                        :aria-label="paginationActionTitle('first', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        :title="paginationActionTitle('first', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        @click="goTaskResultPage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', taskResultPagination.page, taskResultTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', taskResultPagination.page, taskResultTotalPages)"
                        :aria-label="paginationActionTitle('prev', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        :title="paginationActionTitle('prev', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        @click="goTaskResultPage(taskResultPagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ taskResultPagination.page }} / {{ taskResultTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', taskResultPagination.page, taskResultTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', taskResultPagination.page, taskResultTotalPages)"
                        :aria-label="paginationActionTitle('next', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        :title="paginationActionTitle('next', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        @click="goTaskResultPage(taskResultPagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', taskResultPagination.page, taskResultTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', taskResultPagination.page, taskResultTotalPages)"
                        :aria-label="paginationActionTitle('last', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        :title="paginationActionTitle('last', taskResultPagination.page, taskResultTotalPages, '写入结果')"
                        @click="goTaskResultPage(taskResultTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>
                <DataTable :rows="displayResultRows" :columns="resultColumns" aria-label="任务写入结果" empty="暂无写入结果。" />
              </section>
            </div>
            <EmptyState v-else title="未选择任务" body="左侧选择任务查看事件和结果。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'ai'" class="ai-workbench-view">
          <div class="ai-chat-layout">
            <aside class="ai-side-panel">
              <section class="ai-side-card">
                <header>
                  <span>数据参数</span>
                  <strong>{{ aiWorkbenchDataSummary }}</strong>
                </header>
                <div class="ai-side-grid">
                  <label>
                    <span>开始</span>
                    <input v-model="aiWorkbenchForm.start" type="date" />
                  </label>
                  <label>
                    <span>结束</span>
                    <input v-model="aiWorkbenchForm.end" type="date" />
                  </label>
                  <label class="ai-side-period span-full">
                    <span>周期</span>
                    <div class="ai-period-options" role="group" aria-label="AI 分析周期">
                      <button
                        v-for="timeframe in config?.timeframes || ['1d']"
                        :key="timeframe"
                        type="button"
                        :class="['ai-period-option', { active: aiWorkbenchForm.timeframe === timeframe }]"
                        @click="aiWorkbenchForm.timeframe = timeframe"
                      >
                        {{ timeframe }}
                      </button>
                    </div>
                  </label>
                  <label>
                    <span>K线图</span>
                    <input v-model.number="aiWorkbenchForm.max_charts" type="number" min="0" max="12" />
                  </label>
                </div>
              </section>

              <section class="ai-side-card">
                <header>
                  <span>Skill 侧载</span>
                  <strong>{{ aiWorkbenchForm.skill_prompt.trim() ? '已载入' : '未载入' }}</strong>
                </header>
                <div class="ai-side-actions">
                  <label class="mini-action skill-file-action">
                    <Icon name="folder" />
                    导入
                    <input type="file" accept=".md,.txt,text/markdown,text/plain" @change="importAiSkillPrompt" />
                  </label>
                  <template v-if="confirmingClearAiSkillPrompt">
                    <button class="mini-action" type="button" title="取消清空 Skill 提示词" @click="cancelClearAiSkillPrompt">取消</button>
                    <button class="mini-action danger" type="button" :title="aiSkillPromptClearConfirmTitle" @click="confirmClearAiSkillPrompt">确认清空</button>
                  </template>
                  <button
                    v-else
                    class="mini-action"
                    type="button"
                    :disabled="aiSkillPromptClearDisabled"
                    :title="aiSkillPromptClearDisabledReason || '清空 Skill 提示词前需要确认'"
                    @click="requestClearAiSkillPrompt"
                  >
                    清空
                  </button>
                </div>
                <p v-if="confirmingClearAiSkillPrompt" class="ai-side-warning">{{ aiSkillPromptClearConfirmText }}</p>
                <textarea
                  v-model="aiWorkbenchForm.skill_prompt"
                  rows="7"
                  aria-label="Skill 侧载提示词"
                  placeholder="粘贴或导入你的 skill、研究框架、输出约束。"
                ></textarea>
              </section>

            </aside>

            <section class="ai-chat-panel">
              <div class="ai-workbench-tabs" role="tablist" aria-label="AI 工作台页签">
                <button
                  v-for="tab in aiWorkbenchTabs"
                  :key="tab.key"
                  type="button"
                  :class="{ active: activeAiWorkbenchTab === tab.key }"
                  role="tab"
                  :id="aiWorkbenchTabId(tab.key)"
                  :aria-selected="activeAiWorkbenchTab === tab.key"
                  :aria-controls="aiWorkbenchPanelId(tab.key)"
                  :tabindex="activeAiWorkbenchTab === tab.key ? 0 : -1"
                  @click="activeAiWorkbenchTab = tab.key"
                  @keydown="handleAiWorkbenchTabKeydown($event, tab.key)"
                >
                  {{ tab.label }}
                </button>
              </div>

              <div
                v-if="activeAiWorkbenchTab === 'chat'"
                :id="aiWorkbenchPanelId('chat')"
                class="ai-chat-mode"
                role="tabpanel"
                :aria-labelledby="aiWorkbenchTabId('chat')"
              >
              <div class="ai-chat-context">
                <span>{{ aiWorkbenchContextSummary }}</span>
                <div class="ai-chat-context-meta">
                  <strong :class="['ai-run-state', aiWorkbenchStreamStatus, { active: runningAiWorkbench }]">
                    <i></i>
                    {{ aiWorkbenchStatusLabel }}
                  </strong>
                  <em>{{ aiConfigReady ? `模型 ${aiSettings.model}` : '请先在设置页配置模型' }}</em>
                </div>
              </div>

              <div class="ai-chat-thread">
                <article class="ai-chat-message user">
                  <span>用户目标</span>
                  <p>{{ aiWorkbenchForm.prompt || '在底部输入你的分析目标。' }}</p>
                </article>
                <article v-if="aiWorkbenchResultVisible" class="ai-chat-message assistant">
                  <span>AI 输出</span>
                  <div class="ai-workbench-output">
                    <section class="review-markdown-card ai-markdown-card">
                      <article
                        v-for="(block, index) in aiWorkbenchMarkdownBlocks"
                        :key="index"
                        :class="['review-markdown-block', block.type]"
                      >
                        <template v-if="block.type === 'table'">
                          <div class="review-markdown-table">
                            <table aria-label="AI 输出结构化表格">
                              <caption class="sr-only">AI 输出结构化表格</caption>
                              <thead>
                                <tr>
                                  <th v-for="head in block.headers" :key="head" scope="col">{{ head }}</th>
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
                        <template v-else-if="block.type === 'code'">
                          <pre class="review-markdown-code"><code>{{ block.lines.join('\n') }}</code></pre>
                        </template>
                        <template v-else>
                          <h4 v-if="block.title">{{ block.title }}</h4>
                          <p v-for="(line, lineIndex) in block.lines" :key="lineIndex">{{ line }}</p>
                        </template>
                      </article>
                      <em>{{ aiWorkbenchResult?.disclaimer || '仅用于本地行情研究，不构成投资建议。' }}</em>
                    </section>
                    <div v-if="aiWorkbenchChartItems.length" class="research-kline-section ai-kline-section">
                      <div class="review-section-head">
                        <span>AI K线图</span>
                        <strong>{{ aiWorkbenchChartSummary }}</strong>
                      </div>
                      <div class="review-kline-grid">
                        <KlineChart v-for="item in aiWorkbenchChartItems" :key="`ai-${item.symbol}`" :item="item" />
                      </div>
                    </div>
                    <DataTable :rows="aiWorkbenchLatestRows" :columns="aiWorkbenchLatestColumns" aria-label="AI最新指标" empty="暂无最新指标。" />
                    <DataTable :rows="aiWorkbenchRecordRows" :columns="aiWorkbenchRecordColumns" aria-label="AI行情上下文" empty="暂无行情上下文。" />
                  </div>
                </article>
                <EmptyState v-else title="等待对话" body="选择数据、标的与 Skill，在底部输入任务后调用模型。" />
              </div>

              <form class="ai-chat-composer" @submit.prevent="requestRunAiWorkbench">
                <div class="ai-composer-input">
                  <span>任务</span>
                  <textarea
                    v-model="aiWorkbenchForm.prompt"
                    rows="3"
                    aria-label="AI 工作台任务内容"
                    placeholder="输入分析目标，例如：判断这批股票强弱、风险点和下一步观察项。"
                    @input="confirmingRunAiWorkbench = false"
                  ></textarea>
                </div>
                <div class="ai-composer-actions">
                  <template v-if="confirmingLoadAiWorkbenchSymbols">
                    <button class="btn secondary" type="button" title="取消载入标的" @click="cancelLoadAiWorkbenchSymbols">取消</button>
                    <button class="btn danger" type="button" :title="aiWorkbenchLoadSymbolsConfirmText" @click="confirmLoadAiWorkbenchSymbols">确认载入</button>
                  </template>
                  <template v-else-if="confirmingRunAiWorkbench">
                    <button class="btn secondary" type="button" title="取消发送 AI 任务" @click="cancelRunAiWorkbench">取消</button>
                    <button
                      class="btn danger"
                      type="button"
                      :disabled="aiWorkbenchRunDisabled"
                      :title="aiWorkbenchRunDisabledReason || aiWorkbenchRunConfirmText"
                      @click="confirmRunAiWorkbench"
                    >
                      确认发送
                    </button>
                  </template>
                  <button
                    v-else
                    class="btn secondary"
                    type="button"
                    :disabled="aiWorkbenchLoadSymbolsDisabled"
                    :title="aiWorkbenchLoadSymbolsDisabledReason || '载入标的前需要确认'"
                    @click="requestLoadAiWorkbenchSymbols"
                  >
                    载入标的
                  </button>
                  <button
                    v-if="!confirmingRunAiWorkbench"
                    class="btn primary"
                    type="submit"
                    :disabled="aiWorkbenchRunDisabled"
                    :title="aiWorkbenchRunDisabledReason || '发送 AI 任务前需要确认'"
                  >
                    <Icon name="sparkles" />
                    {{ runningAiWorkbench ? '运行中' : '发送' }}
                  </button>
                </div>
                <div class="ai-composer-status" :class="{ busy: runningAiWorkbench, warning: Boolean((aiWorkbenchRunDisabledReason && !runningAiWorkbench) || confirmingLoadAiWorkbenchSymbols || confirmingRunAiWorkbench) }">
                  <i></i>
                  <span>{{ confirmingLoadAiWorkbenchSymbols ? aiWorkbenchLoadSymbolsConfirmText : confirmingRunAiWorkbench ? aiWorkbenchRunConfirmText : aiWorkbenchRunStatusText }}</span>
                </div>
              </form>
              </div>

              <div
                v-else
                :id="aiWorkbenchPanelId('symbols')"
                class="ai-symbol-workspace"
                role="tabpanel"
                :aria-labelledby="aiWorkbenchTabId('symbols')"
              >
                <header class="ai-symbol-workspace-head">
                  <div>
                    <span>标的池</span>
                    <strong>
                      {{ aiCurrentSymbolGroup?.name || '-' }} ·
                      {{ formatInt(aiFilteredSymbolRows.length) }} / {{ formatInt(aiCurrentSymbolRows.length) }}
                    </strong>
                  </div>
                  <button
                    class="mini-action"
                    type="button"
                    :disabled="aiSymbolMetricsDisabled"
                    :title="aiSymbolMetricsDisabledReason || '刷新当前标的池指标前需要确认'"
                    @click="requestAiSymbolRunAction('metrics')"
                  >
                    <Icon name="refresh" />
                    {{ loadingAiSymbolMetrics ? '刷新中' : '刷新指标' }}
                  </button>
                </header>

                <div class="ai-symbol-filter-bar">
                  <label>
                    <span>分组</span>
                    <select
                      v-model="aiSymbolGroupName"
                      :disabled="Boolean(aiSymbolControlsDisabledReason)"
                      :title="aiSymbolControlsDisabledReason || '切换标的分组'"
                      aria-describedby="ai-symbol-status"
                    >
                      <option v-for="group in aiSymbolGroups" :key="group.name" :value="group.name">
                        {{ group.name }} · {{ group.symbols.length }}只
                      </option>
                    </select>
                  </label>
                  <label>
                    <span>搜索</span>
                    <input
                      v-model="aiSymbolKeyword"
                      type="search"
                      placeholder="代码、名称、类型"
                      :disabled="Boolean(aiSymbolControlsDisabledReason)"
                      :title="aiSymbolControlsDisabledReason || '按代码、名称或类型筛选当前分组'"
                      aria-describedby="ai-symbol-status"
                    />
                  </label>
                  <label class="ai-symbol-topn-field">
                    <span>前 N</span>
                    <input
                      v-model.number="aiSymbolTopN"
                      type="number"
                      min="1"
                      step="1"
                      :disabled="Boolean(aiSymbolControlsDisabledReason)"
                      :title="aiSymbolControlsDisabledReason || '设置按当前排序选中的数量'"
                      aria-describedby="ai-symbol-status"
                    />
                  </label>
                  <button class="mini-action" type="button" :disabled="aiSymbolTopNDisabled" :title="aiSymbolTopNDisabledReason || aiSymbolTopNActionTitle" @click="requestAiSymbolAction('topN')">
                    选中前 N
                  </button>
                </div>

                <div class="ai-natural-filter">
                  <input
                    v-model="aiSymbolNaturalQuery"
                    type="text"
                    aria-label="AI 标的自然语言筛选条件"
                    placeholder="例如：选择创业板里成交额最高的股票"
                    :disabled="Boolean(aiSymbolControlsDisabledReason)"
                    :title="aiSymbolControlsDisabledReason || '输入自然语言筛选条件'"
                    aria-describedby="ai-symbol-status"
                  />
                  <button
                    class="mini-action"
                    type="button"
                    :disabled="aiSymbolFilterDisabled"
                    :title="aiSymbolFilterDisabledReason || '执行 AI 筛选前需要确认'"
                    @click="requestAiSymbolRunAction('filter')"
                  >
                    <Icon name="sparkles" />
                    {{ runningAiSymbolFilter ? '筛选中' : 'AI 筛选' }}
                  </button>
                </div>

                <div class="ai-symbol-actions">
                  <template v-if="pendingAiSymbolRunAction">
                    <button class="mini-action" type="button" title="取消当前 AI 标的运行操作" @click="cancelAiSymbolRunAction">取消</button>
                    <button
                      class="mini-action danger"
                      type="button"
                      :disabled="aiSymbolRunPendingDisabled"
                      :title="aiSymbolRunPendingDisabledReason || aiSymbolRunPendingText"
                      @click="confirmAiSymbolRunAction"
                    >
                      确认{{ aiSymbolRunPendingActionLabel }}
                    </button>
                  </template>
                  <template v-else-if="pendingAiSymbolAction">
                    <button class="mini-action" type="button" title="取消当前 AI 标的操作" @click="cancelAiSymbolAction">取消</button>
                    <button
                      class="mini-action danger"
                      type="button"
                      :disabled="aiSymbolPendingActionDisabled"
                      :title="aiSymbolPendingActionDisabledReason || aiSymbolPendingActionText"
                      @click="confirmAiSymbolAction"
                    >
                      确认{{ aiSymbolPendingActionLabel }}
                    </button>
                  </template>
                  <button
                    v-else
                    class="mini-action"
                    type="button"
                    :disabled="aiSymbolReplaceGroupDisabled"
                    :title="aiSymbolReplaceGroupDisabledReason || '替换本类前需要确认'"
                    @click="requestAiSymbolAction('replaceGroup')"
                  >
                    替换本类
                  </button>
                  <button
                    v-if="!pendingAiSymbolAction && !pendingAiSymbolRunAction"
                    class="mini-action"
                    type="button"
                    :disabled="aiSymbolAppendFilteredDisabled"
                    :title="aiSymbolAppendFilteredDisabledReason || '追加当前筛选前需要确认'"
                    @click="requestAiSymbolAction('appendFiltered')"
                  >
                    追加当前筛选
                  </button>
                  <button
                    v-if="!pendingAiSymbolAction && !pendingAiSymbolRunAction"
                    class="mini-action"
                    type="button"
                    :disabled="aiSymbolAppendPageDisabled"
                    :title="aiSymbolAppendPageDisabledReason || '追加本页前需要确认'"
                    @click="requestAiSymbolAction('appendPage')"
                  >
                    追加本页
                  </button>
                  <template v-if="confirmingClearAiSymbols && !pendingAiSymbolAction && !pendingAiSymbolRunAction">
                    <button class="mini-action" type="button" title="取消清空 AI 工作台标的" @click="cancelClearAiSelectedSymbols">
                      取消
                    </button>
                    <button
                      class="mini-action danger"
                      type="button"
                      :disabled="aiSymbolClearDisabled"
                      :title="aiSymbolClearDisabledReason || aiSymbolClearConfirmTitle"
                      @click="confirmClearAiSelectedSymbols"
                    >
                      确认清空
                    </button>
                  </template>
                  <button
                    v-else-if="!pendingAiSymbolAction && !pendingAiSymbolRunAction"
                    class="mini-action"
                    type="button"
                    :disabled="aiSymbolClearDisabled"
                    :title="aiSymbolClearDisabledReason || '清空 AI 工作台已选标的前需要确认'"
                    @click="requestClearAiSelectedSymbols"
                  >
                    清空
                  </button>
                </div>

                <div
                  id="ai-symbol-status"
                  class="ai-symbol-status"
                  role="status"
                  aria-live="polite"
                  :class="{ busy: aiSymbolActionBusy, warning: Boolean(aiSymbolActionWarning) || Boolean(aiSymbolControlsDisabledReason) }"
                >
                  <i></i>
                  <span>{{ pendingAiSymbolRunAction ? aiSymbolRunPendingText : pendingAiSymbolAction ? aiSymbolPendingActionText : confirmingClearAiSymbols ? aiSymbolClearConfirmStatusText : aiSymbolActionStatusText }}</span>
                </div>

                <div class="ai-symbol-table-toolbar">
                  <span>
                    显示 {{ aiSymbolPageFirst }}-{{ aiSymbolPageEnd }} / {{ formatInt(aiSortedSymbolRows.length) }} ·
                    已选 {{ formatInt(aiSelectedSymbols.length) }}
                  </span>
                  <em class="ai-symbol-unit-note">成交额源字段为万元，表内自动换算为万/亿显示。</em>
                  <div class="table-controls">
                    <div class="page-size-group" aria-label="标的池每页条数">
                      <span>每页</span>
                      <button
                        v-for="size in aiSymbolPageSizeOptions"
                        :key="size"
                        type="button"
                        :class="['page-size-button', { active: aiSymbolPagination.pageSize === size }]"
                        :aria-pressed="aiSymbolPagination.pageSize === size"
                        :title="pageSizeButtonTitle(size, aiSymbolPagination.pageSize, 'AI标的池')"
                        @click="setAiSymbolPageSize(size)"
                      >
                        {{ size }}
                      </button>
                    </div>
                    <div class="pagination-controls">
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('first', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-disabled="paginationActionDisabled('first', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-label="paginationActionTitle('first', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        :title="paginationActionTitle('first', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        @click="goAiSymbolPage(1)"
                      >
                        首页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('prev', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-disabled="paginationActionDisabled('prev', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-label="paginationActionTitle('prev', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        :title="paginationActionTitle('prev', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        @click="goAiSymbolPage(aiSymbolPagination.page - 1)"
                      >
                        上一页
                      </button>
                      <span class="pagination-status" aria-live="polite">{{ aiSymbolPagination.page }} / {{ aiSymbolTotalPages }}</span>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('next', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-disabled="paginationActionDisabled('next', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-label="paginationActionTitle('next', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        :title="paginationActionTitle('next', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        @click="goAiSymbolPage(aiSymbolPagination.page + 1)"
                      >
                        下一页
                      </button>
                      <button
                        type="button"
                        :disabled="paginationActionDisabled('last', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-disabled="paginationActionDisabled('last', aiSymbolPagination.page, aiSymbolTotalPages)"
                        :aria-label="paginationActionTitle('last', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        :title="paginationActionTitle('last', aiSymbolPagination.page, aiSymbolTotalPages, 'AI标的池')"
                        @click="goAiSymbolPage(aiSymbolTotalPages)"
                      >
                        末页
                      </button>
                    </div>
                  </div>
                </div>

                <div v-if="aiSortedSymbolRows.length" class="ai-symbol-table-scroll">
                  <table class="ai-symbol-table" aria-label="AI标的池">
                    <caption class="sr-only">AI标的池</caption>
                    <thead>
                      <tr>
                        <th v-for="column in aiSymbolTableColumns" :key="column.key" :aria-sort="aiSymbolAriaSort(column.key)" scope="col">
                          <button
                            type="button"
                            :aria-label="aiSymbolSortAriaLabel(column)"
                            :title="aiSymbolSortAriaLabel(column)"
                            @click="toggleAiSymbolSort(column.key)"
                          >
                            <span>{{ column.label }}</span>
                            <em v-if="aiSymbolSortIndicator(column.key)" aria-hidden="true">{{ aiSymbolSortIndicator(column.key) }}</em>
                          </button>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in aiPagedSymbolRows" :key="row.symbol" :class="{ selected: row.selected }">
                        <td>
                          <input
                            type="checkbox"
                            :checked="row.selected"
                            :aria-label="aiSymbolSelectionLabel(row)"
                            @change="toggleAiSymbol(row.symbol)"
                          />
                        </td>
                        <td><strong>{{ row.symbol }}</strong></td>
                        <td>{{ row.name || '-' }}</td>
                        <td>{{ row.assetLabel }}</td>
                        <td>{{ row.latestDate || '-' }}</td>
                        <td>{{ formatDecimalValue(row.close, 2) }}</td>
                        <td>{{ formatAmountValue(row.amount) }}</td>
                        <td>{{ formatLargeNumberValue(row.volume) }}</td>
                        <td>{{ formatLargeNumberValue(row.marketValue) }}</td>
                        <td>{{ formatPercentValue(row.turnoverRate) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <EmptyState v-else title="暂无标的" body="切换分组或搜索条件后显示。" />

                <label class="ai-selected-symbols ai-symbol-selected-editor">
                  <span>已选代码</span>
                  <textarea v-model="aiWorkbenchForm.symbols" rows="4" placeholder="从标的池选择，或手动输入代码。"></textarea>
                </label>
              </div>
            </section>
          </div>
        </section>

        <section v-else-if="activeView === 'settings'" class="content-grid two">
          <Panel title="系统设置" subtitle="本地配置">
            <form class="task-form" @submit.prevent="saveSettings('system')">
              <div class="settings-runtime-note span-full" :class="{ warning: settingsPathWarning }">
                <strong>{{ runtimeLabel }}</strong>
                <span>{{ settingsPathStatusText }}</span>
              </div>
              <label class="span-full">
                <span>行情根目录</span>
                <div class="path-control">
                  <input v-model="settings.data_root" type="text" />
                  <button
                    class="btn secondary"
                    type="button"
                    :disabled="directoryPickDisabled"
                    :title="directoryPickTitle('data_root')"
                    @click="pickDirectory('data_root')"
                  >
                    <Icon name="folder" />
                    {{ pickingDirectory === 'data_root' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>
              <label class="span-full">
                <span>TDX PYPlugins 或根目录</span>
                <div class="path-control">
                  <input v-model="settings.tdx_path" type="text" />
                  <button
                    class="btn secondary"
                    type="button"
                    :disabled="directoryPickDisabled"
                    :title="directoryPickTitle('tdx_path')"
                    @click="pickDirectory('tdx_path')"
                  >
                    <Icon name="folder" />
                    {{ pickingDirectory === 'tdx_path' ? '选择中' : '选择文件夹' }}
                  </button>
                </div>
              </label>
              <div class="symbol-cache-control span-full">
                <div>
                  <span>股票 / ETF / 指数列表缓存</span>
                  <strong>{{ symbolMetadataCacheLabel }}</strong>
                  <em :title="symbolMetadataCachePath">{{ compactPath(symbolMetadataCachePath) }}</em>
                </div>
                <button
                  v-if="pendingSymbolRefreshTarget !== 'all'"
                  class="btn secondary"
                  type="button"
                  :disabled="symbolGroupRefreshDisabled"
                  :title="symbolGroupRefreshDisabledReason || '更新代码表缓存前需要确认'"
                  @click="requestSymbolGroupRefresh('all')"
                >
                  <Icon name="refresh" />
                  {{ refreshingSymbolGroup === 'all' ? '更新中' : '更新代码表缓存' }}
                </button>
                <div v-else class="symbol-refresh-confirm-actions">
                  <button class="btn secondary" type="button" title="取消更新代码表缓存" @click="cancelSymbolGroupRefresh">
                    取消
                  </button>
                  <button
                    class="btn danger"
                    type="button"
                    :disabled="pendingSymbolRefreshDisabled"
                    :title="pendingSymbolRefreshDisabledReason || pendingSymbolRefreshConfirmText"
                    @click="confirmSymbolGroupRefresh"
                  >
                    确认更新
                  </button>
                </div>
              </div>
              <span v-if="pendingSymbolRefreshTarget === 'all'" class="action-status inline warning symbol-refresh-status span-full">
                <i></i>
                {{ pendingSymbolRefreshConfirmText }}
              </span>
              <div class="action-readiness span-full" :class="{ warning: settingsActionWarning }">
                <strong>{{ settingsActionStateLabel }}</strong>
                <span>{{ settingsActionStatusText }}</span>
              </div>
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
                <button class="btn primary" type="submit" :title="settingsSaveTitle">保存设置</button>
                <template v-if="confirmingResetSettings">
                  <button class="btn secondary" type="button" title="取消恢复默认设置" @click="cancelResetSettings">取消</button>
                  <button class="btn danger" type="button" title="确认恢复默认路径、运行参数和 API 设置" @click="confirmResetSettings">确认恢复</button>
                </template>
                <button v-else class="btn secondary" type="button" title="恢复默认前需要确认" @click="requestResetSettings">恢复默认</button>
                <span v-if="settingsSaveFeedback" class="save-status success">{{ settingsSaveFeedback }}</span>
                <span v-else-if="confirmingResetSettings" class="action-status inline warning settings-reset-status">
                  <i></i>
                  {{ resetSettingsConfirmText }}
                </span>
              </div>
            </form>
          </Panel>

          <Panel title="AI 设置" subtitle="命令框 / 锐评 / AI 模块">
            <form class="task-form ai-settings-form" @submit.prevent="saveSettings('ai')">
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
              <div class="action-readiness span-full" :class="{ warning: Boolean(aiSettingsActionWarning) }">
                <strong>{{ aiSettingsActionStateLabel }}</strong>
                <span>{{ aiSettingsActionStatusText }}</span>
              </div>
              <div class="form-actions span-full">
                <button class="btn primary" type="submit" :title="aiSettingsSaveTitle">保存 AI 设置</button>
                <template v-if="confirmingResetAiPromptSettings">
                  <button class="btn secondary" type="button" title="取消恢复默认提示词" @click="cancelResetAiPromptSettings">取消</button>
                  <button class="btn danger" type="button" title="确认恢复默认提示词" @click="confirmResetAiPromptSettings">确认恢复</button>
                </template>
                <button v-else class="btn secondary" type="button" title="恢复默认提示词前需要确认" @click="requestResetAiPromptSettings">恢复默认提示词</button>
                <span v-if="aiSettingsSaveFeedback" class="save-status success">{{ aiSettingsSaveFeedback }}</span>
                <span v-else-if="confirmingResetAiPromptSettings" class="action-status inline warning settings-reset-status">
                  <i></i>
                  {{ resetAiPromptSettingsConfirmText }}
                </span>
              </div>
            </form>
          </Panel>

          <Panel title="开放数据 API" subtitle="外部调用">
            <div class="api-access-list">
              <article>
                <span>价格 K 线</span>
                <code>{{ priceBarsApiExample }}</code>
                <em>按 stock / etf / index 分页读取本地 parquet；全市场数据用 limit + offset 连续拉取。</em>
              </article>
              <article>
                <span>批量请求</span>
                <code>POST {{ publicApiBaseUrl }}/prices/bars</code>
                <em>请求体支持 symbols、asset_types、timeframe、start、end、adjust、limit、offset。</em>
              </article>
              <article>
                <span>AI 数据处理</span>
                <code>POST {{ publicApiBaseUrl }}/ai/stock-agent</code>
                <em>默认读取当前保存的 AI 设置；内置 stock-data skill，会优先引用本地 SQLite 行情索引。</em>
              </article>
              <article>
                <span>Skill 导入</span>
                <code>AI 工作台 -> 导入 Skill / 系统提示词</code>
                <em>导入 .md / .txt 后作为当前浏览器保存的分析提示词。</em>
              </article>
            </div>
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

    <div v-if="directoryBrowserOpen" class="modal-backdrop" @click.self="closeDirectoryBrowser" @keydown.esc="closeDirectoryBrowser">
      <section
        class="asset-picker-modal directory-browser-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="directory-browser-title"
        aria-describedby="directory-browser-description"
      >
        <header class="asset-picker-head">
          <div>
            <h3 id="directory-browser-title">选择{{ directoryFieldLabel(directoryBrowserField) }}</h3>
            <p id="directory-browser-description">{{ directoryBrowserReason || '浏览当前服务可访问的目录' }}</p>
          </div>
          <button class="icon-button" type="button" aria-label="关闭" @click="closeDirectoryBrowser">
            <Icon name="collapse" />
          </button>
        </header>

        <div class="directory-browser-path">
          <input
            ref="directoryBrowserPathInput"
            v-model="directoryBrowserPath"
            type="text"
            aria-label="当前目录路径"
            @keyup.enter="requestLoadDirectoryBrowser(directoryBrowserPath)"
          />
          <button
            class="btn secondary"
            type="button"
            :disabled="directoryBrowserOpenDisabled"
            :title="directoryBrowserOpenDisabledReason || '读取当前输入路径下的可访问目录'"
            @click="requestLoadDirectoryBrowser(directoryBrowserPath)"
          >
            <Icon name="folder" />
            打开
          </button>
        </div>

        <div class="asset-picker-summary" role="status" aria-live="polite">
          <span :title="directoryBrowserPath">当前位置 {{ compactPath(directoryBrowserPath) }}</span>
          <strong>{{ formatInt(directoryBrowserEntries.length) }} 个目录</strong>
        </div>

        <div v-if="directoryBrowserLoading" class="asset-picker-empty">目录读取中...</div>
        <div v-else-if="directoryBrowserError" class="asset-picker-empty">{{ directoryBrowserError }}</div>
        <div v-else class="directory-browser-list">
          <button
            v-if="directoryBrowserParent"
            class="directory-browser-row parent"
            type="button"
            :disabled="directoryBrowserLoading"
            :title="directoryBrowserLoading ? '正在读取目录，请稍候' : directoryBrowserParent"
            @click="requestLoadDirectoryBrowser(directoryBrowserParent)"
          >
            <Icon name="folder" />
            <span>
              <strong>上级目录</strong>
              <em>{{ directoryBrowserParent }}</em>
            </span>
          </button>
          <button
            v-for="entry in directoryBrowserEntries"
            :key="entry.path"
            class="directory-browser-row"
            type="button"
            :disabled="directoryBrowserLoading || !entry.readable"
            :title="directoryBrowserLoading ? '正在读取目录，请稍候' : entry.readable ? entry.path : '该目录当前不可读取'"
            @click="requestLoadDirectoryBrowser(entry.path)"
          >
            <Icon name="folder" />
            <span>
              <strong>{{ entry.name }}</strong>
              <em>{{ entry.readable ? entry.path : '无读取权限' }}</em>
            </span>
          </button>
          <div v-if="!directoryBrowserParent && !directoryBrowserEntries.length" class="asset-picker-empty">当前目录没有可进入的子目录。</div>
        </div>

        <footer class="asset-picker-footer">
          <span
            v-if="directoryBrowserStatusText"
            class="action-status inline"
            role="status"
            aria-live="polite"
            :class="{ busy: directoryBrowserLoading, warning: directoryBrowserStatusTone === 'warning' }"
          >
            <i></i>
            {{ directoryBrowserStatusText }}
          </span>
          <button class="btn secondary" type="button" @click="closeDirectoryBrowser">取消</button>
          <button
            class="btn primary"
            type="button"
            :disabled="directoryBrowserConfirmDisabled"
            :title="directoryBrowserConfirmDisabledReason || '使用当前位置更新配置'"
            @click="confirmDirectoryBrowserPath"
          >
            使用当前目录
          </button>
        </footer>
      </section>
    </div>

    <div v-if="reviewSymbolPickerOpen" class="modal-backdrop" @click.self="closeReviewSymbolPicker" @keydown.esc="closeReviewSymbolPicker">
      <section
        class="asset-picker-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-symbol-picker-title"
        aria-describedby="review-symbol-picker-description"
      >
        <header class="asset-picker-head">
          <div>
            <h3 id="review-symbol-picker-title">选择复盘标的</h3>
            <p id="review-symbol-picker-description">{{ reviewSymbolPickerSourceSummary }}</p>
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
            :aria-pressed="reviewSymbolPickerType === tabItem.key"
            @click="setReviewSymbolPickerType(tabItem.key)"
          >
            {{ tabItem.label }}
            <span>{{ reviewSymbolPickerCount(tabItem.key) }}</span>
          </button>
        </div>

        <div class="asset-picker-tools">
          <select v-model="reviewSymbolPickerCategory" aria-label="复盘标的分类" @change="cancelReviewSymbolPendingAction">
            <option v-for="item in reviewSymbolPickerCategoryOptions" :key="item.value" :value="item.value">
              {{ item.label }} · {{ formatInt(item.count) }}
            </option>
          </select>
          <input
            ref="reviewSymbolPickerSearchInput"
            v-model="reviewSymbolPickerKeyword"
            type="search"
            aria-label="搜索复盘标的"
            placeholder="搜索代码或名称"
            @input="cancelReviewSymbolPendingAction"
          />
          <button
            class="btn secondary"
            type="button"
            :disabled="reviewSymbolPickerSelectFilteredDisabled"
            :title="reviewSymbolPickerSelectFilteredDisabledReason || '选中当前搜索和分类筛选结果'"
            @click="selectFilteredReviewSymbols"
          >
            选当前结果
          </button>
          <button
            class="btn secondary"
            type="button"
            :disabled="reviewSymbolPickerSelectAllDisabled"
            :title="reviewSymbolPickerSelectAllDisabledReason || '选中当前分类下全部标的'"
            @click="selectAllReviewSymbols"
          >
            全选当前分类
          </button>
          <button
            class="btn secondary"
            type="button"
            :disabled="reviewSymbolPickerClearDisabled"
            :title="reviewSymbolPickerClearDisabledReason || '清空当前弹窗内已选标的'"
            @click="clearReviewSymbolSelection"
          >
            清空
          </button>
        </div>

        <div class="asset-picker-summary" role="status" aria-live="polite">
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
            <input
              type="checkbox"
              :checked="isReviewSymbolSelected(row.symbol)"
              :aria-label="`选择 ${row.symbol} ${row.name || row.assetType || reviewSymbolPickerTypeLabel}`"
              @change="toggleReviewSymbol(row.symbol)"
            />
            <span>
              <strong>{{ row.symbol }}</strong>
              <em>{{ row.name || row.assetType || reviewSymbolPickerTypeLabel }} · {{ row.categoryLabel }}</em>
            </span>
          </label>
        </div>
        <div v-else class="asset-picker-empty">当前分类暂无可选标的。</div>

        <footer class="asset-picker-footer asset-picker-footer-stable">
          <span
            class="action-status inline"
            role="status"
            aria-live="polite"
            :class="{
              'asset-picker-footer-status': true,
              warning: Boolean(reviewSymbolPickerApplyDisabledReason) || Boolean(pendingReviewSymbolAction),
              muted: !reviewSymbolPickerStatusText
            }"
          >
            <i></i>
            {{ reviewSymbolPickerStatusText || '选择标的后可追加或替换。' }}
          </span>
          <div class="asset-picker-footer-actions">
            <button class="btn secondary" type="button" @click="pendingReviewSymbolAction ? cancelReviewSymbolPendingAction() : closeReviewSymbolPicker">
              {{ pendingReviewSymbolAction ? '返回选择' : '取消' }}
            </button>
            <button
              v-show="pendingReviewSymbolAction"
              :class="['btn', pendingReviewSymbolAction === 'replace' ? 'danger' : 'primary']"
              type="button"
              :disabled="reviewSymbolPickerPendingActionDisabled"
              :title="reviewSymbolPickerPendingActionDisabledReason || reviewSymbolPickerStatusText"
              @click="confirmReviewSymbolPickerApply"
            >
              确认{{ reviewSymbolPickerPendingActionLabel }}
            </button>
            <button
              v-show="!pendingReviewSymbolAction"
              class="btn secondary"
              type="button"
              :disabled="reviewSymbolPickerApplyDisabled"
              :title="reviewSymbolPickerApplyDisabledReason || '追加选中前需要确认'"
              @click="requestReviewSymbolPickerApply('append')"
            >
              追加选中
            </button>
            <button
              v-show="!pendingReviewSymbolAction"
              class="btn primary"
              type="button"
              :disabled="reviewSymbolPickerApplyDisabled"
              :title="reviewSymbolPickerApplyDisabledReason || '替换标的前需要确认'"
              @click="requestReviewSymbolPickerApply('replace')"
            >
              替换标的
            </button>
          </div>
        </footer>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
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
  symbol_metadata_cache?: Record<string, any>
}

interface TaskPayload {
  id: string
  kind: string
  status: string
  control?: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  events: Array<Record<string, any>>
  result: { summary: Record<string, any>; records: Array<Record<string, any>> } | null
  error: string | null
}

interface TaskEventItem {
  key: string
  index: number
  stage: string
  label: string
  message: string
  time: string
  visible: boolean
  raw: Record<string, any>
}

interface TaskProgressState {
  title: string
  detail: string
  time: string
  percentText: string
  barWidth: string
  statusClass: string
  ariaLabel: string
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
type SortDirection = 'asc' | 'desc'
type RegimeAdvancedParameterKey =
  | (typeof REGIME_PERCENT_FIELD_KEYS)[number]
  | 'concentration_top_n'
  | 'daily_report_days'
  | 'flow_candidate_limit'
  | 'risk_timeline_days'

interface RegimeAdvancedParameter {
  key: RegimeAdvancedParameterKey
  label: string
  unit: '%' | 'count'
  min?: number
  max?: number
  step: number
  hint: string
}

interface DateRangeFields {
  start: string
  end: string
}

type DirectoryField = 'data_root' | 'tdx_path'
type ResearchTabKey = 'history' | 'cross' | 'review' | 'etf' | 'regime'
type RegimeSectionTabKey = 'overview' | 'daily' | 'flow' | 'factor' | 'asset'
type AiWorkbenchTabKey = 'chat' | 'symbols'
type AiCommandResultState = 'idle' | 'pending' | 'applied' | 'cancelled' | 'empty'
type AiSymbolRunPendingAction = '' | 'metrics' | 'filter'
type AiSymbolPendingAction = '' | 'topN' | 'replaceGroup' | 'appendFiltered' | 'appendPage' | 'filterResult'
type AiSymbolSortKey =
  | 'selected'
  | 'symbol'
  | 'name'
  | 'assetLabel'
  | 'latestDate'
  | 'close'
  | 'amount'
  | 'volume'
  | 'marketValue'
  | 'turnoverRate'
type SymbolRefreshTarget = 'all' | 'index' | 'etf'
type ReviewSymbolPickerType = 'etf' | 'sector'
type ReviewSymbolPendingAction = '' | 'append' | 'replace'
type AssetShortcutType = 'etf' | 'stock' | 'index'
type CrossUniversePendingAction = '' | AssetShortcutType
type DownloadTimeframePendingAction = '' | 'all' | 'default'
type DownloadDatePendingShortcut = '' | DateShortcutKey
type ResearchDateShortcutTarget = 'history' | 'crossTarget' | 'crossCandidate' | 'review' | 'etf' | 'regime'
type EtfRefreshPendingAction = '' | 'tracking' | 'returns'
type EtfClientCacheSource = 'empty' | 'client' | 'memory' | 'disk' | 'network' | 'cleared'

const ASSET_SHORTCUT_LABELS: Record<AssetShortcutType, string> = { etf: 'ETF', stock: '个股', index: '指数' }

interface EtfClientCacheState {
  source: EtfClientCacheSource
  saved_at: number
  record_count: number
}

interface DirectoryEntry {
  name: string
  path: string
  readable: boolean
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
  type: 'table' | 'section' | 'paragraph' | 'list' | 'quote' | 'code'
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
const aiWorkbenchTabs: Array<{ key: AiWorkbenchTabKey; label: string }> = [
  { key: 'chat', label: '对话' },
  { key: 'symbols', label: '标的池' }
]
const aiSymbolTableColumns: Array<{ key: AiSymbolSortKey; label: string }> = [
  { key: 'selected', label: '选中' },
  { key: 'symbol', label: '代码' },
  { key: 'name', label: '名称' },
  { key: 'assetLabel', label: '类型' },
  { key: 'latestDate', label: '最新日期' },
  { key: 'close', label: '最新价' },
  { key: 'amount', label: '成交额' },
  { key: 'volume', label: '成交量' },
  { key: 'marketValue', label: '市值' },
  { key: 'turnoverRate', label: '换手率' }
]

const SETTINGS_STORAGE_KEY = 'tdx-downloader-web-settings'
const RESEARCH_SNAPSHOT_STORAGE_KEY = 'tdx-downloader-research-snapshots'
const ETF_TRACKING_CACHE_STORAGE_KEY = 'tdx-downloader-etf-tracking-cache'
const ETF_RETURNS_CACHE_STORAGE_KEY = 'tdx-downloader-etf-returns-cache'
const API_GET_TIMEOUT_MS = 60_000
const API_POST_TIMEOUT_MS = 60_000
const DOWNLOAD_SUBMIT_TIMEOUT_MS = 15_000
const ETF_TRACKING_CLIENT_CACHE_TTL_MS = 24 * 60 * 60 * 1000
const ETF_RETURNS_CLIENT_CACHE_TTL_MS = 12 * 60 * 60 * 1000
const MAX_RESEARCH_SNAPSHOTS = 60
const CACHE_PAGE_SIZE_OPTIONS = [25, 50, 100]
const PLAN_PAGE_SIZE_OPTIONS = [25, 50, 100]
const ETF_TRACKER_PAGE_SIZE_OPTIONS = [25, 50, 100]
const AI_SYMBOL_PAGE_SIZE_OPTIONS = [25, 50, 100]
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
const REGIME_ADVANCED_PARAMETERS: RegimeAdvancedParameter[] = [
  {
    key: 'liquidity_high_percentile',
    label: '高流动性分位',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '按全市场 20 日平均成交额做横截面排名，分位高于该值的资产归入高流动性层，用于观察权重资产是否补跌。'
  },
  {
    key: 'liquidity_mid_percentile',
    label: '中盘起始分位',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '成交额分位在该值到高流动性分位之间的资产归入中盘核心，低于该值默认视为长尾/低流动性。'
  },
  {
    key: 'liquidity_low_percentile',
    label: '低流动性分位',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '成交额分位低于该值时标记为低流动性层，用于区分长尾资产的弱信号，避免和主线流动性混看。'
  },
  {
    key: 'volatility_high_percentile',
    label: '高波动分位',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '按 HV20 年化波动率横截面排名，分位高于该值的资产归入高波动层，常用于识别弹性资产先承压。'
  },
  {
    key: 'volatility_low_percentile',
    label: '低波动分位',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: 'HV20 分位低于该值时标记为低波动层，用于区分防守型或波动收敛资产。'
  },
  {
    key: 'high_position_drawdown_threshold',
    label: '高位回撤阈值',
    unit: '%',
    max: 0,
    step: 0.5,
    hint: '资产相对 250 日高点的回撤不低于该值时仍视为高位，例如 -10 表示距离高点 10% 内仍属于高位资产。'
  },
  {
    key: 'high_position_return_percentile',
    label: '高位涨幅分位',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '按 120 日涨幅横截面排名，分位高于该值也会归入高位资产，用于捕捉强趋势拥挤区。'
  },
  {
    key: 'leader_return_5d_threshold',
    label: '领涨5日阈值',
    unit: '%',
    step: 0.5,
    hint: '近 5 日收益超过该值的资产计为领涨资产，用于市场缩圈表判断上涨是否集中在少数标的。'
  },
  {
    key: 'stress_ma20_break_threshold',
    label: '压力破位阈值',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '某一层级内跌破 MA20 的资产占比达到该值，且近 5 日收益弱于压力收益阈值时，记为压力信号。'
  },
  {
    key: 'stress_return_5d_threshold',
    label: '压力收益阈值',
    unit: '%',
    step: 0.5,
    hint: '层级近 5 日平均收益低于该值时配合破位阈值触发压力信号；填 0 表示转负即偏弱。'
  },
  {
    key: 'cash_stress_score_threshold',
    label: '现金压力分',
    unit: '%',
    min: 0,
    max: 100,
    step: 1,
    hint: '现金偏好代理层的压力分阈值，由高流动性破位、市场宽度下降和短期动量转弱合成，高于该值表示防守情绪升温。'
  },
  {
    key: 'cash_preference_proxy_threshold',
    label: '现金偏好阈值',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '现金偏好代理达到该值时，日报会标记为明显防守，用于判断资金是否从风险资产转向现金/低风险偏好。'
  },
  {
    key: 'risk_expansion_breadth_threshold',
    label: '扩张宽度',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '站上 MA20 的资产占比高于该值且 5 日动量为正时，市场阶段倾向风险偏好扩张。'
  },
  {
    key: 'risk_contraction_breadth_threshold',
    label: '收缩宽度',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '站上 MA20 的资产占比低于该值时，市场阶段倾向风险偏好收缩。'
  },
  {
    key: 'risk_release_breadth_threshold',
    label: '释放后段宽度',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '市场宽度低于该值且高流动性破位达到阈值时，阶段判为风险释放后段。'
  },
  {
    key: 'high_liquidity_selloff_threshold',
    label: '高流动性抛售',
    unit: '%',
    min: 0,
    max: 100,
    step: 5,
    hint: '高流动性资产中跌破 MA20 的比例达到该值，说明权重/高成交资产也在补跌，是风险释放确认条件之一。'
  },
  {
    key: 'concentration_top_n',
    label: '集中度TopN',
    unit: 'count',
    min: 1,
    max: 500,
    step: 1,
    hint: '计算成交额集中度时取成交额最高的 N 个资产，N 越小越强调头部拥挤，N 越大越平滑。'
  },
  {
    key: 'daily_report_days',
    label: '日报交易日数',
    unit: 'count',
    min: 1,
    max: 120,
    step: 1,
    hint: '日报和近期证据回看多少个交易日，用于展示市场状态变化和最近触发记录。'
  },
  {
    key: 'flow_candidate_limit',
    label: '回流候选数',
    unit: 'count',
    min: 1,
    max: 200,
    step: 1,
    hint: '资金回流候选表最多返回多少只资产；候选按回调、转强、相对强度和流动性综合排序。'
  },
  {
    key: 'risk_timeline_days',
    label: '时间线交易日数',
    unit: 'count',
    min: 5,
    max: 180,
    step: 1,
    hint: '风险释放热力图和 RAI 时间线展示的交易日长度，越长越利于看阶段，越短越聚焦近期。'
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
  missing_index: '索引缺失',
  missing_file: '缺文件',
  read_error: '读取失败',
  missing_columns: '缺字段',
  no_valid_rows: '无有效K线',
  ok: '通过',
  quality_error: '质量异常',
  no_window_data: '窗口无数据',
  coverage_gap: '覆盖缺口',
  coverage_ready: '窗口完整',
  coverage_partial: '窗口缺失',
  coverage_empty: '窗口无数据',
  coverage_unknown: '未建覆盖索引',
  coverage_missing_index: '未建覆盖索引',
  coverage_unavailable: '不可校验覆盖',
  coverage_below_min: '低于阈值',
  not_checked: '未检查',
  ready: '准备完成',
  partial: '部分可用',
  empty: '无可用缓存',
  fetch: '待下载',
  derive: '待派生',
  derived_from_source: '由5m派生',
  derive_from_cached_source: '由本地5m派生',
  fetched: '已下载'
}
const TASK_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  pausing: '暂停中',
  paused: '已暂停',
  cancelling: '终止中',
  cancelled: '已终止',
  succeeded: '已完成',
  failed: '失败'
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
const controllingTaskId = ref('')
const selectedGroup = ref('核心样例')
const pendingDownloadSymbolGroup = ref('')
const previousDownloadSymbolGroup = ref('')
const selectedTimeframes = ref<string[]>(['1d'])
const pendingDownloadTimeframeAction = ref<DownloadTimeframePendingAction>('')
const pendingDownloadDateShortcut = ref<DownloadDatePendingShortcut>('')
const pendingResearchDateShortcut = ref<{ target: ResearchDateShortcutTarget; key: DateShortcutKey } | null>(null)
const confirmingRunAiCommand = ref(false)
const researchTimeframe = ref('1d')
const allAssetsLookbackDays = ref(DEFAULT_ALL_ASSETS_LOOKBACK_DAYS)
const reviewSymbolPickerOpen = ref(false)
const reviewSymbolPickerType = ref<ReviewSymbolPickerType>('etf')
const reviewSymbolPickerCategory = ref(defaultReviewSymbolCategory('etf'))
const reviewSymbolPickerKeyword = ref('')
const reviewSymbolPickerSelection = ref<string[]>([])
const pendingReviewSymbolAction = ref<ReviewSymbolPendingAction>('')
const pendingCrossUniverseAction = ref<CrossUniversePendingAction>('')
const symbolsText = ref('')
const confirmingLoadAiWorkbenchSymbols = ref(false)
const confirmingRunAiWorkbench = ref(false)
const confirmingClearAiSymbols = ref(false)
const pendingAiSymbolAction = ref<AiSymbolPendingAction>('')
const pendingAiSymbolFilterResult = ref<Record<string, any> | null>(null)
const pendingEtfRefreshAction = ref<EtfRefreshPendingAction>('')
const confirmingClearAiSkillPrompt = ref(false)
const confirmingImportIndicatorFormula = ref(false)
const confirmingMapSelectedIndicators = ref(false)
const confirmingComputeSelectedIndicators = ref(false)
const confirmingLoadPriceTable = ref(false)
const confirmingPriceTableCommonIndicators = ref(false)
const confirmingOverviewRefresh = ref(false)
const confirmingTopbarRefresh = ref(false)
const pendingRegimePresetKey = ref<RegimeParameterPresetKey | ''>('')
const planning = ref(false)
const downloading = ref(false)
const confirmingPreviewPlan = ref(false)
const confirmingStartDownload = ref(false)
const confirmingAllAssetsUpdate = ref(false)
const confirmingClearEtfCache = ref(false)
const confirmingLoadEtfReview = ref(false)
const confirmingRunEtfTrackerReview = ref(false)
const confirmingClearRegimeManualSymbols = ref(false)
const confirmingRunHistorySearch = ref(false)
const confirmingRunCrossSearch = ref(false)
const confirmingRunRegimeResearch = ref(false)
const confirmingRunReviewSearch = ref(false)
const confirmingResetResizableCards = ref(false)
const confirmingResetSettings = ref(false)
const loadingOverview = ref(false)
const refreshingTopbar = ref(false)
const loadingSymbolGroups = ref(false)
const refreshingSymbolGroup = ref<SymbolRefreshTarget | ''>('')
const pendingSymbolRefreshTarget = ref<SymbolRefreshTarget | ''>('')
const clearingTasks = ref(false)
const loadingEtfTracking = ref(false)
const loadingEtfReturns = ref(false)
const loadingTradingCalendar = ref(false)
const loadingPriceTable = ref(false)
const loadingIndicatorFormulas = ref(false)
const importingIndicatorFormula = ref(false)
const computingIndicators = ref(false)
const mappingIndicators = ref(false)
const runningResearch = ref<ResearchTabKey | ''>('')
const runningAiReview = ref(false)
const confirmingRunAiReview = ref(false)
const confirmingRegimeExport = ref(false)
const runningAiCommand = ref(false)
const runningAiSymbolFilter = ref(false)
const runningAiWorkbench = ref(false)
const loadingAiSymbolMetrics = ref(false)
const aiWorkbenchStreamText = ref('')
const aiWorkbenchStreamStatus = ref<'idle' | 'preparing' | 'streaming' | 'done' | 'error'>('idle')
const confirmingClearTasks = ref(false)
const confirmingResearchSnapshotLoadId = ref('')
const confirmingResearchSnapshotDeleteId = ref('')
const activeResearchTab = ref<ResearchTabKey>('history')
const activeRegimeSectionTab = ref<RegimeSectionTabKey>('overview')
const activeAiWorkbenchTab = ref<AiWorkbenchTabKey>('chat')
const pickingDirectory = ref<DirectoryField | ''>('')
const directoryBrowserOpen = ref(false)
const directoryBrowserPathInput = ref<HTMLInputElement | null>(null)
const directoryBrowserField = ref<DirectoryField | ''>('')
const directoryBrowserPath = ref('')
const directoryBrowserParent = ref('')
const directoryBrowserEntries = ref<DirectoryEntry[]>([])
const directoryBrowserLoading = ref(false)
const directoryBrowserError = ref('')
const directoryBrowserReason = ref('')
const reviewSymbolPickerSearchInput = ref<HTMLInputElement | null>(null)
const planRows = ref<Array<Record<string, any>>>([])
const planSummary = ref<Record<string, any>>({})
const historyResult = ref<Record<string, any> | null>(null)
const crossResult = ref<Record<string, any> | null>(null)
const reviewResult = ref<Record<string, any> | null>(null)
const regimeResult = ref<Record<string, any> | null>(null)
const activeRegimeRaiKey = ref('')
const regimeRaiWindowStart = ref(-1)
const historyResultSignature = ref('')
const crossResultSignature = ref('')
const reviewResultSignature = ref('')
const regimeResultSignature = ref('')
const etfTrackerResultSignature = ref('')
const etfTrackingRows = ref<Array<Record<string, any>>>([])
const etfReturnRows = ref<Array<Record<string, any>>>([])
const indicatorFormulaRows = ref<Array<Record<string, any>>>([])
const priceTableRows = ref<Array<Record<string, any>>>([])
const aiSymbolMetricRows = ref<Array<Record<string, any>>>([])
const aiSymbolMetricGroupName = ref('')
const symbolMetadataCache = ref<Record<string, any> | null>(null)
const etfTrackingCacheState = reactive<EtfClientCacheState>({ source: 'empty', saved_at: 0, record_count: 0 })
const etfReturnsCacheState = reactive<EtfClientCacheState>({ source: 'empty', saved_at: 0, record_count: 0 })
const tradingCalendarDays = ref<string[]>([])
const settingsSaveFeedback = ref('')
const aiSettingsSaveFeedback = ref('')
const confirmingResetAiPromptSettings = ref(false)
const aiReviewOutput = ref<Record<string, any> | null>(null)
const aiCommandResult = ref<Record<string, any> | null>(null)
const aiCommandResultState = ref<AiCommandResultState>('idle')
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
const priceTableForm = reactive({
  symbols: '000001.SZ',
  timeframe: '1d',
  start: tradingLookbackStartText(60),
  end: todayText(),
  indicators: 'ma5,ma10,ma20'
})
const indicatorImportForm = reactive({
  formula_id_prefix: '',
  text: ''
})
const indicatorMappingForm = reactive({
  asset_type: 'stock'
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
const aiSymbolPagination = reactive({
  page: 1,
  pageSize: AI_SYMBOL_PAGE_SIZE_OPTIONS[1]
})
const aiSymbolSort = reactive<{ key: AiSymbolSortKey; direction: SortDirection }>({
  key: 'amount',
  direction: 'desc'
})

const settings = reactive({
  data_root: '/Volumes/ccOUT 1/tdx-data',
  adjust: 'qfq',
  tdx_path: '/Volumes/[C] Windows 11/new_tdx64/PYPlugins',
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
const aiSymbolGroupName = ref('')
const aiSymbolKeyword = ref('')
const aiSymbolNaturalQuery = ref('')
const aiSymbolTopN = ref(50)
const pendingAiSymbolRunAction = ref<AiSymbolRunPendingAction>('')
const aiWorkbenchForm = reactive({
  symbols: '',
  start: tradingLookbackStartText(60),
  end: todayText(),
  timeframe: '1d',
  skill_prompt: '',
  prompt: '请基于这些本地行情数据，输出强弱判断、风险点和下一步观察项。',
  max_charts: 3
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
const pendingRegimePreset = computed(() =>
  pendingRegimePresetKey.value ? REGIME_PARAMETER_PRESETS.find((preset) => preset.key === pendingRegimePresetKey.value) || null : null
)
const regimePresetConfirmDisabledReason = computed(() => {
  if (!pendingRegimePresetKey.value) return '当前没有待确认的参数预设'
  if (!pendingRegimePreset.value) return '待应用的参数预设不存在，请重新选择'
  return ''
})
const regimePresetConfirmDisabled = computed(() => Boolean(regimePresetConfirmDisabledReason.value))
const regimePresetConfirmText = computed(() => {
  if (regimePresetConfirmDisabledReason.value) return regimePresetConfirmDisabledReason.value
  const preset = pendingRegimePreset.value
  return `确认后将用“${preset?.label || pendingRegimePresetKey.value}”覆盖 ${formatInt(REGIME_PERCENT_FIELD_KEYS.length)} 项风险偏好阈值；当前高级参数未修改。`
})

const activeMeta = computed(() => navItems.find((item) => item.key === activeView.value) || navItems[0])
const activeResearchMeta = computed(() => researchTabs.find((item) => item.key === activeResearchTab.value) || researchTabs[0])
const crossSearchModeLabel = computed(() => (crossForm.search_mode === 'traversal' ? '指定区间' : '同区间'))
const crossCandidateRangeDisabledReason = computed(() =>
  crossForm.search_mode !== 'traversal' ? '候选区间只在指定区间模式下可修改；同区间模式下候选区间跟随目标区间；切换为指定区间后可编辑。' : ''
)
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
const regimeManualSymbols = computed(() => parseSymbols(regimeForm.symbols))
const regimeManualSymbolsClearDisabledReason = computed(() => {
  if (!regimeManualSymbols.value.length) return '当前没有手动补充标的'
  return ''
})
const regimeManualSymbolsClearDisabled = computed(() => Boolean(regimeManualSymbolsClearDisabledReason.value))
const regimeManualSymbolsClearConfirmText = computed(() =>
  `将清空 ${formatInt(regimeManualSymbols.value.length)} 只手动补充标的；所选研究宇宙不会变化。`
)
const selectedRegimeUniverseCount = computed(() =>
  regimeForm.universe_groups.reduce((total, name) => {
    const group = config.value?.symbol_groups.find((item) => item.name === name)
    return total + (group?.symbols.length || 0)
  }, regimeManualSymbols.value.length)
)
const regimeResearchConfirmText = computed(() =>
  `确认后将按 ${formatInt(selectedRegimeUniverseCount.value)} 只候选资产、基准 ${regimeForm.benchmark_symbol || '-'}、${regimeForm.start || '-'} 至 ${regimeForm.end || '-'} 运行市场风险偏好研究。`
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

function researchActionDisabled(tab: ResearchTabKey) {
  return Boolean(researchActionDisabledReason(tab))
}

function researchActionDisabledReason(tab: ResearchTabKey) {
  if (runningResearch.value && runningResearch.value !== tab) return `${researchBusyStatusText.value}，请等待完成。`
  if (runningResearch.value === tab) return researchBusyStatusText.value
  return ''
}

function resultActionDisabledReason(tab: ResearchTabKey) {
  const runningReason = researchActionDisabledReason(tab)
  if (runningReason) return runningReason
  if (!researchResultFor(tab)) return `先运行${activeResearchMetaFor(tab).label}，生成结果后才能保存快照。`
  const staleReason = researchResultStaleReason(tab)
  if (staleReason) return staleReason
  return ''
}

function resultActionDisabled(tab: ResearchTabKey) {
  return Boolean(resultActionDisabledReason(tab))
}

function researchResultStaleReason(tab: ResearchTabKey) {
  if (tab === 'history' && historyResultSignature.value !== historySearchSignature()) return '历史相似参数已变更，请重新搜索后再保存快照。'
  if (tab === 'cross' && crossResultSignature.value !== crossSearchSignature()) return '横截面参数已变更，请重新搜索后再保存快照。'
  if (tab === 'regime' && regimeResultSignature.value !== regimeSearchSignature()) return '市场风偏参数已变更，请重新运行后再保存快照。'
  if (tab === 'review' && reviewResultSignature.value !== reviewSearchSignature()) return '多股复盘参数已变更，请重新生成后再保存快照。'
  if (tab === 'etf' && etfTrackerResultSignature.value !== etfTrackerSearchSignature()) return 'ETF 趋势参数已变更，请重新生成后再保存快照。'
  return ''
}

const activeResearchSnapshotDisabledReason = computed(() => resultActionDisabledReason(activeResearchTab.value))
const activeResearchSnapshotDisabled = computed(() => Boolean(activeResearchSnapshotDisabledReason.value))

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

function assetTypeLabel(value: string) {
  const labels: Record<string, string> = {
    stock: '个股',
    etf: 'ETF',
    index: '指数',
    other: '其他'
  }
  return labels[String(value || 'other')] || '其他'
}

function guessAssetType(symbol: string, name: string, groupName: string) {
  const code = String(symbol || '').split('.', 1)[0]
  const upperName = String(name || '').toUpperCase()
  if (groupName.includes('ETF') || upperName.includes('ETF') || upperName.includes('LOF')) return 'etf'
  if (groupName.includes('指数') || (symbol.endsWith('.SH') && code.startsWith('000')) || code.startsWith('399')) return 'index'
  if (/^(159|510|511|512|513|515|516|517|518|520|560|561|562|563|588)/.test(code)) return 'etf'
  if (/^(000|001|002|003|300|301|600|601|603|605|688|689|430|830|831|832|833|834|835|836|837|838|839|920)/.test(code)) return 'stock'
  return 'other'
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
    '当日收益': formatPercentValue(row.return_1d),
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
const selectedPriceIndicators = computed(() => parseIndicatorIds(priceTableForm.indicators))
const priceTableSummary = computed(() => {
  const indicators = selectedPriceIndicators.value.length ? ` · 指标 ${selectedPriceIndicators.value.join(',')}` : ''
  return `${priceTableForm.timeframe} · ${priceTableForm.start} 至 ${priceTableForm.end}${indicators}`
})
const priceTableColumns = computed(() => [
  { key: '日期', label: '日期' },
  { key: '代码', label: '代码' },
  { key: '名称', label: '名称' },
  { key: '开', label: '开' },
  { key: '高', label: '高' },
  { key: '低', label: '低' },
  { key: '收', label: '收' },
  { key: '成交量', label: '成交量' },
  { key: '成交额', label: '成交额' },
  ...selectedPriceIndicators.value.map((indicator) => ({ key: indicator, label: indicator.toUpperCase() }))
])
const displayPriceTableRows = computed(() =>
  priceTableRows.value.map((row: Record<string, any>) => {
    const result: Record<string, any> = {
      '日期': formatDateTimeText(row.date),
      '代码': row.stock_code,
      '名称': row.stock_name || displaySymbolName(row.stock_code),
      '开': formatDecimalValue(row.open, 2),
      '高': formatDecimalValue(row.high, 2),
      '低': formatDecimalValue(row.low, 2),
      '收': formatDecimalValue(row.close, 2),
      '成交量': formatInt(row.volume),
      '成交额': formatAmountValue(row.amount)
    }
    selectedPriceIndicators.value.forEach((indicator) => {
      result[indicator] = formatDecimalValue(row[indicator], 3)
    })
    return result
  })
)
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
const publicApiBaseUrl = computed(() => `${window.location.origin}${API_BASE}`)
const priceBarsApiExample = computed(
  () => `${publicApiBaseUrl.value}/prices/bars?asset_types=stock&timeframe=1d&start=${settings.start || todayText()}&end=${settings.end || todayText()}&limit=5000`
)
const aiCommandScopeLabel = computed(() => {
  if (activeView.value !== 'research') return `作用于：${activeMeta.value.title}`
  return `作用于：研究工具 / ${activeResearchMeta.value.label}`
})
const chartThemeClass = computed(() => `chart-theme-${chartSettings.theme === 'contrast' ? 'contrast' : 'clean'}`)
const chartDensityClass = computed(() => `chart-density-${chartSettings.density === 'compact' ? 'compact' : 'comfortable'}`)
const aiDefaultSystemPrompt = computed(() =>
  String((reviewResult.value?.ai?.messages || []).find((message: Record<string, string>) => message.role === 'system')?.content || builtinStockDataSkillPrompt())
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
const aiWorkbenchMarkdownBlocks = computed<ReviewMarkdownBlock[]>(() => {
  const content = aiWorkbenchStreamText.value || String(aiWorkbenchResult.value?.content || '')
  const blocks = markdownBlocks(content)
  return blocks.length ? blocks : [{ type: 'paragraph', title: '', lines: ['-'], headers: [], rows: [] }]
})
const aiWorkbenchChartItems = computed(() =>
  (aiWorkbenchResult.value?.chart_items || aiWorkbenchResult.value?.data_context?.chart_items || [])
    .filter((item: Record<string, any>) => Array.isArray(item.candles) && item.candles.length)
)
const aiWorkbenchChartSummary = computed(() => {
  const count = aiWorkbenchChartItems.value.length
  const context = aiWorkbenchResult.value?.data_context || {}
  const range = chartActualRange(aiWorkbenchChartItems.value)
  const rangeText = range ? ` · ${range.start} 至 ${range.end}` : ''
  return count ? `${count} 个标的 · ${context.timeframe || aiWorkbenchForm.timeframe}${rangeText}` : ''
})
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
const runningInContainer = computed(() => ['/data/', '/app/', '/workspace/'].some((prefix) => settings.data_root.startsWith(prefix)))
const symbolMetadataCacheLabel = computed(() => {
  const cache = symbolMetadataCache.value || config.value?.symbol_metadata_cache
  if (!cache?.hit) return '未缓存'
  const savedAt = symbolMetadataCacheTimeText(cache.saved_at)
  return `${formatInt(cache.record_count)} 条${savedAt ? ` · ${savedAt}` : ''}`
})
const symbolMetadataCachePath = computed(() => String((symbolMetadataCache.value || config.value?.symbol_metadata_cache)?.path || ''))
const settingsPathWarning = computed(() => {
  if (!settings.data_root.trim()) return true
  if (runningInContainer.value && settings.tdx_path.startsWith('/Volumes/')) return true
  return false
})
const settingsPathStatusText = computed(() => {
  if (!settings.data_root.trim()) return '行情根目录为空，下载、缓存扫描和研究都会无法执行。'
  if (runningInContainer.value) {
    return settings.tdx_path.startsWith('/Volumes/')
      ? '当前像 Docker 挂载路径；TDX 路径仍是宿主机 /Volumes，容器通常无法直接读取。建议在宿主机更新数据，Docker 只挂载数据目录。'
      : '当前像 Docker 挂载路径；文件夹选择只浏览容器可访问目录，宿主机 TDX 目录需通过挂载或本机更新脚本处理。'
  }
  if (config.value?.runtime === 'parallels') return '当前通过 Parallels/Windows 通达信链路读取代码表；移动硬盘路径变化后，先更新这里的 TDX 路径再刷新代码表缓存。'
  return '当前为本机链路；路径会保存到浏览器 localStorage，仅影响本机控制台。'
})
const directoryPickerStatusText = computed(() => {
  if (pickingDirectory.value) return `正在选择${directoryFieldLabel(pickingDirectory.value)}。`
  if (runningInContainer.value) return '文件夹选择只显示当前服务进程可访问的目录。'
  return '可以用系统选择器；失败时会自动打开服务端目录浏览器。'
})
const symbolCacheRefreshTitle = computed(() => {
  if (loadingSymbolGroups.value) return '代码表缓存正在更新'
  return '重新读取股票、ETF、指数列表并写入本地缓存'
})
const symbolGroupRefreshDisabledReason = computed(() => {
  if (loadingSymbolGroups.value) return '股票、ETF、指数列表正在更新'
  return ''
})
const symbolGroupRefreshDisabled = computed(() => Boolean(symbolGroupRefreshDisabledReason.value))
const pendingSymbolRefreshLabel = computed(() => {
  if (pendingSymbolRefreshTarget.value === 'index') return '指数列表'
  if (pendingSymbolRefreshTarget.value === 'etf') return 'ETF 列表'
  if (pendingSymbolRefreshTarget.value === 'all') return '股票 / ETF / 指数列表缓存'
  return ''
})
const pendingSymbolRefreshDisabledReason = computed(() => {
  if (!pendingSymbolRefreshTarget.value) return '当前没有待确认的代码表刷新操作'
  return symbolGroupRefreshDisabledReason.value
})
const pendingSymbolRefreshDisabled = computed(() => Boolean(pendingSymbolRefreshDisabledReason.value))
const pendingSymbolRefreshConfirmText = computed(() => {
  if (pendingSymbolRefreshDisabledReason.value) return pendingSymbolRefreshDisabledReason.value
  return `确认后将重新读取${pendingSymbolRefreshLabel.value}并写入本地缓存；移动硬盘或 Parallels 路径异常时会直接报错。`
})
const settingsActionWarning = computed(() => settingsPathWarning.value || loadingSymbolGroups.value || Boolean(pickingDirectory.value))
const settingsActionStateLabel = computed(() => {
  if (pickingDirectory.value) return '选择目录中'
  if (loadingSymbolGroups.value) return '更新代码表中'
  if (settingsPathWarning.value) return '请检查路径'
  return '可保存'
})
const settingsActionStatusText = computed(() => {
  if (loadingSymbolGroups.value) return symbolCacheRefreshTitle.value
  if (pickingDirectory.value) return directoryPickerStatusText.value
  return settingsPathStatusText.value
})
const resetSettingsConfirmText = computed(() => '将恢复 API 默认路径、下载参数、Fuyao/AI 设置和图表偏好；已保存到浏览器的当前配置会被移除。')
const settingsSaveTitle = computed(() => '保存路径、复权、批次、Fuyao Key 和运行参数到本机浏览器')
const aiSettingsActionWarning = computed(() => {
  if (!aiSettings.base_url.trim()) return '接口 URL 为空，AI 命令和 AI 工作台不可用。'
  if (!aiSettings.api_key.trim()) return 'API Key 为空，AI 命令和 AI 工作台不可用。'
  if (!aiSettings.model.trim()) return '模型为空，AI 命令和 AI 工作台不可用。'
  return ''
})
const aiSettingsActionStateLabel = computed(() => (aiSettingsActionWarning.value ? '待配置' : '可保存'))
const aiSettingsActionStatusText = computed(() => {
  if (aiSettingsActionWarning.value) return aiSettingsActionWarning.value
  return `将使用模型 ${aiSettings.model.trim()}；参数保存到本机浏览器 localStorage。`
})
const resetAiPromptSettingsConfirmText = computed(() => '将清空系统约束草稿、恢复默认卡片任务提示，并关闭自定义提示词开关。')
const aiSettingsSaveTitle = computed(() => '保存 AI 接口参数和自定义提示词到本机浏览器')
const topbarRefreshing = computed(() => loadingOverview.value || refreshingTopbar.value)
const topbarRefreshTitle = computed(() => {
  if (activeView.value === 'cache') return '扫描缓存并更新索引'
  if (activeView.value === 'tasks') return '刷新任务进度'
  if (activeView.value === 'download') return '刷新任务和缓存状态'
  return '刷新当前页面数据'
})
const topbarRefreshStatusText = computed(() => {
  if (activeView.value === 'cache') return '正在扫描缓存'
  if (activeView.value === 'tasks') return '正在刷新任务'
  if (activeView.value === 'download') return '正在同步任务和缓存'
  return '正在刷新页面数据'
})
const topbarRefreshConfirmText = computed(() => {
  if (activeView.value === 'cache') return '确认后将扫描缓存并更新 SQLite 索引；不会删除本地行情文件。'
  if (activeView.value === 'tasks') return '确认后将刷新任务进度、事件和结果表。'
  if (activeView.value === 'download') return '确认后将同步下载任务进度和缓存概览。'
  return '确认后将刷新当前页面的概览和任务状态。'
})
const overviewRefreshDisabledReason = computed(() => {
  if (loadingOverview.value) return '正在扫描缓存并更新索引'
  return ''
})
const overviewRefreshDisabled = computed(() => Boolean(overviewRefreshDisabledReason.value))
const overviewRefreshConfirmText = computed(() =>
  `确认后将扫描 ${compactPath(settings.data_root)} 的本地行情缓存并更新 SQLite 索引；不会删除本地行情文件。`
)
const directoryPickDisabledReason = computed(() => {
  if (pickingDirectory.value) return `正在选择${directoryFieldLabel(pickingDirectory.value)}`
  return ''
})
const directoryPickDisabled = computed(() => Boolean(directoryPickDisabledReason.value))
const etfTrackingRefreshDisabledReason = computed(() => {
  if (loadingEtfTracking.value) return '正在读取 TDX ETF 接口'
  return ''
})
const etfTrackingRefreshDisabled = computed(() => Boolean(etfTrackingRefreshDisabledReason.value))
const etfReturnsRefreshDisabledReason = computed(() => {
  if (loadingEtfReturns.value) return '正在计算 ETF 收益率'
  if (!etfTrackerReturnSymbols().length) return '当前没有可计算收益率的 ETF 标的'
  return ''
})
const etfReturnsRefreshDisabled = computed(() => Boolean(etfReturnsRefreshDisabledReason.value))
const pendingEtfRefreshDisabledReason = computed(() => {
  if (pendingEtfRefreshAction.value === 'tracking') return etfTrackingRefreshDisabledReason.value
  if (pendingEtfRefreshAction.value === 'returns') return etfReturnsRefreshDisabledReason.value
  return '当前没有待确认的 ETF 刷新操作'
})
const pendingEtfRefreshDisabled = computed(() => Boolean(pendingEtfRefreshDisabledReason.value))
const pendingEtfRefreshConfirmText = computed(() => {
  if (pendingEtfRefreshDisabledReason.value) return pendingEtfRefreshDisabledReason.value
  if (pendingEtfRefreshAction.value === 'tracking') {
    return '确认后将重新读取 TDX ETF 跟踪接口并更新浏览器缓存；完成后会尝试刷新收益率缓存。'
  }
  if (pendingEtfRefreshAction.value === 'returns') {
    return `确认后将按当前 ${formatInt(etfTrackerReturnSymbols().length)} 只 ETF 重新计算当日、近5日、近20日、近50日和 YTD 收益率。`
  }
  return ''
})
const aiCommandDisabledReason = computed(() => {
  if (runningAiCommand.value) return '正在解析上一条命令'
  if (aiCommandResultState.value === 'pending') return '请先确认或取消当前 AI 命令解析结果'
  if (!aiCommandForm.text.trim()) return '先输入要执行的自然语言命令'
  return ''
})
const aiCommandDisabled = computed(() => Boolean(aiCommandDisabledReason.value))
const aiCommandHasWarnings = computed(() => Boolean((aiCommandResult.value?.warnings || []).length))
const aiCommandPatchCount = computed(() => (Array.isArray(aiCommandResult.value?.patches) ? aiCommandResult.value?.patches.length || 0 : 0))
const aiCommandApplyDisabledReason = computed(() => {
  if (runningAiCommand.value) return '正在解析命令，请稍候'
  if (aiCommandResultState.value !== 'pending') return '当前没有待确认的 AI 命令结果'
  if (!aiCommandResult.value) return '当前没有可应用的 AI 命令结果'
  if (!aiCommandPatchCount.value) return '解析结果没有可应用参数'
  return ''
})
const aiCommandApplyDisabled = computed(() => Boolean(aiCommandApplyDisabledReason.value))
const aiCommandApplyConfirmText = computed(() =>
  `确认后将应用 ${formatInt(aiCommandPatchCount.value)} 项 AI 命令参数变更。`
)
const aiCommandRunConfirmText = computed(() =>
  aiConfigReady.value
    ? `确认后将使用模型 ${aiSettings.model.trim()} 解析当前命令；解析结果仍需再次确认才会应用。`
    : '确认后将使用本地规则解析当前命令；解析结果仍需再次确认才会应用。'
)
const aiCommandStatusText = computed(() => {
  if (runningAiCommand.value) return '正在解析意图、匹配本地参数并准备应用。'
  if (confirmingRunAiCommand.value) return aiCommandRunConfirmText.value
  if (!aiCommandForm.text.trim()) return '输入命令后，会先解析为本地可执行参数；涉及股票池时优先使用本地索引。'
  if (!aiCommandResult.value) return aiConfigReady.value ? '将使用已保存模型参数；股票筛选仍由本地结构化数据执行。' : '未配置模型时会使用本地规则规划。'
  if (aiCommandResultState.value === 'pending') return `命令已解析，确认后才会应用 ${formatInt(aiCommandPatchCount.value)} 项参数变更。`
  if (aiCommandResultState.value === 'cancelled') return 'AI 命令参数未修改。'
  if (aiCommandResultState.value === 'empty') return '命令已解析，但没有可应用参数。'
  if (aiCommandHasWarnings.value) return '命令已应用，但存在警告需要复核。'
  return '命令已应用到当前页面。'
})
const aiSkillPromptClearDisabledReason = computed(() => {
  if (!aiWorkbenchForm.skill_prompt.trim()) return '当前没有已载入 Skill 提示词'
  return ''
})
const aiSkillPromptClearDisabled = computed(() => Boolean(aiSkillPromptClearDisabledReason.value))
const aiSkillPromptClearConfirmTitle = computed(() => '确认清空当前 Skill 提示词')
const aiSkillPromptClearConfirmText = computed(() => '将清空当前 AI 工作台侧载 Skill 提示词；不会删除本地 skill 文件。')
const downloadActionReadyReason = computed(() => {
  if (!parsedSymbols.value.length) return '请填写或选择至少 1 个标的代码'
  if (!selectedDownloadTimeframes.value.length) return '请至少选择 1 个下载周期'
  if (!settings.start || !settings.end) return '请填写开始和结束日期'
  if (settings.start > settings.end) return '开始日期不能晚于结束日期'
  if (!settings.data_root.trim()) return '请填写行情根目录'
  return ''
})
const downloadActionReady = computed(() => !downloadActionReadyReason.value)
const downloadActionWarning = computed(() => {
  if (!downloadActionReady.value) return ''
  if (!planRows.value.length) return '尚未预览计划，执行下载前建议先查看缺口。'
  return ''
})
const downloadActionStatusText = computed(() => {
  if (planning.value) return '正在比较任务交易日与本地缓存，生成可翻页下载计划。'
  if (downloading.value) return '正在提交后台任务，提交后会跳转到执行记录。'
  return downloadActionReadyReason.value || downloadActionWarning.value || `当前将处理 ${formatInt(parsedSymbols.value.length)} 个标的、${downloadTimeframeSummary.value}。`
})
const previewPlanDisabledReason = computed(() => {
  if (planning.value) return '下载计划正在生成'
  if (downloading.value) return '下载任务提交中'
  return downloadActionReadyReason.value
})
const previewPlanDisabled = computed(() => Boolean(previewPlanDisabledReason.value))
const previewPlanConfirmText = computed(() =>
  `确认后将只读比较 ${formatInt(parsedSymbols.value.length)} 个标的、${downloadTimeframeSummary.value}、${settings.start} 至 ${settings.end} 的本地缓存缺口；不会提交下载任务。`
)
const startDownloadDisabledReason = computed(() => {
  if (downloading.value) return '下载任务提交中'
  if (planning.value) return '请等待当前计划生成完成'
  return downloadActionReadyReason.value
})
const startDownloadDisabled = computed(() => Boolean(startDownloadDisabledReason.value))
const downloadBusyStatusText = computed(() => {
  if (planning.value) return '生成下载计划中'
  if (downloading.value) return '提交后台任务中'
  return ''
})
const startDownloadRequestTitle = computed(() => '进入确认状态，确认后才提交后台下载任务')
const startDownloadConfirmTitle = computed(() => `确认提交下载：${formatInt(parsedSymbols.value.length)} 个标的，${downloadTimeframeSummary.value}，${settings.start} 至 ${settings.end}`)
const startDownloadConfirmStatusText = computed(() => {
  const previewHint = planRows.value.length ? `当前预览计划 ${formatInt(planRows.value.length)} 条。` : '尚未预览计划。'
  return `${previewHint} 确认后将提交后台任务并写入本地行情缓存。`
})
const latestTask = computed(() => tasks.value[0])
const latestTaskText = computed(() => latestTask.value ? latestTask.value.status : '无')
const clearTasksDisabledReason = computed(() => {
  if (clearingTasks.value) return '任务历史正在清理'
  if (!tasks.value.length) return '当前没有任务历史'
  return ''
})
const clearTasksDisabled = computed(() => Boolean(clearTasksDisabledReason.value))
const clearTasksConfirmTitle = computed(() => `确认清理当前 ${formatInt(tasks.value.length)} 条任务记录；该操作只清理页面历史，不删除本地行情数据。`)
const clearTasksConfirmStatusText = computed(() => {
  if (clearingTasks.value) return '正在清理任务历史，请稍候。'
  return `将清理当前 ${formatInt(tasks.value.length)} 条任务记录；不会删除本地行情数据。`
})
const clearTasksCancelDisabledReason = computed(() => {
  if (clearingTasks.value) return '任务历史正在清理，暂不能取消'
  return ''
})
const clearTasksCancelDisabled = computed(() => Boolean(clearTasksCancelDisabledReason.value))
const clearTasksConfirmDisabledReason = computed(() => {
  if (clearingTasks.value) return '任务历史正在清理'
  if (!confirmingClearTasks.value) return '请先点击清空历史进入确认状态'
  if (!tasks.value.length) return '当前没有任务历史'
  return ''
})
const clearTasksConfirmDisabled = computed(() => Boolean(clearTasksConfirmDisabledReason.value))
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) || tasks.value[0] || null)
const selectedTaskControlText = computed(() => {
  if (!selectedTask.value) return '未选择任务'
  const control = selectedTask.value.control && selectedTask.value.control !== 'run' ? ` · ${selectedTask.value.control}` : ''
  return `${taskStatusLabel(selectedTask.value.status)}${control}`
})
const selectedTaskEvents = computed(() =>
  (selectedTask.value?.events || []).map((event: Record<string, any>, index: number) => ({
    key: `${index}-${event.time || event.stage || event.label || ''}`,
    index: index + 1,
    stage: String(event.stage || ''),
    label: String(event.label || event.stage || '-'),
    message: taskEventMessage(event),
    time: formatDateTimeText(event.time),
    visible: event.visible !== false,
    raw: event
  }))
)
const selectedTaskProgress = computed(() => taskProgressState(selectedTask.value))
const latestTaskProgress = computed(() => taskProgressState(latestTask.value))
const visibleTaskEvents = computed(() =>
  selectedTaskEvents.value.filter(isVisibleTaskEvent).slice(Math.max(0, selectedTaskEvents.value.filter(isVisibleTaskEvent).length - TASK_EVENT_WINDOW_SIZE))
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

function isVisibleTaskEvent(event: TaskEventItem) {
  if (!event.visible) return false
  return true
}

function taskEventMessage(event: Record<string, any>) {
  const message = String(event.message || '').trim()
  if (message) return message
  const current = Number(event.progress_current || event.step_index || event.window_step_index || 0)
  const total = Number(event.progress_total || event.step_count || event.window_step_count || 0)
  const parts: string[] = []
  if (Number.isFinite(current) && Number.isFinite(total) && current > 0 && total > 0) {
    parts.push(`进度 ${formatInt(current)} / ${formatInt(total)}`)
  }
  if (event.symbol_count) parts.push(`${formatInt(Number(event.symbol_count))} 只标的`)
  if (event.rows || event.rows_returned) parts.push(`${formatInt(Number(event.rows || event.rows_returned))} 行`)
  const start = String(event.start || event.window_start || '').trim()
  const end = String(event.end || event.window_end || '').trim()
  if (start || end) parts.push(`${start || '-'} 至 ${end || '-'}`)
  return parts.join(' · ') || String(event.stage || '-')
}

function taskProgressState(task: TaskPayload | null | undefined): TaskProgressState | null {
  if (!task) return null
  const progressEvent = [...(task.events || [])].reverse().find((event) => Number(event.progress_total || 0) > 0)
  if (!progressEvent && !['succeeded', 'failed', 'cancelled'].includes(task.status)) return null
  const current = Number(progressEvent?.progress_current || 0)
  const total = Number(progressEvent?.progress_total || 0)
  const rawRatio = Number(progressEvent?.progress_ratio)
  const ratio = task.status === 'succeeded'
    ? 1
    : total > 0
      ? clampRatio(Number.isFinite(rawRatio) ? rawRatio : current / total)
      : 0
  const percent = Math.round(ratio * 100)
  const title = progressEvent
    ? String(progressEvent.label || progressEvent.stage || '当前进度')
    : taskStatusLabel(task.status)
  const detail = progressEvent ? taskEventMessage(progressEvent) : task.error || taskStatusLabel(task.status)
  const time = formatDateTimeText(progressEvent?.time || task.finished_at || task.started_at || task.created_at)
  const statusClass = task.status === 'failed'
    ? 'negative'
    : task.status === 'cancelled'
      ? 'warning'
      : task.status === 'succeeded'
        ? 'positive'
        : 'running'
  return {
    title,
    detail,
    time,
    percentText: `${percent}%`,
    barWidth: `${percent}%`,
    statusClass,
    ariaLabel: `${title}，${percent}%`
  }
}

function clampRatio(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}
const parsedSymbols = computed(() => parseSymbols(symbolsText.value))
const allAssetSymbols = computed(() =>
  uniqueStringsInOrder((config.value?.symbol_groups || []).flatMap((group) => group.symbols))
)
const pendingDownloadSymbolGroupRecord = computed(() =>
  pendingDownloadSymbolGroup.value
    ? config.value?.symbol_groups.find((group) => group.name === pendingDownloadSymbolGroup.value) || null
    : null
)
const downloadSymbolGroupConfirmDisabledReason = computed(() => {
  if (!pendingDownloadSymbolGroup.value) return '当前没有待确认的代码来源'
  if (!pendingDownloadSymbolGroupRecord.value) return '待应用的代码来源不存在，请重新选择'
  if (!pendingDownloadSymbolGroupRecord.value.symbols.length) return '待应用的代码来源没有标的'
  return ''
})
const downloadSymbolGroupConfirmDisabled = computed(() => Boolean(downloadSymbolGroupConfirmDisabledReason.value))
const downloadSymbolGroupConfirmText = computed(() => {
  if (downloadSymbolGroupConfirmDisabledReason.value) return downloadSymbolGroupConfirmDisabledReason.value
  const group = pendingDownloadSymbolGroupRecord.value
  return `确认后将用“${group?.name || pendingDownloadSymbolGroup.value}”的 ${formatInt(group?.symbols.length || 0)} 只标的覆盖当前 ${formatInt(parsedSymbols.value.length)} 只下载标的。`
})
const allAssetsUpdateDisabledReason = computed(() => {
  if (!allAssetSymbols.value.length) return '代码库为空，先刷新代码表缓存'
  return ''
})
const allAssetsUpdateDisabled = computed(() => Boolean(allAssetsUpdateDisabledReason.value))
const allAssetsUpdateDays = computed(() =>
  Math.max(1, Math.trunc(Number(allAssetsLookbackDays.value) || DEFAULT_ALL_ASSETS_LOOKBACK_DAYS))
)
const allAssetsUpdateConfirmText = computed(() =>
  `将覆盖下载任务的标的、开始日期、结束日期并清空当前预览计划；共 ${formatInt(allAssetSymbols.value.length)} 只资产，近 ${allAssetsUpdateDays.value} 个交易日。`
)
const aiSymbolGroups = computed(() => (config.value?.symbol_groups || []).filter((group) => group.symbols.length > 0))
const aiCurrentSymbolGroup = computed(() => {
  const groups = aiSymbolGroups.value
  return groups.find((group) => group.name === aiSymbolGroupName.value) || groups[0] || null
})
const aiSelectedSymbols = computed(() => parseSymbols(aiWorkbenchForm.symbols))
const aiSelectedSymbolSet = computed(() => new Set(aiSelectedSymbols.value))
const aiSymbolMetricMap = computed(() => {
  const metrics = new Map<string, Record<string, any>>()
  aiSymbolMetricRows.value.forEach((row: Record<string, any>) => {
    const symbol = normalizeSymbol(String(row.symbol || row.stock_code || ''))
    if (symbol) metrics.set(symbol, row)
  })
  return metrics
})
const aiCurrentSymbolRows = computed(() =>
  uniqueStringsInOrder(aiCurrentSymbolGroup.value?.symbols || []).map((symbol) => {
    const normalized = normalizeSymbol(symbol)
    const meta = cacheSymbolMeta.value.get(normalized)
    const name = symbolNameMap.value.get(normalized) || meta?.name || ''
    const assetType = meta?.assetType || guessAssetType(normalized, name, aiCurrentSymbolGroup.value?.name || '')
    const metrics = aiSymbolMetricMap.value.get(normalized) || {}
    return {
      symbol: normalized,
      name,
      assetType,
      assetLabel: assetTypeLabel(assetType),
      selected: aiSelectedSymbolSet.value.has(normalized),
      latestDate: formatDateOnly(metrics.latest_date),
      close: finiteNumberOrNull(metrics.close),
      amount: finiteNumberOrNull(metrics.amount),
      volume: finiteNumberOrNull(metrics.volume),
      marketValue: finiteNumberOrNull(metrics.market_value),
      turnoverRate: finiteNumberOrNull(metrics.turnover_rate)
    }
  }).filter((row) => row.symbol)
)
const aiFilteredSymbolRows = computed(() => {
  const keyword = aiSymbolKeyword.value.trim().toLowerCase()
  if (!keyword) return aiCurrentSymbolRows.value
  return aiCurrentSymbolRows.value.filter((row) =>
    `${row.symbol} ${row.name} ${row.assetType} ${row.assetLabel}`.toLowerCase().includes(keyword)
  )
})
const aiSortedSymbolRows = computed(() => {
  const rows = [...aiFilteredSymbolRows.value]
  const key = aiSymbolSort.key
  const direction = aiSymbolSort.direction
  return rows.sort((left, right) => {
    const result = compareAiSymbolValues(left[key], right[key])
    return direction === 'asc' ? result : -result
  })
})
const aiSymbolTotalPages = computed(() => Math.max(1, Math.ceil(aiSortedSymbolRows.value.length / aiSymbolPagination.pageSize)))
const aiSymbolPageStartIndex = computed(() =>
  aiSortedSymbolRows.value.length ? (aiSymbolPagination.page - 1) * aiSymbolPagination.pageSize : 0
)
const aiSymbolPageEnd = computed(() =>
  Math.min(aiSymbolPageStartIndex.value + aiSymbolPagination.pageSize, aiSortedSymbolRows.value.length)
)
const aiSymbolPageFirst = computed(() => (aiSortedSymbolRows.value.length ? aiSymbolPageStartIndex.value + 1 : 0))
const aiPagedSymbolRows = computed(() => aiSortedSymbolRows.value.slice(aiSymbolPageStartIndex.value, aiSymbolPageEnd.value))
const aiSymbolPageSizeOptions = AI_SYMBOL_PAGE_SIZE_OPTIONS
const aiSymbolControlsDisabledReason = computed(() => {
  if (pendingAiSymbolRunAction.value) return '请先确认或取消当前 AI 标的运行操作'
  if (pendingAiSymbolAction.value) return '请先确认或取消当前 AI 标的操作'
  if (confirmingClearAiSymbols.value) return '请先确认或取消清空已选标的'
  return ''
})
const aiSymbolMetricsDisabledReason = computed(() => {
  if (loadingAiSymbolMetrics.value) return '当前标的池指标正在刷新'
  if (!aiCurrentSymbolRows.value.length) return '当前分组没有可刷新标的'
  return ''
})
const aiSymbolMetricsDisabled = computed(() => Boolean(aiSymbolMetricsDisabledReason.value))
const aiSymbolTopNCount = computed(() => Math.max(1, Math.trunc(Number(aiSymbolTopN.value) || 1)))
const aiSymbolTopNDisabledReason = computed(() => {
  if (!aiSortedSymbolRows.value.length) return '当前表格没有可选标的'
  return ''
})
const aiSymbolTopNDisabled = computed(() => Boolean(aiSymbolTopNDisabledReason.value))
const aiSymbolTopNActionTitle = computed(() =>
  `按当前排序选中前 ${formatInt(Math.min(aiSymbolTopNCount.value, aiSortedSymbolRows.value.length))} 只`
)
const aiSymbolFilterDisabledReason = computed(() => {
  if (runningAiSymbolFilter.value) return 'AI 筛选正在执行'
  if (pendingAiSymbolAction.value) return '请先确认或取消当前 AI 标的操作'
  if (!aiSymbolNaturalQuery.value.trim()) return '请先输入筛选条件'
  if (!aiCurrentSymbolRows.value.length) return '当前分组没有可筛选标的'
  return ''
})
const aiSymbolFilterDisabled = computed(() => Boolean(aiSymbolFilterDisabledReason.value))
const aiSymbolRunPendingActionLabel = computed(() => {
  const labels: Record<AiSymbolRunPendingAction, string> = {
    '': '',
    metrics: '刷新指标',
    filter: 'AI 筛选'
  }
  return labels[pendingAiSymbolRunAction.value]
})
const aiSymbolRunPendingDisabledReason = computed(() => {
  if (pendingAiSymbolRunAction.value === 'metrics') return aiSymbolMetricsDisabledReason.value
  if (pendingAiSymbolRunAction.value === 'filter') return aiSymbolFilterDisabledReason.value
  return '当前没有待确认的 AI 标的运行操作'
})
const aiSymbolRunPendingDisabled = computed(() => Boolean(aiSymbolRunPendingDisabledReason.value))
const aiSymbolRunPendingText = computed(() => {
  if (aiSymbolRunPendingDisabledReason.value) return aiSymbolRunPendingDisabledReason.value
  if (pendingAiSymbolRunAction.value === 'metrics') {
    return `确认后将刷新“${aiCurrentSymbolGroup.value?.name || '当前分组'}” ${formatInt(aiCurrentSymbolRows.value.length)} 只标的的最新行情指标。`
  }
  if (pendingAiSymbolRunAction.value === 'filter') {
    return `确认后将解析“${aiSymbolNaturalQuery.value.trim()}”，并在“${aiCurrentSymbolGroup.value?.name || '当前分组'}” ${formatInt(aiCurrentSymbolRows.value.length)} 只标的中执行筛选。`
  }
  return ''
})
const pendingAiSymbolFilterSymbols = computed(() => {
  const patches = pendingAiSymbolFilterResult.value?.patches || []
  const patch = Array.isArray(patches)
    ? patches.find((item: Record<string, any>) => String(item.target || '') === 'aiWorkbenchForm.symbols')
    : null
  return parseSymbols(String(patch?.value || ''))
})
const aiSymbolReplaceGroupDisabledReason = computed(() => {
  if (!aiCurrentSymbolRows.value.length) return '当前分组没有可替换标的'
  return ''
})
const aiSymbolReplaceGroupDisabled = computed(() => Boolean(aiSymbolReplaceGroupDisabledReason.value))
const aiSymbolAppendFilteredDisabledReason = computed(() => {
  if (!aiFilteredSymbolRows.value.length) return '当前筛选结果为空'
  return ''
})
const aiSymbolAppendFilteredDisabled = computed(() => Boolean(aiSymbolAppendFilteredDisabledReason.value))
const aiSymbolAppendPageDisabledReason = computed(() => {
  if (!aiPagedSymbolRows.value.length) return '当前页没有可追加标的'
  return ''
})
const aiSymbolAppendPageDisabled = computed(() => Boolean(aiSymbolAppendPageDisabledReason.value))
const aiSymbolPendingActionLabel = computed(() => {
  const labels: Record<AiSymbolPendingAction, string> = {
    '': '',
    topN: '选中前 N',
    replaceGroup: '替换本类',
    appendFiltered: '追加当前筛选',
    appendPage: '追加本页',
    filterResult: '载入 AI 筛选结果'
  }
  return labels[pendingAiSymbolAction.value]
})
const aiSymbolPendingActionDisabledReason = computed(() => {
  if (pendingAiSymbolAction.value === 'filterResult') {
    if (!pendingAiSymbolFilterResult.value) return '当前没有待确认的 AI 筛选结果'
    if (!pendingAiSymbolFilterSymbols.value.length) return 'AI 筛选结果没有可载入标的'
    return ''
  }
  if (pendingAiSymbolAction.value === 'topN') return aiSymbolTopNDisabledReason.value
  if (pendingAiSymbolAction.value === 'replaceGroup') return aiSymbolReplaceGroupDisabledReason.value
  if (pendingAiSymbolAction.value === 'appendFiltered') return aiSymbolAppendFilteredDisabledReason.value
  if (pendingAiSymbolAction.value === 'appendPage') return aiSymbolAppendPageDisabledReason.value
  return '请先选择要确认的 AI 标的操作'
})
const aiSymbolPendingActionDisabled = computed(() => Boolean(aiSymbolPendingActionDisabledReason.value))
const aiSymbolPendingActionText = computed(() => {
  const currentCount = aiSelectedSymbols.value.length
  if (pendingAiSymbolAction.value === 'topN') {
    return `将用当前排序前 ${formatInt(Math.min(aiSymbolTopNCount.value, aiSortedSymbolRows.value.length))} 只覆盖 AI 工作台当前 ${formatInt(currentCount)} 只标的。`
  }
  if (pendingAiSymbolAction.value === 'replaceGroup') {
    return `将用“${aiCurrentSymbolGroup.value?.name || '当前分类'}”的 ${formatInt(aiCurrentSymbolRows.value.length)} 只标的覆盖 AI 工作台当前 ${formatInt(currentCount)} 只。`
  }
  if (pendingAiSymbolAction.value === 'appendFiltered') {
    return `将把当前筛选结果 ${formatInt(aiFilteredSymbolRows.value.length)} 只追加到 AI 工作台，当前已选 ${formatInt(currentCount)} 只。`
  }
  if (pendingAiSymbolAction.value === 'appendPage') {
    return `将把当前页 ${formatInt(aiPagedSymbolRows.value.length)} 只追加到 AI 工作台，当前已选 ${formatInt(currentCount)} 只。`
  }
  if (pendingAiSymbolAction.value === 'filterResult') {
    const totalCount = Number(pendingAiSymbolFilterResult.value?.selected_symbol_count || pendingAiSymbolFilterSymbols.value.length)
    return `AI 筛选匹配 ${formatInt(totalCount)} 只，确认后将载入 ${formatInt(pendingAiSymbolFilterSymbols.value.length)} 只并覆盖当前 ${formatInt(currentCount)} 只标的。`
  }
  return ''
})
const aiSymbolClearDisabledReason = computed(() => {
  if (!aiSelectedSymbols.value.length) return '当前没有已选标的'
  return ''
})
const aiSymbolClearDisabled = computed(() => Boolean(aiSymbolClearDisabledReason.value))
const aiSymbolClearConfirmTitle = computed(() => `确认清空 AI 工作台当前 ${formatInt(aiSelectedSymbols.value.length)} 只已选标的`)
const aiSymbolClearConfirmStatusText = computed(() =>
  `将清空 AI 工作台当前 ${formatInt(aiSelectedSymbols.value.length)} 只已选标的；不会删除本地行情数据。`
)
const aiSymbolActionBusy = computed(() => loadingAiSymbolMetrics.value || runningAiSymbolFilter.value)
const aiSymbolActionWarning = computed(() =>
  aiSymbolMetricsDisabledReason.value ||
  aiSymbolTopNDisabledReason.value ||
  aiSymbolFilterDisabledReason.value ||
  aiSymbolReplaceGroupDisabledReason.value ||
  aiSymbolClearDisabledReason.value
)
const aiSymbolActionStatusText = computed(() => {
  if (loadingAiSymbolMetrics.value) return `正在刷新 ${formatInt(aiCurrentSymbolRows.value.length)} 只标的的最新行情指标。`
  if (runningAiSymbolFilter.value) return '正在解析筛选条件，并用本地结构化数据执行选股。'
  const availableActions: string[] = []
  if (!aiSymbolMetricsDisabledReason.value) availableActions.push('刷新指标')
  if (!aiSymbolTopNDisabledReason.value) availableActions.push('选前 N')
  if (!aiSymbolFilterDisabledReason.value) availableActions.push('AI 筛选')
  if (!aiSymbolAppendFilteredDisabledReason.value) availableActions.push('追加筛选')
  if (!aiSymbolAppendPageDisabledReason.value) availableActions.push('追加本页')
  if (!aiSymbolReplaceGroupDisabledReason.value) availableActions.push('替换本类')
  if (!aiSymbolClearDisabledReason.value) availableActions.push('清空已选')
  if (availableActions.length) {
    return `${availableActions.join('、')}可执行；当前已选 ${formatInt(aiSelectedSymbols.value.length)} 只。`
  }
  return '当前没有可操作标的，请切换分组或刷新代码表缓存。'
})
const aiWorkbenchContextSummary = computed(() => {
  const range = `${aiWorkbenchForm.start || '-'} 至 ${aiWorkbenchForm.end || '-'}`
  const skill = aiWorkbenchForm.skill_prompt.trim() ? 'Skill 已载入' : '无 Skill'
  const symbols = aiSelectedSymbols.value.length ? `已选 ${formatInt(aiSelectedSymbols.value.length)} 只` : '未选标的'
  return `${symbols} · ${aiWorkbenchForm.timeframe} · ${range} · ${skill}`
})
const aiWorkbenchDataSummary = computed(() => {
  const symbols = aiSelectedSymbols.value.length ? `已选 ${formatInt(aiSelectedSymbols.value.length)} 只` : '未选标的'
  return `${aiWorkbenchForm.timeframe} · ${symbols}`
})
const aiWorkbenchLoadSourceSymbols = computed(() => parseSymbols(reviewForm.symbols || symbolsText.value))
const aiWorkbenchLoadSymbolsDisabledReason = computed(() => {
  if (!aiWorkbenchLoadSourceSymbols.value.length) return '复盘标的和下载任务标的都为空'
  return ''
})
const aiWorkbenchLoadSymbolsDisabled = computed(() => Boolean(aiWorkbenchLoadSymbolsDisabledReason.value))
const aiWorkbenchLoadSymbolsConfirmText = computed(() => {
  const sourceLabel = parseSymbols(reviewForm.symbols).length ? '多股复盘标的' : '下载任务标的'
  return `将用 ${sourceLabel} 覆盖 AI 工作台当前标的，共 ${formatInt(aiWorkbenchLoadSourceSymbols.value.length)} 只。`
})
const aiWorkbenchStatusLabel = computed(() => {
  if (!aiConfigReady.value) return '未配置模型'
  if (aiWorkbenchStreamStatus.value === 'preparing') return '整理本地行情'
  if (aiWorkbenchStreamStatus.value === 'streaming') return '模型生成中'
  if (aiWorkbenchStreamStatus.value === 'done') return '已完成'
  if (aiWorkbenchStreamStatus.value === 'error') return '运行失败'
  return aiWorkbenchResult.value ? '结果已就绪' : '等待发送'
})
const aiWorkbenchResultVisible = computed(() => Boolean(aiWorkbenchResult.value || aiWorkbenchStreamText.value))
const aiWorkbenchRunDisabledReason = computed(() => {
  if (runningAiWorkbench.value) return 'AI 模块正在运行'
  if (!aiConfigReady.value) return '请先在系统设置里填写接口 URL、API Key 和模型'
  if (!aiSelectedSymbols.value.length) return '请先在标的池选择或手动输入至少 1 个代码'
  if (!aiWorkbenchForm.prompt.trim()) return '请先填写任务目标'
  return ''
})
const aiWorkbenchRunDisabled = computed(() => Boolean(aiWorkbenchRunDisabledReason.value))
const aiWorkbenchRunConfirmText = computed(() =>
  `确认后将发送 ${formatInt(aiSelectedSymbols.value.length)} 只标的、${aiWorkbenchForm.timeframe}、${aiWorkbenchForm.start || '-'} 至 ${aiWorkbenchForm.end || '-'} 的本地行情上下文给模型。`
)
const aiWorkbenchRunStatusText = computed(() => {
  if (runningAiWorkbench.value) return aiWorkbenchStatusLabel.value
  if (aiWorkbenchRunDisabledReason.value) return aiWorkbenchRunDisabledReason.value
  return `将发送 ${formatInt(aiSelectedSymbols.value.length)} 只标的的本地行情上下文。`
})
const researchBusyStatusText = computed(() => {
  const labels: Record<string, string> = {
    history: '历史相似搜索中',
    cross: '横截面相似搜索中',
    review: '多股复盘生成中',
    etf: 'ETF 趋势对比生成中',
    regime: '市场风险偏好研究中'
  }
  return labels[runningResearch.value] || '研究任务运行中'
})
const downloadTimeframeOptions = computed(() => sortTimeframes(config.value?.timeframes || Object.keys(TIMEFRAME_DIR_NAMES)))
const selectedDownloadTimeframes = computed(() => normalizeDownloadTimeframes(selectedTimeframes.value))
const downloadTimeframeSummary = computed(() => {
  const selected = selectedDownloadTimeframes.value
  if (!selected.length) return '未选择'
  if (selected.length === downloadTimeframeOptions.value.length) return `全周期 ${selected.length}`
  return selected.join(' / ')
})
const downloadTimeframePendingSelection = computed(() => {
  if (pendingDownloadTimeframeAction.value === 'all') return [...downloadTimeframeOptions.value]
  if (pendingDownloadTimeframeAction.value === 'default') {
    return normalizeDownloadTimeframes(config.value?.defaults?.timeframes || ['1d'])
  }
  return []
})
const downloadTimeframePendingDisabledReason = computed(() => {
  if (!pendingDownloadTimeframeAction.value) return '当前没有待确认的下载周期修改'
  if (!downloadTimeframePendingSelection.value.length) return '当前没有可应用的下载周期'
  return ''
})
const downloadTimeframePendingDisabled = computed(() => Boolean(downloadTimeframePendingDisabledReason.value))
const downloadTimeframePendingText = computed(() => {
  if (downloadTimeframePendingDisabledReason.value) return downloadTimeframePendingDisabledReason.value
  const label = pendingDownloadTimeframeAction.value === 'all' ? '全周期' : '默认周期'
  return `确认后将下载周期改为${label}：${downloadTimeframePendingSelection.value.join(' / ')}，并清空当前预览计划。`
})
const downloadDateShortcutPendingRange = computed(() =>
  pendingDownloadDateShortcut.value ? dateRangeForShortcut(pendingDownloadDateShortcut.value) : { start: '', end: '' }
)
const downloadDateShortcutPendingLabel = computed(() =>
  DATE_RANGE_SHORTCUTS.find((item) => item.key === pendingDownloadDateShortcut.value)?.label || ''
)
const downloadDateShortcutPendingDisabledReason = computed(() => {
  if (!pendingDownloadDateShortcut.value) return '当前没有待确认的日期快捷修改'
  if (!downloadDateShortcutPendingRange.value.start || !downloadDateShortcutPendingRange.value.end) return '日期快捷没有可应用区间'
  return ''
})
const downloadDateShortcutPendingDisabled = computed(() => Boolean(downloadDateShortcutPendingDisabledReason.value))
const downloadDateShortcutPendingText = computed(() => {
  if (downloadDateShortcutPendingDisabledReason.value) return downloadDateShortcutPendingDisabledReason.value
  return `确认后将下载日期改为${downloadDateShortcutPendingLabel.value}：${downloadDateShortcutPendingRange.value.start} 至 ${downloadDateShortcutPendingRange.value.end}，并清空当前预览计划。`
})
const researchDateShortcutPendingRange = computed(() =>
  pendingResearchDateShortcut.value ? dateRangeForShortcut(pendingResearchDateShortcut.value.key) : { start: '', end: '' }
)
const researchDateShortcutPendingLabel = computed(() =>
  DATE_RANGE_SHORTCUTS.find((item) => item.key === pendingResearchDateShortcut.value?.key)?.label || ''
)
const researchDateShortcutPendingTargetLabel = computed(() => {
  const target = pendingResearchDateShortcut.value?.target
  if (target === 'history') return '历史相似窗口'
  if (target === 'crossTarget') return '横截面目标窗口'
  if (target === 'crossCandidate') return '横截面候选区间'
  if (target === 'review') return '多股复盘区间'
  if (target === 'etf') return 'ETF 趋势区间'
  if (target === 'regime') return '市场风偏区间'
  return '研究日期'
})
const researchDateShortcutPendingDisabledReason = computed(() => {
  if (!pendingResearchDateShortcut.value) return '当前没有待确认的研究日期快捷修改'
  if (
    pendingResearchDateShortcut.value.target === 'crossCandidate' &&
    crossCandidateRangeDisabledReason.value
  ) return crossCandidateRangeDisabledReason.value
  if (!researchDateShortcutPendingRange.value.start || !researchDateShortcutPendingRange.value.end) return '日期快捷没有可应用区间'
  return ''
})
const researchDateShortcutPendingText = computed(() => {
  if (researchDateShortcutPendingDisabledReason.value) return researchDateShortcutPendingDisabledReason.value
  return `确认后将${researchDateShortcutPendingTargetLabel.value}改为${researchDateShortcutPendingLabel.value}：${researchDateShortcutPendingRange.value.start} 至 ${researchDateShortcutPendingRange.value.end}；旧研究结果不会自动刷新。`
})
const priceTableSymbolCount = computed(() => parseSymbols(priceTableForm.symbols).length)
const priceTableDateRangeReason = computed(() => {
  if (!priceTableForm.start || !priceTableForm.end) return '请填写开始和结束日期'
  if (priceTableForm.start > priceTableForm.end) return '开始日期不能晚于结束日期'
  return ''
})
const priceTableActionDisabledReason = computed(() => {
  if (loadingPriceTable.value) return '股票数据表正在读取'
  if (!priceTableSymbolCount.value) return '请填写至少 1 个股票代码'
  return priceTableDateRangeReason.value
})
const priceTableActionDisabled = computed(() => Boolean(priceTableActionDisabledReason.value))
const priceTableActionStatusText = computed(() => {
  if (loadingPriceTable.value) return '正在读取 K 线、补算缺失指标并刷新表格。'
  if (priceTableActionDisabledReason.value) return priceTableActionDisabledReason.value
  const indicatorText = selectedPriceIndicators.value.length ? `，附带 ${formatInt(selectedPriceIndicators.value.length)} 个指标` : ''
  return `将读取 ${formatInt(priceTableSymbolCount.value)} 个代码、${priceTableForm.timeframe}、${priceTableForm.start} 至 ${priceTableForm.end}${indicatorText}。`
})
const priceTableLoadConfirmText = computed(() => `${priceTableActionStatusText.value} 本次只刷新页面表格，不写入行情文件。`)
const priceTableCommonIndicatorsConfirmText = computed(() =>
  `确认后将指标列改为 ma5、ma10、ma20；当前已选 ${formatInt(selectedPriceIndicators.value.length)} 个指标。`
)
const indicatorImportDisabledReason = computed(() => {
  if (importingIndicatorFormula.value) return '指标公式正在导入'
  if (!indicatorImportForm.text.trim()) return '请先粘贴通达信公式文本'
  return ''
})
const indicatorImportDisabled = computed(() => Boolean(indicatorImportDisabledReason.value))
const indicatorImportConfirmText = computed(() => {
  const prefix = indicatorImportForm.formula_id_prefix.trim()
  const asset = indicatorMappingForm.asset_type || '全部资产'
  return `将解析公式并写入本地指标库，导入后加入当前指标列，并自动绑定到${asset}${prefix ? `；公式前缀 ${prefix}` : ''}。`
})
const indicatorMappingDisabledReason = computed(() => {
  if (mappingIndicators.value) return '指标映射正在保存'
  if (!selectedPriceIndicators.value.length) return '请先选择至少 1 个指标'
  return ''
})
const indicatorMappingDisabled = computed(() => Boolean(indicatorMappingDisabledReason.value))
const indicatorMappingTargetLabel = computed(() => {
  const firstSymbol = parseSymbols(priceTableForm.symbols)[0] || ''
  if (firstSymbol) return firstSymbol
  return indicatorMappingForm.asset_type || '全部资产'
})
const indicatorMappingConfirmText = computed(() =>
  `将把 ${formatInt(selectedPriceIndicators.value.length)} 个指标绑定到 ${indicatorMappingTargetLabel.value}，周期 ${priceTableForm.timeframe}。`
)
const indicatorComputeDisabledReason = computed(() => {
  if (computingIndicators.value) return '指标正在计算'
  if (!priceTableSymbolCount.value) return '请先填写至少 1 个股票代码'
  if (!selectedPriceIndicators.value.length) return '请先选择至少 1 个指标'
  return priceTableDateRangeReason.value
})
const indicatorComputeDisabled = computed(() => Boolean(indicatorComputeDisabledReason.value))
const indicatorComputeConfirmText = computed(() =>
  `将按 ${formatInt(priceTableSymbolCount.value)} 个代码、${formatInt(selectedPriceIndicators.value.length)} 个指标、${priceTableForm.timeframe}、${priceTableForm.start} 至 ${priceTableForm.end} 写入本地指标数据。`
)
const indicatorConfirmingAction = computed(() => {
  if (confirmingImportIndicatorFormula.value) return 'import'
  if (confirmingMapSelectedIndicators.value) return 'map'
  if (confirmingComputeSelectedIndicators.value) return 'compute'
  return ''
})
const indicatorConfirmingActionText = computed(() => {
  if (confirmingImportIndicatorFormula.value) return indicatorImportConfirmText.value
  if (confirmingMapSelectedIndicators.value) return indicatorMappingConfirmText.value
  if (confirmingComputeSelectedIndicators.value) return indicatorComputeConfirmText.value
  return ''
})
const indicatorAnyActionReady = computed(() =>
  !indicatorImportDisabledReason.value || !indicatorMappingDisabledReason.value || !indicatorComputeDisabledReason.value
)
const indicatorActionWarning = computed(() => (indicatorAnyActionReady.value ? '' : indicatorActionStatusText.value))
const indicatorActionStateLabel = computed(() => {
  if (importingIndicatorFormula.value) return '导入中'
  if (mappingIndicators.value) return '绑定中'
  if (computingIndicators.value) return '计算中'
  return indicatorAnyActionReady.value ? '可执行' : '待补充'
})
const indicatorActionStatusText = computed(() => {
  if (importingIndicatorFormula.value) return '正在解析公式并写入本地指标库。'
  if (mappingIndicators.value) return '正在保存指标与资产范围的映射。'
  if (computingIndicators.value) return '正在按当前代码、周期和日期窗口计算指标。'
  const ready: string[] = []
  if (!indicatorImportDisabledReason.value) ready.push('导入')
  if (!indicatorMappingDisabledReason.value) ready.push('绑定')
  if (!indicatorComputeDisabledReason.value) ready.push('计算')
  if (ready.length) {
    const blockers = [indicatorImportDisabledReason.value, indicatorMappingDisabledReason.value, indicatorComputeDisabledReason.value].filter(Boolean)
    return `${ready.join('、')}可执行${blockers.length ? `；其他动作需先处理：${uniqueStrings(blockers).join('；')}` : '。'}`
  }
  return uniqueStrings([indicatorImportDisabledReason.value, indicatorMappingDisabledReason.value, indicatorComputeDisabledReason.value].filter(Boolean)).join('；')
})
const etfTrackerActionDisabledReason = computed(() => {
  const runningReason = researchActionDisabledReason('etf')
  if (runningReason) return runningReason
  if (!etfTrackerReviewSymbols.value.length) return '当前 ETF 筛选结果为空'
  return ''
})
const etfTrackerActionDisabled = computed(() => Boolean(etfTrackerActionDisabledReason.value))
const etfLoadReviewDisabledReason = computed(() => {
  const runningReason = researchActionDisabledReason('etf')
  if (runningReason) return runningReason
  if (!etfTrackerReviewSymbols.value.length) return '当前 ETF 筛选结果为空，无法载入多股复盘'
  return ''
})
const etfLoadReviewDisabled = computed(() => Boolean(etfLoadReviewDisabledReason.value))
const etfLoadReviewConfirmText = computed(() =>
  `将用当前 ETF 筛选结果覆盖多股复盘参数，共 ${formatInt(etfTrackerReviewSymbols.value.length)} 只 ETF。`
)
const etfTrackerReviewConfirmText = computed(() =>
  `确认后将按当前 ETF 筛选结果生成趋势对比，复盘 ${formatInt(etfTrackerReviewSymbols.value.length)} 只，并刷新多股复盘排序、K 线和锐评输出。`
)
const regimeExportDisabledReason = computed(() => {
  const runningReason = researchActionDisabledReason('regime')
  if (runningReason) return runningReason
  if (!regimeResult.value) return '先运行市场风险偏好研究，生成结果后才能导出 JSON'
  return ''
})
const regimeExportDisabled = computed(() => Boolean(regimeExportDisabledReason.value))
const regimeExportFilename = computed(() => {
  const result = regimeResult.value
  const date = formatDateOnly(result?.summary?.as_of) || regimeForm.end || todayText()
  return `market-regime-${date}.json`
})
const regimeExportConfirmText = computed(() =>
  `确认后将下载 ${regimeExportFilename.value}，内容为当前市场风险偏好研究结果。`
)
const reviewAiActionDisabledReason = computed(() => {
  if (runningAiReview.value) return 'AI 覆盖正在生成'
  if (!reviewResult.value?.ai?.messages?.length) return '先生成多股复盘，得到可发送给 AI 的证据'
  return ''
})
const reviewAiActionDisabled = computed(() => Boolean(reviewAiActionDisabledReason.value))
const reviewSearchConfirmText = computed(() => {
  const count = parseSymbols(reviewForm.symbols).length
  const aiText = reviewForm.enable_ai_review ? '，生成完成后将尝试 AI 锐评。' : '。'
  return `确认后将按 ${formatInt(count)} 只标的、${reviewForm.start || '-'} 至 ${reviewForm.end || '-'} 生成多股复盘，刷新排序、K 线和锐评输出${aiText}`
})
const reviewAiConfirmText = computed(() => {
  const count = parseSymbols(reviewForm.symbols).length
  return aiConfigReady.value
    ? `确认后将发送多股复盘证据给模型，覆盖当前复盘与锐评输出；当前标的 ${formatInt(count)} 只。`
    : '未配置完整 AI 接口，确认后仅切回本地规则锐评，不调用模型。'
})
const reviewAiActionStatusText = computed(() => {
  if (runningAiReview.value) return '正在调用模型生成复盘、分析和视频锐评。'
  if (confirmingRunAiReview.value) return reviewAiConfirmText.value
  if (reviewAiActionDisabledReason.value) return reviewAiActionDisabledReason.value
  if (!aiConfigReady.value) return 'AI 接口未配置，点击后将保留本地规则锐评。'
  return `将使用模型 ${aiSettings.model.trim()} 覆盖当前复盘锐评。`
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
const reviewSymbolPickerSelectFilteredDisabledReason = computed(() => {
  if (!filteredReviewSymbolPickerRows.value.length) return '当前搜索和分类下没有可选标的'
  return ''
})
const reviewSymbolPickerSelectFilteredDisabled = computed(() => Boolean(reviewSymbolPickerSelectFilteredDisabledReason.value))
const reviewSymbolPickerSelectAllDisabledReason = computed(() => {
  if (!categoryFilteredReviewSymbolPickerRows.value.length) return '当前分类没有可选标的'
  return ''
})
const reviewSymbolPickerSelectAllDisabled = computed(() => Boolean(reviewSymbolPickerSelectAllDisabledReason.value))
const reviewSymbolPickerClearDisabledReason = computed(() => {
  if (!reviewSymbolPickerSelection.value.length) return '当前没有已选标的'
  return ''
})
const reviewSymbolPickerClearDisabled = computed(() => Boolean(reviewSymbolPickerClearDisabledReason.value))
const reviewSymbolPickerApplyDisabledReason = computed(() => {
  if (!reviewSymbolPickerSelection.value.length) return '先选择要写入多股复盘的标的'
  return ''
})
const reviewSymbolPickerApplyDisabled = computed(() => Boolean(reviewSymbolPickerApplyDisabledReason.value))
const reviewSymbolPickerPendingActionLabel = computed(() => {
  const labels: Record<ReviewSymbolPendingAction, string> = {
    append: '追加选中',
    replace: '替换标的',
    '': ''
  }
  return labels[pendingReviewSymbolAction.value]
})
const reviewSymbolPickerPendingActionDisabledReason = computed(() => {
  if (!pendingReviewSymbolAction.value) return '当前没有待确认的复盘标的操作'
  return reviewSymbolPickerApplyDisabledReason.value
})
const reviewSymbolPickerPendingActionDisabled = computed(() => Boolean(reviewSymbolPickerPendingActionDisabledReason.value))
const reviewSymbolPickerCurrentCount = computed(() => parseSymbols(reviewForm.symbols).length)
const reviewSymbolPickerStatusText = computed(() => {
  if (reviewSymbolPickerApplyDisabledReason.value) return reviewSymbolPickerApplyDisabledReason.value
  const selectedCount = formatInt(reviewSymbolPickerSelection.value.length)
  const currentCount = formatInt(reviewSymbolPickerCurrentCount.value)
  if (pendingReviewSymbolAction.value === 'append') {
    return `确认后将把 ${selectedCount} 只${reviewSymbolPickerTypeLabel.value}追加到当前 ${currentCount} 只复盘标的。`
  }
  if (pendingReviewSymbolAction.value === 'replace') {
    return `确认后将用 ${selectedCount} 只${reviewSymbolPickerTypeLabel.value}替换当前 ${currentCount} 只复盘标的。`
  }
  return `已选 ${selectedCount} 只${reviewSymbolPickerTypeLabel.value}，追加或替换前需要确认。`
})
const directoryBrowserOpenDisabledReason = computed(() => {
  if (directoryBrowserLoading.value) return '正在读取目录，请稍候'
  if (!directoryBrowserPath.value.trim()) return '先输入或选择一个目录路径'
  return ''
})
const directoryBrowserOpenDisabled = computed(() => Boolean(directoryBrowserOpenDisabledReason.value))
const directoryBrowserConfirmDisabledReason = computed(() => {
  if (directoryBrowserLoading.value) return '正在读取目录，请稍候'
  if (!directoryBrowserField.value) return '目录字段未确定，请关闭后重新选择'
  if (!directoryBrowserPath.value.trim()) return '先输入或选择一个目录路径'
  if (directoryBrowserError.value) return '当前目录读取失败，请先打开一个有效目录'
  return ''
})
const directoryBrowserConfirmDisabled = computed(() => Boolean(directoryBrowserConfirmDisabledReason.value))
const directoryBrowserStatusTone = computed(() => {
  if (directoryBrowserLoading.value || directoryBrowserError.value || directoryBrowserConfirmDisabledReason.value) return 'warning'
  return 'info'
})
const directoryBrowserStatusText = computed(() => {
  if (directoryBrowserLoading.value) return '正在读取目录'
  if (directoryBrowserError.value) return directoryBrowserError.value
  if (directoryBrowserConfirmDisabledReason.value) return directoryBrowserConfirmDisabledReason.value
  return `将使用 ${compactPath(directoryBrowserPath.value)}`
})
const crossUniversePendingActionLabel = computed(() => {
  const action = pendingCrossUniverseAction.value
  if (!action) return ''
  return `所有${ASSET_SHORTCUT_LABELS[action]}`
})
const crossUniversePendingSymbols = computed(() => {
  const action = pendingCrossUniverseAction.value
  return action ? symbolsForAssetType(action) : []
})
const crossUniverseCurrentCount = computed(() => parseSymbols(crossForm.universe_symbols).length)
const crossUniversePendingDisabledReason = computed(() => {
  const action = pendingCrossUniverseAction.value
  if (!action) return '当前没有待确认的候选标的操作'
  if (!crossUniversePendingSymbols.value.length) {
    return `${ASSET_SHORTCUT_LABELS[action]}候选为空，请先刷新代码表或缓存。`
  }
  return ''
})
const crossUniversePendingDisabled = computed(() => Boolean(crossUniversePendingDisabledReason.value))
const crossUniversePendingStatusText = computed(() => {
  if (crossUniversePendingDisabledReason.value) return crossUniversePendingDisabledReason.value
  return `确认后将用 ${formatInt(crossUniversePendingSymbols.value.length)} 个${crossUniversePendingActionLabel.value}候选覆盖当前 ${formatInt(crossUniverseCurrentCount.value)} 个候选标的。`
})
const historySearchConfirmText = computed(() =>
  `确认后将按 ${historyForm.symbol || '-'}、${historyForm.window_start || '-'} 至 ${historyForm.as_of || '-'} 搜索历史相似窗口，返回前 ${formatInt(historyForm.top_n)} 个匹配。`
)
const crossSearchConfirmText = computed(() => {
  const mode = crossForm.search_mode === 'traversal' ? `指定区间 ${crossForm.traversal_start || '-'} 至 ${crossForm.traversal_end || '-'}` : `同区间，日期容忍 ${formatInt(crossForm.date_tolerance_bars)} K`
  return `确认后将按 ${crossForm.target_symbol || '-'}、目标 ${crossForm.start || '-'} 至 ${crossForm.end || '-'} 搜索 ${formatInt(crossUniverseCurrentCount.value)} 个候选；${mode}。`
})
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
  {
    label: '缓存标的',
    value: formatInt(summary.value.price_cached_symbol_count ?? summary.value.symbol_count),
    detail: `${formatInt(summary.value.price_asset_type_count ?? summary.value.asset_type_count)} 类资产`
  },
  {
    label: '可用周期项',
    value: `${formatInt(summary.value.price_data_inventory_cached_count ?? summary.value.data_inventory_cached_count)} / ${formatInt(summary.value.price_data_inventory_row_count ?? summary.value.data_inventory_row_count)}`,
    detail: `${formatInt(summary.value.price_data_inventory_unavailable_count ?? summary.value.data_inventory_unavailable_count)} 缺口`
  },
  {
    label: 'K线总量',
    value: formatInt(summary.value.price_data_inventory_total_rows ?? summary.value.data_inventory_total_rows),
    detail: formatBytes(summary.value.price_data_inventory_total_file_size_bytes ?? summary.value.data_inventory_total_file_size_bytes)
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
watch(
  () => [aiSymbolGroupName.value, aiSymbolKeyword.value, aiSymbolPagination.pageSize],
  () => {
    aiSymbolPagination.page = 1
  }
)
watch(
  () => [activeAiWorkbenchTab.value, aiSymbolGroupName.value, aiCurrentSymbolRows.value.length],
  () => {
    if (activeView.value === 'ai' && activeAiWorkbenchTab.value === 'symbols') {
      void loadAiSymbolMetrics(false, false)
    }
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
watch(aiSymbolTotalPages, () => {
  goAiSymbolPage(aiSymbolPagination.page)
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
  if (view === 'ai' && activeAiWorkbenchTab.value === 'symbols') {
    void loadAiSymbolMetrics(false, false)
  }
  if (view === 'research' && activeResearchTab.value === 'etf') ensureEtfTrackingLoaded()
  normalizeResizableCardWidths()
})
watch(activeResearchTab, (tab) => {
  if (tab === 'etf') ensureEtfTrackingLoaded()
  normalizeResizableCardWidths()
})

function aiWorkbenchTabId(key: AiWorkbenchTabKey) {
  return `ai-workbench-${key}-tab`
}

function aiWorkbenchPanelId(key: AiWorkbenchTabKey) {
  return `ai-workbench-${key}-panel`
}

function handleAiWorkbenchTabKeydown(event: KeyboardEvent, key: AiWorkbenchTabKey) {
  handleTabKeydown(event, key, aiWorkbenchTabs.map((item) => item.key), (nextKey) => {
    activeAiWorkbenchTab.value = nextKey
  })
}

function researchTabId(key: ResearchTabKey) {
  return `research-${key}-tab`
}

function researchPanelId(key: ResearchTabKey) {
  return `research-${key}-panel`
}

function handleResearchTabKeydown(event: KeyboardEvent, key: ResearchTabKey) {
  handleTabKeydown(event, key, researchTabs.map((item) => item.key), (nextKey) => {
    activeResearchTab.value = nextKey
  })
}

function regimeSectionTabId(key: RegimeSectionTabKey) {
  return `regime-section-${key}-tab`
}

function regimeSectionPanelId(key: RegimeSectionTabKey) {
  return `regime-section-${key}-panel`
}

function handleRegimeSectionTabKeydown(event: KeyboardEvent, key: RegimeSectionTabKey) {
  handleTabKeydown(event, key, regimeSectionTabs.map((item) => item.key), (nextKey) => {
    activeRegimeSectionTab.value = nextKey
  })
}

function handleTabKeydown<T extends string>(event: KeyboardEvent, key: T, keys: T[], setKey: (nextKey: T) => void) {
  const index = keys.indexOf(key)
  if (index < 0) return
  let nextIndex = index
  if (event.key === 'ArrowRight') nextIndex = (index + 1) % keys.length
  else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + keys.length) % keys.length
  else if (event.key === 'Home') nextIndex = 0
  else if (event.key === 'End') nextIndex = keys.length - 1
  else return
  event.preventDefault()
  setKey(keys[nextIndex])
}

const planColumns = [
  { key: 'stock_code', label: '代码' },
  { key: 'timeframe', label: '周期' },
  { key: 'action', label: '动作' },
  { key: 'reason', label: '原因' },
  { key: 'catalog_status', label: '文件索引' },
  { key: 'coverage_status', label: '窗口覆盖' },
  { key: 'missing_rows', label: '缺失K数' },
  { key: 'coverage_ratio', label: '覆盖率' }
]
const cacheColumns = [
  { key: 'stock_code', label: '代码' },
  { key: 'stock_name', label: '名称' },
  { key: 'asset_type', label: '资产' },
  { key: 'timeframe', label: '周期' },
  { key: 'status', label: '状态' },
  { key: 'coverage_status', label: '窗口覆盖' },
  { key: 'coverage_missing_rows', label: '缺失K数' },
  { key: 'coverage_ratio', label: '覆盖率' },
  { key: 'data_kind', label: '数据' },
  { key: 'indicator', label: '指标' },
  { key: 'adjust', label: '复权' },
  { key: 'coverage_start_at', label: '窗口开始' },
  { key: 'coverage_end_at', label: '窗口结束' },
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
  { key: '当日收益', label: '当日收益' },
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
  void loadIndicatorFormulas()
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
    symbolMetadataCache.value = config.value?.symbol_metadata_cache || null
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
  ensureAiSymbolGroup()
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
  cancelApplySymbolGroup()
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
    applySymbolGroupsPayload(data)
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

function applySymbolGroupsPayload(data: Record<string, any>) {
  if (data.symbol_metadata_cache) {
    symbolMetadataCache.value = data.symbol_metadata_cache
    if (config.value) config.value.symbol_metadata_cache = data.symbol_metadata_cache
  }
  if (!config.value) return
  config.value.symbol_groups = (data.groups || []).filter(isSymbolGroup)
  config.value.symbol_names = {
    ...(config.value.symbol_names || {}),
    ...(data.symbol_names || {})
  }
  ensureAiSymbolGroup()
}

function ensureAiSymbolGroup() {
  const groups = config.value?.symbol_groups || []
  if (!groups.length) {
    aiSymbolGroupName.value = ''
    return
  }
  if (!groups.some((group) => group.name === aiSymbolGroupName.value)) {
    aiSymbolGroupName.value = groups[0].name
  }
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
  if (loadingEtfTracking.value) {
    if (notify) showNotice('info', 'ETF接口正在读取', etfTrackingRefreshDisabledReason.value)
    return false
  }
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
  if (loadingEtfReturns.value) {
    if (notify) showNotice('info', 'ETF收益率正在计算', etfReturnsRefreshDisabledReason.value)
    return false
  }
  const symbols = etfTrackerReturnSymbols()
  if (!symbols.length) {
    if (notify) showNotice('info', 'ETF收益率未计算', etfReturnsRefreshDisabledReason.value || '当前没有可计算收益率的 ETF 标的')
    return false
  }
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

function requestEtfRefreshAction(action: Exclude<EtfRefreshPendingAction, ''>) {
  pendingEtfRefreshAction.value = action
  if (pendingEtfRefreshDisabledReason.value) {
    const title = action === 'tracking' ? 'ETF接口不可刷新' : 'ETF收益率不可刷新'
    showNotice('info', title, pendingEtfRefreshDisabledReason.value)
    pendingEtfRefreshAction.value = ''
    return
  }
  confirmingRunEtfTrackerReview.value = false
  confirmingLoadEtfReview.value = false
  showNotice('info', action === 'tracking' ? '确认刷新 TDX ETF 接口' : '确认刷新 ETF 收益率', pendingEtfRefreshConfirmText.value)
}

function cancelEtfRefreshAction() {
  pendingEtfRefreshAction.value = ''
  showNotice('info', 'ETF 数据未刷新', '当前 ETF 接口缓存和收益率缓存未修改。')
}

function confirmEtfRefreshAction() {
  const action = pendingEtfRefreshAction.value
  if (!action) {
    showNotice('info', 'ETF 数据未刷新', '请先选择要刷新的 ETF 数据。')
    return
  }
  if (pendingEtfRefreshDisabledReason.value) {
    showNotice('info', 'ETF 数据未刷新', pendingEtfRefreshDisabledReason.value)
    pendingEtfRefreshAction.value = ''
    return
  }
  pendingEtfRefreshAction.value = ''
  if (action === 'tracking') void loadEtfTracking(true)
  if (action === 'returns') void loadEtfReturns(true)
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

function requestClearEtfClientCache() {
  confirmingClearEtfCache.value = true
  showNotice('info', '确认清理 ETF 缓存', '该操作只清理浏览器本地 ETF 接口和收益缓存，不删除行情数据。')
}

function cancelClearEtfClientCache() {
  confirmingClearEtfCache.value = false
  showNotice('info', '已取消清理', 'ETF 浏览器缓存未修改。')
}

function confirmClearEtfClientCache() {
  if (!confirmingClearEtfCache.value) {
    requestClearEtfClientCache()
    return
  }
  window.localStorage.removeItem(ETF_TRACKING_CACHE_STORAGE_KEY)
  window.localStorage.removeItem(ETF_RETURNS_CACHE_STORAGE_KEY)
  updateEtfCacheState(etfTrackingCacheState, 'cleared', etfTrackingRows.value.length, 0)
  updateEtfCacheState(etfReturnsCacheState, 'cleared', etfReturnRows.value.length, 0)
  confirmingClearEtfCache.value = false
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

function symbolMetadataCacheTimeText(savedAt: unknown) {
  const raw = Number(savedAt || 0)
  if (!Number.isFinite(raw) || raw <= 0) return ''
  const milliseconds = raw < 1000000000000 ? raw * 1000 : raw
  return formatDateTimeText(new Date(milliseconds).toISOString())
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

function symbolGroupRefreshTitle(target: SymbolRefreshTarget) {
  if (symbolGroupRefreshDisabledReason.value) return symbolGroupRefreshDisabledReason.value
  if (target === 'index') return '重新读取指数列表并更新本地代码表缓存'
  if (target === 'etf') return '重新读取 ETF 列表并更新本地代码表缓存'
  return symbolCacheRefreshTitle.value
}

function requestSymbolGroupRefresh(target: SymbolRefreshTarget) {
  pendingSymbolRefreshTarget.value = target
  if (pendingSymbolRefreshDisabledReason.value) {
    showNotice('info', '代码表未刷新', pendingSymbolRefreshDisabledReason.value)
    pendingSymbolRefreshTarget.value = ''
    return
  }
  showNotice('info', '确认刷新代码表', pendingSymbolRefreshConfirmText.value)
}

function cancelSymbolGroupRefresh() {
  pendingSymbolRefreshTarget.value = ''
  showNotice('info', '代码表未刷新', '股票、ETF、指数列表缓存未修改。')
}

function confirmSymbolGroupRefresh() {
  if (pendingSymbolRefreshDisabledReason.value) {
    showNotice('info', '代码表未刷新', pendingSymbolRefreshDisabledReason.value)
    return
  }
  const target = pendingSymbolRefreshTarget.value
  if (!target) {
    showNotice('info', '代码表未刷新', '请先选择要刷新的代码表范围。')
    return
  }
  void refreshShortcutGroup(target)
}

async function refreshShortcutGroup(target: SymbolRefreshTarget) {
  if (symbolGroupRefreshDisabledReason.value) {
    showNotice('info', '代码表正在更新', symbolGroupRefreshDisabledReason.value)
    return
  }
  const targetGroup = target === 'index' ? '板块指数' : target === 'etf' ? 'ETF列表' : ''
  const targetLabel = target === 'index' ? '指数' : target === 'etf' ? 'ETF' : '代码表'
  pendingSymbolRefreshTarget.value = ''
  refreshingSymbolGroup.value = target
  loadingSymbolGroups.value = true
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    settings.tdx_path = normalizeTdxPath(settings.tdx_path)
    const data = await apiPost('/symbol-metadata/refresh', {
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      target: target === 'all' ? '' : target
    })
    applySymbolGroupsPayload(data)
    if (target === 'all') {
      showNotice('success', '代码表缓存已更新', `已缓存 ${formatInt(data.symbol_metadata_cache?.record_count)} 条股票、ETF 与指数名称。`)
      return
    }
    const group = config.value?.symbol_groups.find((item) => item.name === targetGroup)
    if (!group || !group.symbols.length) {
      showNotice('info', `${targetLabel}列表为空`, `未从当前 TDX 路径读取到${targetLabel}列表，请检查 TDX PYPlugins、TDX 根目录或代码表。`)
      return
    }
    selectedGroup.value = group.name
    symbolsText.value = group.symbols.join('\n')
    showNotice('success', `${targetLabel}列表已刷新`, `${group.name} 已读取 ${formatInt(group.symbols.length)} 只。`)
  } catch (error) {
    showError(`${targetLabel}列表刷新失败`, error)
  } finally {
    loadingSymbolGroups.value = false
    refreshingSymbolGroup.value = ''
  }
}

async function loadOverview(refresh: boolean, options: { includeRecords?: boolean } = {}) {
  if (refresh) confirmingOverviewRefresh.value = false
  loadingOverview.value = true
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    settings.tdx_path = normalizeTdxPath(settings.tdx_path)
    const includeRecords = options.includeRecords ?? activeView.value === 'cache'
    const coverageWindow = overviewCoverageWindow()
    const params = new URLSearchParams({
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      refresh: String(refresh),
      include_records: String(includeRecords),
      start: coverageWindow.start,
      end: coverageWindow.end
    })
    const nextOverview = await apiGet(`/overview?${params.toString()}`)
    overview.value = includeRecords
      ? nextOverview
      : {
          ...nextOverview,
          records: overview.value?.records || [],
          record_count: nextOverview.record_count ?? overview.value?.record_count ?? 0
        }
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

function requestOverviewRefresh() {
  if (overviewRefreshDisabledReason.value) {
    showNotice('info', '缓存扫描不可用', overviewRefreshDisabledReason.value)
    return
  }
  confirmingOverviewRefresh.value = true
  showNotice('info', '确认扫描缓存', overviewRefreshConfirmText.value)
}

function cancelOverviewRefresh() {
  confirmingOverviewRefresh.value = false
  showNotice('info', '缓存未扫描', 'SQLite 索引和缓存概览未刷新。')
}

function confirmOverviewRefresh() {
  if (overviewRefreshDisabledReason.value) {
    showNotice('info', '缓存扫描不可用', overviewRefreshDisabledReason.value)
    confirmingOverviewRefresh.value = false
    return
  }
  void loadOverview(true)
}

async function loadIndicatorFormulas() {
  if (loadingIndicatorFormulas.value) return false
  loadingIndicatorFormulas.value = true
  try {
    const params = new URLSearchParams({ data_root: normalizeDataRoot(settings.data_root) })
    const data = await apiGet(`/indicators/formulas?${params.toString()}`)
    indicatorFormulaRows.value = Array.isArray(data.records) ? data.records : []
    return true
  } catch (error) {
    showError('指标公式加载失败', error)
    return false
  } finally {
    loadingIndicatorFormulas.value = false
  }
}

async function importIndicatorFormula() {
  if (indicatorImportDisabledReason.value) {
    if (!importingIndicatorFormula.value) showNotice('error', '指标公式参数不足', indicatorImportDisabledReason.value)
    return
  }
  importingIndicatorFormula.value = true
  try {
    const data = await apiPost('/indicators/import-tdx', {
      data_root: normalizeDataRoot(settings.data_root),
      text: indicatorImportForm.text,
      formula_id_prefix: indicatorImportForm.formula_id_prefix
    })
    await loadIndicatorFormulas()
    const imported = Array.isArray(data.records) ? data.records : []
    const first = imported[0]
    if (first?.formula_id) {
      priceTableForm.indicators = uniqueStringsInOrder([...selectedPriceIndicators.value, String(first.formula_id)]).join(',')
      await apiPost('/indicators/mappings', {
        data_root: normalizeDataRoot(settings.data_root),
        formula_id: String(first.formula_id),
        asset_type: indicatorMappingForm.asset_type,
        timeframe: priceTableForm.timeframe,
        enabled: true
      })
    }
    indicatorImportForm.text = ''
    confirmingImportIndicatorFormula.value = false
    confirmingMapSelectedIndicators.value = false
    confirmingComputeSelectedIndicators.value = false
    showNotice('success', '指标公式已导入', `已导入 ${formatInt(imported.length)} 个输出指标。`)
  } catch (error) {
    showError('指标公式导入失败', error)
  } finally {
    importingIndicatorFormula.value = false
  }
}

function requestImportIndicatorFormula() {
  if (indicatorImportDisabledReason.value) {
    showNotice('error', '指标公式参数不足', indicatorImportDisabledReason.value)
    return
  }
  confirmingMapSelectedIndicators.value = false
  confirmingComputeSelectedIndicators.value = false
  confirmingImportIndicatorFormula.value = true
  showNotice('info', '确认导入指标公式', indicatorImportConfirmText.value)
}

function cancelImportIndicatorFormula() {
  confirmingImportIndicatorFormula.value = false
  showNotice('info', '已取消导入指标公式', '公式文本、前缀和映射资产未修改。')
}

function confirmImportIndicatorFormula() {
  if (indicatorImportDisabledReason.value) {
    showNotice('error', '指标公式参数不足', indicatorImportDisabledReason.value)
    return
  }
  if (!confirmingImportIndicatorFormula.value) {
    requestImportIndicatorFormula()
    return
  }
  importIndicatorFormula()
}

function requestMapSelectedIndicators() {
  if (indicatorMappingDisabledReason.value) {
    showNotice('error', '未选择指标', indicatorMappingDisabledReason.value)
    return
  }
  confirmingImportIndicatorFormula.value = false
  confirmingComputeSelectedIndicators.value = false
  confirmingMapSelectedIndicators.value = true
  showNotice('info', '确认绑定选中指标', indicatorMappingConfirmText.value)
}

function cancelMapSelectedIndicators() {
  confirmingMapSelectedIndicators.value = false
  showNotice('info', '已取消绑定指标', '本地指标映射未修改。')
}

function confirmMapSelectedIndicators() {
  if (indicatorMappingDisabledReason.value) {
    showNotice('error', '未选择指标', indicatorMappingDisabledReason.value)
    return
  }
  if (!confirmingMapSelectedIndicators.value) {
    requestMapSelectedIndicators()
    return
  }
  mapSelectedIndicators()
}

function requestComputeSelectedIndicators() {
  if (indicatorComputeDisabledReason.value) {
    showNotice('error', '指标计算参数不足', indicatorComputeDisabledReason.value)
    return
  }
  confirmingImportIndicatorFormula.value = false
  confirmingMapSelectedIndicators.value = false
  confirmingComputeSelectedIndicators.value = true
  showNotice('info', '确认计算选中指标', indicatorComputeConfirmText.value)
}

function cancelComputeSelectedIndicators() {
  confirmingComputeSelectedIndicators.value = false
  showNotice('info', '已取消计算指标', '本地指标数据未修改。')
}

function confirmComputeSelectedIndicators() {
  if (indicatorComputeDisabledReason.value) {
    showNotice('error', '指标计算参数不足', indicatorComputeDisabledReason.value)
    return
  }
  if (!confirmingComputeSelectedIndicators.value) {
    requestComputeSelectedIndicators()
    return
  }
  computeSelectedIndicators()
}

async function computeSelectedIndicators() {
  const symbols = parseSymbols(priceTableForm.symbols)
  const indicators = selectedPriceIndicators.value
  if (indicatorComputeDisabledReason.value) {
    if (!computingIndicators.value) showNotice('error', '指标计算参数不足', indicatorComputeDisabledReason.value)
    return
  }
  computingIndicators.value = true
  try {
    const data = await apiPost('/indicators/compute', {
      data_root: normalizeDataRoot(settings.data_root),
      adjust: settings.adjust,
      timeframe: priceTableForm.timeframe,
      symbols,
      formula_ids: indicators,
      start: priceTableForm.start,
      end: priceTableForm.end,
      force: false
    })
    await loadOverview(true, { includeRecords: true })
    confirmingComputeSelectedIndicators.value = false
    showNotice('success', '指标计算完成', `已处理 ${formatInt(data.record_count)} 条指标任务。`)
  } catch (error) {
    showError('指标计算失败', error)
  } finally {
    computingIndicators.value = false
  }
}

async function mapSelectedIndicators() {
  const indicators = selectedPriceIndicators.value
  if (indicatorMappingDisabledReason.value) {
    if (!mappingIndicators.value) showNotice('error', '未选择指标', indicatorMappingDisabledReason.value)
    return
  }
  mappingIndicators.value = true
  try {
    const firstSymbol = parseSymbols(priceTableForm.symbols)[0] || ''
    await Promise.all(indicators.map((formulaId) => apiPost('/indicators/mappings', {
      data_root: normalizeDataRoot(settings.data_root),
      formula_id: formulaId,
      stock_code: firstSymbol,
      asset_type: firstSymbol ? '' : indicatorMappingForm.asset_type,
      timeframe: priceTableForm.timeframe,
      enabled: true
    })))
    confirmingMapSelectedIndicators.value = false
    showNotice('success', '指标映射已保存', firstSymbol ? `已绑定到 ${firstSymbol}。` : `已绑定到 ${indicatorMappingForm.asset_type || '全部资产'}。`)
  } catch (error) {
    showError('指标映射失败', error)
  } finally {
    mappingIndicators.value = false
  }
}

async function loadPriceTable() {
  if (priceTableActionDisabledReason.value) {
    if (!loadingPriceTable.value) showNotice('error', '股票数据表参数不足', priceTableActionDisabledReason.value)
    return
  }
  confirmingLoadPriceTable.value = false
  confirmingPriceTableCommonIndicators.value = false
  loadingPriceTable.value = true
  try {
    const data = await apiPost('/prices/bars', {
      data_root: normalizeDataRoot(settings.data_root),
      adjust: settings.adjust,
      timeframe: priceTableForm.timeframe,
      symbols: parseSymbols(priceTableForm.symbols),
      indicators: selectedPriceIndicators.value,
      start: priceTableForm.start,
      end: priceTableForm.end,
      limit: 500,
      order: 'desc',
      compute_missing_indicators: true
    })
    priceTableRows.value = Array.isArray(data.records) ? data.records : []
    showNotice('success', '股票数据表已读取', `已载入 ${formatInt(priceTableRows.value.length)} 行。`)
  } catch (error) {
    showError('股票数据表读取失败', error)
  } finally {
    loadingPriceTable.value = false
  }
}

function requestLoadPriceTable() {
  if (priceTableActionDisabledReason.value) {
    showNotice('error', '股票数据表参数不足', priceTableActionDisabledReason.value)
    return
  }
  confirmingPriceTableCommonIndicators.value = false
  confirmingLoadPriceTable.value = true
  showNotice('info', '确认读取股票数据表', priceTableLoadConfirmText.value)
}

function cancelLoadPriceTable() {
  confirmingLoadPriceTable.value = false
  showNotice('info', '股票数据表未读取', '当前页面表格未刷新。')
}

function confirmLoadPriceTable() {
  if (priceTableActionDisabledReason.value) {
    showNotice('error', '股票数据表参数不足', priceTableActionDisabledReason.value)
    confirmingLoadPriceTable.value = false
    return
  }
  void loadPriceTable()
}

function requestPriceTableCommonIndicators() {
  confirmingLoadPriceTable.value = false
  confirmingPriceTableCommonIndicators.value = true
  showNotice('info', '确认应用常用均线', priceTableCommonIndicatorsConfirmText.value)
}

function cancelPriceTableCommonIndicators() {
  confirmingPriceTableCommonIndicators.value = false
  showNotice('info', '常用均线未应用', '股票数据表指标列未修改。')
}

function confirmPriceTableCommonIndicators() {
  priceTableForm.indicators = 'ma5,ma10,ma20'
  confirmingPriceTableCommonIndicators.value = false
  showNotice('success', '常用均线已应用', '指标列已改为 ma5、ma10、ma20。')
}

async function refreshActiveView() {
  confirmingTopbarRefresh.value = false
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

function requestTopbarRefresh() {
  if (topbarRefreshing.value) {
    showNotice('info', '当前页面正在刷新', topbarRefreshStatusText.value)
    return
  }
  confirmingTopbarRefresh.value = true
  showNotice('info', '确认刷新当前页面', topbarRefreshConfirmText.value)
}

function cancelTopbarRefresh() {
  confirmingTopbarRefresh.value = false
  showNotice('info', '当前页面未刷新', '页面数据和本地索引未修改。')
}

function confirmTopbarRefresh() {
  if (topbarRefreshing.value) {
    showNotice('info', '当前页面正在刷新', topbarRefreshStatusText.value)
    confirmingTopbarRefresh.value = false
    return
  }
  void refreshActiveView()
}

async function previewPlan() {
  confirmingPreviewPlan.value = false
  confirmingStartDownload.value = false
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

function requestPreviewPlan() {
  const disabledReason = previewPlanDisabledReason.value
  if (disabledReason) {
    showNotice('info', '下载计划暂不可预览', disabledReason)
    return
  }
  confirmingStartDownload.value = false
  confirmingPreviewPlan.value = true
  showNotice('info', '确认预览下载计划', previewPlanConfirmText.value)
}

function cancelPreviewPlan() {
  confirmingPreviewPlan.value = false
  showNotice('info', '下载计划未预览', '没有请求计划接口，当前预览结果未修改。')
}

function confirmPreviewPlan() {
  const disabledReason = previewPlanDisabledReason.value
  if (disabledReason) {
    showNotice('info', '下载计划暂不可预览', disabledReason)
    confirmingPreviewPlan.value = false
    return
  }
  void previewPlan()
}

function requestStartDownload() {
  const disabledReason = startDownloadDisabledReason.value
  if (disabledReason) {
    showNotice('info', '下载任务暂不可提交', disabledReason)
    return
  }
  confirmingStartDownload.value = true
  showNotice('info', '请确认执行下载', startDownloadConfirmStatusText.value)
}

function cancelStartDownload() {
  confirmingStartDownload.value = false
  showNotice('info', '已取消下载提交', '没有提交后台任务，本地行情缓存未修改。')
}

async function confirmStartDownload() {
  const disabledReason = startDownloadDisabledReason.value
  if (disabledReason) {
    showNotice('info', '下载任务暂不可提交', disabledReason)
    return
  }
  if (!confirmingStartDownload.value) {
    requestStartDownload()
    return
  }
  downloading.value = true
  try {
    showNotice('info', '正在提交下载任务', '已向本地 API 发起下载任务请求，等待任务编号返回。')
    const task = await apiPost('/download', payload(), { timeoutMs: DOWNLOAD_SUBMIT_TIMEOUT_MS })
    confirmingStartDownload.value = false
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
  confirmingRunHistorySearch.value = false
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
    historyResultSignature.value = historySearchSignature()
    showNotice('success', '历史相似完成', `匹配 ${formatInt(historyResult.value?.summary?.match_count)} 个窗口。`)
  } catch (error) {
    showError('历史相似失败', error)
  } finally {
    runningResearch.value = ''
  }
}

function requestRunHistorySearch() {
  if (researchActionDisabledReason('history')) {
    showNotice('error', '历史相似不可搜索', researchActionDisabledReason('history'))
    return
  }
  confirmingRunCrossSearch.value = false
  confirmingRunHistorySearch.value = true
  showNotice('info', '确认搜索历史相似', historySearchConfirmText.value)
}

function cancelRunHistorySearch() {
  confirmingRunHistorySearch.value = false
  showNotice('info', '历史相似未搜索', '当前历史匹配结果和窗口 K 线未修改。')
}

function confirmRunHistorySearch() {
  if (researchActionDisabledReason('history')) {
    showNotice('error', '历史相似不可搜索', researchActionDisabledReason('history'))
    return
  }
  if (!confirmingRunHistorySearch.value) {
    requestRunHistorySearch()
    return
  }
  void runHistorySearch()
}

async function runCrossSectionSearch() {
  confirmingRunCrossSearch.value = false
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
    crossResultSignature.value = crossSearchSignature()
    showNotice('success', '横截面搜索完成', `匹配 ${formatInt(crossResult.value?.summary?.match_count)} 个标的。`)
  } catch (error) {
    showError('横截面搜索失败', error)
  } finally {
    runningResearch.value = ''
  }
}

function requestRunCrossSectionSearch() {
  if (researchActionDisabledReason('cross')) {
    showNotice('error', '横截面相似不可搜索', researchActionDisabledReason('cross'))
    return
  }
  confirmingRunHistorySearch.value = false
  confirmingRunCrossSearch.value = true
  showNotice('info', '确认搜索横截面相似', crossSearchConfirmText.value)
}

function cancelRunCrossSectionSearch() {
  confirmingRunCrossSearch.value = false
  showNotice('info', '横截面相似未搜索', '当前横截面匹配结果和窗口 K 线未修改。')
}

function confirmRunCrossSectionSearch() {
  if (researchActionDisabledReason('cross')) {
    showNotice('error', '横截面相似不可搜索', researchActionDisabledReason('cross'))
    return
  }
  if (!confirmingRunCrossSearch.value) {
    requestRunCrossSectionSearch()
    return
  }
  void runCrossSectionSearch()
}

async function runReviewSearch() {
  confirmingRunReviewSearch.value = false
  confirmingRunAiReview.value = false
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

function requestRunReviewSearch() {
  if (researchActionDisabledReason('review')) {
    showNotice('error', '多股复盘不可生成', researchActionDisabledReason('review'))
    return
  }
  confirmingRunAiReview.value = false
  confirmingRunReviewSearch.value = true
  showNotice('info', '确认生成多股复盘', reviewSearchConfirmText.value)
}

function cancelRunReviewSearch() {
  confirmingRunReviewSearch.value = false
  showNotice('info', '多股复盘未生成', '当前排序、K 线和锐评未修改。')
}

function confirmRunReviewSearch() {
  if (researchActionDisabledReason('review')) {
    showNotice('error', '多股复盘不可生成', researchActionDisabledReason('review'))
    return
  }
  if (!confirmingRunReviewSearch.value) {
    requestRunReviewSearch()
    return
  }
  void runReviewSearch()
}

async function runEtfTrackerReview() {
  const selected = etfTrackerReviewSymbols.value
  if (!selected.length) {
    showNotice('error', 'ETF筛选为空', '请调整类型、跟踪指数或关键词。')
    return
  }
  confirmingRunEtfTrackerReview.value = false
  confirmingLoadEtfReview.value = false
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

function requestRunEtfTrackerReview() {
  if (etfTrackerActionDisabledReason.value) {
    showNotice('error', 'ETF趋势对比不可生成', etfTrackerActionDisabledReason.value)
    return
  }
  confirmingLoadEtfReview.value = false
  confirmingRunEtfTrackerReview.value = true
  showNotice('info', '确认生成 ETF 趋势对比', etfTrackerReviewConfirmText.value)
}

function cancelRunEtfTrackerReview() {
  confirmingRunEtfTrackerReview.value = false
  showNotice('info', 'ETF趋势对比未生成', '当前 ETF 趋势、复盘排序和 K 线未修改。')
}

function confirmRunEtfTrackerReview() {
  if (etfTrackerActionDisabledReason.value) {
    showNotice('error', 'ETF趋势对比不可生成', etfTrackerActionDisabledReason.value)
    return
  }
  if (!confirmingRunEtfTrackerReview.value) {
    requestRunEtfTrackerReview()
    return
  }
  void runEtfTrackerReview()
}

function requestRunMarketRegimeResearch() {
  if (researchActionDisabledReason('regime')) {
    showNotice('error', '市场风偏研究不可运行', researchActionDisabledReason('regime'))
    return
  }
  confirmingClearRegimeManualSymbols.value = false
  confirmingRunRegimeResearch.value = true
  showNotice('info', '确认运行市场风偏研究', regimeResearchConfirmText.value)
}

function cancelRunMarketRegimeResearch() {
  confirmingRunRegimeResearch.value = false
  showNotice('info', '市场风偏研究未运行', '当前市场风险偏好结果未修改。')
}

function confirmRunMarketRegimeResearch() {
  if (researchActionDisabledReason('regime')) {
    showNotice('error', '市场风偏研究不可运行', researchActionDisabledReason('regime'))
    return
  }
  if (!confirmingRunRegimeResearch.value) {
    requestRunMarketRegimeResearch()
    return
  }
  void runMarketRegimeResearch()
}

async function runMarketRegimeResearch() {
  confirmingRunRegimeResearch.value = false
  confirmingClearRegimeManualSymbols.value = false
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
    regimeResultSignature.value = regimeSearchSignature()
    const phase = regimeResult.value?.risk_appetite?.phase || '已生成'
    showNotice('success', '市场风险偏好研究完成', `${phase} · ${formatInt(regimeResult.value?.summary?.asset_count)} 个资产。`)
  } catch (error) {
    showError('市场风险偏好研究失败', error)
  } finally {
    runningResearch.value = ''
  }
}

function requestClearRegimeManualSymbols() {
  if (regimeManualSymbolsClearDisabledReason.value) {
    showNotice('info', '没有可清空标的', regimeManualSymbolsClearDisabledReason.value)
    return
  }
  confirmingClearRegimeManualSymbols.value = true
  showNotice('info', '确认清空手动标的', regimeManualSymbolsClearConfirmText.value)
}

function cancelClearRegimeManualSymbols() {
  confirmingClearRegimeManualSymbols.value = false
  showNotice('info', '已取消清空', '市场风偏手动补充标的未修改。')
}

function confirmClearRegimeManualSymbols() {
  if (regimeManualSymbolsClearDisabledReason.value) {
    showNotice('info', '没有可清空标的', regimeManualSymbolsClearDisabledReason.value)
    return
  }
  if (!confirmingClearRegimeManualSymbols.value) {
    requestClearRegimeManualSymbols()
    return
  }
  const count = regimeManualSymbols.value.length
  regimeForm.symbols = ''
  confirmingClearRegimeManualSymbols.value = false
  confirmingRunRegimeResearch.value = false
  showNotice('success', '手动标的已清空', `已清空 ${formatInt(count)} 只手动补充标的。`)
}

async function runAiCommand() {
  if (!aiCommandForm.text.trim()) return
  confirmingRunAiCommand.value = false
  runningAiCommand.value = true
  aiCommandResultState.value = 'idle'
  try {
    const result = await apiPost('/ai/command', {
      ...researchPayloadBase(),
      tdx_path: settings.tdx_path,
      end: aiCommandEndDate(),
      text: aiCommandForm.text,
      current_view: activeView.value,
      research_tab: activeResearchTab.value,
      base_url: aiSettings.base_url.trim(),
      api_key: aiSettings.api_key.trim(),
      model: aiSettings.model.trim(),
      temperature: Number(aiSettings.temperature ?? 0)
    })
    aiCommandResult.value = result
    aiCommandResultState.value = (result.patches || []).length ? 'pending' : 'empty'
    if (aiCommandResultState.value === 'pending') {
      showNotice('info', 'AI 命令已解析', aiCommandApplyConfirmText.value)
    } else {
      showNotice('info', 'AI 命令已解析', result.summary || '没有可应用的参数变更。')
    }
  } catch (error) {
    aiCommandResultState.value = 'idle'
    showError('AI 命令失败', error)
  } finally {
    runningAiCommand.value = false
  }
}

function requestRunAiCommand() {
  if (aiCommandDisabledReason.value) {
    showNotice('info', 'AI 命令不可解析', aiCommandDisabledReason.value)
    return
  }
  confirmingRunAiCommand.value = true
  showNotice('info', '确认解析 AI 命令', aiCommandRunConfirmText.value)
}

function cancelRunAiCommand() {
  confirmingRunAiCommand.value = false
  showNotice('info', 'AI 命令未解析', '没有调用模型或本地规则，当前页面参数未修改。')
}

function confirmRunAiCommand() {
  if (aiCommandDisabledReason.value) {
    showNotice('info', 'AI 命令不可解析', aiCommandDisabledReason.value)
    confirmingRunAiCommand.value = false
    return
  }
  void runAiCommand()
}

function handleAiCommandInput() {
  confirmingRunAiCommand.value = false
  if (aiCommandResultState.value === 'pending') {
    aiCommandResultState.value = 'cancelled'
    showNotice('info', 'AI 命令参数未修改', '已取消上一条待确认结果。')
  }
  aiCommandResult.value = null
  aiCommandResultState.value = 'idle'
}

function cancelAiCommandApply() {
  if (aiCommandResultState.value !== 'pending') return
  aiCommandResultState.value = 'cancelled'
  showNotice('info', 'AI 命令参数未修改', '当前页面参数保持不变。')
}

function confirmAiCommandApply() {
  const disabledReason = aiCommandApplyDisabledReason.value
  if (disabledReason) {
    showNotice('info', 'AI 命令暂不可应用', disabledReason)
    return
  }
  if (!aiCommandResult.value) return
  applyAiCommandResult(aiCommandResult.value)
  aiCommandResultState.value = 'applied'
  showNotice('success', 'AI 命令已应用', aiCommandResult.value.summary || '已根据命令更新参数。')
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
    cancelApplySymbolGroup()
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

function requestLoadAiWorkbenchSymbols() {
  if (aiWorkbenchLoadSymbolsDisabledReason.value) {
    showNotice('info', '没有可载入标的', aiWorkbenchLoadSymbolsDisabledReason.value)
    return
  }
  confirmingLoadAiWorkbenchSymbols.value = true
  showNotice('info', '确认载入 AI 标的', aiWorkbenchLoadSymbolsConfirmText.value)
}

function cancelLoadAiWorkbenchSymbols() {
  confirmingLoadAiWorkbenchSymbols.value = false
  showNotice('info', '已取消载入', 'AI 工作台当前标的未修改。')
}

function confirmLoadAiWorkbenchSymbols() {
  if (aiWorkbenchLoadSymbolsDisabledReason.value) {
    showNotice('info', '没有可载入标的', aiWorkbenchLoadSymbolsDisabledReason.value)
    return
  }
  if (!confirmingLoadAiWorkbenchSymbols.value) {
    requestLoadAiWorkbenchSymbols()
    return
  }
  const symbols = aiWorkbenchLoadSourceSymbols.value
  aiWorkbenchForm.symbols = symbols.join('\n')
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  showNotice('success', 'AI 标的已载入', `已写入 ${formatInt(symbols.length)} 只标的。`)
}

function requestRunAiWorkbench() {
  if (aiWorkbenchRunDisabledReason.value) {
    showNotice('error', aiWorkbenchRunBlockedTitle(), aiWorkbenchRunDisabledReason.value)
    return
  }
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = true
  showNotice('info', '确认发送 AI 任务', aiWorkbenchRunConfirmText.value)
}

function cancelRunAiWorkbench() {
  confirmingRunAiWorkbench.value = false
  showNotice('info', 'AI 任务未发送', '模型未调用，本地行情上下文未发送。')
}

function confirmRunAiWorkbench() {
  if (aiWorkbenchRunDisabledReason.value) {
    showNotice('error', aiWorkbenchRunBlockedTitle(), aiWorkbenchRunDisabledReason.value)
    return
  }
  if (!confirmingRunAiWorkbench.value) {
    requestRunAiWorkbench()
    return
  }
  void runAiWorkbench()
}

async function runAiWorkbench() {
  if (aiWorkbenchRunDisabledReason.value) {
    showNotice('error', aiWorkbenchRunBlockedTitle(), aiWorkbenchRunDisabledReason.value)
    return
  }
  confirmingRunAiWorkbench.value = false
  confirmingLoadAiWorkbenchSymbols.value = false
  runningAiWorkbench.value = true
  aiWorkbenchStreamStatus.value = 'preparing'
  aiWorkbenchStreamText.value = ''
  aiWorkbenchResult.value = null
  const payload = {
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
    max_charts: numberOrDefault(aiWorkbenchForm.max_charts, 3)
  }
  try {
    aiWorkbenchResult.value = await apiPostStream('/ai/stock-agent-stream', payload, {
      context: (data) => {
        aiWorkbenchResult.value = {
          content: aiWorkbenchStreamText.value,
          ...data
        }
        aiWorkbenchStreamStatus.value = 'streaming'
      },
      delta: (data) => {
        aiWorkbenchStreamText.value += String(data.content || '')
        if (aiWorkbenchResult.value) {
          aiWorkbenchResult.value = {
            ...aiWorkbenchResult.value,
            content: aiWorkbenchStreamText.value
          }
        }
        aiWorkbenchStreamStatus.value = 'streaming'
      },
      done: (data) => {
        aiWorkbenchStreamText.value = String(data.content || aiWorkbenchStreamText.value)
        aiWorkbenchResult.value = data
        aiWorkbenchStreamStatus.value = 'done'
      }
    })
    showNotice('success', 'AI 模块已生成', '模型已读取受限本地行情上下文并返回结果。')
  } catch (error) {
    aiWorkbenchStreamStatus.value = 'error'
    showError('AI 模块运行失败', error)
  } finally {
    runningAiWorkbench.value = false
  }
}

function aiWorkbenchRunBlockedTitle() {
  if (!aiConfigReady.value) return 'AI 接口未配置'
  if (!aiSelectedSymbols.value.length) return '未选择标的'
  if (!aiWorkbenchForm.prompt.trim()) return '未填写任务目标'
  return 'AI 任务不可发送'
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
    confirmingClearAiSkillPrompt.value = false
    aiWorkbenchForm.skill_prompt = text
    showNotice('success', 'Skill 已导入', `${file.name} 已载入 AI 模块提示词。`)
  } catch (error) {
    showError('Skill 导入失败', error)
  } finally {
    if (input) input.value = ''
  }
}

function requestClearAiSkillPrompt() {
  if (aiSkillPromptClearDisabledReason.value) {
    showNotice('info', '没有可清空 Skill', aiSkillPromptClearDisabledReason.value)
    return
  }
  confirmingClearAiSkillPrompt.value = true
  showNotice('info', '确认清空 Skill 提示词', aiSkillPromptClearConfirmText.value)
}

function cancelClearAiSkillPrompt() {
  confirmingClearAiSkillPrompt.value = false
  showNotice('info', '已取消清空', 'AI 工作台侧载 Skill 提示词未修改。')
}

function confirmClearAiSkillPrompt() {
  if (aiSkillPromptClearDisabledReason.value) {
    showNotice('info', '没有可清空 Skill', aiSkillPromptClearDisabledReason.value)
    return
  }
  if (!confirmingClearAiSkillPrompt.value) {
    requestClearAiSkillPrompt()
    return
  }
  aiWorkbenchForm.skill_prompt = ''
  confirmingClearAiSkillPrompt.value = false
  showNotice('success', 'Skill 提示词已清空', 'AI 工作台将回到默认提示词。')
}

function requestMarketRegimeJsonExport() {
  if (regimeExportDisabledReason.value) {
    showNotice('info', '没有可导出结果', regimeExportDisabledReason.value)
    return
  }
  confirmingRegimeExport.value = true
  showNotice('info', '确认导出市场风偏 JSON', regimeExportConfirmText.value)
}

function cancelMarketRegimeJsonExport() {
  confirmingRegimeExport.value = false
  showNotice('info', '市场风偏 JSON 未导出', '没有下载文件。')
}

function confirmMarketRegimeJsonExport() {
  if (regimeExportDisabledReason.value) {
    showNotice('info', '没有可导出结果', regimeExportDisabledReason.value)
    confirmingRegimeExport.value = false
    return
  }
  if (!confirmingRegimeExport.value) {
    requestMarketRegimeJsonExport()
    return
  }
  downloadMarketRegimeJson()
}

function downloadMarketRegimeJson() {
  const result = regimeResult.value
  if (regimeExportDisabledReason.value) {
    showNotice('info', '没有可导出结果', regimeExportDisabledReason.value)
    return
  }
  if (!result) return
  confirmingRegimeExport.value = false
  downloadJson(regimeExportFilename.value, result)
  showNotice('success', '市场风偏 JSON 已导出', regimeExportFilename.value)
}

function loadEtfTrackerSymbolsToReview() {
  const selected = etfTrackerReviewSymbols.value
  if (etfLoadReviewDisabledReason.value) {
    showNotice('error', '无法载入多股复盘', etfLoadReviewDisabledReason.value)
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
  confirmingLoadEtfReview.value = false
  showNotice('success', '已载入多股复盘', `已写入 ${formatInt(selected.length)} 只 ETF。`)
}

function requestLoadEtfTrackerSymbolsToReview() {
  if (etfLoadReviewDisabledReason.value) {
    showNotice('error', '无法载入多股复盘', etfLoadReviewDisabledReason.value)
    return
  }
  confirmingLoadEtfReview.value = true
  showNotice('info', '确认载入多股复盘', etfLoadReviewConfirmText.value)
}

function cancelLoadEtfTrackerSymbolsToReview() {
  confirmingLoadEtfReview.value = false
  showNotice('info', '已取消载入', '多股复盘参数未修改。')
}

function confirmLoadEtfTrackerSymbolsToReview() {
  if (etfLoadReviewDisabledReason.value) {
    showNotice('error', '无法载入多股复盘', etfLoadReviewDisabledReason.value)
    return
  }
  if (!confirmingLoadEtfReview.value) {
    requestLoadEtfTrackerSymbolsToReview()
    return
  }
  confirmingLoadEtfReview.value = false
  loadEtfTrackerSymbolsToReview()
}

function requestRunAiReview() {
  if (reviewAiActionDisabledReason.value) {
    showNotice('error', 'AI 覆盖不可用', reviewAiActionDisabledReason.value)
    return
  }
  confirmingRunAiReview.value = true
  showNotice('info', '确认 AI 覆盖复盘', reviewAiConfirmText.value)
}

function cancelRunAiReview() {
  confirmingRunAiReview.value = false
  showNotice('info', 'AI 覆盖未执行', '当前复盘与锐评输出未修改。')
}

function confirmRunAiReview() {
  if (reviewAiActionDisabledReason.value) {
    showNotice('error', 'AI 覆盖不可用', reviewAiActionDisabledReason.value)
    return
  }
  if (!confirmingRunAiReview.value) {
    requestRunAiReview()
    return
  }
  void runAiReview()
}

async function runAiReview(options: { fallbackToLocal?: boolean } = {}) {
  const result = reviewResult.value
  if (reviewAiActionDisabledReason.value) {
    if (!runningAiReview.value) showNotice('error', 'AI 证据缺失', reviewAiActionDisabledReason.value)
    return
  }
  if (!result) return
  confirmingRunAiReview.value = false
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
      evidence: result.ai.evidence || {},
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

function requestResetAiPromptSettings() {
  confirmingResetAiPromptSettings.value = true
  showNotice('info', '确认恢复默认提示词', resetAiPromptSettingsConfirmText.value)
}

function cancelResetAiPromptSettings() {
  confirmingResetAiPromptSettings.value = false
  showNotice('info', '已取消恢复默认提示词', 'AI 自定义提示词草稿未修改。')
}

function confirmResetAiPromptSettings() {
  if (!confirmingResetAiPromptSettings.value) {
    requestResetAiPromptSettings()
    return
  }
  resetAiPromptSettings()
}

function resetAiPromptSettings() {
  confirmingResetAiPromptSettings.value = false
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

function builtinStockDataSkillPrompt() {
  return [
    '你是 TDX Downloader 的本地股票数据助手。',
    '默认使用当前保存的 AI 接口参数，不要求用户重复提供 API Key。',
    '筛选、排序、取前 N 时优先使用后端本地 SQLite 行情索引 ai_price_bars。',
    '不要编造股票池；无法从本地数据验证时明确说明本地数据不足。',
    '输出仅用于本地行情研究，不构成投资建议。'
  ].join('\n')
}

function saveActiveResearchSnapshot() {
  saveResearchSnapshot(activeResearchTab.value)
}

function saveResearchSnapshot(tab: ResearchTabKey) {
  const result = researchResultFor(tab)
  const disabledReason = resultActionDisabledReason(tab)
  if (disabledReason) {
    showNotice('info', '没有可保存结果', disabledReason)
    return
  }
  if (!result) return
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
  confirmingResearchSnapshotLoadId.value = ''
  confirmingResearchSnapshotDeleteId.value = ''
  persistResearchSnapshots()
  showNotice('success', '快照已保存', `${activeResearchMetaFor(tab).label}结果已保存到本机浏览器。`)
}

function loadResearchSnapshot(snapshot: ResearchSnapshot) {
  confirmingResearchSnapshotLoadId.value = ''
  confirmingResearchSnapshotDeleteId.value = ''
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
  if (snapshot.tab === 'history') historyResultSignature.value = historySearchSignature()
  if (snapshot.tab === 'cross') crossResultSignature.value = crossSearchSignature()
  if (snapshot.tab === 'review') reviewResultSignature.value = reviewSearchSignature()
  if (snapshot.tab === 'etf') {
    etfTrackerResultSignature.value = etfTrackerSearchSignature()
    reviewResultSignature.value = ''
  }
  if (snapshot.tab === 'regime') regimeResultSignature.value = regimeSearchSignature()
  showNotice('success', '快照已载入', snapshot.title)
}

function requestLoadResearchSnapshot(snapshot: ResearchSnapshot) {
  confirmingResearchSnapshotLoadId.value = snapshot.id
  confirmingResearchSnapshotDeleteId.value = ''
  showNotice('info', '确认载入快照', `将用“${snapshot.title}”覆盖当前研究表单和结果。`)
}

function cancelLoadResearchSnapshot() {
  confirmingResearchSnapshotLoadId.value = ''
  showNotice('info', '已取消载入', '当前研究表单和结果未修改。')
}

function confirmLoadResearchSnapshot(snapshot: ResearchSnapshot) {
  if (confirmingResearchSnapshotLoadId.value !== snapshot.id) {
    requestLoadResearchSnapshot(snapshot)
    return
  }
  loadResearchSnapshot(snapshot)
}

function requestDeleteResearchSnapshot(snapshotId: string) {
  confirmingResearchSnapshotLoadId.value = ''
  confirmingResearchSnapshotDeleteId.value = snapshotId
  showNotice('info', '确认删除快照', '再次点击该行的“删除”才会移除本地研究快照。')
}

function cancelDeleteResearchSnapshot() {
  confirmingResearchSnapshotDeleteId.value = ''
  showNotice('info', '已取消删除', '研究快照未修改。')
}

function confirmDeleteResearchSnapshot(snapshotId: string) {
  if (confirmingResearchSnapshotDeleteId.value !== snapshotId) {
    requestDeleteResearchSnapshot(snapshotId)
    return
  }
  deleteResearchSnapshot(snapshotId)
}

function deleteResearchSnapshot(snapshotId: string) {
  researchSnapshots.value = researchSnapshots.value.filter((snapshot) => snapshot.id !== snapshotId)
  confirmingResearchSnapshotLoadId.value = ''
  confirmingResearchSnapshotDeleteId.value = ''
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

function requestClearTaskHistory() {
  if (clearTasksDisabledReason.value) {
    showNotice('info', '无法清空任务历史', clearTasksDisabledReason.value)
    return
  }
  confirmingClearTasks.value = true
}

function cancelClearTaskHistory() {
  if (clearTasksCancelDisabledReason.value) {
    showNotice('info', '暂不能取消清理', clearTasksCancelDisabledReason.value)
    return
  }
  confirmingClearTasks.value = false
}

function confirmClearTaskHistory() {
  const disabledReason = clearTasksConfirmDisabledReason.value
  if (disabledReason) {
    showNotice('info', '任务历史未清理', disabledReason)
    return
  }
  if (!confirmingClearTasks.value) {
    requestClearTaskHistory()
    return
  }
  void clearTaskHistory()
}

async function clearTaskHistory() {
  const disabledReason = clearTasksConfirmDisabledReason.value
  if (disabledReason) {
    showNotice('info', '任务历史未清理', disabledReason)
    return
  }
  clearingTasks.value = true
  try {
    const data = await apiDelete('/tasks')
    await loadTasks()
    if (!tasks.value.some((task) => task.id === selectedTaskId.value)) selectedTaskId.value = tasks.value[0]?.id || ''
    confirmingClearTasks.value = false
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

function taskStatusLabel(status: string) {
  return TASK_STATUS_LABELS[String(status || '')] || status || '未知'
}

function taskCanPause(task: TaskPayload) {
  return ['queued', 'running'].includes(String(task.status || '')) && task.control !== 'pause'
}

function taskCanResume(task: TaskPayload) {
  return ['paused', 'pausing'].includes(String(task.status || ''))
}

function taskCanCancel(task: TaskPayload) {
  return ['queued', 'running', 'pausing', 'paused', 'cancelling'].includes(String(task.status || ''))
}

function taskHasControls(task: TaskPayload) {
  return taskCanPause(task) || taskCanResume(task) || taskCanCancel(task)
}

function taskControlBusy(task: TaskPayload) {
  return controllingTaskId.value === task.id || String(task.status || '') === 'cancelling'
}

function taskPauseTitle(task: TaskPayload) {
  if (taskControlBusy(task)) return '任务控制请求处理中'
  if (taskCanPause(task)) return '暂停该后台任务'
  return `当前状态为${taskStatusLabel(task.status)}，不能暂停`
}

function taskResumeTitle(task: TaskPayload) {
  if (taskControlBusy(task)) return '任务控制请求处理中'
  if (taskCanResume(task)) return '继续该后台任务'
  return `当前状态为${taskStatusLabel(task.status)}，不能继续`
}

function taskCancelTitle(task: TaskPayload) {
  if (taskControlBusy(task)) return '任务控制请求处理中'
  if (taskCanCancel(task)) return '终止该后台任务'
  return `当前状态为${taskStatusLabel(task.status)}，不能终止`
}

async function controlTask(task: TaskPayload, action: 'pause' | 'resume' | 'cancel') {
  if (taskControlBusy(task)) {
    showNotice('info', '任务控制处理中', '请等待当前控制请求返回。')
    return
  }
  const disabled =
    action === 'pause'
      ? !taskCanPause(task)
      : action === 'resume'
        ? !taskCanResume(task)
        : !taskCanCancel(task)
  if (disabled) {
    showNotice('info', '任务状态已变化', '当前任务状态不支持该操作，请刷新任务列表确认。')
    return
  }
  const labels = { pause: '暂停', resume: '继续', cancel: '终止' }
  controllingTaskId.value = task.id
  try {
    const updated = await apiPost(`/tasks/${task.id}/${action}`, {})
    selectedTaskId.value = updated.id || task.id
    await loadTasks({ silent: true })
    showNotice('success', `已请求${labels[action]}`, `任务 ${task.id.slice(0, 12)} 状态为 ${taskStatusLabel(updated.status)}。`)
  } catch (error) {
    showError(`任务${labels[action]}失败`, error)
  } finally {
    controllingTaskId.value = ''
  }
}

async function pickDirectory(field: DirectoryField) {
  if (directoryPickDisabledReason.value) {
    showNotice('info', '目录选择进行中', directoryPickDisabledReason.value)
    return
  }
  pickingDirectory.value = field
  try {
    const data = await apiPost('/pick-directory', {
      initial_directory: settings[field],
      title: `选择${directoryFieldLabel(field)}`
    })
    if (!data.path || data.cancelled) return
    settings[field] = field === 'data_root' ? normalizeDataRoot(data.path) : normalizeTdxPath(data.path)
    await loadSymbolGroups(true)
    showNotice('success', '目录已选择', `${directoryFieldLabel(field)} 已更新。`)
  } catch (error) {
    try {
      await openDirectoryBrowser(field, extractErrorMessage(error))
    } catch (browserError) {
      showError('选择目录失败', browserError)
    }
  } finally {
    pickingDirectory.value = ''
  }
}

async function openDirectoryBrowser(field: DirectoryField, reason = '') {
  directoryBrowserField.value = field
  directoryBrowserReason.value = reason
  directoryBrowserOpen.value = true
  const initialPath = directoryInitialPath(field)
  await loadDirectoryBrowser(initialPath)
  await nextTick()
  directoryBrowserPathInput.value?.focus()
  directoryBrowserPathInput.value?.select()
}

function requestLoadDirectoryBrowser(path: string) {
  if (directoryBrowserLoading.value) {
    showNotice('info', '目录正在读取', '请等待当前目录读取完成。')
    return
  }
  void loadDirectoryBrowser(path)
}

async function loadDirectoryBrowser(path: string) {
  if (directoryBrowserLoading.value) {
    showNotice('info', '目录正在读取', '请等待当前目录读取完成。')
    return
  }
  const targetPath = String(path || '').trim()
  if (!targetPath) {
    directoryBrowserError.value = directoryBrowserOpenDisabledReason.value || '先输入或选择一个目录路径'
    return
  }
  directoryBrowserLoading.value = true
  directoryBrowserError.value = ''
  try {
    const query = encodeURIComponent(targetPath)
    const data = await apiGet(`/directories?path=${query}`)
    directoryBrowserPath.value = String(data.path || '')
    directoryBrowserParent.value = String(data.parent || '')
    directoryBrowserEntries.value = Array.isArray(data.entries) ? data.entries : []
  } catch (error) {
    directoryBrowserEntries.value = []
    directoryBrowserParent.value = ''
    directoryBrowserError.value = extractErrorMessage(error)
  } finally {
    directoryBrowserLoading.value = false
  }
}

async function confirmDirectoryBrowserPath() {
  const disabledReason = directoryBrowserConfirmDisabledReason.value
  if (disabledReason) {
    showNotice('info', '目录暂不可用', disabledReason)
    return
  }
  const field = directoryBrowserField.value
  const selectedPath = directoryBrowserPath.value.trim()
  if (!field || !selectedPath) return
  settings[field] = field === 'data_root' ? normalizeDataRoot(selectedPath) : normalizeTdxPath(selectedPath)
  closeDirectoryBrowser()
  await loadSymbolGroups(true)
  showNotice('success', '目录已选择', `${directoryFieldLabel(field)} 已更新。`)
}

function closeDirectoryBrowser() {
  directoryBrowserOpen.value = false
  directoryBrowserField.value = ''
  directoryBrowserError.value = ''
  directoryBrowserReason.value = ''
}

function directoryFieldLabel(field: DirectoryField | '') {
  if (field === 'data_root') return '行情根目录'
  if (field === 'tdx_path') return 'TDX PYPlugins 或根目录'
  return '文件夹'
}

function directoryInitialPath(field: DirectoryField) {
  const configured = String(settings[field] || '').trim()
  if (configured) return configured
  const dataRoot = String(settings.data_root || '').trim()
  if (dataRoot) return dataRoot
  return '/data'
}

function directoryPickerTitle(field: DirectoryField) {
  if (pickingDirectory.value && pickingDirectory.value !== field) return `正在选择${directoryFieldLabel(pickingDirectory.value)}`
  if (runningInContainer.value) return `浏览当前服务可访问的${directoryFieldLabel(field)}目录`
  return `选择${directoryFieldLabel(field)}`
}

function directoryPickTitle(field: DirectoryField) {
  return directoryPickDisabledReason.value || directoryPickerTitle(field)
}

function requestApplySymbolGroup(event: Event) {
  const nextGroup = String((event.target as HTMLSelectElement | null)?.value || 'custom')
  if (nextGroup === 'custom') {
    cancelApplySymbolGroup()
    selectedGroup.value = 'custom'
    return
  }
  if (nextGroup === selectedGroup.value) {
    cancelApplySymbolGroup()
    return
  }
  const group = config.value?.symbol_groups.find((item) => item.name === nextGroup)
  if (!group) {
    showNotice('error', '代码来源不可用', '当前代码来源不存在，请刷新代码表缓存后重试。')
    selectedGroup.value = previousDownloadSymbolGroup.value || 'custom'
    pendingDownloadSymbolGroup.value = ''
    previousDownloadSymbolGroup.value = ''
    return
  }
  previousDownloadSymbolGroup.value = selectedGroup.value
  pendingDownloadSymbolGroup.value = group.name
  showNotice('info', '确认应用代码来源', downloadSymbolGroupConfirmText.value)
}

function cancelApplySymbolGroup() {
  if (pendingDownloadSymbolGroup.value) {
    selectedGroup.value = previousDownloadSymbolGroup.value || 'custom'
  }
  pendingDownloadSymbolGroup.value = ''
  previousDownloadSymbolGroup.value = ''
}

function confirmApplySymbolGroup() {
  const disabledReason = downloadSymbolGroupConfirmDisabledReason.value
  if (disabledReason) {
    showNotice('error', '代码来源不可用', disabledReason)
    cancelApplySymbolGroup()
    return
  }
  const group = pendingDownloadSymbolGroupRecord.value
  if (!group) return
  symbolsText.value = group.symbols.join('\n')
  selectedGroup.value = group.name
  pendingDownloadSymbolGroup.value = ''
  previousDownloadSymbolGroup.value = ''
  showNotice('success', '代码来源已应用', `已填入 ${formatInt(group.symbols.length)} 只${group.name}标的。`)
}

function handleDownloadSymbolsInput() {
  if (pendingDownloadSymbolGroup.value) cancelApplySymbolGroup()
  selectedGroup.value = 'custom'
}

function replaceAiSymbolsFromGroup() {
  if (aiSymbolReplaceGroupDisabledReason.value) {
    showNotice('error', '无法替换标的', aiSymbolReplaceGroupDisabledReason.value)
    return
  }
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  confirmingClearAiSymbols.value = false
  pendingAiSymbolAction.value = ''
  pendingAiSymbolFilterResult.value = null
  const allSymbols = uniqueStringsInOrder(aiCurrentSymbolRows.value.map((row) => row.symbol))
  aiWorkbenchForm.symbols = allSymbols.join('\n')
  const suffix = `，共 ${formatInt(allSymbols.length)} 只。`
  showNotice('success', 'AI 标的已替换', `${aiCurrentSymbolGroup.value?.name || '当前分类'}${suffix}`)
}

function appendAiSymbols(rows: Array<{ symbol: string }>, title: string) {
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  confirmingClearAiSymbols.value = false
  pendingAiSymbolAction.value = ''
  pendingAiSymbolFilterResult.value = null
  const beforeCount = aiSelectedSymbols.value.length
  const symbols = uniqueStringsInOrder([
    ...aiSelectedSymbols.value,
    ...rows.map((row) => row.symbol)
  ])
  aiWorkbenchForm.symbols = symbols.join('\n')
  const addedCount = Math.max(0, symbols.length - beforeCount)
  showNotice('success', title, `已追加 ${formatInt(addedCount)} 只，当前 ${formatInt(symbols.length)} 只。`)
}

function appendFilteredAiSymbols() {
  if (aiSymbolAppendFilteredDisabledReason.value) {
    showNotice('error', '无法追加标的', aiSymbolAppendFilteredDisabledReason.value)
    return
  }
  appendAiSymbols(aiFilteredSymbolRows.value, 'AI 标的已追加')
}

function appendPageAiSymbols() {
  if (aiSymbolAppendPageDisabledReason.value) {
    showNotice('error', '无法追加标的', aiSymbolAppendPageDisabledReason.value)
    return
  }
  appendAiSymbols(aiPagedSymbolRows.value, 'AI 标的已追加')
}

function selectTopAiSymbols() {
  if (aiSymbolTopNDisabledReason.value) {
    showNotice('error', '无法选中前 N', aiSymbolTopNDisabledReason.value)
    return
  }
  const count = aiSymbolTopNCount.value
  aiSymbolTopN.value = count
  const symbols = uniqueStringsInOrder(aiSortedSymbolRows.value.slice(0, count).map((row) => row.symbol))
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  confirmingClearAiSymbols.value = false
  pendingAiSymbolAction.value = ''
  pendingAiSymbolFilterResult.value = null
  aiWorkbenchForm.symbols = symbols.join('\n')
  showNotice('success', 'AI 标的已替换', `已选当前排序前 ${formatInt(symbols.length)} 只。`)
}

function requestAiSymbolAction(action: AiSymbolPendingAction) {
  pendingAiSymbolAction.value = action
  confirmingClearAiSymbols.value = false
  confirmingLoadAiWorkbenchSymbols.value = false
  if (aiSymbolPendingActionDisabledReason.value) {
    showNotice('error', 'AI 标的操作不可用', aiSymbolPendingActionDisabledReason.value)
    pendingAiSymbolAction.value = ''
    if (action === 'filterResult') pendingAiSymbolFilterResult.value = null
    return
  }
  showNotice('info', `确认${aiSymbolPendingActionLabel.value}`, aiSymbolPendingActionText.value)
}

function cancelAiSymbolAction() {
  const label = aiSymbolPendingActionLabel.value || 'AI 标的操作'
  if (pendingAiSymbolAction.value === 'filterResult') pendingAiSymbolFilterResult.value = null
  pendingAiSymbolAction.value = ''
  showNotice('info', `已取消${label}`, 'AI 工作台标的未修改。')
}

function confirmAiSymbolAction() {
  if (aiSymbolPendingActionDisabledReason.value) {
    showNotice('error', 'AI 标的操作不可用', aiSymbolPendingActionDisabledReason.value)
    return
  }
  const action = pendingAiSymbolAction.value
  if (action === 'topN') {
    selectTopAiSymbols()
    return
  }
  if (action === 'replaceGroup') {
    replaceAiSymbolsFromGroup()
    return
  }
  if (action === 'appendFiltered') {
    appendFilteredAiSymbols()
    return
  }
  if (action === 'appendPage') {
    appendPageAiSymbols()
    return
  }
  if (action === 'filterResult') {
    confirmAiSymbolFilterResult()
    return
  }
  showNotice('error', 'AI 标的操作不可用', '请先选择要确认的 AI 标的操作')
}

function confirmAiSymbolFilterResult() {
  if (!pendingAiSymbolFilterResult.value) {
    showNotice('error', 'AI 筛选结果不可用', '当前没有待确认的 AI 筛选结果。')
    pendingAiSymbolAction.value = ''
    return
  }
  const result = pendingAiSymbolFilterResult.value
  applyAiCommandResult(result)
  const selected = parseSymbols(aiWorkbenchForm.symbols)
  const totalCount = Number(result.selected_symbol_count || selected.length)
  pendingAiSymbolFilterResult.value = null
  pendingAiSymbolAction.value = ''
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  confirmingClearAiSymbols.value = false
  showNotice('success', '自然语言筛选已载入', `匹配 ${formatInt(totalCount)} 只，已载入 ${formatInt(selected.length)} 只标的。`)
}

function requestClearAiSelectedSymbols() {
  if (aiSymbolClearDisabledReason.value) {
    showNotice('info', '没有可清空标的', aiSymbolClearDisabledReason.value)
    return
  }
  confirmingClearAiSymbols.value = true
  showNotice('info', '确认清空 AI 标的', aiSymbolClearConfirmStatusText.value)
}

function cancelClearAiSelectedSymbols() {
  confirmingClearAiSymbols.value = false
  showNotice('info', '已取消清空', 'AI 工作台已选标的未修改。')
}

function confirmClearAiSelectedSymbols() {
  if (aiSymbolClearDisabledReason.value) {
    showNotice('info', '没有可清空标的', aiSymbolClearDisabledReason.value)
    return
  }
  if (!confirmingClearAiSymbols.value) {
    requestClearAiSelectedSymbols()
    return
  }
  const count = aiSelectedSymbols.value.length
  aiWorkbenchForm.symbols = ''
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  confirmingClearAiSymbols.value = false
  pendingAiSymbolAction.value = ''
  pendingAiSymbolFilterResult.value = null
  showNotice('success', 'AI 标的已清空', `已清空 ${formatInt(count)} 只已选标的。`)
}

function toggleAiSymbol(symbol: string) {
  const normalized = normalizeSymbol(symbol)
  if (!normalized) return
  confirmingLoadAiWorkbenchSymbols.value = false
  confirmingRunAiWorkbench.value = false
  confirmingClearAiSymbols.value = false
  if (pendingAiSymbolAction.value) {
    pendingAiSymbolAction.value = ''
    pendingAiSymbolFilterResult.value = null
  }
  const selected = aiSelectedSymbolSet.value.has(normalized)
    ? aiSelectedSymbols.value.filter((item) => item !== normalized)
    : [...aiSelectedSymbols.value, normalized]
  aiWorkbenchForm.symbols = uniqueStringsInOrder(selected).join('\n')
}

function toggleAiSymbolSort(key: AiSymbolSortKey) {
  if (aiSymbolSort.key !== key) {
    aiSymbolSort.key = key
    aiSymbolSort.direction = 'desc'
    return
  }
  aiSymbolSort.direction = aiSymbolSort.direction === 'desc' ? 'asc' : 'desc'
}

function aiSymbolSortIndicator(key: AiSymbolSortKey) {
  if (aiSymbolSort.key !== key) return ''
  return aiSymbolSort.direction === 'desc' ? '↓' : '↑'
}

function aiSymbolAriaSort(key: AiSymbolSortKey) {
  if (aiSymbolSort.key !== key) return 'none'
  return aiSymbolSort.direction === 'desc' ? 'descending' : 'ascending'
}

function aiSymbolSortAriaLabel(column: { key: AiSymbolSortKey; label: string }) {
  if (aiSymbolSort.key !== column.key) return `${column.label}列，点击后按降序排列`
  if (aiSymbolSort.direction === 'desc') return `${column.label}列，当前降序，点击后按升序排列`
  return `${column.label}列，当前升序，点击后按降序排列`
}

function aiSymbolSelectionLabel(row: { symbol: string; name?: unknown; assetLabel?: unknown }) {
  const name = String(row.name || row.assetLabel || '').trim()
  return name ? `选择 ${row.symbol} ${name}` : `选择 ${row.symbol}`
}

async function loadAiSymbolMetrics(force: boolean, notify: boolean) {
  const groupName = aiCurrentSymbolGroup.value?.name || ''
  const symbols = uniqueStringsInOrder(aiCurrentSymbolRows.value.map((row) => row.symbol))
  pendingAiSymbolRunAction.value = ''
  if (force && aiSymbolMetricsDisabledReason.value) {
    if (!loadingAiSymbolMetrics.value) showNotice('error', '无法刷新指标', aiSymbolMetricsDisabledReason.value)
    return false
  }
  if (!groupName || !symbols.length) {
    aiSymbolMetricRows.value = []
    aiSymbolMetricGroupName.value = ''
    return false
  }
  if (!force && aiSymbolMetricGroupName.value === groupName && aiSymbolMetricRows.value.length) return true
  if (loadingAiSymbolMetrics.value) return false
  loadingAiSymbolMetrics.value = true
  try {
    const data = await apiPost('/symbol-metrics', {
      data_root: normalizeDataRoot(settings.data_root),
      adjust: settings.adjust,
      symbols,
      end: aiWorkbenchForm.end || todayText()
    })
    aiSymbolMetricRows.value = Array.isArray(data.records) ? data.records : []
    aiSymbolMetricGroupName.value = groupName
    if (notify) {
      showNotice('success', '标的指标已刷新', `读取 ${formatInt(data.record_count)} / ${formatInt(data.requested_count)} 只最新日线。`)
    }
    return true
  } catch (error) {
    showError('标的指标加载失败', error)
    return false
  } finally {
    loadingAiSymbolMetrics.value = false
  }
}

function requestAiSymbolRunAction(action: Exclude<AiSymbolRunPendingAction, ''>) {
  pendingAiSymbolRunAction.value = action
  pendingAiSymbolAction.value = ''
  pendingAiSymbolFilterResult.value = null
  confirmingClearAiSymbols.value = false
  if (aiSymbolRunPendingDisabledReason.value) {
    showNotice('error', 'AI 标的操作不可执行', aiSymbolRunPendingDisabledReason.value)
    pendingAiSymbolRunAction.value = ''
    return
  }
  showNotice('info', `确认${aiSymbolRunPendingActionLabel.value}`, aiSymbolRunPendingText.value)
}

function cancelAiSymbolRunAction() {
  pendingAiSymbolRunAction.value = ''
  showNotice('info', 'AI 标的操作未执行', '当前标的指标、筛选结果和已选标的未修改。')
}

function confirmAiSymbolRunAction() {
  const action = pendingAiSymbolRunAction.value
  if (!action) {
    showNotice('info', 'AI 标的操作未执行', '请先选择要确认的 AI 标的操作。')
    return
  }
  if (aiSymbolRunPendingDisabledReason.value) {
    showNotice('error', 'AI 标的操作不可执行', aiSymbolRunPendingDisabledReason.value)
    pendingAiSymbolRunAction.value = ''
    return
  }
  pendingAiSymbolRunAction.value = ''
  if (action === 'metrics') void loadAiSymbolMetrics(true, true)
  if (action === 'filter') void runAiSymbolFilter()
}

async function runAiSymbolFilter() {
  const text = aiSymbolNaturalQuery.value.trim()
  if (aiSymbolFilterDisabledReason.value) {
    if (!runningAiSymbolFilter.value) showNotice('error', '无法执行 AI 筛选', aiSymbolFilterDisabledReason.value)
    return
  }
  pendingAiSymbolRunAction.value = ''
  runningAiSymbolFilter.value = true
  try {
    const result = await apiPost('/ai/command', {
      ...researchPayloadBase(),
      tdx_path: settings.tdx_path,
      end: aiCommandEndDate(),
      text,
      current_view: 'ai',
      research_tab: activeResearchTab.value,
      base_url: aiSettings.base_url.trim(),
      api_key: aiSettings.api_key.trim(),
      model: aiSettings.model.trim(),
      temperature: Number(aiSettings.temperature ?? 0)
    })
    pendingAiSymbolFilterResult.value = result
    requestAiSymbolAction('filterResult')
  } catch (error) {
    pendingAiSymbolFilterResult.value = null
    pendingAiSymbolAction.value = ''
    showError('自然语言筛选失败', error)
  } finally {
    runningAiSymbolFilter.value = false
  }
}

function applyAllAssetsRecentUpdate() {
  const disabledReason = allAssetsUpdateDisabledReason.value
  if (disabledReason) {
    showNotice('error', '全资产更新不可用', disabledReason)
    return
  }
  const days = allAssetsUpdateDays.value
  allAssetsLookbackDays.value = days
  cancelApplySymbolGroup()
  selectedGroup.value = 'custom'
  symbolsText.value = allAssetSymbols.value.join('\n')
  settings.start = tradingLookbackStartText(days)
  settings.end = latestTradingDayText()
  planRows.value = []
  planSummary.value = {}
  confirmingAllAssetsUpdate.value = false
  showNotice('success', '已应用全资产更新', `已载入 ${formatInt(allAssetSymbols.value.length)} 只资产，时间窗为近 ${days} 个交易日。`)
}

function requestAllAssetsRecentUpdate() {
  const disabledReason = allAssetsUpdateDisabledReason.value
  if (disabledReason) {
    showNotice('error', '全资产更新不可用', disabledReason)
    return
  }
  confirmingAllAssetsUpdate.value = true
  showNotice('info', '确认应用全资产', allAssetsUpdateConfirmText.value)
}

function cancelAllAssetsRecentUpdate() {
  confirmingAllAssetsUpdate.value = false
  showNotice('info', '已取消全资产更新', '下载任务标的、日期和当前预览计划未修改。')
}

function confirmAllAssetsRecentUpdate() {
  if (allAssetsUpdateDisabledReason.value) {
    showNotice('error', '全资产更新不可用', allAssetsUpdateDisabledReason.value)
    return
  }
  if (!confirmingAllAssetsUpdate.value) {
    requestAllAssetsRecentUpdate()
    return
  }
  applyAllAssetsRecentUpdate()
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
  if (pendingDownloadTimeframeAction.value) {
    pendingDownloadTimeframeAction.value = ''
  }
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

function sameDownloadTimeframes(left: string[], right: string[]) {
  return left.length === right.length && left.every((item, index) => item === right[index])
}

function selectAllDownloadTimeframes() {
  selectedTimeframes.value = [...downloadTimeframeOptions.value]
  clearPlanPreview()
}

function selectDefaultDownloadTimeframe() {
  selectedTimeframes.value = normalizeDownloadTimeframes(config.value?.defaults?.timeframes || ['1d'])
  clearPlanPreview()
}

function requestDownloadTimeframeAction(action: DownloadTimeframePendingAction) {
  pendingDownloadTimeframeAction.value = action
  if (downloadTimeframePendingDisabledReason.value) {
    showNotice('info', '下载周期未修改', downloadTimeframePendingDisabledReason.value)
    pendingDownloadTimeframeAction.value = ''
    return
  }
  if (sameDownloadTimeframes(selectedDownloadTimeframes.value, downloadTimeframePendingSelection.value)) {
    showNotice('info', '下载周期未修改', '当前已经是该周期选择。')
    pendingDownloadTimeframeAction.value = ''
    return
  }
  showNotice('info', '确认修改下载周期', downloadTimeframePendingText.value)
}

function cancelDownloadTimeframeAction() {
  pendingDownloadTimeframeAction.value = ''
  showNotice('info', '下载周期未修改', '当前周期选择和预览计划未修改。')
}

function confirmDownloadTimeframeAction() {
  if (downloadTimeframePendingDisabledReason.value) {
    showNotice('info', '下载周期未修改', downloadTimeframePendingDisabledReason.value)
    return
  }
  const action = pendingDownloadTimeframeAction.value
  if (action === 'all') {
    selectAllDownloadTimeframes()
  } else if (action === 'default') {
    selectDefaultDownloadTimeframe()
  } else {
    showNotice('info', '下载周期未修改', '请先选择要应用的周期快捷操作。')
    return
  }
  pendingDownloadTimeframeAction.value = ''
  showNotice('success', '下载周期已更新', `当前周期：${downloadTimeframeSummary.value}；预览计划已清空。`)
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

function requestCrossUniverseFromAssetType(type: AssetShortcutType) {
  const symbols = symbolsForAssetType(type)
  const label = ASSET_SHORTCUT_LABELS[type]
  if (!symbols.length) {
    showNotice('error', `${label}候选为空`, '当前配置没有可用标的，请先刷新指数或 ETF 列表。')
    return
  }
  pendingCrossUniverseAction.value = type
  showNotice('info', '确认覆盖候选标的', crossUniversePendingStatusText.value)
}

function cancelCrossUniverseAction() {
  pendingCrossUniverseAction.value = ''
}

function confirmCrossUniverseAction() {
  const action = pendingCrossUniverseAction.value
  if (!action) return
  setCrossUniverseFromAssetType(action)
}

function setCrossUniverseFromAssetType(type: AssetShortcutType) {
  const symbols = symbolsForAssetType(type)
  const label = ASSET_SHORTCUT_LABELS[type]
  if (!symbols.length) {
    pendingCrossUniverseAction.value = ''
    showNotice('error', `${label}候选为空`, '当前配置没有可用标的，请先刷新指数或 ETF 列表。')
    return
  }
  crossForm.universe_symbols = symbols.join('\n')
  pendingCrossUniverseAction.value = ''
  showNotice('success', '候选标的已更新', `已填入 ${formatInt(symbols.length)} 个${label}候选。`)
}

async function openReviewSymbolPicker(type: ReviewSymbolPickerType) {
  cancelReviewSymbolPendingAction()
  reviewSymbolPickerOpen.value = true
  reviewSymbolPickerType.value = type
  reviewSymbolPickerCategory.value = defaultReviewSymbolCategory(type)
  reviewSymbolPickerKeyword.value = ''
  prefillReviewSymbolSelection()
  await nextTick()
  reviewSymbolPickerSearchInput.value?.focus()
}

function closeReviewSymbolPicker() {
  cancelReviewSymbolPendingAction()
  reviewSymbolPickerOpen.value = false
}

function setReviewSymbolPickerType(type: ReviewSymbolPickerType) {
  cancelReviewSymbolPendingAction()
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
  reviewSymbolPickerSelection.value = currentGroupSymbols.filter((symbol) => current.has(symbol))
}

function isReviewSymbolSelected(symbol: string) {
  return reviewSymbolPickerSelectionSet.value.has(symbol)
}

function toggleReviewSymbol(symbol: string) {
  cancelReviewSymbolPendingAction()
  if (isReviewSymbolSelected(symbol)) {
    reviewSymbolPickerSelection.value = reviewSymbolPickerSelection.value.filter((item) => item !== symbol)
    return
  }
  reviewSymbolPickerSelection.value = uniqueStringsInOrder([...reviewSymbolPickerSelection.value, symbol])
}

function selectFilteredReviewSymbols() {
  cancelReviewSymbolPendingAction()
  if (reviewSymbolPickerSelectFilteredDisabledReason.value) {
    showNotice('info', '没有可选标的', reviewSymbolPickerSelectFilteredDisabledReason.value)
    return
  }
  reviewSymbolPickerSelection.value = uniqueStringsInOrder([
    ...reviewSymbolPickerSelection.value,
    ...filteredReviewSymbolPickerRows.value.map((row) => row.symbol)
  ])
  showNotice('success', '已选当前结果', `当前弹窗已选 ${formatInt(reviewSymbolPickerSelection.value.length)} 只。`)
}

function selectAllReviewSymbols() {
  cancelReviewSymbolPendingAction()
  if (reviewSymbolPickerSelectAllDisabledReason.value) {
    showNotice('info', '没有可选标的', reviewSymbolPickerSelectAllDisabledReason.value)
    return
  }
  reviewSymbolPickerSelection.value = categoryFilteredReviewSymbolPickerRows.value.map((row) => row.symbol)
  showNotice('success', '已选当前分类', `当前分类 ${formatInt(reviewSymbolPickerSelection.value.length)} 只已选中。`)
}

function clearReviewSymbolSelection() {
  cancelReviewSymbolPendingAction()
  if (reviewSymbolPickerClearDisabledReason.value) {
    showNotice('info', '没有可清空标的', reviewSymbolPickerClearDisabledReason.value)
    return
  }
  reviewSymbolPickerSelection.value = []
}

function requestReviewSymbolPickerApply(mode: Exclude<ReviewSymbolPendingAction, ''>) {
  const disabledReason = reviewSymbolPickerApplyDisabledReason.value
  if (disabledReason) {
    showNotice('info', '复盘标的未更新', disabledReason)
    return
  }
  pendingReviewSymbolAction.value = mode
  showNotice('info', mode === 'replace' ? '确认替换复盘标的' : '确认追加复盘标的', reviewSymbolPickerStatusText.value)
}

function cancelReviewSymbolPendingAction() {
  pendingReviewSymbolAction.value = ''
}

function confirmReviewSymbolPickerApply() {
  const mode = pendingReviewSymbolAction.value
  if (!mode) return
  applyReviewSymbolSelection(mode)
}

function applyReviewSymbolSelection(mode: 'append' | 'replace') {
  const disabledReason = reviewSymbolPickerApplyDisabledReason.value
  if (disabledReason) {
    pendingReviewSymbolAction.value = ''
    showNotice('info', '复盘标的未更新', disabledReason)
    return
  }
  const selected = reviewSymbolPickerSelection.value
  if (!selected.length) {
    pendingReviewSymbolAction.value = ''
    return
  }
  const symbols = mode === 'append' ? uniqueStringsInOrder([...parseSymbols(reviewForm.symbols), ...selected]) : selected
  reviewForm.symbols = symbols.join('\n')
  reviewResult.value = null
  aiReviewOutput.value = null
  reviewResultSignature.value = ''
  pendingReviewSymbolAction.value = ''
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

function aiCommandEndDate() {
  if (activeView.value === 'ai') return aiWorkbenchForm.end || latestTradingDayText()
  if (activeView.value === 'download') return settings.end || latestTradingDayText()
  if (activeView.value === 'research') {
    if (activeResearchTab.value === 'review') return reviewForm.end || latestTradingDayText()
    if (activeResearchTab.value === 'cross') return crossForm.end || latestTradingDayText()
    if (activeResearchTab.value === 'regime') return regimeForm.end || latestTradingDayText()
    if (activeResearchTab.value === 'history') return historyForm.as_of || latestTradingDayText()
    if (activeResearchTab.value === 'etf') return etfTrackerForm.end || latestTradingDayText()
  }
  return latestTradingDayText()
}

function historySearchSignature() {
  return JSON.stringify({
    data_root: normalizeDataRoot(settings.data_root),
    adjust: settings.adjust,
    timeframe: researchTimeframe.value,
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
}

function crossSearchSignature() {
  return JSON.stringify({
    data_root: normalizeDataRoot(settings.data_root),
    adjust: settings.adjust,
    timeframe: researchTimeframe.value,
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

function regimeSearchSignature() {
  return JSON.stringify({
    data_root: normalizeDataRoot(settings.data_root),
    adjust: settings.adjust,
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

function saveSettings(scope: 'system' | 'ai' = 'system') {
  if (scope === 'system') confirmingResetSettings.value = false
  if (scope === 'ai') confirmingResetAiPromptSettings.value = false
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
  markSettingsSaved(scope)
}

function markSettingsSaved(scope: 'system' | 'ai') {
  const text = `已保存 · ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`
  if (scope === 'ai') {
    aiSettingsSaveFeedback.value = text
    settingsSaveFeedback.value = ''
    showNotice('success', 'AI 设置已保存', '大模型命令框、AI 工作台和复盘 AI 会读取当前参数。')
  } else {
    settingsSaveFeedback.value = text
    aiSettingsSaveFeedback.value = ''
    showNotice('success', '设置已保存', '下次打开控制台会自动使用当前路径、运行参数和 API Key。')
  }
  window.setTimeout(() => {
    if (scope === 'ai' && aiSettingsSaveFeedback.value === text) aiSettingsSaveFeedback.value = ''
    if (scope === 'system' && settingsSaveFeedback.value === text) settingsSaveFeedback.value = ''
  }, 4200)
}

function requestResetSettings() {
  confirmingResetSettings.value = true
  showNotice('info', '确认恢复默认设置', resetSettingsConfirmText.value)
}

function cancelResetSettings() {
  confirmingResetSettings.value = false
  showNotice('info', '已取消恢复默认', '系统设置保持不变。')
}

function confirmResetSettings() {
  if (!confirmingResetSettings.value) {
    requestResetSettings()
    return
  }
  resetSettings()
}

function resetSettings() {
  confirmingResetSettings.value = false
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
  settingsSaveFeedback.value = ''
  aiSettingsSaveFeedback.value = ''
  showNotice('info', '已恢复默认', '已恢复 API 提供的默认路径、运行参数和默认 AI 设置。')
}

function requestResetResizableCards() {
  confirmingResetResizableCards.value = true
  showNotice('info', '确认还原卡片尺寸', '该操作会清除当前页面全部手动调整的卡片尺寸。')
}

function cancelResetResizableCards() {
  confirmingResetResizableCards.value = false
  showNotice('info', '已取消还原', '卡片尺寸保持不变。')
}

function confirmResetResizableCards() {
  if (!confirmingResetResizableCards.value) {
    requestResetResizableCards()
    return
  }
  resetResizableCards()
}

function resetResizableCards() {
  confirmingResetResizableCards.value = false
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
    const defaultDataRoot = normalizeDataRoot(String(config.value?.defaults?.data_root || settings.data_root))
    const defaultTdxPath = normalizeTdxPath(String(config.value?.defaults?.tdx_path || settings.tdx_path))
    Object.assign(settings, {
      data_root: savedPathForCurrentRuntime(saved.data_root, defaultDataRoot) || settings.data_root,
      adjust: saved.adjust ?? settings.adjust,
      tdx_path: savedPathForCurrentRuntime(saved.tdx_path, defaultTdxPath),
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

function savedPathForCurrentRuntime(savedPath: unknown, defaultPath: string) {
  const saved = String(savedPath || '').trim()
  const currentDefault = String(defaultPath || '').trim()
  if (!saved) return currentDefault
  if (!currentDefault && saved.startsWith('/Volumes/')) return ''
  if (currentDefault.startsWith('/data/') && saved.startsWith('/Volumes/')) return currentDefault
  return saved
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

async function apiGet(path: string, options: { headers?: Record<string, string>; timeoutMs?: number } = {}) {
  const response = await fetchWithTimeout(
    `${API_BASE}${path}`,
    { headers: options.headers || {} },
    options.timeoutMs ?? API_GET_TIMEOUT_MS
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function apiDelete(path: string) {
  const response = await fetchWithTimeout(`${API_BASE}${path}`, { method: 'DELETE' }, API_POST_TIMEOUT_MS)
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function apiPost(path: string, body: Record<string, any>, options: { timeoutMs?: number } = {}) {
  const response = await fetchWithTimeout(
    `${API_BASE}${path}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    },
    options.timeoutMs ?? API_POST_TIMEOUT_MS
  )
  if (!response.ok) throw new Error(await response.text())
  return response.json()
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`请求超时：${Math.round(timeoutMs / 1000)} 秒内未收到响应。`)
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

async function apiPostStream(
  path: string,
  body: Record<string, any>,
  handlers: {
    context?: (data: Record<string, any>) => void
    delta?: (data: Record<string, any>) => void
    done?: (data: Record<string, any>) => void
  }
) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body)
  })
  if (!response.ok) throw new Error(await response.text())
  if (!response.body) throw new Error('浏览器不支持流式响应。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalPayload: Record<string, any> | null = null
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\n\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const event = parseSseEvent(frame)
      if (!event) continue
      if (event.type === 'error') {
        throw new Error(String(event.data.detail || 'AI 流式接口返回错误。'))
      }
      if (event.type === 'context') handlers.context?.(event.data)
      if (event.type === 'delta') handlers.delta?.(event.data)
      if (event.type === 'done') {
        finalPayload = event.data
        handlers.done?.(event.data)
      }
    }
  }
  const tail = buffer.trim()
  if (tail) {
    const event = parseSseEvent(tail)
    if (event?.type === 'error') throw new Error(String(event.data.detail || 'AI 流式接口返回错误。'))
    if (event?.type === 'done') {
      finalPayload = event.data
      handlers.done?.(event.data)
    }
  }
  if (!finalPayload) throw new Error('AI 流式接口未返回完成事件。')
  return finalPayload
}

function parseSseEvent(frame: string): { type: string; data: Record<string, any> } | null {
  const lines = frame.split(/\r?\n/)
  const type = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
  const dataText = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
  if (!dataText) return null
  return { type, data: JSON.parse(dataText) }
}

function parseSymbols(text: string) {
  return text.split(/[\s,;，、]+/).map((item) => item.trim()).filter(Boolean)
}

function parseIndicatorIds(text: string) {
  return uniqueStringsInOrder(
    String(text || '')
      .split(/[\s,;，、]+/)
      .map((item) => item.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_').replace(/^_+|_+$/g, ''))
      .filter(Boolean)
  )
}

function isIndicatorSelected(formulaId: unknown) {
  const normalized = String(formulaId || '').trim().toLowerCase()
  return Boolean(normalized && selectedPriceIndicators.value.includes(normalized))
}

function togglePriceIndicator(formulaId: unknown) {
  const normalized = String(formulaId || '').trim().toLowerCase()
  if (!normalized) return
  const current = selectedPriceIndicators.value
  priceTableForm.indicators = current.includes(normalized)
    ? current.filter((item) => item !== normalized).join(',')
    : [...current, normalized].join(',')
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

function requestDownloadDateShortcut(key: DateShortcutKey) {
  pendingDownloadDateShortcut.value = key
  if (downloadDateShortcutPendingDisabledReason.value) {
    showNotice('info', '下载日期未修改', downloadDateShortcutPendingDisabledReason.value)
    pendingDownloadDateShortcut.value = ''
    return
  }
  if (isDateShortcutActive(settings, key)) {
    showNotice('info', '下载日期未修改', '当前已经是该日期快捷区间。')
    pendingDownloadDateShortcut.value = ''
    return
  }
  showNotice('info', '确认修改下载日期', downloadDateShortcutPendingText.value)
}

function cancelDownloadDateShortcut() {
  pendingDownloadDateShortcut.value = ''
  showNotice('info', '下载日期未修改', '当前日期区间和预览计划未修改。')
}

function confirmDownloadDateShortcut() {
  if (downloadDateShortcutPendingDisabledReason.value) {
    showNotice('info', '下载日期未修改', downloadDateShortcutPendingDisabledReason.value)
    return
  }
  const key = pendingDownloadDateShortcut.value
  if (!key) {
    showNotice('info', '下载日期未修改', '请先选择要应用的日期快捷操作。')
    return
  }
  applyDateShortcut(settings, key)
  clearPlanPreview()
  pendingDownloadDateShortcut.value = ''
  showNotice('success', '下载日期已更新', `当前区间：${settings.start} 至 ${settings.end}；预览计划已清空。`)
}

function requestResearchDateShortcut(target: ResearchDateShortcutTarget, key: DateShortcutKey) {
  pendingResearchDateShortcut.value = { target, key }
  if (researchDateShortcutPendingDisabledReason.value) {
    showNotice('info', '研究日期未修改', researchDateShortcutPendingDisabledReason.value)
    pendingResearchDateShortcut.value = null
    return
  }
  if (researchDateShortcutAlreadyActive(target, key)) {
    showNotice('info', '研究日期未修改', '当前已经是该日期快捷区间。')
    pendingResearchDateShortcut.value = null
    return
  }
  showNotice('info', '确认修改研究日期', researchDateShortcutPendingText.value)
}

function cancelResearchDateShortcut() {
  pendingResearchDateShortcut.value = null
  showNotice('info', '研究日期未修改', '当前研究参数和结果未修改。')
}

function confirmResearchDateShortcut() {
  const pending = pendingResearchDateShortcut.value
  if (!pending) {
    showNotice('info', '研究日期未修改', '请先选择要应用的日期快捷操作。')
    return
  }
  if (researchDateShortcutPendingDisabledReason.value) {
    showNotice('info', '研究日期未修改', researchDateShortcutPendingDisabledReason.value)
    return
  }
  const targetLabel = researchDateShortcutPendingTargetLabel.value
  applyResearchDateShortcut(pending.target, pending.key)
  pendingResearchDateShortcut.value = null
  showNotice('success', '研究日期已更新', `${targetLabel}已更新；请重新运行研究刷新结果。`)
}

function applyResearchDateShortcut(target: ResearchDateShortcutTarget, key: DateShortcutKey) {
  if (target === 'history') {
    applyHistoryDateShortcut(key)
    return
  }
  if (target === 'crossTarget') {
    applyDateShortcut(crossForm, key)
    return
  }
  if (target === 'crossCandidate') {
    applyCandidateDateShortcut(key)
    return
  }
  if (target === 'review') {
    applyDateShortcut(reviewForm, key)
    return
  }
  if (target === 'etf') {
    applyDateShortcut(etfTrackerForm, key)
    return
  }
  if (target === 'regime') applyDateShortcut(regimeForm, key)
}

function researchDateShortcutAlreadyActive(target: ResearchDateShortcutTarget, key: DateShortcutKey) {
  if (target === 'history') return isHistoryDateShortcutActive(key)
  if (target === 'crossTarget') return isDateShortcutActive(crossForm, key)
  if (target === 'crossCandidate') return isCandidateDateShortcutActive(key)
  if (target === 'review') return isDateShortcutActive(reviewForm, key)
  if (target === 'etf') return isDateShortcutActive(etfTrackerForm, key)
  if (target === 'regime') return isDateShortcutActive(regimeForm, key)
  return false
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

function overviewCoverageWindow(): DateRangeFields {
  const start = isDateText(settings.start) ? settings.start : tradingLookbackStartText(20)
  const end = isDateText(settings.end) ? settings.end : latestTradingDayText()
  return start <= end ? { start, end } : { start: end, end }
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
  const parts = text.split(/[\\/]+/)
  const last = parts[parts.length - 1]?.toLowerCase() || ''
  const parent = parts[parts.length - 2]?.toLowerCase() || ''
  if ((last === 'user' || last === 'sys') && parent === 'pyplugins') {
    const collapsed = parts.slice(0, -1).join(text.includes('\\') && !text.includes('/') ? '\\' : '/')
    return collapsed || text
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
  if (value === null || value === undefined || value === '') return '-'
  const amount = Number(value) * 10000
  if (!Number.isFinite(amount)) return '-'
  if (Math.abs(amount) >= 100000000) return `${(amount / 100000000).toFixed(2)}亿`
  if (Math.abs(amount) >= 10000) return `${(amount / 10000).toFixed(1)}万`
  return amount.toFixed(0)
}

function formatLargeNumberValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  if (!Number.isFinite(number)) return '-'
  if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(2)}亿`
  if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(1)}万`
  return number.toFixed(0)
}

function finiteNumberOrNull(value: unknown) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
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

function compareAiSymbolValues(left: unknown, right: unknown) {
  const leftEmpty = left === null || left === undefined || left === ''
  const rightEmpty = right === null || right === undefined || right === ''
  if (leftEmpty && rightEmpty) return 0
  if (leftEmpty) return -1
  if (rightEmpty) return 1
  if (typeof left === 'boolean' || typeof right === 'boolean') {
    return Number(Boolean(left)) - Number(Boolean(right))
  }
  const leftNumber = Number(left)
  const rightNumber = Number(right)
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber
  }
  const leftText = String(left)
  const rightText = String(right)
  if (/^\d{4}-\d{2}-\d{2}/.test(leftText) && /^\d{4}-\d{2}-\d{2}/.test(rightText)) {
    return Date.parse(leftText) - Date.parse(rightText)
  }
  return leftText.localeCompare(rightText, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' })
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
    coverage_status: STATUS_LABELS[String(row.coverage_status || '')] || row.coverage_status,
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
    coverage_ratio: formatRatioText(row.coverage_ratio),
    coverage_start_at: formatDateTimeText(row.coverage_start_at),
    coverage_end_at: formatDateTimeText(row.coverage_end_at),
    coverage_first_missing_at: formatDateTimeText(row.coverage_first_missing_at),
    coverage_last_missing_at: formatDateTimeText(row.coverage_last_missing_at),
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

type PaginationAction = 'first' | 'prev' | 'next' | 'last'

function normalizePageNumber(page: number, totalPages: number) {
  return Math.min(Math.max(1, Math.trunc(page || 1)), Math.max(1, totalPages))
}

function paginationActionDisabled(action: PaginationAction, page: number, totalPages: number) {
  const current = normalizePageNumber(page, totalPages)
  if (action === 'first' || action === 'prev') return current <= 1
  return current >= Math.max(1, totalPages)
}

function paginationActionTitle(action: PaginationAction, page: number, totalPages: number, label = '表格') {
  const current = normalizePageNumber(page, totalPages)
  const total = Math.max(1, totalPages)
  const disabled = paginationActionDisabled(action, current, total)
  if (disabled && (action === 'first' || action === 'prev')) return `${label}已在第一页`
  if (disabled) return `${label}已在最后一页`
  if (action === 'first') return `跳到${label}第一页`
  if (action === 'prev') return `跳到${label}上一页（第 ${current - 1} 页）`
  if (action === 'next') return `跳到${label}下一页（第 ${current + 1} 页）`
  return `跳到${label}最后一页（第 ${total} 页）`
}

function pageSizeButtonTitle(size: number, currentSize: number, label = '表格') {
  return size === currentSize ? `${label}当前每页 ${size} 条` : `${label}切换为每页 ${size} 条`
}

function goCachePage(page: number) {
  cachePagination.page = normalizePageNumber(page, cacheTotalPages.value)
}

function setPlanPageSize(size: number) {
  planPagination.pageSize = size
  planPagination.page = 1
}

function goPlanPage(page: number) {
  planPagination.page = normalizePageNumber(page, planTotalPages.value)
}

function setEtfTrackerPageSize(size: number) {
  etfTrackerPagination.pageSize = size
  etfTrackerPagination.page = 1
}

function goEtfTrackerPage(page: number) {
  etfTrackerPagination.page = normalizePageNumber(page, etfTrackerTotalPages.value)
}

function setAiSymbolPageSize(size: number) {
  aiSymbolPagination.pageSize = size
  aiSymbolPagination.page = 1
}

function goAiSymbolPage(page: number) {
  aiSymbolPagination.page = normalizePageNumber(page, aiSymbolTotalPages.value)
}

function setRegimeFlowCandidatePageSize(size: number) {
  regimeFlowCandidatePagination.pageSize = size
  regimeFlowCandidatePagination.page = 1
}

function goRegimeFlowCandidatePage(page: number) {
  regimeFlowCandidatePagination.page = normalizePageNumber(page, regimeFlowCandidateTotalPages.value)
}

function setRegimeMarketScopePageSize(size: number) {
  regimeMarketScopePagination.pageSize = size
  regimeMarketScopePagination.page = 1
}

function goRegimeMarketScopePage(page: number) {
  regimeMarketScopePagination.page = normalizePageNumber(page, regimeMarketScopeTotalPages.value)
}

function requestRegimeParameterPreset(key: RegimeParameterPresetKey) {
  const preset = REGIME_PARAMETER_PRESETS.find((item) => item.key === key)
  if (!preset) {
    showNotice('error', '参数预设不可用', '待应用的风险偏好参数预设不存在。')
    return
  }
  pendingRegimePresetKey.value = key
  showNotice('info', '确认应用参数预设', regimePresetConfirmText.value)
}

function cancelRegimeParameterPreset() {
  pendingRegimePresetKey.value = ''
  showNotice('info', '参数预设未应用', '当前高级参数未修改。')
}

function confirmRegimeParameterPreset() {
  const disabledReason = regimePresetConfirmDisabledReason.value
  if (disabledReason) {
    showNotice('error', '参数预设不可用', disabledReason)
    pendingRegimePresetKey.value = ''
    return
  }
  const key = pendingRegimePresetKey.value
  if (!key) return
  applyRegimeParameterPreset(key)
}

function applyRegimeParameterPreset(key: RegimeParameterPresetKey) {
  const preset = REGIME_PARAMETER_PRESETS.find((item) => item.key === key)
  if (!preset) return
  for (const [field, value] of Object.entries(preset.values)) {
    ;(regimeForm as Record<string, any>)[field] = value
  }
  pendingRegimePresetKey.value = ''
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
  taskEventPagination.page = normalizePageNumber(page, taskEventTotalPages.value)
}

function setTaskResultPageSize(size: number) {
  taskResultPagination.pageSize = size
  taskResultPagination.page = 1
}

function goTaskResultPage(page: number) {
  taskResultPagination.page = normalizePageNumber(page, taskResultTotalPages.value)
}

function setTaskQualityIssuePageSize(size: number) {
  taskQualityIssuePagination.pageSize = size
  taskQualityIssuePagination.page = 1
}

function goTaskQualityIssuePage(page: number) {
  taskQualityIssuePagination.page = normalizePageNumber(page, taskQualityIssueTotalPages.value)
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
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : '-'
}

function formatRatioText(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : '-'
}

function trendMeterWidth(value: unknown) {
  const number = Number(String(value || '').replace('%', ''))
  if (!Number.isFinite(number)) return '12%'
  return `${Math.min(100, Math.max(8, 50 + number * 2))}%`
}

function formatDecimalValue(value: unknown, digits = 2) {
  if (value === null || value === undefined || value === '') return '-'
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
  const blocks: ReviewMarkdownBlock[] = []
  let pending: string[] = []
  let codeLines: string[] = []
  let inCode = false
  const flushPending = () => {
    const block = markdownTextBlock(pending)
    if (block) blocks.push(block)
    pending = []
  }
  String(text || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .forEach((line) => {
      if (line.trim().startsWith('```')) {
        if (inCode) {
          blocks.push({ type: 'code', title: '', lines: codeLines, headers: [], rows: [] })
          codeLines = []
          inCode = false
        } else {
          flushPending()
          inCode = true
        }
        return
      }
      if (inCode) {
        codeLines.push(line)
        return
      }
      if (!line.trim()) {
        flushPending()
        return
      }
      pending.push(line)
    })
  if (inCode && codeLines.length) {
    blocks.push({ type: 'code', title: '', lines: codeLines, headers: [], rows: [] })
  }
  flushPending()
  return blocks
}

function markdownTextBlock(rawLines: string[]): ReviewMarkdownBlock | null {
  const lines = rawLines.map((line) => line.trim()).filter(Boolean)
  if (!lines.length) return null
  const tableLines = lines.filter((line) => line.startsWith('|'))
  if (tableLines.length) {
    const rows = tableLines.map(tableCells)
    const [headers = [], ...bodyRows] = rows.filter((cells) => !isMarkdownDividerRow(cells))
    return { type: 'table', title: '', lines: [], headers, rows: bodyRows }
  }
  if (lines.every((line) => /^>\s?/.test(line))) {
    return {
      type: 'quote',
      title: '',
      lines: lines.map((line) => cleanMarkdownLine(line.replace(/^>\s?/, ''))),
      headers: [],
      rows: []
    }
  }
  if (lines.every((line) => /^([-*]|\d+[.)])\s+/.test(line))) {
    return {
      type: 'list',
      title: '',
      lines: lines.map(cleanMarkdownLine),
      headers: [],
      rows: []
    }
  }
  const heading = lines[0].match(/^#{1,6}\s+(.+)$/)
  if (heading) {
    return {
      type: 'section',
      title: cleanMarkdownLine(heading[1]),
      lines: lines.slice(1).map(cleanMarkdownLine).filter(Boolean),
      headers: [],
      rows: []
    }
  }
  return textBlock(lines)
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
    .replace(/^#{1,6}\s+/, '')
    .replace(/\*\*/g, '')
    .replace(/^[-*]\s+/, '• ')
    .replace(/^\d+[.)]\s+/, '• ')
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

function noticeRole(payload: NoticePayload) {
  return payload.type === 'error' ? 'alert' : 'status'
}

function noticeAriaLive(payload: NoticePayload) {
  return payload.type === 'error' ? 'assertive' : 'polite'
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
