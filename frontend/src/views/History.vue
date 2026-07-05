<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NCard, NDataTable, NTag, NButton, NSpace, NInput, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as bkApi from '../api/backups'
import type { BackupFile } from '../api/backups'
import * as connApi from '../api/connections'
import type { Connection } from '../api/connections'

const msg = useMessage()
const data = ref<BackupFile[]>([])
const conns = ref<Connection[]>([])
const filter = ref('')

async function load() {
  try {
    const [b, c] = await Promise.all([bkApi.listBackups(), connApi.listConnections()])
    data.value = b.data; conns.value = c.data
  } catch (e: any) { msg.error('加载历史失败') }
}
function connLabel(id: number) { return conns.value.find(x => x.id === id)?.name ?? `#${id}` }
function download(id: number) { window.open(bkApi.downloadUrl(id), '_blank') }
const fmtMs = (ms?: number | null) => (ms == null ? '—' : (ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`))
const fmtBytes = (n?: number | null) => { if (!n) return '—'; const u = ['B','KB','MB','GB']; const i = Math.floor(Math.log(n)/Math.log(1024)); return (n/Math.pow(1024,i)).toFixed(1)+' '+u[i] }
const statusTag = (s: string) => {
  const m: Record<string, 'success'|'warning'|'error'|'info'|'default'> = { success:'success', failed:'error', running:'info', cancelled:'default' }
  return h(NTag, { type: m[s] || 'default', size: 'small', bordered: false }, { default: () => s })
}

const columns: DataTableColumns<BackupFile> = [
  { title: '时间', key: 'started_at', render: r => new Date(r.started_at).toLocaleString() },
  { title: '连接', key: 'connection_id', render: r => connLabel(r.connection_id) },
  { title: '数据库', key: 'db_name', render: r => r.db_name || '全部' },
  { title: '触发', key: 'trigger', render: r => r.trigger === 'scheduled' ? '计划' : '手动' },
  { title: '状态', key: 'status', render: r => statusTag(r.status) },
  { title: '大小', key: 'size', render: r => fmtBytes(r.size) },
  { title: '耗时', key: 'duration_ms', render: r => fmtMs(r.duration_ms) },
  { title: '校验和', key: 'checksum', ellipsis: { tooltip: true }, render: r => r.checksum ? r.checksum.slice(0, 12) + '…' : '—' },
  { title: '操作', key: 'actions', render: r => r.status === 'success' ? h(NButton, { size: 'small', onClick: () => download(r.id) }, { default: () => '下载' }) : null },
]

onMounted(load)
</script>

<template>
  <n-card title="备份历史" :bordered="false">
    <template #header-extra>
      <n-input v-model:value="filter" placeholder="筛选连接名…" clearable style="width:220px" />
    </template>
    <n-data-table
      :columns="columns"
      :data="filter ? data.filter(r => connLabel(r.connection_id).includes(filter)) : data"
      :bordered="false" :pagination="{ pageSize: 15 }" />
  </n-card>
</template>
