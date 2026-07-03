<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NCard, NDataTable, NTag, NButton, NSpace, NSelect, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as logsApi from '../api/logs'
import type { SystemLog } from '../api/logs'

const msg = useMessage()
const data = ref<SystemLog[]>([])
const level = ref<string | null>(null)
const levelOpts = [
  { label: '全部', value: '' },
  { label: 'info', value: 'info' },
  { label: 'error', value: 'error' },
  { label: 'warning', value: 'warning' },
]
async function load() {
  try {
    const { data: d } = await logsApi.listLogs(level.value || undefined)
    data.value = d
  } catch (e: any) { msg.error('加载失败') }
}
const tag = (l: string) => {
  const m: Record<string, 'success'|'warning'|'error'|'info'|'default'> = { info: 'info', error: 'error', warning: 'warning' }
  return h(NTag, { size: 'small', bordered: false, type: m[l] || 'default' }, { default: () => l })
}
const columns: DataTableColumns<SystemLog> = [
  { title: '时间', key: 'created_at', render: r => new Date(r.created_at).toLocaleString() },
  { title: '级别', key: 'level', render: r => tag(r.level) },
  { title: '来源', key: 'source' },
  { title: '消息', key: 'message', ellipsis: { tooltip: true } },
]
onMounted(load)
</script>

<template>
  <n-card title="系统日志" :bordered="false">
    <template #header-extra>
      <n-space align="center">
        <n-select v-model:value="level" :options="levelOpts" size="small" style="width:120px" @update:value="load" />
        <n-button size="small" @click="load">刷新</n-button>
      </n-space>
    </template>
    <n-data-table :columns="columns" :data="data" :bordered="false" :pagination="{ pageSize: 20 }" />
  </n-card>
</template>
