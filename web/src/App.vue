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
          <button class="icon-button" :disabled="loadingOverview" @click="loadOverview(false)">
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
              <label>
                <span>代码来源</span>
                <select v-model="selectedGroup" :disabled="loadingSymbolGroups" @change="applySymbolGroup">
                  <option value="custom">自定义</option>
                  <option v-for="group in config?.symbol_groups || []" :key="group.name" :value="group.name">
                    {{ group.name }} · {{ group.symbols.length }}只
                  </option>
                </select>
              </label>

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
            <p class="table-caption">显示 {{ filteredCacheRows.length }} / {{ cacheRows.length }} 条，接口最多返回 500 条。</p>
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

          <Panel title="研究参数" subtitle="本地缓存">
            <div class="filter-row">
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
              <label class="span-double">
                <span>行情根目录</span>
                <input v-model="settings.data_root" type="text" />
              </label>
            </div>
          </Panel>

          <Panel title="研究快照" :subtitle="activeResearchMeta.label">
            <div class="snapshot-toolbar">
              <span>{{ activeResearchSnapshots.length }} 个当前模块快照</span>
              <button class="btn secondary" type="button" :disabled="!activeResearchResult" @click="saveActiveResearchSnapshot">
                <Icon name="save" />
                保存当前结果
              </button>
            </div>
            <div v-if="activeResearchSnapshots.length" class="snapshot-list">
              <article v-for="snapshot in activeResearchSnapshots" :key="snapshot.id" class="snapshot-row">
                <div>
                  <strong>{{ snapshot.title }}</strong>
                  <span>{{ snapshot.createdAt }} · {{ snapshot.summary }}</span>
                </div>
                <div class="snapshot-actions">
                  <button class="icon-button" type="button" title="载入快照" @click="loadResearchSnapshot(snapshot)">
                    <Icon name="download" />
                  </button>
                  <button class="icon-button danger" type="button" title="删除快照" @click="deleteResearchSnapshot(snapshot.id)">
                    <Icon name="trash" />
                  </button>
                </div>
              </article>
            </div>
            <EmptyState v-else title="暂无快照" body="运行当前研究模块后可保存结果，之后可一键载入。" />
          </Panel>

          <section v-if="activeResearchTab === 'history'" class="content-grid two">
            <Panel title="历史时序相似" subtitle="单标的">
              <form class="task-form" @submit.prevent="runHistorySearch">
                <label>
                  <span>标的代码</span>
                  <input v-model="historyForm.symbol" type="text" />
                </label>
                <label>
                  <span>截至日期</span>
                  <input v-model="historyForm.as_of" type="date" />
                </label>
                <label>
                  <span>窗口K数</span>
                  <input v-model.number="historyForm.window_size" type="number" min="2" />
                </label>
                <label>
                  <span>返回数量</span>
                  <input v-model.number="historyForm.top_n" type="number" min="1" />
                </label>
                <label>
                  <span>排除近端K数</span>
                  <input v-model.number="historyForm.exclusion_bars" type="number" min="0" />
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
            </Panel>

            <Panel title="历史匹配结果" subtitle="按综合相似度排序">
              <DataTable :rows="displayHistoryRows" :columns="historyColumns" empty="暂无历史匹配结果。" />
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
            </Panel>

            <Panel title="横截面匹配结果" subtitle="日期容忍后择优">
              <DataTable :rows="displayCrossRows" :columns="crossColumns" empty="暂无横截面匹配结果。" />
            </Panel>
          </section>

          <section v-else class="content-grid two">
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
                <label class="span-full">
                  <span>复盘标的</span>
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
              <Panel title="复盘文本" subtitle="默认输出">
                <div v-if="reviewText || videoScriptText" class="text-output">
                  <label>
                    <span>排序复盘</span>
                    <textarea :value="reviewText" rows="10" readonly></textarea>
                  </label>
                  <label>
                    <span>视频脚本</span>
                    <textarea :value="videoScriptText" rows="7" readonly></textarea>
                  </label>
                </div>
                <EmptyState v-else title="暂无复盘文本" body="生成复盘后展示默认排序复盘和视频脚本。" />
              </Panel>
              <Panel title="AI 锐评接口" subtitle="证据与提示词">
                <div v-if="reviewResult?.ai" class="ai-interface">
                  <div class="kv-list compact">
                    <div class="kv-row"><span>证据模式</span><strong>{{ reviewResult.ai.evidence?.mode || '-' }}</strong></div>
                    <div class="kv-row"><span>消息数量</span><strong>{{ reviewResult.ai.messages?.length || 0 }}</strong></div>
                  </div>
                  <label>
                    <span>模型 messages</span>
                    <textarea :value="aiMessagesText" rows="8" readonly></textarea>
                  </label>
                  <label>
                    <span>证据 JSON</span>
                    <textarea :value="aiEvidenceText" rows="8" readonly></textarea>
                  </label>
                </div>
                <EmptyState v-else title="暂无 AI 证据" body="生成复盘后展示可直接提交给模型的 evidence/messages。" />
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
            <div v-if="selectedTask" class="event-list">
              <div v-for="(event, index) in selectedTask.events" :key="index" class="event-row">
                <strong>{{ event.label }}</strong>
                <span>{{ event.message || event.stage }}</span>
                <em>{{ event.time }}</em>
              </div>
              <div v-if="selectedTask.error" class="error-box">{{ selectedTask.error }}</div>
              <DataTable
                v-if="selectedTask.result?.records?.length"
                :rows="displayResultRows"
                :columns="resultColumns"
                empty=""
              />
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

          <Panel title="运行状态" subtitle="API">
            <div class="kv-list">
              <div class="kv-row"><span>API</span><strong>http://127.0.0.1:8622</strong></div>
              <div class="kv-row"><span>运行链路</span><strong>{{ runtimeLabel }}</strong></div>
              <div class="kv-row"><span>索引文件</span><strong>{{ overview?.catalog_path || '未扫描' }}</strong></div>
              <div class="kv-row"><span>索引状态</span><strong>{{ overview?.catalog_exists ? '存在' : '未生成' }}</strong></div>
              <div class="kv-row"><span>数据上限</span><strong>表格最多显示 500 条记录</strong></div>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import DataTable from './components/DataTable.vue'
import EmptyState from './components/EmptyState.vue'
import Icon from './components/Icon.vue'
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

type DirectoryField = 'data_root' | 'tdx_path'
type ResearchTabKey = 'history' | 'cross' | 'review'

interface ResearchSnapshot {
  id: string
  tab: ResearchTabKey
  title: string
  createdAt: string
  summary: string
  payload: Record<string, any>
  result: Record<string, any>
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
const STATUS_LABELS: Record<string, string> = {
  cached: '可用',
  missing_file: '缺文件',
  read_error: '读取失败',
  missing_columns: '缺字段',
  no_valid_rows: '无有效K线',
  ok: '通过',
  quality_error: '质量异常',
  no_window_data: '窗口无数据',
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
const symbolsText = ref('')
const planning = ref(false)
const downloading = ref(false)
const loadingOverview = ref(false)
const loadingSymbolGroups = ref(false)
const clearingTasks = ref(false)
const runningResearch = ref<ResearchTabKey | ''>('')
const activeResearchTab = ref<ResearchTabKey>('history')
const pickingDirectory = ref<DirectoryField | ''>('')
const planRows = ref<Array<Record<string, any>>>([])
const planSummary = ref<Record<string, any>>({})
const historyResult = ref<Record<string, any> | null>(null)
const crossResult = ref<Record<string, any> | null>(null)
const reviewResult = ref<Record<string, any> | null>(null)
const researchSnapshots = ref<ResearchSnapshot[]>([])
const notice = ref<NoticePayload | null>(null)
const cacheFilters = reactive({
  keyword: '',
  assetType: '',
  timeframe: '',
  status: ''
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

const historyForm = reactive({
  symbol: '000001.SZ',
  as_of: todayText(),
  window_size: 20,
  top_n: 10,
  exclusion_bars: 20,
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
const displayCacheRows = computed(() => filteredCacheRows.value.map((row: Record<string, any>) => displayRecord(row)))
const displayPlanRows = computed(() => planRows.value.map((row: Record<string, any>) => displayRecord(row)))
const displayResultRows = computed(() =>
  (selectedTask.value?.result?.records || []).map((row: Record<string, any>) => displayRecord(row))
)
const displayHistoryRows = computed(() =>
  (historyResult.value?.results || []).map((row: Record<string, any>) => displayResearchRecord(row))
)
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
const aiMessagesText = computed(() => JSON.stringify(reviewResult.value?.ai?.messages || [], null, 2))
const aiEvidenceText = computed(() => JSON.stringify(reviewResult.value?.ai?.evidence || {}, null, 2))
const reviewText = computed(() => String(reviewResult.value?.text?.review || ''))
const videoScriptText = computed(() => String(reviewResult.value?.text?.video_script || ''))
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
const latestTask = computed(() => tasks.value[0])
const latestTaskText = computed(() => latestTask.value ? latestTask.value.status : '无')
const selectedTask = computed(() => tasks.value.find((task) => task.id === selectedTaskId.value) || tasks.value[0] || null)
const parsedSymbols = computed(() => parseSymbols(symbolsText.value))
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
  { key: 'status', label: '状态' },
  { key: 'rows', label: '行数' },
  { key: 'end_at', label: '结束' }
]
const resultColumns = [
  { key: 'stock_code', label: '代码' },
  { key: 'timeframe', label: '周期' },
  { key: 'action', label: '动作' },
  { key: 'rows_written', label: '写入行' },
  { key: 'new_rows', label: '新增行' },
  { key: 'message', label: '信息' }
]
const historyColumns = [
  { key: 'symbol', label: '代码' },
  { key: '窗口开始', label: '窗口开始' },
  { key: '窗口结束', label: '窗口结束' },
  { key: 'K线数量', label: 'K线' },
  { key: '综合相似度', label: '综合' },
  { key: '路径相似度', label: '路径' },
  { key: '区间收益', label: '收益' },
  { key: '最大回撤', label: '回撤' },
  { key: '后5根收益', label: '后5K' }
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
  window.setInterval(loadTasks, 2500)
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

async function loadSymbolGroups(preserveSelected: boolean) {
  loadingSymbolGroups.value = true
  const previousGroup = selectedGroup.value
  const previousSymbols = symbolsText.value
  try {
    settings.data_root = normalizeDataRoot(settings.data_root)
    const params = new URLSearchParams({
      data_root: settings.data_root,
      tdx_path: settings.tdx_path
    })
    const data = await apiGet(`/symbol-groups?${params.toString()}`)
    if (config.value) config.value.symbol_groups = (data.groups || []).filter(isSymbolGroup)
  } catch (error) {
    showError('快捷代码加载失败', error)
  } finally {
    loadingSymbolGroups.value = false
  }
  if (preserveSelected && previousGroup === 'custom') return
  const refreshed = config.value?.symbol_groups.find((item) => item.name === previousGroup)
  if (preserveSelected && refreshed) {
    symbolsText.value = refreshed.symbols.join('\n')
    return
  }
  if (preserveSelected) {
    selectedGroup.value = 'custom'
    symbolsText.value = previousSymbols
    return
  }
  const firstGroup = config.value?.symbol_groups?.[0]
  if (firstGroup) {
    selectedGroup.value = firstGroup.name
    symbolsText.value = firstGroup.symbols.join('\n')
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
  } catch (error) {
    showError(refresh ? '缓存扫描失败' : '缓存概览加载失败', error)
  } finally {
    loadingOverview.value = false
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
      as_of: historyForm.as_of,
      window_size: Number(historyForm.window_size || 20),
      top_n: Number(historyForm.top_n || 10),
      exclusion_bars: Number(historyForm.exclusion_bars || 0),
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
    showNotice('success', '复盘已生成', `完成 ${formatInt(reviewResult.value?.summary?.ranked_count)} 个标的排序。`)
  } catch (error) {
    showError('复盘生成失败', error)
  } finally {
    runningResearch.value = ''
  }
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
  showNotice('success', '快照已载入', snapshot.title)
}

function deleteResearchSnapshot(snapshotId: string) {
  researchSnapshots.value = researchSnapshots.value.filter((snapshot) => snapshot.id !== snapshotId)
  persistResearchSnapshots()
  showNotice('info', '快照已删除', '本地研究快照列表已更新。')
}

async function loadTasks() {
  try {
    const data = await apiGet('/tasks')
    tasks.value = data.tasks || []
    if (!selectedTaskId.value && tasks.value[0]) selectedTaskId.value = tasks.value[0].id
  } catch (error) {
    showError('任务列表加载失败', error)
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
  if (tab === 'history') return `历史相似 · ${historyForm.symbol || '-'} · ${historyForm.as_of || '-'}`
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
  window.localStorage.setItem(
    SETTINGS_STORAGE_KEY,
    JSON.stringify({
      data_root: settings.data_root,
      adjust: settings.adjust,
      tdx_path: settings.tdx_path,
      batch_size: settings.batch_size,
      strict_after_update: settings.strict_after_update
    })
  )
  showNotice('success', '设置已保存', '下次打开控制台会自动使用当前路径和运行参数。')
}

function resetSettings() {
  window.localStorage.removeItem(SETTINGS_STORAGE_KEY)
  Object.assign(settings, config.value?.defaults || {})
  settings.data_root = normalizeDataRoot(settings.data_root)
  selectedTimeframe.value = config.value?.defaults?.timeframes?.[0] || '1d'
  showNotice('info', '已恢复默认', '已恢复 API 提供的默认路径和运行参数。')
}

function restoreSettings() {
  const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (saved.data_root) saved.data_root = normalizeDataRoot(saved.data_root)
    Object.assign(settings, saved)
  } catch {
    window.localStorage.removeItem(SETTINGS_STORAGE_KEY)
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

function todayText() {
  return new Date().toISOString().slice(0, 10)
}

function offsetDateText(offsetDays: number) {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  return date.toISOString().slice(0, 10)
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
