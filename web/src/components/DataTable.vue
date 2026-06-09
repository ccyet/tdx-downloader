<template>
  <div class="data-table-shell">
    <div v-if="rows.length && hasHiddenColumns" class="data-table-toolbar">
      <span>显示 {{ visibleColumns.length }} / {{ columns.length }} 列 · 更多指标</span>
      <button class="table-expand-toggle" type="button" @click="expanded = !expanded">
        {{ expanded ? '收起表格' : '展开查看' }}
      </button>
    </div>
    <div v-if="rows.length" class="table-wrap" :class="{ expanded }">
      <table>
        <thead>
          <tr>
            <th
              v-for="column in visibleColumns"
              :key="column.key"
              :aria-sort="ariaSort(column)"
            >
              <button
                class="table-sort-button"
                type="button"
                :aria-label="sortAriaLabel(column)"
                :title="sortAriaLabel(column)"
                @click="toggleSort(column)"
              >
                <span>{{ column.label }}</span>
                <em v-if="sortIndicator(column)" aria-hidden="true">{{ sortIndicator(column) }}</em>
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in sortedRows" :key="index">
            <td
              v-for="column in visibleColumns"
              :key="column.key"
              :class="cellToneClass(column, row[column.key])"
              :title="String(row[column.key] ?? '')"
            >
              <span :class="['cell-badge', cellToneClass(column, row[column.key])]">
                {{ cellText(row[column.key]) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else :title="empty || '暂无数据'" body="" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EmptyState from './EmptyState.vue'

interface DataTableColumn {
  key: string
  label: string
}

type SortDirection = 'asc' | 'desc'
type CellTone = 'positive' | 'negative' | 'success' | 'warning' | 'danger' | 'info'

const DEFAULT_COMPACT_COLUMN_COUNT = 8
const TABLE_TONE_CLASSES: Record<CellTone, string> = {
  positive: 'tone-positive',
  negative: 'tone-negative',
  success: 'tone-success',
  warning: 'tone-warning',
  danger: 'tone-danger',
  info: 'tone-info'
}

const props = defineProps<{
  rows: Array<Record<string, unknown>>
  columns: DataTableColumn[]
  empty: string
}>()

const expanded = ref(false)
const sortState = ref<{ key: string; direction: SortDirection } | null>(null)

const hasHiddenColumns = computed(() => props.columns.length > DEFAULT_COMPACT_COLUMN_COUNT)
const visibleColumns = computed(() =>
  expanded.value || !hasHiddenColumns.value ? props.columns : props.columns.slice(0, DEFAULT_COMPACT_COLUMN_COUNT)
)
const sortedRows = computed(() => {
  const state = sortState.value
  if (!state) return props.rows
  return [...props.rows].sort((left, right) => {
    const result = compareValues(left[state.key], right[state.key])
    return state.direction === 'asc' ? result : -result
  })
})

watch(
  () => props.columns.map((column) => column.key).join('|'),
  () => {
    sortState.value = null
    expanded.value = false
  }
)

function toggleSort(column: DataTableColumn) {
  if (sortState.value?.key !== column.key) {
    sortState.value = { key: column.key, direction: 'desc' }
    return
  }
  if (sortState.value.direction === 'desc') {
    sortState.value = { key: column.key, direction: 'asc' }
    return
  }
  sortState.value = null
}

function sortIndicator(column: DataTableColumn) {
  if (sortState.value?.key !== column.key) return ''
  return sortState.value.direction === 'desc' ? '↓' : '↑'
}

function sortAriaLabel(column: DataTableColumn) {
  if (sortState.value?.key !== column.key) return `${column.label}列，点击后按降序排列`
  if (sortState.value.direction === 'desc') return `${column.label}列，当前降序，点击后按升序排列`
  return `${column.label}列，当前升序，点击后取消排序`
}

function ariaSort(column: DataTableColumn) {
  if (sortState.value?.key !== column.key) return 'none'
  return sortState.value.direction === 'desc' ? 'descending' : 'ascending'
}

function cellText(value: unknown) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function compareValues(left: unknown, right: unknown) {
  const leftNumber = comparableNumber(left)
  const rightNumber = comparableNumber(right)
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber
  }
  return cellText(left).localeCompare(cellText(right), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' })
}

function comparableNumber(value: unknown) {
  if (typeof value === 'number') return value
  const text = cellText(value).replace(/,/g, '').trim()
  if (!text || text === '-') return NaN
  if (/^-?\d+(\.\d+)?%$/.test(text)) return Number(text.slice(0, -1)) / 100
  const amountMatch = /^(-?\d+(?:\.\d+)?)(万|亿)$/.exec(text)
  if (amountMatch) {
    const unit = amountMatch[2] === '亿' ? 100000000 : 10000
    return Number(amountMatch[1]) * unit
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
    return Date.parse(text)
  }
  return /^-?\d+(\.\d+)?$/.test(text) ? Number(text) : NaN
}

function cellToneClass(column: DataTableColumn, value: unknown) {
  const tone = cellTone(column, value)
  return tone ? TABLE_TONE_CLASSES[tone] : ''
}

function cellTone(column: DataTableColumn, value: unknown): CellTone | '' {
  const text = cellText(value)
  const key = `${column.key} ${column.label}`
  const percent = comparableNumber(text)
  if (/%$/.test(text) || /收益|涨幅|回撤|占比|覆盖率|YTD|当日|近\d+日/.test(key)) {
    if (Number.isFinite(percent) && percent > 0) return 'positive'
    if (Number.isFinite(percent) && percent < 0) return 'negative'
  }
  if (/失败|错误|异常|缺|无数据|missing|error|failed|danger/i.test(text)) return 'danger'
  if (/待|部分|未扫描|预览|fetch|pending|partial/i.test(text)) return 'warning'
  if (/可用|已下载|通过|完成|成功|cached|success|ok/i.test(text)) return 'success'
  if (/TDX接口|代码表\/缓存|股票型|其他型|宽基类|行业指数类|主题类|债类|其他类/.test(text)) return 'info'
  return ''
}
</script>
