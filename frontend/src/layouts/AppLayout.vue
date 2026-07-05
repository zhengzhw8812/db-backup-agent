<script setup lang="ts">
import { useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NButton, NSpace } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../composables/useTheme'

const auth = useAuthStore()
const router = useRouter()
const { dark, toggle } = useTheme()

const menuOptions = [
  { label: '仪表盘', key: 'dashboard' },
  { label: '数据库连接', key: 'connections' },
  { label: '备份计划', key: 'schedules' },
  { label: '备份', key: 'backups' },
  { label: '恢复', key: 'restore' },
  { label: '云存储', key: 'cloud' },
  { label: '备份历史', key: 'history' },
  { label: '设置', key: 'settings' },
  { label: '日志', key: 'logs' },
  // 3b 增加:备份 / 历史 / 日志 / 设置
]
function onSelect(key: string) { router.push(`/${key}`) }
async function logout() { await auth.doLogout(); router.push('/login') }
</script>

<template>
  <n-layout has-sider style="height:100vh">
    <n-layout-sider bordered :width="220" content-style="padding:12px">
      <div class="logo">📦 DB Backup</div>
      <n-menu :options="menuOptions" :value="$route.path.slice(1)" @update:value="onSelect" />
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="height:56px;padding:0 20px;display:flex;align-items:center;justify-content:flex-end">
        <n-space align="center">
          <n-button quaternary @click="toggle">{{ dark ? '🌞 浅色' : '🌙 深色' }}</n-button>
          <span style="opacity:.7">{{ auth.user?.username }}</span>
          <n-button quaternary @click="logout">登出</n-button>
        </n-space>
      </n-layout-header>
      <n-layout-content content-style="padding:24px;background:#f8fafc">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<style scoped>
.logo { font-weight: 700; padding: 8px 4px 16px; font-size: 16px }
</style>
