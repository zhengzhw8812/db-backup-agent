<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NForm, NFormItem, NInput, NInputNumber, NSwitch, NButton, NSpace, useMessage } from 'naive-ui'
import * as setApi from '../api/settings'
import type { NotificationSettings } from '../api/settings'

const msg = useMessage()
const loading = ref(false)
const f = ref<NotificationSettings>({
  email_enabled: false, smtp_host: null, smtp_port: 465, smtp_ssl: true, smtp_starttls: false,
  smtp_user: null, smtp_password: null, smtp_from: null, recipients: null,
  wechat_enabled: false, wechat_corp_id: null, wechat_agent_id: null, wechat_secret: null,
  notify_on_success: true, notify_on_failure: true,
})

async function load() {
  const { data } = await setApi.getNotifications()
  // 读回时密码/secret 为空(后端不回传),保留空以免覆盖
  f.value = { ...data, smtp_password: null, wechat_secret: null }
}
async function save() {
  loading.value = true
  try {
    await setApi.putNotifications(f.value)
    msg.success('已保存')
    f.value.smtp_password = null
    f.value.wechat_secret = null
  } catch (e: any) { msg.error(e.response?.data?.detail || '保存失败') }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <n-space vertical :size="16">
    <n-card title="通知设置" :bordered="false">
      <n-form label-placement="top">
        <n-space align="center">
          <n-form-item label="启用邮件"><n-switch v-model:value="f.email_enabled" /></n-form-item>
          <n-form-item label="成功通知"><n-switch v-model:value="f.notify_on_success" /></n-form-item>
          <n-form-item label="失败通知"><n-switch v-model:value="f.notify_on_failure" /></n-form-item>
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

    <n-button type="primary" :loading="loading" @click="save">保存设置</n-button>
  </n-space>
</template>
