<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="page-header">
    <div>
      <h2 class="ph-title">{{ title }}</h2>
      <p v-if="description" class="ph-desc">{{ description }}</p>
    </div>
    <div class="ph-actions"><slot /></div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.ph-title { margin: 0; font-size: 20px; font-weight: 700 }
.ph-desc { margin: 4px 0 0; opacity: .65; font-size: 13px }
@media (max-width: 767px) {
  .ph-actions { width: 100% }
  .ph-actions :deep(.n-button) { min-height: 44px }
}
</style>
