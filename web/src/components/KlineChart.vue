<template>
  <article class="kline-chart">
    <header class="kline-chart-head">
      <div>
        <span>{{ rankLabel }}</span>
        <strong>{{ displayName }}</strong>
        <em>{{ item.symbol }} · {{ candleCount }} 根K线</em>
      </div>
      <b :class="returnClass">{{ formatPercent(periodReturn) }}</b>
    </header>

    <svg viewBox="0 0 640 320" role="img" :aria-label="`${displayName}窗口期K线图`">
      <defs>
        <linearGradient :id="gradientId" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#e8fffb" />
          <stop offset="100%" stop-color="#ffffff" />
        </linearGradient>
      </defs>
      <rect class="plot-bg" x="44" y="28" width="580" height="206" rx="10" :fill="`url(#${gradientId})`" />
      <g class="grid">
        <g v-for="tick in priceTicks" :key="tick.value">
          <line x1="44" x2="624" :y1="tick.y" :y2="tick.y" />
          <text x="38" :y="tick.y + 4" text-anchor="end">{{ formatPrice(tick.value) }}</text>
        </g>
      </g>
      <polyline v-if="closeLinePoints" class="close-line" :points="closeLinePoints" />
      <g class="candles">
        <g v-for="(candle, index) in normalizedCandles" :key="`${candle.date}-${index}`">
          <line
            :class="['wick', candleTone(candle)]"
            :x1="xFor(index)"
            :x2="xFor(index)"
            :y1="priceY(candle.high)"
            :y2="priceY(candle.low)"
          />
          <rect
            :class="['body', candleTone(candle)]"
            :x="xFor(index) - candleWidth / 2"
            :y="bodyY(candle)"
            :width="candleWidth"
            :height="bodyHeight(candle)"
            rx="1"
          />
        </g>
      </g>
      <g class="volume">
        <line x1="44" x2="624" y1="286" y2="286" />
        <rect
          v-for="(candle, index) in normalizedCandles"
          :key="`v-${candle.date}-${index}`"
          :class="['volume-bar', candleTone(candle)]"
          :x="xFor(index) - volumeWidth / 2"
          :y="volumeY(candle.volume)"
          :width="volumeWidth"
          :height="286 - volumeY(candle.volume)"
          rx="1"
        />
      </g>
      <text class="axis-label" x="44" y="309">{{ startDate }}</text>
      <text class="axis-label" x="624" y="309" text-anchor="end">{{ endDate }}</text>
    </svg>

    <footer>
      <span>收盘 {{ formatPrice(lastClose) }}</span>
      <span>回撤 {{ formatPercent(maxDrawdown) }}</span>
      <span>{{ startDate }} - {{ endDate }}</span>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface RawCandle {
  date?: string
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  volume?: number | null
}

interface Candle {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface KlineItem {
  symbol: string
  name?: string
  rank?: number | string
  overview?: Record<string, any>
  candles: RawCandle[]
}

const props = defineProps<{
  item: KlineItem
}>()

const chartWidth = 640
const plotLeft = 44
const plotRight = 624
const plotTop = 28
const plotBottom = 234
const volumeTop = 252
const volumeBottom = 286
const plotWidth = plotRight - plotLeft
const gradientId = computed(() => `kline-gradient-${props.item.symbol.replace(/[^a-zA-Z0-9]/g, '-')}`)

const normalizedCandles = computed<Candle[]>(() =>
  (props.item.candles || [])
    .map((row) => ({
      date: String(row.date || ''),
      open: numberValue(row.open),
      high: numberValue(row.high),
      low: numberValue(row.low),
      close: numberValue(row.close),
      volume: Math.max(numberValue(row.volume), 0)
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

const candleCount = computed(() => normalizedCandles.value.length)
const displayName = computed(() => props.item.name || props.item.symbol)
const rankLabel = computed(() => (props.item.rank ? `#${props.item.rank}` : '窗口走势'))
const periodReturn = computed(() => numberValue(props.item.overview?.return))
const maxDrawdown = computed(() => numberValue(props.item.overview?.max_drawdown))
const returnClass = computed(() => (periodReturn.value >= 0 ? 'positive' : 'negative'))
const startDate = computed(() => formatDate(normalizedCandles.value[0]?.date))
const endDate = computed(() => formatDate(normalizedCandles.value[normalizedCandles.value.length - 1]?.date))
const lastClose = computed(() => normalizedCandles.value[normalizedCandles.value.length - 1]?.close ?? NaN)

const priceRange = computed(() => {
  if (!normalizedCandles.value.length) return { min: 0, max: 1 }
  const lows = normalizedCandles.value.map((row) => row.low)
  const highs = normalizedCandles.value.map((row) => row.high)
  const min = Math.min(...lows)
  const max = Math.max(...highs)
  const span = Math.max(max - min, Math.abs(max) * 0.02, 0.01)
  return { min: min - span * 0.08, max: max + span * 0.08 }
})

const priceTicks = computed(() => {
  const ticks = []
  for (let index = 0; index < 4; index += 1) {
    const ratio = index / 3
    const value = priceRange.value.max - (priceRange.value.max - priceRange.value.min) * ratio
    ticks.push({ value, y: plotTop + (plotBottom - plotTop) * ratio })
  }
  return ticks
})

const candleWidth = computed(() => Math.max(2, Math.min(12, (plotWidth / Math.max(candleCount.value, 1)) * 0.58)))
const volumeWidth = computed(() => Math.max(1, Math.min(10, candleWidth.value * 0.72)))
const maxVolume = computed(() => Math.max(...normalizedCandles.value.map((row) => row.volume), 1))
const closeLinePoints = computed(() =>
  normalizedCandles.value.map((row, index) => `${xFor(index)},${priceY(row.close)}`).join(' ')
)

function xFor(index: number): number {
  if (candleCount.value <= 1) return chartWidth / 2
  return plotLeft + (plotWidth / (candleCount.value - 1)) * index
}

function priceY(price: number): number {
  const range = priceRange.value.max - priceRange.value.min || 1
  return plotBottom - ((price - priceRange.value.min) / range) * (plotBottom - plotTop)
}

function volumeY(volume: number): number {
  const ratio = Math.max(0, Math.min(volume / maxVolume.value, 1))
  return volumeBottom - ratio * (volumeBottom - volumeTop)
}

function bodyY(candle: Candle): number {
  return Math.min(priceY(candle.open), priceY(candle.close))
}

function bodyHeight(candle: Candle): number {
  return Math.max(Math.abs(priceY(candle.open) - priceY(candle.close)), 2)
}

function candleTone(candle: Candle): 'up' | 'down' {
  return candle.close >= candle.open ? 'up' : 'down'
}

function numberValue(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : NaN
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
  if (!value) return '-'
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

svg {
  width: 100%;
  height: auto;
  display: block;
}

.plot-bg {
  stroke: #d6e6e4;
}

.grid line,
.volume line {
  stroke: #dfe9ee;
  stroke-width: 1;
}

.grid text,
.axis-label {
  fill: #718096;
  font-size: 11px;
  font-weight: 700;
}

.close-line {
  fill: none;
  stroke: #087f78;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.2;
  opacity: 0.68;
}

.wick,
.body {
  stroke-width: 1.4;
}

.wick.up,
.body.up {
  stroke: #d63d2e;
  fill: #d63d2e;
}

.wick.down,
.body.down {
  stroke: #008a55;
  fill: #008a55;
}

.volume-bar {
  opacity: 0.26;
}

.volume-bar.up {
  fill: #d63d2e;
}

.volume-bar.down {
  fill: #008a55;
}

footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
}
</style>
