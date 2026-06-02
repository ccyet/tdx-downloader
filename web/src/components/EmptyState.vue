<template>
  <div class="empty-state">
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
