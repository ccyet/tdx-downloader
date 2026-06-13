<template>
  <div class="paginated-table">
    <div v-if="rows.length > pageSize" class="table-toolbar">
      <p class="table-caption">显示 {{ pageFirst }}-{{ pageEnd }} / {{ rows.length }} 条</p>
      <div class="table-controls">
        <div class="page-size-group" :aria-label="`${ariaLabel || '表格'}每页条数`">
          <span>每页</span>
          <button
            v-for="size in pageSizeOptions"
            :key="size"
            type="button"
            :class="['page-size-button', { active: pageSize === size }]"
            :aria-pressed="pageSize === size ? 'true' : 'false'"
            :title="pageSizeButtonTitle(size)"
            @click="setPageSize(size)"
          >
            {{ size }}
          </button>
        </div>
        <div class="pagination-controls">
          <button
            type="button"
            :disabled="paginationActionDisabled('first')"
            :aria-disabled="paginationActionDisabled('first')"
            :aria-label="paginationActionTitle('first')"
            :title="paginationActionTitle('first')"
            @click="goPage(1)"
          >
            首页
          </button>
          <button
            type="button"
            :disabled="paginationActionDisabled('prev')"
            :aria-disabled="paginationActionDisabled('prev')"
            :aria-label="paginationActionTitle('prev')"
            :title="paginationActionTitle('prev')"
            @click="goPage(page - 1)"
          >
            上一页
          </button>
          <span class="pagination-status" aria-live="polite">{{ page }} / {{ totalPages }}</span>
          <button
            type="button"
            :disabled="paginationActionDisabled('next')"
            :aria-disabled="paginationActionDisabled('next')"
            :aria-label="paginationActionTitle('next')"
            :title="paginationActionTitle('next')"
            @click="goPage(page + 1)"
          >
            下一页
          </button>
          <button
            type="button"
            :disabled="paginationActionDisabled('last')"
            :aria-disabled="paginationActionDisabled('last')"
            :aria-label="paginationActionTitle('last')"
            :title="paginationActionTitle('last')"
            @click="goPage(totalPages)"
          >
            末页
          </button>
        </div>
      </div>
    </div>
    <DataTable :rows="pagedRows" :columns="columns" :empty="empty" :aria-label="ariaLabel || empty || '分页数据表'" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import DataTable from './DataTable.vue'

interface DataTableColumn {
  key: string
  label: string
}

type PaginationAction = 'first' | 'prev' | 'next' | 'last'

const props = withDefaults(defineProps<{
  rows: Array<Record<string, unknown>>
  columns: DataTableColumn[]
  empty: string
  pageSizeOptions?: number[]
  defaultPageSize?: number
  ariaLabel?: string
}>(), {
  pageSizeOptions: () => [10, 15, 30],
  defaultPageSize: 10,
  ariaLabel: ''
})

const page = ref(1)
const pageSize = ref(props.defaultPageSize)

const totalPages = computed(() => Math.max(1, Math.ceil(props.rows.length / pageSize.value)))
const pageStartIndex = computed(() => (props.rows.length ? (page.value - 1) * pageSize.value : 0))
const pageEnd = computed(() => Math.min(pageStartIndex.value + pageSize.value, props.rows.length))
const pageFirst = computed(() => (props.rows.length ? pageStartIndex.value + 1 : 0))
const pagedRows = computed(() => props.rows.slice(pageStartIndex.value, pageEnd.value))

watch(
  () => [props.rows.length, pageSize.value],
  () => {
    goPage(page.value)
  }
)

watch(
  () => props.columns.map((column) => column.key).join('|'),
  () => {
    page.value = 1
  }
)

function setPageSize(size: number) {
  pageSize.value = size
  page.value = 1
}

function goPage(target: number) {
  page.value = Math.min(Math.max(1, Math.trunc(target || 1)), totalPages.value)
}

function paginationActionDisabled(action: PaginationAction) {
  if (action === 'first' || action === 'prev') return page.value <= 1
  return page.value >= totalPages.value
}

function paginationActionTitle(action: PaginationAction) {
  const label = props.ariaLabel || '表格'
  if (paginationActionDisabled(action) && (action === 'first' || action === 'prev')) return `${label}已在第一页`
  if (paginationActionDisabled(action)) return `${label}已在最后一页`
  if (action === 'first') return `跳到${label}第一页`
  if (action === 'prev') return `跳到${label}上一页（第 ${page.value - 1} 页）`
  if (action === 'next') return `跳到${label}下一页（第 ${page.value + 1} 页）`
  return `跳到${label}最后一页（第 ${totalPages.value} 页）`
}

function pageSizeButtonTitle(size: number) {
  const label = props.ariaLabel || '表格'
  return size === pageSize.value ? `${label}当前每页 ${size} 条` : `${label}切换为每页 ${size} 条`
}
</script>
