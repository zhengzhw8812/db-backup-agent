<script setup lang="ts">
// 四页合一壳:备份文件 / 备份计划 / 恢复(原 Backups+Schedules+History+Restore)
// 壳持有共享数据与备份进度流(provide 给 Tab),Tab 状态同步到 ?tab=
import PageHeader from '../components/PageHeader.vue'
import { ref, provide, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NTabs, NTabPane, NDrawer, NDrawerContent, NSteps, NStep, NText, useMessage,
} from 'naive-ui'
import * as connApi from '../api/connections'
import type { Connection } from '../api/connections'
import * as bkApi from '../api/backups'
import type { BackupFile } from '../api/backups'
import * as jobsApi from '../api/jobs'
import type { Job } from '../api/jobs'
import * as schedApi from '../api/schedules'
import type { Schedule } from '../api/schedules'
import * as rsApi from '../api/restore'
import type { Restore } from '../api/restore'
import { useJobStream } from '../composables/useJobStream'
import FilesTab from '../components/backup/FilesTab.vue'
import SchedulesTab from '../components/backup/SchedulesTab.vue'
import RestoreTab from '../components/backup/RestoreTab.vue'

const msg = useMessage()
const route = useRoute()
const router = useRouter()

// ---------- 共享数据 ----------
const conns = ref<Connection[]>([])
const files = ref<BackupFile[]>([])
const jobs = ref<Job[]>([])
const schedules = ref<Schedule[]>([])
const restores = ref<Restore[]>([])

async function load() {
  try {
    const [c, f, j, s, r] = await Promise.all([
      connApi.listConnections(), bkApi.listBackups(), jobsApi.listJobs(),
      schedApi.listSchedules(), rsApi.listRestores(),
    ])
    conns.value = c.data; files.value = f.data; jobs.value = j.data
    schedules.value = s.data; restores.value = r.data
  } catch (e: any) { msg.error('加载数据失败') }
}

// ---------- Tab 状态与 URL query 同步(书签/跳转直达) ----------
const TABS = ['files', 'schedules', 'restore']
function normalizeTab(t: unknown): string {
  return TABS.includes(t as string) ? (t as string) : 'files'
}
const activeTab = ref(normalizeTab(route.query.tab))
watch(() => route.query.tab, t => { activeTab.value = normalizeTab(t) })
function onTabUpdate(tab: string) {
  activeTab.value = tab
  router.replace({ query: { ...route.query, tab } })
}

// ---------- 备份执行流(立即备份 / 计划立即执行 / 验证共用) ----------
const showProgress = ref(false)
const { events, status, subscribe } = useJobStream()
let pollTimer: number | undefined
let lastIds: number[] = []  // 本次触发的 record_ids;poll 直到其中没有 running 才停

async function runBackupFor(connId: number | null) {
  if (connId == null) { msg.warning('请先选择连接'); return }
  try {
    const r = await jobsApi.runBackup(connId)
    const ids = r.data.record_ids || []
    lastIds = ids
    showProgress.value = true
    if (ids.length) subscribe(ids[0])  // v1:进度抽屉跟第一条;其余靠 poll 刷新
    msg.success(`已创建 ${ids.length} 条备份任务`)
    poll()
  } catch (e: any) { msg.error(e.response?.data?.detail || '启动失败') }
}

function poll() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    await load()
    // 多库备份:本批触发的记录都不再 running 才停
    if (!jobs.value.some(j => lastIds.includes(j.id))) {
      window.clearInterval(pollTimer); pollTimer = undefined
    }
  }, 2000)
}

provide('backupRun', { runBackupFor, show: showProgress, events, status, subscribe })

const STAGES = ['dump', 'compress', 'success']
function currentStep() {
  if (status.value === 'success') return STAGES.length
  if (status.value === 'failed') {
    return STAGES.indexOf(events.value.filter(e => e.stage !== 'failed').slice(-1)[0]?.stage ?? '') + 1
  }
  const last = events.value.filter(e => STAGES.includes(e.stage)).slice(-1)[0]?.stage
  return last ? STAGES.indexOf(last) + 1 : 0
}

// ---------- 文件表「恢复」按钮:切到恢复 Tab 并预选 ----------
// 带自增序号:再次点击同一备份时引用变化,RestoreTab 的 watch 才会重新触发
const restorePreset = ref<{ id: number; n: number } | null>(null)
let presetSeq = 0
function onRestorePreset(id: number) {
  restorePreset.value = { id, n: ++presetSeq }
  onTabUpdate('restore')
}

// ---------- 计划「立即执行」:执行备份并切回文件 Tab 看进度 ----------
function onScheduleRunNow(connectionId: number) {
  onTabUpdate('files')
  runBackupFor(connectionId)
}

onMounted(load)
onUnmounted(() => { if (pollTimer) window.clearInterval(pollTimer) })
</script>

<template>

  <PageHeader title="备份" description="备份文件、备份计划与恢复" />
  <n-tabs :value="activeTab" type="line" @update:value="onTabUpdate">
    <n-tab-pane name="files" tab="💾 备份文件">
      <FilesTab :files="files" :jobs="jobs" :conns="conns" @refresh="load" @restore="onRestorePreset" />
    </n-tab-pane>
    <n-tab-pane name="schedules" tab="⏰ 备份计划" display-directive="show:lazy">
      <SchedulesTab :schedules="schedules" :conns="conns" @refresh="load" @run-now="onScheduleRunNow" />
    </n-tab-pane>
    <n-tab-pane name="restore" tab="♻️ 恢复" display-directive="show:lazy">
      <RestoreTab :files="files" :conns="conns" :restores="restores" :preset="restorePreset" @refresh="load" />
    </n-tab-pane>
  </n-tabs>

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
