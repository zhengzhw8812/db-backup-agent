<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { NCard, NForm, NFormItem, NInput, NButton, useMessage } from 'naive-ui'

const auth = useAuthStore()
const router = useRouter()
const msg = useMessage()
const username = ref(''); const password = ref(''); const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    await auth.doLogin(username.value, password.value)
    router.push('/')
  } catch {
    msg.error('用户名或密码错误')
  } finally { loading.value = false }
}
</script>

<template>
  <div class="login-wrap">
    <div class="glass-card">
      <h1>数据库备份管理器</h1>
      <p class="subtitle">Database Backup Agent</p>
      <n-form @submit.prevent="submit">
        <n-form-item label="用户名"><n-input v-model:value="username" placeholder="admin" /></n-form-item>
        <n-form-item label="密码"><n-input v-model:value="password" type="password" @keyup.enter="submit" /></n-form-item>
        <n-button type="primary" block :loading="loading" @click="submit">登录</n-button>
      </n-form>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #6366f1, #8b5cf6 45%, #ec4899);
}
.glass-card {
  width: 360px; padding: 36px 32px; border-radius: 18px;
  background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.25);
  backdrop-filter: blur(12px); color: #fff; box-shadow: 0 8px 32px rgba(0,0,0,.18);
}
.glass-card h1 { margin: 0 0 4px; font-size: 22px; font-weight: 700 }
.subtitle { margin: 0 0 20px; opacity: .85; font-size: 13px }
</style>
