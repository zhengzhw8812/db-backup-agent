<script setup lang="ts">
// 备份文件 Tab:立即备份、进行中任务、备份文件表(原 备份+备份历史 两页合并)
import { ref, h, inject, computed, watch } from 'vue'
import {
  NCard, NDataTable, NButton, NSelect, NSpace, NPopconfirm, NInput, NTag, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as connApi from '../../api/connections'
import type { Connection } from '../../api/connections'
import * as jobsApi from '../../api/jobs'
import type { Job } from '../../api/jobs'
import * as bkApi from '../../api/backups'
import type { BackupFile } from '../../api/backups'
import { useStatusTag } from '../../composables/useStatusTag'
import { relativeTime, fullTime } from '../../composables/useRelativeTime'
import EmptyState from '../EmptyState.vue'
import { useBreakpoint } from '../../composables/useBreakpoint'

const { isMobile } = useBreakpoint()
const msg = useMessage()

const props = defineProps<{ files: BackupFile[]; jobs: Job[]; conns: Connection[] }>()
const emit = defineEmits<{ (e: 'refresh'): void; (e: 'restore', id: number): void }>()

// 壳页面提供的备份执行流(进度抽屉 + SSE 订阅 + 轮询)
const backupRun = inject<{
  runBackupFor: (connId: number | null) => Promise<void>
  show: { value: boolean }
  events: { value: Array<{ id: number; stage: string; detail?: string }> }
  status: { value: string }
  subscribe: (id: number, eventsUrl?: string, opts?: { terminal: string[] }) => void
}>('backupRun')!

const selectedConn = ref<number | null>(null)
const filter = ref('')

const connOptions = () => props.conns.map(c => ({ label: `${c.name} (${c.type})`, value: c.id }))
function connLabel(id: number) { return props.conns.find(c => c.id === id)?.name ?? `#${id}` }

async function runNow() {
  if (selectedConn.value == null) { msg.warning('请先选择连接'); return }
  await backupRun.runBackupFor(selectedConn.value)
}

const STAGES = ['dump', 'compress', 'success']
function currentStep() {
  if (backupRun.status.value === 'success') return STAGES.length
  if (backupRun.status.value === 'failed') {
    return STAGES.indexOf(backupRun.events.value.filter(e => e.stage !== 'failed').slice(-1)[0]?.stage ?? '') + 1
  }
  const last = backupRun.events.value.filter(e => STAGES.includes(e.stage)).slice(-1)[0]?.stage
  return last ? STAGES.indexOf(last) + 1 : 0
}

async function cancel(id: number) {
  try { await jobsApi.cancelJob(id); msg.success('已请求取消'); emit('refresh') }
  catch (e: any) { msg.error(e.response?.data?.detail || '取消失败') }
}
async function remove(id: number) {
  try { await bkApi.deleteBackup(id); msg.success('已删除'); emit('refresh') }
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
const statusTag = useStatusTag()

const verifyTag = (s: string | null, err?: string | null) => {
  if (!s || s === 'running')
    return h(NTag, { type: s === 'running' ? 'info' : 'default', size: 'small', bordered: false },
             { default: () => s || '未验证' })
  const m: Record<string, 'success' | 'error'> = { passed: 'success', failed: 'error' }
  const tag = h(NTag, { type: m[s] || 'default', size: 'small', bordered: false }, { default: () => s })
  return err ? h('span', { title: err }, [tag]) : tag  // 失败原因悬浮可见
}

async function verify(id: number) {
  try {
    await bkApi.verifyBackup(id)
    msg.success('验证任务已排队')
    backupRun.show.value = true
    backupRun.subscribe(id, undefined, { terminal: ['passed', 'failed'] })
    watchOnceStatus()
  } catch {
    msg.error('验证任务排队失败')
  }
}
// 验证到终态后刷新列表(通过一次性 watch)
function watchOnceStatus() {
  const stop = watch(() => backupRun.status.value, (s: string) => {
    if (s === 'passed' || s === 'failed') { emit('refresh'); stop() }
  })
}

const filtered = computed(() =>
  filter.value ? props.files.filter(r => connLabel(r.connection_id).includes(filter.value)) : props.files)

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
  { title: '时间', key: 'started_at', render: r => h('span', { title: fullTime(r.started_at) }, relativeTime(r.started_at)) },
  { title: '连接', key: 'connection_id', render: r => connLabel(r.connection_id) },
  { title: '库', key: 'db_name', render: r => r.db_name || '全部' },
  { title: '触发', key: 'trigger', render: r => r.trigger === 'scheduled' ? '计划' : '手动' },
  { title: '状态', key: 'status', render: r => statusTag(r.status) },
  { title: '验证', key: 'verify_status', render: r => verifyTag(r.verify_status, r.verify_error) },
  { title: '大小', key: 'size', render: r => fmtBytes(r.size) },
  { title: '耗时', key: 'duration_ms', render: r => fmtMs(r.duration_ms) },
  {
    title: '操作', key: 'actions', width: 260, render: r => h(NSpace, { size: 'small' }, {
      default: () => [
        r.status === 'success'
          ? h(NButton, { size: 'small', onClick: () => download(r.id) }, { default: () => '下载' })
          : null,
        r.status === 'success' && r.file_path && r.verify_status !== 'running'
          ? h(NButton, { size: 'small', onClick: () => verify(r.id) }, { default: () => '验证' })
          : null,
        r.status === 'success'
          ? h(NButton, { size: 'small', onClick: () => emit('restore', r.id) }, { default: () => '恢复' })
          : null,
        h(NPopconfirm, { onPositiveClick: () => remove(r.id) }, {
          trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }),
          default: () => '确认删除?',
        }),
      ],
    }),
  },
]
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
      <template v-if="!isMobile">
        <n-data-table v-if="jobs.length" :columns="jobColumns" :data="jobs" :bordered="false" size="small" striped />
        <EmptyState v-else icon="⏳" text="当前没有进行中的任务" />
      </template>
      <template v-else>
        <n-card v-for="j in jobs" :key="j.id" class="mcard" size="small" :title="`#${j.id} ${j.db_name || '全部'}`">
          <div class="mrow"><span class="mlabel">状态</span><component :is="statusTag(j.status)" /></div>
          <div class="mactions">
            <n-button size="large" @click="cancel(j.id)">取消</n-button>
          </div>
        </n-card>
      </template>
    </n-card>

    <n-card title="备份文件" :bordered="false">
      <template #header-extra>
        <n-input v-model:value="filter" placeholder="筛选连接名…" clearable style="width:220px" />
      </template>
      <template v-if="!isMobile">
        <n-data-table v-if="filtered.length" :columns="fileColumns" :data="filtered" :bordered="false"
                      size="small" striped :pagination="{ pageSize: 15 }" />
        <EmptyState v-else-if="!filter" icon="💾" text="还没有备份" action-text="立即备份" @action="() => runNow()" />
        <EmptyState v-else icon="💾" text="没有匹配的备份" />
      </template>
      <template v-else>
        <n-card v-for="r in filtered" :key="r.id" class="mcard" size="small">
          <div class="mrow"><span class="mlabel">时间</span><span :title="fullTime(r.started_at)">{{ relativeTime(r.started_at) }}</span></div>
          <div class="mrow"><span class="mlabel">连接/库</span><span>{{ connLabel(r.connection_id) }} · {{ r.db_name || '全部' }}</span></div>
          <div class="mrow"><span class="mlabel">触发</span><span>{{ r.trigger === 'scheduled' ? '计划' : '手动' }}</span></div>
          <div class="mrow"><span class="mlabel">状态</span><component :is="statusTag(r.status)" /></div>
          <div class="mrow"><span class="mlabel">验证</span><component :is="verifyTag(r.verify_status, r.verify_error)" /></div>
          <div class="mrow"><span class="mlabel">大小</span><span>{{ fmtBytes(r.size) }}</span></div>
          <div class="mactions">
            <n-button v-if="r.status === 'success'" size="large" @click="download(r.id)">下载</n-button>
            <n-button v-if="r.status === 'success' && r.file_path" size="large" @click="verify(r.id)">验证</n-button>
            <n-button v-if="r.status === 'success'" size="large" @click="emit('restore', r.id)">恢复</n-button>
            <n-popconfirm @positive-click="remove(r.id)"><template #trigger><n-button size="large" type="error" ghost>删除</n-button></template>确认删除?</n-popconfirm>
          </div>
        </n-card>
      </template>
    </n-card>
  </n-space>
</template>

<style scoped>
.mcard { margin-bottom: 12px }
.mrow { display: flex; justify-content: space-between; gap: 8px; padding: 3px 0; font-size: 13px }
.mlabel { opacity: .55; flex-shrink: 0 }
.mactions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap }
.mactions .n-button { flex: 1; min-height: 44px }
</style>
