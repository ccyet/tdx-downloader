<template>
  <section class="panel resizable-card" data-resizable-card>
    <div class="panel-title">
      <strong>{{ title }}</strong>
      <span>{{ subtitle }}</span>
    </div>
    <slot />
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle: string
}>()
</script>
