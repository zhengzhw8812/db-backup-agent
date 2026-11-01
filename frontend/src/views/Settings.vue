<script setup lang="ts">
import PageHeader from '../components/PageHeader.vue'
import { ref, h, onMounted } from 'vue'
import {
  NCard, NPopconfirm, NList, NListItem, NText, NForm, NFormItem, NInput, NInputNumber,
  NSwitch, NButton, NSpace, NDataTable, NModal, NSelect, NTag, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as setApi from '../api/settings'
import type { NotificationGlobal, Channel, ChannelType, ChannelInput } from '../api/settings'
import * as sbApi from '../api/self-backup'

const msg = useMessage()

// ---------- 配置库 SQL 导入还原 ----------
const importFile = ref<File | null>(null)
const restoring = ref('')

function pickImport(e: Event) {
  const t = e.target as HTMLInputElement
  importFile.value = t.files?.[0] ?? null
}

async function importSql() {
  if (!importFile.value) { msg.warning('先选择 .sql 文件'); return }
  const fd = new FormData()
  fd.append('file', importFile.value)
  try {
    await sbApi.importSql(fd)
    msg.success('已暂存,重启容器后生效')
    importFile.value = null
    const el = document.querySelector<HTMLInputElement>('input[type="file"][accept=".sql"]')
    if (el) el.value = ''
  } catch (e: any) { msg.error(e.response?.data?.detail || '导入失败') }
}

async function restoreListed(name: string) {
  restoring.value = name
  try {
    await sbApi.restoreListed(name)
    msg.success('已暂存,重启容器后生效')
  } catch (e: any) { msg.error(e.response?.data?.detail || '还原失败') }
  finally { restoring.value = '' }
}

// ---------- 全局通知开关 ----------
const globalLoading = ref(false)
const globalLoaded = ref(false)  // 仅加载成功后才允许保存,避免用默认值覆盖真实配置
const g = ref<NotificationGlobal>({ notify_on_success: true, notify_on_failure: true, notify_watchdog: true })

async function loadGlobal() {
  try {
    g.value = (await setApi.getGlobalNotifications()).data
    globalLoaded.value = true
  } catch { msg.error('加载通知设置失败,请刷新重试') }
}

async function saveGlobal() {
  globalLoading.value = true
  try {
    g.value = (await setApi.putGlobalNotifications(g.value)).data
    msg.success('已保存')
  } catch (e: any) { msg.error(e.response?.data?.detail || '保存失败') }
  finally { globalLoading.value = false }
}

// ---------- 通知渠道列表(同渠道可多条/多账号) ----------
const channels = ref<Channel[]>([])
const showChannel = ref(false)
const editingChannel = ref<Channel | null>(null)
const channelSaving = ref(false)
const testing = ref<number | null>(null)

const typeOptions: Array<{ label: string; value: ChannelType }> = [
  { label: '📧 邮箱', value: 'email' },
  { label: '💬 企业微信', value: 'wechat' },
  { label: '🪶 飞书', value: 'feishu' },
  { label: '🔔 Server酱', value: 'serverchan' },
]
const typeLabel = (t: string) => typeOptions.find(o => o.value === t)?.label ?? t

// 表单:config 为非敏感配置;secret 编辑留空 = 不改
const cform = ref<{
  type: ChannelType; name: string; enabled: boolean
  config: {
    smtp_host?: string; smtp_port?: number | null; smtp_ssl?: boolean; smtp_starttls?: boolean
    smtp_user?: string; smtp_from?: string; recipients?: string
    corp_id?: string; agent_id?: string
  }
  secret: { password?: string; secret?: string; webhook?: string; sign?: string; sendkey?: string }
}>({ type: 'email', name: '', enabled: true, config: {}, secret: {} })

function openChannelAdd() {
  editingChannel.value = null
  cform.value = { type: 'email', name: '', enabled: true, config: { smtp_ssl: true, smtp_starttls: false }, secret: {} }
  showChannel.value = true
}

function openChannelEdit(row: Channel) {
  editingChannel.value = row
  cform.value = {
    type: row.type, name: row.name, enabled: row.enabled,
    config: { ...(row.config as typeof cform.value.config) },
    secret: {},  // 密钥留空不改
  }
  showChannel.value = true
}

async function saveChannel() {
  channelSaving.value = true
  try {
    // secret 全空 → 传 null(保留已存密文)
    const secretEmpty = !Object.values(cform.value.secret).some(v => v && v.trim())
    const payload: ChannelInput = {
      type: cform.value.type, name: cform.value.name, enabled: cform.value.enabled,
      config: cform.value.config as Record<string, unknown>,
      secret: secretEmpty ? null : cform.value.secret,
    }
    if (editingChannel.value) await setApi.updateChannel(editingChannel.value.id, payload)
    else await setApi.createChannel(payload)
    msg.success('已保存')
    showChannel.value = false
    await loadChannels()
  } catch (e: any) { msg.error(e.response?.data?.detail || '保存失败') }
  finally { channelSaving.value = false }
}

async function toggleChannel(row: Channel, val: boolean) {
  try {
    await setApi.updateChannel(row.id, {
      type: row.type, name: row.name, enabled: val, config: row.config, secret: null,
    })
    row.enabled = val
  } catch (e: any) { msg.error(e.response?.data?.detail || '更新失败') }
}

async function removeChannel(id: number) {
  try { await setApi.deleteChannel(id); msg.success('已删除'); await loadChannels() }
  catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}

async function testOne(row: Channel) {
  testing.value = row.id
  try {
    await setApi.testChannel(row.id)
    msg.success(`「${row.name}」测试消息已发出`)
  } catch (e: any) {
    msg.error(e.response?.data?.detail || '测试失败')
  } finally { testing.value = null }
}

async function loadChannels() {
  try { channels.value = (await setApi.listChannels()).data }
  catch { msg.error('加载通知渠道失败') }
}

const channelColumns: DataTableColumns<Channel> = [
  { title: '类型', key: 'type', width: 130, render: r => h(NTag, { size: 'small', bordered: false }, { default: () => typeLabel(r.type) }) },
  { title: '名称', key: 'name' },
  { title: '启用', key: 'enabled', width: 80, render: r => h(NSwitch, { value: r.enabled, size: 'small', 'onUpdate:value': (v: boolean) => toggleChannel(r, v) }) },
  {
    title: '操作', key: 'actions', width: 220,
    render: r => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', loading: testing.value === r.id, onClick: () => testOne(r) }, { default: () => '测试' }),
        h(NButton, { size: 'small', onClick: () => openChannelEdit(r) }, { default: () => '编辑' }),
        h(NPopconfirm, { onPositiveClick: () => removeChannel(r.id) }, {
          trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }),
          default: () => `确认删除渠道「${r.name}」?`,
        }),
      ],
    }),
  },
]

// ---------- 备份验证 ----------
const verifyAuto = ref(false)

async function loadVerify() {
  try {
    const { data } = await setApi.getVerifySettings()
    verifyAuto.value = data.auto_enabled
  } catch { msg.error('加载验证设置失败') }
}

async function saveVerify() {
  try {
    await setApi.putVerifySettings({ auto_enabled: verifyAuto.value })
    msg.success('验证设置已保存')
  } catch (e: any) { msg.error(e.response?.data?.detail || '保存失败') }
}

// ---------- 配置库自备份 ----------
const snaps = ref<Array<{ name: string; kind: 'gz' | 'sql'; size: number; created_at: string }>>([])
const fmtSize = (n: number) => n < 1024 ? `${n}B` : n < 1048576 ? `${(n/1024).toFixed(1)}KB` : `${(n/1048576).toFixed(1)}MB`

async function loadSnaps() {
  try { snaps.value = (await sbApi.listSelfBackups()).data } catch { /* 静默 */ }
}

async function runSelfBackupNow(fmt: 'gz' | 'sql' = 'gz') {
  try {
    const r = await sbApi.runSelfBackup(fmt)
    msg.success(`自备份完成:${r.data.name}`)
    await loadSnaps()
  } catch (e: any) { msg.error(e.response?.data?.detail || '自备份失败') }
}

async function removeSnap(name: string) {
  try { await sbApi.deleteSelfBackup(name); msg.success('已删除'); await loadSnaps() }
  catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}

onMounted(() => { loadGlobal(); loadChannels(); loadVerify(); loadSnaps() })
</script>

<template>

  <PageHeader title="设置" description="通知渠道、验证与配置库自备份" /><n-space vertical :size="16">
    <n-card title="通知设置" :bordered="false">
      <n-form label-placement="top">
        <n-space align="center">
          <n-form-item label="成功通知"><n-switch v-model:value="g.notify_on_success" /></n-form-item>
          <n-form-item label="失败通知"><n-switch v-model:value="g.notify_on_failure" /></n-form-item>
          <n-form-item label="失联告警"><n-switch v-model:value="g.notify_watchdog" /></n-form-item>
          <n-form-item label=" ">
            <n-button type="primary" size="small" :loading="globalLoading" :disabled="!globalLoaded" @click="saveGlobal">保存开关</n-button>
          </n-form-item>
        </n-space>
        <n-text depth="3">备份成功/失败与失联告警按上述全局开关推送到下方所有已启用渠道。</n-text>
      </n-form>
    </n-card>

    <n-card title="通知渠道" :bordered="false">
      <template #header-extra>
        <n-button type="primary" size="small" @click="openChannelAdd">+ 新建渠道</n-button>
      </template>
      <n-data-table v-if="channels.length" :columns="channelColumns" :data="channels" :bordered="false" size="small" striped />
      <n-text v-else depth="3">还没有通知渠道;同一类型可以建多条(不同账号),发送时逐一推送。</n-text>
    </n-card>

    <n-card title="备份验证" :bordered="false">
      <n-form label-placement="top">
        <n-form-item label="每周自动验证">
          <n-space align="center">
            <n-switch v-model:value="verifyAuto" />
            <n-button :loading="false" @click="saveVerify">保存</n-button>
          </n-space>
        </n-form-item>
        <n-text depth="3">开启后每周一 03:30 自动校验备份文件完整性(gzip CRC + 校验和),损坏的备份会触发失败通知。</n-text>
      </n-form>
    </n-card>

    <n-card title="配置库自备份" :bordered="false">
      <n-space vertical :size="8">
        <n-space align="center">
          <n-button type="primary" @click="() => runSelfBackupNow('gz')">立即备份</n-button>
          <n-button @click="() => runSelfBackupNow('sql')">导出 SQL</n-button>
          <n-button @click="() => (importFile ? importSql() : undefined)" :disabled="!importFile">导入 SQL 还原</n-button>
          <input type="file" accept=".sql" @change="pickImport" />
          <n-text depth="3">每日 04:00 自动备份配置库并上传云端(保留本地 7 份 / 云端 30 份)。恢复:下载快照后停容器、覆盖 data/sqlite/app.db、再启动。</n-text>
        </n-space>
        <n-list v-if="snaps.length" bordered>
          <n-list-item v-for="s in snaps" :key="s.name">
            <n-space justify="space-between" style="width: 100%">
              <span>{{ s.name }}({{ fmtSize(s.size) }})</span>
              <n-space>
                <n-popconfirm v-if="s.kind === 'sql'" @positive-click="restoreListed(s.name)">
                  <template #trigger>
                    <n-button size="small" type="warning" :loading="restoring === s.name">还原</n-button>
                  </template>
                  将覆盖当前配置库,重启容器后生效,并自动留底当前配置。确认?
                </n-popconfirm>
                <n-button size="small" tag="a" :href="sbApi.downloadUrl(s.name)" target="_blank">下载</n-button>
                <n-popconfirm @positive-click="removeSnap(s.name)">
                  <template #trigger>
                    <n-button size="small" type="error" ghost>删除</n-button>
                  </template>
                  确认删除快照 {{ s.name }}?(本地与云端副本一并删除)
                </n-popconfirm>
              </n-space>
            </n-space>
          </n-list-item>
        </n-list>
      </n-space>
    </n-card>
  </n-space>

  <n-modal v-model:show="showChannel" preset="card" :title="editingChannel ? '编辑渠道' : '新建渠道'"
           style="width: 520px" :mask-closable="false" :close-on-esc="false">
    <n-form label-placement="top">
      <n-space>
        <n-form-item label="类型">
          <n-select v-model:value="cform.type" :options="typeOptions" :disabled="!!editingChannel" style="width: 180px" />
        </n-form-item>
        <n-form-item label="名称"><n-input v-model:value="cform.name" placeholder="例如:个人邮箱 / 运维群" style="width: 260px" /></n-form-item>
      </n-space>
      <n-form-item label="启用"><n-switch v-model:value="cform.enabled" /></n-form-item>

      <template v-if="cform.type === 'email'">
        <n-space>
          <n-form-item label="SMTP 主机"><n-input v-model:value="cform.config.smtp_host" /></n-form-item>
          <n-form-item label="端口"><n-input-number v-model:value="cform.config.smtp_port" /></n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="用户名"><n-input v-model:value="cform.config.smtp_user" /></n-form-item>
          <n-form-item label="密码(留空不改)"><n-input v-model:value="cform.secret.password" type="password" show-password-on="click" placeholder="留空保持不变" /></n-form-item>
        </n-space>
        <n-space>
          <n-form-item label="发件人"><n-input v-model:value="cform.config.smtp_from" /></n-form-item>
          <n-form-item label="收件人(逗号分隔)"><n-input v-model:value="cform.config.recipients" /></n-form-item>
        </n-space>
        <n-space align="center">
          <n-form-item label="SSL"><n-switch v-model:value="cform.config.smtp_ssl" /></n-form-item>
          <n-form-item label="STARTTLS"><n-switch v-model:value="cform.config.smtp_starttls" /></n-form-item>
        </n-space>
      </template>

      <template v-else-if="cform.type === 'wechat'">
        <n-space>
          <n-form-item label="Corp ID"><n-input v-model:value="cform.config.corp_id" /></n-form-item>
          <n-form-item label="Agent ID"><n-input v-model:value="cform.config.agent_id" /></n-form-item>
        </n-space>
        <n-form-item label="Secret(留空不改)"><n-input v-model:value="cform.secret.secret" type="password" show-password-on="click" placeholder="留空保持不变" /></n-form-item>
      </template>

      <template v-else-if="cform.type === 'feishu'">
        <n-form-item label="Webhook 地址"><n-input v-model:value="cform.secret.webhook" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxx(已保存则留空)" /></n-form-item>
        <n-form-item label="加签密钥(可选,留空不改)"><n-input v-model:value="cform.secret.sign" type="password" placeholder="(已保存则留空)" /></n-form-item>
      </template>

      <template v-else>
        <n-form-item label="Server酱 SendKey"><n-input v-model:value="cform.secret.sendkey" placeholder="SCT...(已保存则留空)" /></n-form-item>
      </template>

      <n-space justify="end">
        <n-button @click="showChannel = false">取消</n-button>
        <n-button type="primary" :loading="channelSaving" @click="saveChannel">保存</n-button>
      </n-space>
    </n-form>
  </n-modal>
</template>
