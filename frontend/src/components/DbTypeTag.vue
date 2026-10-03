<script setup lang="ts">
import { computed } from 'vue'
import { dbMeta } from '../utils/dbicons'

const props = defineProps<{ type: string | null | undefined; showLabel?: boolean }>()
const meta = computed(() => dbMeta(props.type))
</script>

<template>
  <span class="dbtag" :title="meta.label">
    <span class="dbtag-icon">{{ meta.icon }}</span>
    <span v-if="showLabel !== false" class="dbtag-label">{{ meta.label }}</span>
  </span>
</template>

<style scoped>
.dbtag { display: inline-flex; align-items: center; gap: 5px; font-size: 13px }
.dbtag-icon { font-size: 15px }
</style>
