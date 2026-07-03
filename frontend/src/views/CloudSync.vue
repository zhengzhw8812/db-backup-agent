<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NCard, NDataTable, NButton, NSpace, NModal, NForm, NFormItem, NInput, NSwitch, NTag, NSelect, NPopconfirm, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as cloudApi from '../api/cloud'
import type { CloudDestination, SyncTarget } from '../api/cloud'
import * as connApi from '../api/connections'
import * as bkApi from '../api/backups'

const msg = useMessage()
const dests = ref<CloudDestination[]>([])
const targets = ref<SyncTarget[]>([])
const connOptions = ref<{ label: string; value: number }[]>([])
const backupOptions = ref<{ label: string; value: number }[]>([])
const showDest = ref(false)
const showTarget = ref(false)
const selConn = ref<number | null>(null)
const selDest = ref<number | null>(null)
const selBackup = ref<number | null>(null)

const destForm = ref({ name: '', provider: 's3', endpoint: '', region: '', bucket: '', access_key: '', secret: '', prefix: '', secure: false, enabled: true })

async function load() {
  const [d, t, c, b] = await Promise.all([cloudApi.listDestinations(), cloudApi.listTargets(), connApi.listConnections(), bkApi.listBackups()])
  dests.value = d.data; targets.value = t.data
  connOptions.value = c.data.map(x => ({ label: `${x.name} (${x.type})`, value: x.id }))
  backupOptions.value = b.data.filter(x => x.status === 'success').map(x => ({ label: `#${x.id}`, value: x.id }))
}
async function saveDest() {
  try {
    await cloudApi.createDestination({ ...destForm.value, region: destForm.value.region || null })
    msg.success('已添加'); showDest.value = false; destForm.value = { name: '', provider: 's3', endpoint: '', region: '', bucket: '', access_key: '', secret: '', prefix: '', secure: false, enabled: true }
    await load()
  } catch (e: any) { msg.error(e.response?.data?.detail || '失败') }
}
async function testDest(id: number) {
  try { await cloudApi.testDestination(id); msg.success('连接成功') }
  catch (e: any) { msg.error(e.response?.data?.detail || '连接失败') }
}
async function rmDest(id: number) { await cloudApi.deleteDestination(id); msg.success('已删除'); await load() }
async function addTarget() {
  if (selConn.value == null || selDest.value == null) { msg.warning('请选连接和云目标'); return }
  await cloudApi.createTarget({ connection_id: selConn.value, cloud_destination_id: selDest.value })
  msg.success('已添加'); showTarget.value = false; await load()
}
async function rmTarget(id: number) { await cloudApi.deleteTarget(id); msg.success('已删除'); await load() }
async function doSync() {
  if (selBackup.value == null) { msg.warning('请选备份'); return }
  try { await cloudApi.syncRun(selBackup.value); msg.success('同步任务已提交') }
  catch (e: any) { msg.error(e.response?.data?.detail || '提交失败') }
}
function destName(id: number) { return dests.value.find(d => d.id === id)?.name ?? `#${id}` }
function connName(id: number) { return connOptions.value.find(c => c.value === id)?.label ?? `#${id}` }

const destCols: DataTableColumns<CloudDestination> = [
  { title: '名称', key: 'name' },
  { title: '类型', key: 'provider' },
  { title: 'Endpoint', key: 'endpoint' },
  { title: '桶', key: 'bucket' },
  { title: '前缀', key: 'prefix' },
  { title: 'HTTPS', key: 'secure', render: r => h(NTag, { size: 'small', bordered: false, type: r.secure ? 'success' : 'warning' }, { default: () => r.secure ? '是' : '否' }) },
  { title: '操作', key: 'a', render: r => h(NSpace, null, { default: () => [
    h(NButton, { size: 'small', onClick: () => testDest(r.id) }, { default: () => '测试' }),
    h(NPopconfirm, { onPositiveClick: () => rmDest(r.id) }, { trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }), default: () => '确认删除?' }),
  ] }) },
]
const targetCols: DataTableColumns<SyncTarget> = [
  { title: '连接', key: 'connection_id', render: r => connName(r.connection_id) },
  { title: '云目标', key: 'cloud_destination_id', render: r => destName(r.cloud_destination_id) },
  { title: '操作', key: 'a', render: r => h(NPopconfirm, { onPositiveClick: () => rmTarget(r.id) }, { trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }), default: () => '确认删除?' }) },
]

onMounted(load)
</script>

<template>
  <n-space vertical :size="16">
    <n-card title="云存储目标" :bordered="false">
      <template #header-extra>
        <n-button type="primary" @click="showDest = true">+ 添加</n-button>
      </template>
      <n-data-table :columns="destCols" :data="dests" :bordered="false" />
    </n-card>

    <n-card title="同步规则(连接 → 云目标)" :bordered="false">
      <template #header-extra>
        <n-button type="primary" @click="showTarget = true">+ 添加</n-button>
      </template>
      <n-data-table :columns="targetCols" :data="targets" :bordered="false" />
    </n-card>

    <n-card title="手动同步" :bordered="false">
      <n-space align="center">
        <n-select v-model:value="selBackup" :options="backupOptions" placeholder="选一份成功备份" style="width:240px" />
        <n-button type="primary" @click="doSync">同步到云</n-button>
      </n-space>
    </n-card>
  </n-space>

  <n-modal v-model:show="showDest" preset="card" title="添加云存储目标(MinIO / S3 兼容)" style="width:520px">
    <n-form label-placement="top">
      <n-form-item label="名称"><n-input v-model:value="destForm.name" /></n-form-item>
      <n-space>
        <n-form-item label="Endpoint (host:port)"><n-input v-model:value="destForm.endpoint" placeholder="localhost:9000" /></n-form-item>
        <n-form-item label="桶名"><n-input v-model:value="destForm.bucket" /></n-form-item>
      </n-space>
      <n-space>
        <n-form-item label="Access Key"><n-input v-model:value="destForm.access_key" /></n-form-item>
        <n-form-item label="Secret"><n-input v-model:value="destForm.secret" type="password" show-password-on="click" /></n-form-item>
      </n-space>
      <n-space>
        <n-form-item label="前缀"><n-input v-model:value="destForm.prefix" placeholder="(可选)" /></n-form-item>
        <n-form-item label="区域"><n-input v-model:value="destForm.region" placeholder="(可选)" /></n-form-item>
      </n-space>
      <n-space align="center">
        <n-form-item label="HTTPS"><n-switch v-model:value="destForm.secure" /></n-form-item>
        <n-form-item label="启用"><n-switch v-model:value="destForm.enabled" /></n-form-item>
      </n-space>
      <n-button type="primary" block @click="saveDest">保存</n-button>
    </n-form>
  </n-modal>

  <n-modal v-model:show="showTarget" preset="card" title="添加同步规则" style="width:460px">
    <n-space vertical :size="12">
      <n-select v-model:value="selConn" :options="connOptions" placeholder="选数据库连接" filterable />
      <n-select v-model:value="selDest" :options="dests.map(d => ({ label: d.name, value: d.id }))" placeholder="选云目标" filterable />
      <n-button type="primary" block @click="addTarget">保存</n-button>
    </n-space>
  </n-modal>
</template>
