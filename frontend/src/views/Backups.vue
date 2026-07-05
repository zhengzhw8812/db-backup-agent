<script setup lang="ts">
import { ref, h, onMounted, onUnmounted } from 'vue'
import {
  NCard, NDataTable, NButton, NSelect, NSpace, NDrawer, NDrawerContent,
  NTag, NPopconfirm, NStep, NSteps, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as connApi from '../api/connections'
import type { Connection } from '../api/connections'
import * as jobsApi from '../api/jobs'
import type { Job } from '../api/jobs'
import * as bkApi from '../api/backups'
import type { BackupFile } from '../api/backups'
import { useJobStream } from '../composables/useJobStream'

const msg = useMessage()
const conns = ref<Connection[]>([])
const selectedConn = ref<number | null>(null)
const files = ref<BackupFile[]>([])
const jobs = ref<Job[]>([])
const showProgress = ref(false)
const { events, status, subscribe } = useJobStream()
let pollTimer: number | undefined

const connOptions = () => conns.value.map(c => ({ label: `${c.name} (${c.type})`, value: c.id }))
function connLabel(id: number) { return conns.value.find(c => c.id === id)?.name ?? `#${id}` }

const STAGES = ['dump', 'compress', 'success']
function currentStep() {
  if (status.value === 'success') return STAGES.length
  if (status.value === 'failed') {
    return STAGES.indexOf(events.value.filter(e => e.stage !== 'failed').slice(-1)[0]?.stage ?? '') + 1
  }
  const last = events.value.filter(e => STAGES.includes(e.stage)).slice(-1)[0]?.stage
  return last ? STAGES.indexOf(last) + 1 : 0
}

async function load() {
  try {
    const [c, f, j] = await Promise.all([connApi.listConnections(), bkApi.listBackups(), jobsApi.listJobs()])
    conns.value = c.data; files.value = f.data; jobs.value = j.data
  } catch (e: any) { msg.error('加载数据失败') }
}
async function runNow() {
  if (selectedConn.value == null) { msg.warning('请先选择连接'); return }
  try {
    const r = await jobsApi.runBackup(selectedConn.value)
    const ids = r.data.record_ids || []
    showProgress.value = true
    if (ids.length) subscribe(ids[0])  // v1:进度抽屉跟第一条;其余靠下方 poll 刷新
    msg.success(`已创建 ${ids.length} 条备份任务`)
    poll()
  } catch (e: any) { msg.error(e.response?.data?.detail || '启动失败') }
}
function poll() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    await load()
    if (['success', 'failed', 'cancelled'].includes(status.value)) {
      window.clearInterval(pollTimer); pollTimer = undefined
    }
  }, 2000)
}
async function cancel(id: number) {
  try { await jobsApi.cancelJob(id); msg.success('已请求取消'); await load() }
  catch (e: any) { msg.error(e.response?.data?.detail || '取消失败') }
}
async function remove(id: number) {
  try { await bkApi.deleteBackup(id); msg.success('已删除'); await load() }
  catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}
function download(id: number) { window.open(bkApi.downloadUrl(id), '_blank') }

const fmtMs = (ms?: number | null) => (ms == null ? '—' : (ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`))
const fmtBytes = (n?: number | null) => {
  if (!n) return '—'
  const u = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(n) / Math.log(1024))
  return (n / Math.pow(1024, i)).toFixed(1) + ' ' + u[i]
}
const statusTag = (s: string) => {
  const m: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
    success: 'success', failed: 'error', running: 'info', cancelled: 'default',
  }
  return h(NTag, { type: m[s] || 'default', size: 'small', bordered: false }, { default: () => s })
}

const jobColumns: DataTableColumns<Job> = [
  { title: '记录', key: 'id' },
  { title: '连接', key: 'connection_id', render: r => connLabel(r.connection_id) },
  { title: '触发', key: 'trigger' },
  { title: '库', key: 'db_name', render: r => r.db_name || '全部' },
  { title: '状态', key: 'status', render: r => statusTag(r.status) },
  {
    title: '操作', key: 'actions',
    render: r => h(NButton, { size: 'small', onClick: () => cancel(r.id) }, { default: () => '取消' }),
  },
]
const fileColumns: DataTableColumns<BackupFile> = [
  { title: '时间', key: 'started_at', render: r => new Date(r.started_at).toLocaleString() },
  { title: '连接', key: 'connection_id', render: r => connLabel(r.connection_id) },
  { title: '库', key: 'db_name', render: r => r.db_name || '全部' },
  { title: '状态', key: 'status', render: r => statusTag(r.status) },
  { title: '大小', key: 'size', render: r => fmtBytes(r.size) },
  { title: '耗时', key: 'duration_ms', render: r => fmtMs(r.duration_ms) },
  {
    title: '操作', key: 'actions', render: r => h(NSpace, null, {
      default: () => [
        r.status === 'success'
          ? h(NButton, { size: 'small', onClick: () => download(r.id) }, { default: () => '下载' })
          : null,
        h(NPopconfirm, { onPositiveClick: () => remove(r.id) }, {
          trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }),
          default: () => '确认删除?',
        }),
      ],
    }),
  },
]

onMounted(load)
onUnmounted(() => { if (pollTimer) window.clearInterval(pollTimer) })
</script>

<template>
  <n-space vertical :size="16">
    <n-card title="立即备份" :bordered="false">
      <n-space align="center">
        <n-select
          v-model:value="selectedConn"
          :options="connOptions()"
          placeholder="选择数据库连接"
          style="width:300px"
          filterable
        />
        <n-button type="primary" @click="runNow">立即备份</n-button>
      </n-space>
    </n-card>

    <n-card v-if="jobs.length" title="进行中的任务" :bordered="false">
      <n-data-table :columns="jobColumns" :data="jobs" :bordered="false" />
    </n-card>

    <n-card title="备份文件" :bordered="false">
      <n-data-table :columns="fileColumns" :data="files" :bordered="false" />
    </n-card>
  </n-space>

  <n-drawer v-model:show="showProgress" :width="420" placement="right">
    <n-drawer-content title="备份进度" closable>
      <n-steps
        :current="currentStep()"
        :status="status === 'failed' ? 'error' : (status === 'success' ? 'finish' : 'process')"
      >
        <n-step title="导出 (dump)" />
        <n-step title="压缩 + 校验 (compress)" />
        <n-step title="完成 (success)" />
      </n-steps>
      <div style="margin-top:16px">
        <n-text depth="3">实时日志:</n-text>
        <div class="log">
          <div v-for="e in events" :key="e.id">
            • {{ e.stage }} <span v-if="e.detail" style="opacity:.6">— {{ e.detail }}</span>
          </div>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.log {
  margin-top: 8px;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  max-height: 300px;
  overflow: auto;
}
</style>
