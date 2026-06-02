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

          <div class="asset-overview-grid">
            <article class="overview-hero-card">
              <div class="asset-card-head">
                <div class="asset-icon"><Icon name="database" /></div>
                <div>
                  <span>缓存资产总览</span>
                  <strong>{{ formatInt(summary.symbol_count) }} 标的</strong>
                </div>
              </div>
              <div class="dashboard-key-stats">
                <div v-for="item in dashboardKeyStats" :key="item.label" class="dashboard-key-stat">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
            </article>

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
                <span>标的 · {{ formatInt(asset.rows) }} 行 · {{ formatInt(asset.cachedPeriodItems) }} / {{ formatInt(asset.totalPeriodItems) }} 周期项可用</span>
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

          <div class="content-grid two">
            <Panel title="周期覆盖概览" subtitle="缓存资产">
              <div v-if="displayTimeframeRows.length" class="split-list">
                <div v-for="row in displayTimeframeRows" :key="row.timeframe" class="split-row">
                  <strong>{{ row.timeframe }}</strong>
                  <span>{{ formatInt(row.cached_count) }} 可用</span>
                  <em>{{ formatInt(row.unavailable_count) }} 缺口 · {{ formatInt(row.rows) }} 行</em>
                </div>
              </div>
              <EmptyState v-else title="暂无周期覆盖" body="扫描缓存后展示不同周期的可用资产数量。" />
            </Panel>

            <div class="view-stack">
              <Panel title="运行环境" subtitle="TDX">
                <div class="kv-list">
                  <div class="kv-row"><span>行情根目录</span><strong>{{ settings.data_root }}</strong></div>
                  <div class="kv-row"><span>TDX PYPlugins/user</span><strong>{{ settings.tdx_path }}</strong></div>
                  <div class="kv-row"><span>复权</span><strong>{{ settings.adjust }}</strong></div>
                  <div class="kv-row"><span>批次大小</span><strong>{{ settings.batch_size }}</strong></div>
                  <div class="kv-row"><span>严格复核</span><strong>{{ settings.strict_after_update ? '开启' : '关闭' }}</strong></div>
                </div>
              </Panel>

              <Panel title="最近执行" subtitle="任务">
                <div v-if="latestTask" class="recent-task-card">
                  <strong>{{ latestTask.status }}</strong>
                  <span>{{ latestTask.id }}</span>
                  <em>{{ latestTask.error || latestTask.finished_at || latestTask.started_at || latestTask.created_at }}</em>
                </div>
                <EmptyState v-else title="暂无任务" body="执行下载后这里展示最近一次任务状态。" />
              </Panel>
            </div>
          </div>

          <Panel title="回测准备度" subtitle="按资产类型和周期">
            <DataTable :rows="displayReadinessRows" :columns="readinessColumns" empty="暂无准备度记录，先扫描缓存。" />
          </Panel>
        </section>

        <section v-else-if="activeView === 'download'" class="content-grid form-grid">
          <Panel title="下载参数" subtitle="任务配置">
            <form class="task-form" @submit.prevent="previewPlan">
              <label>
                <span>代码来源</span>
                <select v-model="selectedGroup" @change="applySymbolGroup">
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

interface ConfigPayload {
  defaults: Record<string, any>
  timeframes: string[]
  asset_types: Array<{ value: string; label: string }>
  symbol_groups: Array<{ name: string; symbols: string[] }>
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

const IMPORTANT_ASSET_TYPES = [
  { value: 'etf', label: 'ETF', tone: 'blue', icon: 'archive' },
  { value: 'stock', label: '个股', tone: 'green', icon: 'key' },
  { value: 'index', label: '指数', tone: 'indigo', icon: 'layers' }
]

const navItems = [
  { key: 'dashboard', label: '总览', title: 'TDX 数据运营工作台', description: '查看缓存资产、运行环境和最近任务。', icon: 'dashboard' },
  { key: 'download', label: '下载任务', title: '下载任务', description: '配置代码、周期、时间窗并在后台执行。', icon: 'download' },
  { key: 'cache', label: '缓存资产', title: '缓存资产', description: '查看 SQLite catalog 与本地 parquet 缓存。', icon: 'archive' },
  { key: 'tasks', label: '执行记录', title: '执行记录', description: '查看后台任务状态、错误和写入结果。', icon: 'activity' },
  { key: 'settings', label: '系统设置', title: '系统设置', description: '配置默认路径、复权方式和运行参数。', icon: 'settings' }
]

const SETTINGS_STORAGE_KEY = 'tdx-downloader-web-settings'
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
const sidebarCollapsed = ref(false)
const activeView = ref('dashboard')
const config = ref<ConfigPayload | null>(null)
const overview = ref<Record<string, any> | null>(null)
const tasks = ref<TaskPayload[]>([])
const selectedTaskId = ref('')
const selectedGroup = ref('核心样例')
const selectedTimeframe = ref('1d')
const symbolsText = ref('')
const planning = ref(false)
const downloading = ref(false)
const loadingOverview = ref(false)
const clearingTasks = ref(false)
const pickingDirectory = ref<DirectoryField | ''>('')
const planRows = ref<Array<Record<string, any>>>([])
const planSummary = ref<Record<string, any>>({})
const notice = ref<NoticePayload | null>(null)
const cacheFilters = reactive({
  keyword: '',
  assetType: '',
  timeframe: '',
  status: ''
})

const settings = reactive({
  data_root: '/Volumes/ccOUT 1/tdx-data/daily',
  adjust: 'qfq',
  tdx_path: '/Volumes/[C] Windows 11/new_tdx64/PYPlugins/user',
  start: '',
  end: '',
  mode: 'smart',
  batch_size: 100,
  strict_after_update: true
})

const activeMeta = computed(() => navItems.find((item) => item.key === activeView.value) || navItems[0])
const summary = computed(() => overview.value?.summary || {})
const assetRows = computed(() => overview.value?.by_asset_type || [])
const timeframeRows = computed(() => overview.value?.by_timeframe || [])
const datasetRows = computed(() => overview.value?.by_dataset || [])
const readinessRows = computed(() => overview.value?.readiness || [])
const displayReadinessRows = computed(() => readinessRows.value.map((row: Record<string, any>) => displayRecord(row)))
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
const displayTimeframeRows = computed(() =>
  [...timeframeRows.value].sort(
    (left: Record<string, any>, right: Record<string, any>) =>
      timeframeRank(String(left.timeframe || '')) - timeframeRank(String(right.timeframe || ''))
  )
)
const dashboardKeyStats = computed(() => [
  { label: '资产类型', value: `${formatInt(summary.value.asset_type_count)} 类` },
  {
    label: '可用周期项',
    value: `${formatInt(summary.value.data_inventory_cached_count)} / ${formatInt(summary.value.data_inventory_row_count)}`
  },
  { label: '缺口项', value: formatInt(summary.value.data_inventory_unavailable_count) },
  { label: '总行数', value: formatInt(summary.value.data_inventory_total_rows) },
  { label: '文件体积', value: formatBytes(summary.value.data_inventory_total_file_size_bytes) },
  { label: '运行链路', value: runtimeLabel.value }
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

const readinessColumns = [
  { key: 'timeframe', label: '周期' },
  { key: 'asset_type_label', label: '资产' },
  { key: 'status', label: '状态' },
  { key: 'total_count', label: '总数' },
  { key: 'cached_count', label: '可用' },
  { key: 'missing_count', label: '缺口' },
  { key: 'latest_end_at', label: '最近结束' }
]
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

onMounted(async () => {
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
  const firstGroup = config.value?.symbol_groups?.[0]
  if (firstGroup) {
    selectedGroup.value = firstGroup.name
    symbolsText.value = firstGroup.symbols.join('\n')
  }
}

async function loadOverview(refresh: boolean) {
  loadingOverview.value = true
  try {
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
    settings[field] = data.path
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

function payload() {
  return {
    ...settings,
    symbols: parsedSymbols.value,
    timeframes: [selectedTimeframe.value],
    batch_size: Number(settings.batch_size || 100)
  }
}

function saveSettings() {
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
  selectedTimeframe.value = config.value?.defaults?.timeframes?.[0] || '1d'
  showNotice('info', '已恢复默认', '已恢复 API 提供的默认路径和运行参数。')
}

function restoreSettings() {
  const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY)
  if (!raw) return
  try {
    Object.assign(settings, JSON.parse(raw))
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

function compactPath(path: string) {
  if (!path) return '未设置'
  return path.length > 34 ? `${path.slice(0, 16)}...${path.slice(-14)}` : path
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
