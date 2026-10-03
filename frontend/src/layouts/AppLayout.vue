<script setup lang="ts">
import { h, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NDrawer, NDrawerContent, NIcon, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../composables/useTheme'
import { useBreakpoint } from '../composables/useBreakpoint'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { dark, toggle } = useTheme()
const { isMobile } = useBreakpoint()

const PAGE_ICONS: Record<string, string> = {
  dashboard: '📊', connections: '🔌', schedules: '⏰', backups: '💾',
  restore: '♻️', cloud: '☁️', history: '📜', settings: '⚙️', logs: '📋',
}

const MENU = [
  { label: '📊 仪表盘', key: 'dashboard' },
  { label: '🔌 数据库连接', key: 'connections' },
  { label: '⏰ 备份计划', key: 'schedules' },
  { label: '💾 备份', key: 'backups' },
  { label: '♻️ 恢复', key: 'restore' },
  { label: '☁️ 云存储', key: 'cloud' },
  { label: '📜 备份历史', key: 'history' },
  { label: '⚙️ 设置', key: 'settings' },
  { label: '📋 日志', key: 'logs' },
]

const collapsed = ref(localStorage.getItem('sider-collapsed') === '1')
const drawerOpen = ref(false)
const activeKey = ref(route.path.slice(1))

watch(() => route.path, (p) => {
  activeKey.value = p.slice(1)
  drawerOpen.value = false  // 移动端路由跳转后自动收起抽屉
})
watch(collapsed, (v) => localStorage.setItem('sider-collapsed', v ? '1' : '0'))

function onSelect(key: string) { router.push(`/${key}`) }
async function logout() { await auth.doLogout(); router.push('/login') }
</script>

<template>
  <n-layout has-sider style="height:100vh">
    <!-- 桌面侧栏 -->
    <n-layout-sider
      v-if="!isMobile"
      bordered
      collapse-mode="width"
      :collapsed="collapsed"
      :collapsed-width="64"
      :width="220"
      show-trigger
      @update:collapsed="(v: boolean) => (collapsed = v)"
      content-style="padding:12px"
    >
      <div class="logo">{{ collapsed ? '📦' : '📦 DB Backup' }}</div>
      <n-menu
        :options="MENU"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="20"
        :value="activeKey"
        @update:value="onSelect"
      />
      <div class="sider-version">v3.2.0</div>
    </n-layout-sider>

    <!-- 移动抽屉侧栏 -->
    <n-drawer v-if="isMobile" v-model:show="drawerOpen" :width="240" placement="left">
      <n-drawer-content :body-content-style="{ padding: '12px' }">
        <div class="logo">📦 DB Backup</div>
        <n-menu :options="MENU" :value="activeKey" @update:value="onSelect" />
      </n-drawer-content>
    </n-drawer>

    <n-layout>
      <n-layout-header bordered class="topbar">
        <div class="topbar-left">
          <n-button v-if="isMobile" quaternary @click="drawerOpen = true">
            <template #icon><span class="hamburger">☰</span></template>
          </n-button>
          <span v-if="isMobile" class="brand">DB Backup</span>
          <span v-else class="page-title">{{ PAGE_ICONS[activeKey] || '' }} {{ MENU.find(m => m.key === activeKey)?.label?.slice(3) || '' }}</span>
        </div>
        <n-space align="center" :size="8">
          <n-button quaternary size="small" @click="toggle">{{ dark ? '🌞' : '🌙' }}</n-button>
          <span class="username">{{ auth.user?.username }}</span>
          <n-button quaternary size="small" @click="logout">登出</n-button>
        </n-space>
      </n-layout-header>
      <n-layout-content content-style="padding:16px;">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<style scoped>
.logo { font-weight: 700; padding: 8px 4px 16px; font-size: 16px; white-space: nowrap; overflow: hidden }
.topbar {
  height: 56px; padding: 0 16px;
  display: flex; align-items: center; justify-content: space-between;
}
.topbar-left { display: flex; align-items: center; gap: 8px }
.brand { font-weight: 700 }
.page-title { font-weight: 600; font-size: 15px }
.username { opacity: .7; font-size: 13px }
.hamburger { font-size: 18px }
.sider-version { opacity: .4; font-size: 11px; text-align: center; padding: 10px 0 2px }
@media (max-width: 767px) {
  .topbar :deep(.n-button) { min-height: 44px }
}
</style>
