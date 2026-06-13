<template>
  <div class="empty-state" role="status" aria-live="polite">
    <strong>{{ title }}</strong>
    <span>{{ body }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  body: string
}>()
</script>
