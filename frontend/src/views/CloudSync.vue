<script setup lang="ts">
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoint } from '../composables/useBreakpoint'

const { isMobile } = useBreakpoint()
import { ref, computed, h, onMounted } from 'vue'
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

const destForm = ref({ name: '', provider: 's3', endpoint: '', region: '', bucket: '', access_key: '', secret: '', prefix: '', secure: false, enabled: true,
  mount: { server: '', export: '', version: 'nfs4', share: '', domain: '', username: '' }, mount_password: '' })
const isShare = computed(() => destForm.value.provider === 'nfs' || destForm.value.provider === 'smb')

async function load() {
  try {
    const [d, t, c, b] = await Promise.all([cloudApi.listDestinations(), cloudApi.listTargets(), connApi.listConnections(), bkApi.listBackups()])
    dests.value = d.data; targets.value = t.data
    connOptions.value = c.data.map(x => ({ label: `${x.name} (${x.type})`, value: x.id }))
    backupOptions.value = b.data.filter(x => x.status === 'success').map(x => ({ label: `#${x.id}`, value: x.id }))
  } catch (e: any) { msg.error('加载云同步数据失败') }
}
async function saveDest() {
  try {
    await cloudApi.createDestination({ ...destForm.value, region: destForm.value.region || null })
    msg.success('已添加'); showDest.value = false; destForm.value = { name: '', provider: 's3', endpoint: '', region: '', bucket: '', access_key: '', secret: '', prefix: '', secure: false, enabled: true,
  mount: { server: '', export: '', version: 'nfs4', share: '', domain: '', username: '' }, mount_password: '' }
    await load()
  } catch (e: any) { msg.error(e.response?.data?.detail || '失败') }
}
async function testDest(id: number) {
  try { await cloudApi.testDestination(id); msg.success('连接成功') }
  catch (e: any) { msg.error(e.response?.data?.detail || '连接失败') }
}
async function rmDest(id: number) {
  try { await cloudApi.deleteDestination(id); msg.success('已删除'); await load() }
  catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}
async function addTarget() {
  if (selConn.value == null || selDest.value == null) { msg.warning('请选连接和云目标'); return }
  try {
    await cloudApi.createTarget({ connection_id: selConn.value, cloud_destination_id: selDest.value })
    msg.success('已添加'); showTarget.value = false; await load()
  } catch (e: any) { msg.error(e.response?.data?.detail || '添加失败') }
}
async function rmTarget(id: number) {
  try { await cloudApi.deleteTarget(id); msg.success('已删除'); await load() }
  catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}
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
  { title: '挂载', key: 'mounted', render: (r: any) => r.mounted == null ? '—' : h(NTag, { type: r.mounted ? 'success' : 'error', size: 'small', bordered: false }, { default: () => r.mounted ? '已挂载' : '未挂载' }) },
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
  
  <PageHeader title="云存储" description="备份目的地与同步规则" /><n-space vertical :size="16">
    <n-card title="云存储目标" :bordered="false">
      <template #header-extra>
        <n-button type="primary" @click="showDest = true">+ 添加</n-button>
      </template>
      <template v-if="!isMobile">
      <n-data-table :columns="destCols" :data="dests" :bordered="false" />
      </template>
<template v-else>
        <n-card v-for="d in dests" :key="d.id" class="mcard" :title="d.name" size="small">
          <div class="mrow"><span class="mlabel">类型</span><span>{{ d.provider }}</span></div>
          <div class="mrow" v-if="d.provider === 'nfs' || d.provider === 'smb'"><span class="mlabel">挂载</span>
            <n-tag size="small" :bordered="false" :type="d.mounted ? 'success' : 'error'">{{ d.mounted ? '已挂载' : '未挂载' }}</n-tag></div>
          <div class="mrow" v-if="d.endpoint"><span class="mlabel">Endpoint</span><span>{{ d.endpoint }}</span></div>
          <div class="mrow" v-if="d.bucket"><span class="mlabel">桶</span><span>{{ d.bucket }}{{ d.prefix ? '/' + d.prefix : '' }}</span></div>
          <div class="mactions">
            <n-button size="large" @click="testDest(d.id)">{{ d.provider === 'nfs' || d.provider === 'smb' ? '探针' : '测试' }}</n-button>
            <n-popconfirm @positive-click="rmDest(d.id)"><template #trigger><n-button size="large" type="error" ghost>删除</n-button></template>确认删除?</n-popconfirm>
          </div>
        </n-card>
      </template>
    </n-card>

    <n-card title="同步规则(连接 → 云目标)" :bordered="false">
      <template #header-extra>
        <n-button type="primary" @click="showTarget = true">+ 添加</n-button>
      </template>
      <template v-if="!isMobile">
        <n-data-table :columns="targetCols" :data="targets" :bordered="false" />
      </template>
      <template v-else>
        <n-card v-for="t in targets" :key="t.id" class="mcard" size="small" :title="connName(t.connection_id)">
          <div class="mrow"><span class="mlabel">云目标</span><span>{{ destName(t.cloud_destination_id) }}</span></div>
          <div class="mactions">
            <n-popconfirm @positive-click="rmTarget(t.id)"><template #trigger><n-button size="large" type="error" ghost>删除</n-button></template>确认删除?</n-popconfirm>
          </div>
        </n-card>
      </template>
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
        <n-form-item label="类型">
          <n-radio-group v-model:value="destForm.provider">
            <n-radio-button value="s3">S3 / MinIO</n-radio-button>
            <n-radio-button value="nfs">NFS</n-radio-button>
            <n-radio-button value="smb">SMB</n-radio-button>
          </n-radio-group>
        </n-form-item>
        <template v-if="destForm.provider === 'nfs'">
          <n-form-item label="服务器"><n-input v-model:value="destForm.mount.server" placeholder="192.168.1.10" /></n-form-item>
          <n-form-item label="导出路径"><n-input v-model:value="destForm.mount.export" placeholder="/export/backup" /></n-form-item>
          <n-form-item label="协议版本">
            <n-radio-group v-model:value="destForm.mount.version">
              <n-radio-button value="nfs4">NFSv4</n-radio-button>
              <n-radio-button value="nfs3">NFSv3</n-radio-button>
            </n-radio-group>
          </n-form-item>
        </template>
        <template v-if="destForm.provider === 'smb'">
          <n-form-item label="服务器"><n-input v-model:value="destForm.mount.server" placeholder="192.168.1.10" /></n-form-item>
          <n-form-item label="共享名"><n-input v-model:value="destForm.mount.share" placeholder="backup" /></n-form-item>
          <n-form-item label="域(可选)"><n-input v-model:value="destForm.mount.domain" /></n-form-item>
          <n-form-item label="用户名"><n-input v-model:value="destForm.mount.username" /></n-form-item>
          <n-form-item label="密码"><n-input v-model:value="destForm.mount_password" type="password" show-password-on="click" /></n-form-item>
        </template>
        <template v-if="destForm.provider === 's3'">
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
      </template>
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
