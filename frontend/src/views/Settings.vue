<script setup lang="ts">
import PageHeader from '../components/PageHeader.vue'
import { ref, onMounted } from 'vue'
import { NCard, NPopconfirm, NList, NListItem, NText, NForm, NFormItem, NInput, NInputNumber, NSwitch, NButton, NSpace, useMessage } from 'naive-ui'
import * as setApi from '../api/settings'
import * as sbApi from '../api/self-backup'

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
import type { NotificationSettings } from '../api/settings'

const msg = useMessage()
const loading = ref(false)
const loaded = ref(false)  // 仅加载成功后才允许保存,避免用默认值覆盖真实配置
const f = ref<NotificationSettings>({
  email_enabled: false, smtp_host: null, smtp_port: 465, smtp_ssl: true, smtp_starttls: false,
  smtp_user: null, smtp_password: null, smtp_from: null, recipients: null,
  wechat_enabled: false, wechat_corp_id: null, wechat_agent_id: null, wechat_secret: null,
  notify_on_success: true, notify_on_failure: true, notify_watchdog: true,
  feishu_enabled: false, feishu_webhook: null, feishu_secret: null,
  serverchan_enabled: false, serverchan_sendkey: null,
})

async function load() {
  try {
    const { data } = await setApi.getNotifications()
    // 读回时密码/secret 为空(后端不回传),保留空以免覆盖
    f.value = { ...data, smtp_password: null, wechat_secret: null, feishu_webhook: null, feishu_secret: null, serverchan_sendkey: null }
    loaded.value = true
  } catch (e: any) {
    msg.error('加载通知配置失败,请刷新重试')
  }
}
async function save() {
  loading.value = true
  try {
    await setApi.putNotifications(f.value)
    msg.success('已保存')
    f.value.smtp_password = null; f.value.wechat_secret = null
    f.value.feishu_webhook = null; f.value.feishu_secret = null; f.value.serverchan_sendkey = null
  } catch (e: any) { msg.error(e.response?.data?.detail || '保存失败') }
  finally { loading.value = false }
}
const verifyAuto = ref(false)

async function loadVerify() {
  try {
    const { data } = await setApi.getVerifySettings()
    verifyAuto.value = data.auto_enabled
  } catch (e: any) {
    msg.error('加载验证设置失败')
  }
}

async function saveVerify() {
  try {
    await setApi.putVerifySettings({ auto_enabled: verifyAuto.value })
    msg.success('验证设置已保存')
  } catch (e: any) {
    msg.error(e.response?.data?.detail || '保存失败')
  }
}

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

onMounted(() => { load(); loadVerify(); loadSnaps() })
</script>

<template>
  
  <PageHeader title="设置" description="通知、验证与配置库自备份" /><n-space vertical :size="16">
    <n-card title="通知设置" :bordered="false">
      <n-form label-placement="top">
        <n-space align="center">
          <n-form-item label="启用邮件"><n-switch v-model:value="f.email_enabled" /></n-form-item>
          <n-form-item label="成功通知"><n-switch v-model:value="f.notify_on_success" /></n-form-item>
          <n-form-item label="失败通知"><n-switch v-model:value="f.notify_on_failure" /></n-form-item>
          <n-form-item label="失联告警"><n-switch v-model:value="f.notify_watchdog" /></n-form-item>
        </n-space>
        <template v-if="f.email_enabled">
          <n-space>
            <n-form-item label="SMTP 主机"><n-input v-model:value="f.smtp_host" /></n-form-item>
            <n-form-item label="端口"><n-input-number v-model:value="f.smtp_port" /></n-form-item>
          </n-space>
          <n-space>
            <n-form-item label="用户名"><n-input v-model:value="f.smtp_user" /></n-form-item>
            <n-form-item label="密码(留空不改)"><n-input v-model:value="f.smtp_password" type="password" show-password-on="click" placeholder="留空保持不变" /></n-form-item>
          </n-space>
          <n-space>
            <n-form-item label="发件人"><n-input v-model:value="f.smtp_from" /></n-form-item>
            <n-form-item label="收件人(逗号分隔)"><n-input v-model:value="f.recipients" /></n-form-item>
          </n-space>
          <n-space align="center">
            <n-form-item label="SSL"><n-switch v-model:value="f.smtp_ssl" /></n-form-item>
            <n-form-item label="STARTTLS"><n-switch v-model:value="f.smtp_starttls" /></n-form-item>
          </n-space>
        </template>
      </n-form>
    
    <n-card title="飞书 / 个人微信(Server酱)" :bordered="false">
      <n-form label-placement="top">
        <n-space align="center">
          <n-form-item label="启用飞书机器人"><n-switch v-model:value="f.feishu_enabled" /></n-form-item>
          <n-form-item label="启用 Server酱"><n-switch v-model:value="f.serverchan_enabled" /></n-form-item>
        </n-space>
        <n-form-item label="飞书 Webhook 地址"><n-input v-model:value="f.feishu_webhook" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxx(已保存则留空)" /></n-form-item>
        <n-form-item label="飞书加签密钥(可选)"><n-input v-model:value="f.feishu_secret" type="password" placeholder="(已保存则留空)" /></n-form-item>
        <n-form-item label="Server酱 SendKey"><n-input v-model:value="f.serverchan_sendkey" type="password" placeholder="SCT...(已保存则留空)" /></n-form-item>
        <n-text depth="3">备份成功/失败与失联告警将按各渠道开关推送;Webhook/SendKey 保存后不回显,留空即保持原值。</n-text>
      </n-form>
    </n-card>
    </n-card>

    <n-card title="企业微信" :bordered="false">
      <n-form label-placement="top">
        <n-form-item label="启用企业微信"><n-switch v-model:value="f.wechat_enabled" /></n-form-item>
        <template v-if="f.wechat_enabled">
          <n-space>
            <n-form-item label="Corp ID"><n-input v-model:value="f.wechat_corp_id" /></n-form-item>
            <n-form-item label="Agent ID"><n-input v-model:value="f.wechat_agent_id" /></n-form-item>
          </n-space>
          <n-form-item label="Secret(留空不改)"><n-input v-model:value="f.wechat_secret" type="password" show-password-on="click" placeholder="留空保持不变" /></n-form-item>
        </template>
      </n-form>
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
          <n-text depth="3">每日 04:00 自动备份配置库(VACUUM INTO 一致性快照),保留最近 7 份。恢复:下载快照后停容器、覆盖 data/sqlite/app.db、再启动。</n-text>
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
              </n-space>
            </n-space>
          </n-list-item>
        </n-list>
      </n-space>
    </n-card>

    <n-button type="primary" :loading="loading" :disabled="!loaded" @click="save">保存设置</n-button>
  </n-space>
</template>
