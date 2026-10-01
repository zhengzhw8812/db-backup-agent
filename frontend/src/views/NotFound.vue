<script setup lang="ts">
import { NButton, NCard, NResult } from 'naive-ui'
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <n-card :bordered="false" style="margin-top: 10vh">
    <n-result status="404" title="页面不存在" description="你要找的页面不存在或已被移动">
      <template #footer>
        <n-button type="primary" @click="router.push('/dashboard')">返回仪表盘</n-button>
      </template>
    </n-result>
  </n-card>
</template>
