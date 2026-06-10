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
            @click="setPageSize(size)"
          >
            {{ size }}
          </button>
        </div>
        <div class="pagination-controls">
          <button type="button" :disabled="page <= 1" @click="goPage(1)">首页</button>
          <button type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
          <button type="button" :disabled="page >= totalPages" @click="goPage(totalPages)">末页</button>
        </div>
      </div>
    </div>
    <DataTable :rows="pagedRows" :columns="columns" :empty="empty" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import DataTable from './DataTable.vue'

interface DataTableColumn {
  key: string
  label: string
}

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
</script>
