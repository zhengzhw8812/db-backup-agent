<script setup lang="ts">
import { ref, h, computed, onMounted, onUnmounted } from 'vue'
import {
  NCard, NDataTable, NSelect, NSpace, NButton, NDrawer, NDrawerContent,
  NTag, NModal, NInput, NSteps, NStep, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as bkApi from '../api/backups'
import type { BackupFile } from '../api/backups'
import * as connApi from '../api/connections'
import type { Connection } from '../api/connections'
import * as rsApi from '../api/restore'
import type { Restore } from '../api/restore'
import { useJobStream } from '../composables/useJobStream'

const msg = useMessage()
const backups = ref<BackupFile[]>([])
const conns = ref<Connection[]>([])
const restores = ref<Restore[]>([])
const selectedBackup = ref<number | null>(null)
const selectedConn = ref<number | null>(null)
const showConfirm = ref(false)
const confirmText = ref('')
const showProgress = ref(false)
const currentRestoreId = ref<number | null>(null)
const { events, status, subscribe } = useJobStream()
let pollTimer: number | undefined

const successBackups = computed(() => backups.value.filter(b => b.status === 'success'))
function connLabel(id: number) { return conns.value.find(c => c.id === id)?.name ?? `#${id}` }
const backupOptions = () => successBackups.value.map(b => ({
  label: `#${b.id} · ${connLabel(b.connection_id)} · ${fmtBytes(b.size)}`,
  value: b.id,
}))
const connOptions = () => conns.value.map(c => ({ label: `${c.name} (${c.type})`, value: c.id }))
const targetConn = computed(() => conns.value.find(c => c.id === selectedConn.value))
const canSubmit = computed(() => selectedBackup.value != null && selectedConn.value != null)
const confirmMatches = computed(() => targetConn.value != null && confirmText.value === targetConn.value.name)

async function load() {
  const [b, c, r] = await Promise.all([bkApi.listBackups(), connApi.listConnections(), rsApi.listRestores()])
  backups.value = b.data; conns.value = c.data; restores.value = r.data
}

function openConfirm() {
  if (selectedBackup.value == null) { msg.warning('请先选择备份'); return }
  if (selectedConn.value == null) { msg.warning('请先选择目标连接'); return }
  confirmText.value = ''
  showConfirm.value = true
}

async function doRestore() {
  if (selectedBackup.value == null || selectedConn.value == null || !confirmMatches.value) return
  showConfirm.value = false
  try {
    const r = await rsApi.runRestore(selectedBackup.value, selectedConn.value)
    currentRestoreId.value = r.data.record_id
    showProgress.value = true
    subscribe(r.data.record_id, rsApi.eventsUrl)
    poll()
  } catch (e: any) { msg.error(e.response?.data?.detail || '启动恢复失败') }
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

async function cancelCurrent() {
  if (currentRestoreId.value == null) return
  await rsApi.cancelRestore(currentRestoreId.value)
  msg.success('已请求取消')
  await load()
}

const STAGES = ['verify', 'decompress', 'restore', 'success']
function currentStep() {
  if (status.value === 'success') return STAGES.length
  if (status.value === 'failed') {
    return STAGES.indexOf(events.value.filter(e => e.stage !== 'failed').slice(-1)[0]?.stage ?? '') + 1
  }
  const last = events.value.filter(e => STAGES.includes(e.stage)).slice(-1)[0]?.stage
  return last ? STAGES.indexOf(last) + 1 : 0
}

const fmtBytes = (n?: number | null) => { if (!n) return '—'; const u = ['B','KB','MB','GB']; const i = Math.floor(Math.log(n)/Math.log(1024)); return (n/Math.pow(1024,i)).toFixed(1)+' '+u[i] }
const fmtMs = (ms?: number | null) => (ms == null ? '—' : (ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`))
const statusTag = (s: string) => {
  const m: Record<string, 'success'|'warning'|'error'|'info'|'default'> = { success:'success', failed:'error', running:'info', cancelled:'default' }
  return h(NTag, { type: m[s] || 'default', size: 'small', bordered: false }, { default: () => s })
}

const restoreColumns: DataTableColumns<Restore> = [
  { title: '记录', key: 'id' },
  { title: '源备份', key: 'backup_record_id' },
  { title: '目标连接', key: 'target_connection_id', render: r => connLabel(r.target_connection_id) },
  { title: '状态', key: 'status', render: r => statusTag(r.status) },
  { title: '耗时', key: 'duration_ms', render: r => fmtMs(r.duration_ms) },
  { title: '错误', key: 'error', ellipsis: { tooltip: true } },
]

onMounted(load)
onUnmounted(() => { if (pollTimer) window.clearInterval(pollTimer) })
</script>

<template>
  <n-space vertical :size="16">
    <n-card title="一键恢复" :bordered="false">
      <n-space vertical :size="12">
        <n-space align="center">
          <n-select v-model:value="selectedBackup" :options="backupOptions()" placeholder="选择一份成功备份" style="width:380px" filterable />
        </n-space>
        <n-space align="center">
          <n-select v-model:value="selectedConn" :options="connOptions()" placeholder="选择目标连接" style="width:380px" filterable />
          <n-button type="error" :disabled="!canSubmit" @click="openConfirm">恢复</n-button>
        </n-space>
        <n-text depth="3">恢复会把备份写入目标连接并覆盖同名数据,操作不可撤销;执行前服务端会校验 SHA-256 完整性。</n-text>
      </n-space>
    </n-card>

    <n-card title="恢复历史" :bordered="false">
      <n-data-table :columns="restoreColumns" :data="restores" :bordered="false" />
    </n-card>
  </n-space>

  <n-modal v-model:show="showConfirm" preset="card" title="危险操作确认" style="width:460px">
    <n-space vertical :size="12">
      <n-text>即将把备份恢复到目标连接 <b>{{ targetConn?.name }}</b>,<b>覆盖同名数据</b>。</n-text>
      <n-text depth="3">请输入目标连接名 <b>{{ targetConn?.name }}</b> 以确认:</n-text>
      <n-input v-model:value="confirmText" placeholder="输入连接名" />
      <n-button type="error" block :disabled="!confirmMatches" @click="doRestore">确认恢复</n-button>
    </n-space>
  </n-modal>

  <n-drawer v-model:show="showProgress" :width="420" placement="right">
    <n-drawer-content title="恢复进度" closable>
      <n-steps
        :current="currentStep()"
        :status="status === 'failed' ? 'error' : (status === 'success' ? 'finish' : 'process')"
      >
        <n-step title="完整性校验 (verify)" />
        <n-step title="解压 (decompress)" />
        <n-step title="还原 (restore)" />
        <n-step title="完成 (success)" />
      </n-steps>
      <div style="margin-top:16px">
        <n-space align="center" justify="space-between">
          <n-text depth="3">实时日志:</n-text>
          <n-button size="small" :disabled="['success','failed','cancelled'].includes(status)" @click="cancelCurrent">取消</n-button>
        </n-space>
        <div class="log">
          <div v-for="(e, i) in events" :key="i">
            • {{ e.stage }} <span v-if="e.detail" style="opacity:.6">— {{ e.detail }}</span>
          </div>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.log { margin-top: 8px; font-family: ui-monospace, monospace; font-size: 13px; max-height: 300px; overflow: auto; }
</style>
