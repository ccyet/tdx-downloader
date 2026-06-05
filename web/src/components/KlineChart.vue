<template>
  <article class="kline-chart">
    <header class="kline-chart-head">
      <div>
        <span>{{ rankLabel }}</span>
        <strong>{{ displayName }}</strong>
        <em>{{ itemSymbol }} · {{ candleCount }} 根K线</em>
      </div>
      <b :class="returnClass">{{ formatPercent(periodReturn) }}</b>
    </header>

    <div ref="chartRoot" class="plotly-kline" role="img" :aria-label="`${displayName}窗口期K线图`"></div>

    <footer>
      <span>收盘 {{ formatPrice(lastClose) }}</span>
      <span>回撤 {{ formatPercent(maxDrawdown) }}</span>
      <span>{{ startDate }} - {{ endDate }}</span>
      <span>拖动缩放 · 双击复位</span>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

interface RawCandle {
  date?: string
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  volume?: number | null
  amount?: number | null
}

interface RawSegment {
  start?: string
  end?: string
  direction?: string
  return?: number | null
}

interface Candle {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  turnover: number
}

interface Segment {
  start: string
  end: string
  direction: string
  return: number
}

interface KlineItem {
  symbol?: string
  name?: string
  label?: string
  rank?: number | string
  overview?: Record<string, any>
  candles?: RawCandle[]
  segments?: RawSegment[]
}

const props = defineProps<{
  item: KlineItem
}>()

const chartRoot = ref<HTMLDivElement | null>(null)
let resizeObserver: ResizeObserver | null = null
let plotlyModule: any | null = null
let plotlyPromise: Promise<any> | null = null

const itemSymbol = computed(() => props.item.symbol || '-')
const normalizedCandles = computed<Candle[]>(() =>
  (props.item.candles || [])
    .map((row) => ({
      date: formatDate(row.date),
      open: numberValue(row.open),
      high: numberValue(row.high),
      low: numberValue(row.low),
      close: numberValue(row.close),
      volume: Math.max(numberValue(row.volume), 0),
      amount: Math.max(numberValue(row.amount), 0),
      turnover: turnoverValue(row)
    }))
    .filter(
      (row) =>
        row.date &&
        Number.isFinite(row.open) &&
        Number.isFinite(row.high) &&
        Number.isFinite(row.low) &&
        Number.isFinite(row.close)
    )
)
const normalizedSegments = computed<Segment[]>(() =>
  (props.item.segments || [])
    .map((row) => ({
      start: formatDate(row.start),
      end: formatDate(row.end),
      direction: String(row.direction || ''),
      return: numberValue(row.return)
    }))
    .filter((row) => row.start && row.end)
)

const candleCount = computed(() => normalizedCandles.value.length)
const displayName = computed(() => props.item.name || itemSymbol.value)
const rankLabel = computed(() => {
  if (props.item.label) return props.item.label
  if (!props.item.rank) return '窗口走势'
  const rank = String(props.item.rank)
  return Number.isFinite(Number(rank)) ? `#${rank}` : rank
})
const periodReturn = computed(() => {
  const fromOverview = numberValue(props.item.overview?.return)
  return Number.isFinite(fromOverview) ? fromOverview : candleReturn(normalizedCandles.value)
})
const maxDrawdown = computed(() => {
  const fromOverview = numberValue(props.item.overview?.max_drawdown)
  return Number.isFinite(fromOverview) ? fromOverview : candleDrawdown(normalizedCandles.value)
})
const returnClass = computed(() => (periodReturn.value >= 0 ? 'positive' : 'negative'))
const startDate = computed(() => normalizedCandles.value[0]?.date || '-')
const endDate = computed(() => normalizedCandles.value[normalizedCandles.value.length - 1]?.date || '-')
const lastClose = computed(() => normalizedCandles.value[normalizedCandles.value.length - 1]?.close ?? NaN)

const plotData = computed(() => {
  const candles = normalizedCandles.value
  return [
    {
      type: 'candlestick',
      x: candles.map((row) => row.date),
      open: candles.map((row) => row.open),
      high: candles.map((row) => row.high),
      low: candles.map((row) => row.low),
      close: candles.map((row) => row.close),
      name: displayName.value,
      increasing: { line: { color: '#d63d2e', width: 1.2 }, fillcolor: '#d63d2e' },
      decreasing: { line: { color: '#008a55', width: 1.2 }, fillcolor: '#008a55' },
      hovertemplate: '日期 %{x}<br>开 %{open:.2f}<br>高 %{high:.2f}<br>低 %{low:.2f}<br>收 %{close:.2f}<extra></extra>'
    },
    {
      type: 'bar',
      x: candles.map((row) => row.date),
      y: candles.map((row) => row.turnover),
      yaxis: 'y2',
      name: '成交额',
      marker: {
        color: candles.map((row) => (candleTone(row) === 'up' ? 'rgba(214, 61, 46, 0.22)' : 'rgba(0, 138, 85, 0.22)'))
      },
      hovertemplate: '成交额 %{y:.0f}<extra></extra>'
    }
  ]
})

const plotLayout = computed(() => ({
  autosize: true,
  height: 380,
  margin: { l: 46, r: 18, t: 8, b: 72 },
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: '#fbfffe',
  dragmode: 'zoom',
  hovermode: 'x unified',
  showlegend: false,
  shapes: segmentShapes(),
  xaxis: {
    type: 'category',
    rangeslider: { visible: false },
    showgrid: false,
    tickfont: { color: '#718096', size: 10 },
    tickangle: -35,
    automargin: true,
    nticks: 8,
    linecolor: '#dfe9ee',
    zeroline: false,
    fixedrange: false
  },
  yaxis: {
    domain: [0.34, 1],
    title: { text: '价格', font: { color: '#607083', size: 11 } },
    gridcolor: '#e5edf2',
    tickfont: { color: '#718096', size: 10 },
    zeroline: false,
    fixedrange: false
  },
  yaxis2: {
    domain: [0, 0.2],
    title: { text: '额', font: { color: '#607083', size: 11 } },
    showgrid: false,
    tickfont: { color: '#718096', size: 10 },
    zeroline: false,
    fixedrange: false
  }
}))

const plotConfig = {
  responsive: true,
  displaylogo: false,
  scrollZoom: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d']
}

watch(
  () => props.item,
  () => {
    void renderChart()
  },
  { deep: true }
)

onMounted(() => {
  void renderChart()
  if (chartRoot.value && 'ResizeObserver' in window) {
    resizeObserver = new ResizeObserver(() => {
      if (!chartRoot.value || !plotlyModule) return
      plotlyModule.Plots.resize(chartRoot.value)
    })
    resizeObserver.observe(chartRoot.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (chartRoot.value && plotlyModule) plotlyModule.purge(chartRoot.value)
})

async function renderChart() {
  await nextTick()
  if (!chartRoot.value) return
  const Plotly = await loadPlotly()
  await Plotly.react(chartRoot.value, plotData.value as any, plotLayout.value as any, plotConfig as any)
}

async function loadPlotly() {
  if (plotlyModule) return plotlyModule
  if (!plotlyPromise) {
    plotlyPromise = import('plotly.js-dist-min').then((module) => (module as any).default || module)
  }
  plotlyModule = await plotlyPromise
  return plotlyModule
}

function segmentShapes() {
  return normalizedSegments.value.map((segment) => {
    return {
      type: 'rect',
      xref: 'x',
      yref: 'paper',
      x0: segment.start,
      x1: segment.end,
      y0: 0,
      y1: 1,
      fillcolor: segmentFillColor(segment.direction),
      line: { width: 0 },
      layer: 'below'
    }
  })
}

function segmentFillColor(direction: string) {
  if (['当前窗口', '相似区间', 'window', 'match'].includes(direction)) return 'rgba(9, 199, 190, 0.12)'
  return ['上涨', '反弹', 'rise', 'up'].includes(direction) ? 'rgba(214, 61, 46, 0.08)' : 'rgba(0, 138, 85, 0.08)'
}

function candleTone(candle: Candle): 'up' | 'down' {
  return candle.close >= candle.open ? 'up' : 'down'
}

function candleReturn(candles: Candle[]): number {
  if (candles.length < 2 || candles[0].close === 0) return NaN
  return candles[candles.length - 1].close / candles[0].close - 1
}

function candleDrawdown(candles: Candle[]): number {
  let peak = -Infinity
  let drawdown = 0
  for (const candle of candles) {
    if (!Number.isFinite(candle.close)) continue
    peak = Math.max(peak, candle.close)
    if (peak > 0) drawdown = Math.min(drawdown, candle.close / peak - 1)
  }
  return drawdown
}

function numberValue(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : NaN
}

function turnoverValue(row: RawCandle): number {
  const amount = numberValue(row.amount)
  if (Number.isFinite(amount) && amount > 0) return amount
  const volume = numberValue(row.volume)
  return Number.isFinite(volume) && volume > 0 ? volume : 0
}

function formatPercent(value: number): string {
  return Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '-'
}

function formatPrice(value: number): string {
  if (!Number.isFinite(value)) return '-'
  if (Math.abs(value) >= 1000) return value.toFixed(0)
  if (Math.abs(value) >= 100) return value.toFixed(1)
  return value.toFixed(2)
}

function formatDate(value?: string): string {
  if (!value) return ''
  return value.slice(0, 10)
}
</script>

<style scoped>
.kline-chart {
  min-width: 0;
  display: grid;
  gap: 10px;
  border: 1px solid #cde2e0;
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
}

.kline-chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.kline-chart-head div {
  min-width: 0;
}

.kline-chart-head span,
.kline-chart-head em,
footer {
  color: #607083;
  font-size: 12px;
  font-weight: 700;
}

.kline-chart-head strong {
  display: block;
  margin-top: 2px;
  overflow: hidden;
  color: #101828;
  font-size: 17px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kline-chart-head b {
  border-radius: 8px;
  padding: 7px 9px;
  font-size: 14px;
  font-weight: 900;
  white-space: nowrap;
}

.kline-chart-head b.positive {
  background: #ffecea;
  color: #d63d2e;
}

.kline-chart-head b.negative {
  background: #e6f8ef;
  color: #008a55;
}

.plotly-kline {
  min-height: 380px;
  overflow: hidden;
  border: 1px solid #d6e6e4;
  border-radius: 8px;
  background: linear-gradient(180deg, #f9fffe 0%, #ffffff 100%);
}

.plotly-kline :deep(.modebar) {
  top: 4px !important;
  right: 4px !important;
}

.plotly-kline :deep(.modebar-btn path) {
  fill: #607083;
}

footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
}
</style>
