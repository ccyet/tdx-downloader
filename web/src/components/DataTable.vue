<template>
  <div class="table-wrap">
    <table v-if="rows.length">
      <thead>
        <tr><th v-for="column in columns" :key="column.key">{{ column.label }}</th></tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="index">
          <td v-for="column in columns" :key="column.key" :title="String(row[column.key] ?? '')">
            {{ row[column.key] ?? '-' }}
          </td>
        </tr>
      </tbody>
    </table>
    <EmptyState v-else :title="empty || '暂无数据'" body="" />
  </div>
</template>

<script setup lang="ts">
import EmptyState from './EmptyState.vue'

defineProps<{
  rows: Array<Record<string, unknown>>
  columns: Array<{ key: string; label: string }>
  empty: string
}>()
</script>
