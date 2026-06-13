<template>
  <section class="panel resizable-card" data-resizable-card :aria-labelledby="titleId">
    <div class="panel-title">
      <strong :id="titleId">{{ title }}</strong>
      <span>{{ subtitle }}</span>
    </div>
    <slot />
  </section>
</template>

<script setup lang="ts">
import { getCurrentInstance } from 'vue'

defineProps<{
  title: string
  subtitle: string
}>()

const titleId = `panel-${getCurrentInstance()?.uid ?? 'section'}-title`
</script>
