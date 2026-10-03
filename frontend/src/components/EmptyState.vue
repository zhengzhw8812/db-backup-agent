<script setup lang="ts">
defineProps<{ icon?: string; text: string; actionText?: string }>()
const emit = defineEmits<{ (e: 'action'): void }>()
</script>

<template>
  <div class="empty">
    <div class="e-icon">{{ icon || '📭' }}</div>
    <p class="e-text">{{ text }}</p>
    <n-button v-if="actionText" type="primary" size="large" @click="emit('action')">
      {{ actionText }}
    </n-button>
  </div>
</template>

<script lang="ts">
import { NButton } from 'naive-ui'
import { defineComponent } from 'vue'
export default defineComponent({ components: { NButton } })
</script>

<style scoped>
.empty { text-align: center; padding: 36px 12px }
.e-icon { font-size: 40px; margin-bottom: 8px; opacity: .8 }
.e-text { opacity: .55; margin: 0 0 14px; font-size: 14px }
</style>
