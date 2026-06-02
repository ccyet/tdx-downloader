<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-if="name === 'dashboard'" d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" />
    <path v-else-if="name === 'download'" d="M12 3v11m0 0 4-4m-4 4-4-4M5 20h14" />
    <path v-else-if="name === 'archive'" d="M4 7h16v14H4zM4 7l2-4h12l2 4M9 12h6" />
    <path v-else-if="name === 'activity'" d="M3 12h4l2-7 4 14 2-7h6" />
    <path v-else-if="name === 'collapse'" d="m15 6-6 6 6 6" />
    <path v-else-if="name === 'expand'" d="m9 6 6 6-6 6" />
    <path v-else-if="name === 'refresh'" d="M20 12a8 8 0 1 1-2.3-5.7M20 4v6h-6" />
    <path
      v-else-if="name === 'database'"
      d="M5 7c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Zm0 0v10c0 1.7 3.1 3 7 3s7-1.3 7-3V7M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"
    />
    <path v-else-if="name === 'key'" d="M14 7a5 5 0 1 0 1.4 3.6L21 5v4h-3v3h-3" />
    <path v-else-if="name === 'alert'" d="M12 3 2.8 20h18.4L12 3ZM12 9v5M12 17h.01" />
    <path v-else-if="name === 'layers'" d="m12 3 9 5-9 5-9-5 9-5Zm-9 10 9 5 9-5" />
    <path v-else-if="name === 'clock'" d="M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
    <path
      v-else-if="name === 'link'"
      d="M10 13a5 5 0 0 0 7.1 0l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1M14 11a5 5 0 0 0-7.1 0l-2 2a5 5 0 0 0 7.1 7.1l1.1-1.1"
    />
    <path
      v-else-if="name === 'clipboard'"
      d="M8 4h8v4H8zM6 6H5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-1M8 13h8M8 17h5"
    />
    <path v-else-if="name === 'folder'" d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    <path
      v-else-if="name === 'settings'"
      d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.1 2.1-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V20h-3v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1-2.1-2.1.1-.1A1.7 1.7 0 0 0 6 14.6a1.7 1.7 0 0 0-1.5-1H4v-3h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2.1-2.1.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5V4h3v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1 2.1 2.1-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.2v3h-.2a1.7 1.7 0 0 0-1.5 1Z"
    />
    <path v-else-if="name === 'trash'" d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" />
    <path v-else d="M12 5v14M5 12h14" />
  </svg>
</template>

<script setup lang="ts">
defineProps<{ name: string }>()
</script>
