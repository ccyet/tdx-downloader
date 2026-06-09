<template>
  <article :class="['metric-card', 'resizable-card', tone]" data-resizable-card>
    <div class="metric-icon"><Icon :name="icon" /></div>
    <div>
      <span>{{ title }}</span>
      <strong>{{ value }}</strong>
      <em>{{ detail }}</em>
    </div>
  </article>
</template>

<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  title: string
  value: string
  detail: string
  tone: string
  icon: string
}>()
</script>
