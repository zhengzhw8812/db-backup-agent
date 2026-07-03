# Phase 3a — 前端骨架 + 登录 + 布局 + 主题 + 连接页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** 搭起 Vue 3 SPA 骨架(Vite + TS + Naive UI + Pinia + Router + axios),实现:登录流程(C 玻璃质感)、路由守卫、主题系统(A 浅色默认 + 深色切换)、应用布局(侧栏导航 + 顶栏),并把"数据库连接"页接到 Phase 1 的 `/api/v1/connections` CRUD —— 端到端打通前端栈。

**Architecture:** `frontend/` 独立目录,Vite 开发服务器经代理转发 `/api` 到后端(uvicorn :5001)。生产构建 `npm run build` 产出 `dist/`,由 FastAPI 托管(本计划不涉及,留到打包任务)。Pinia 管 auth/theme 状态;axios 封装 API;EventSource 留到 3b(SSE 进度)。

**Tech Stack:** Vue 3 + Vite + TypeScript, Naive UI, Pinia, Vue Router, axios。ECharts 留到 3b(仪表盘)。

**设计基调:** A 专业克制(浅色默认,靛蓝 #4f46e5 点缀,对标 Linear/Vercel)+ 内置深色模式 + 登录页 C 玻璃质感(渐变 + 毛玻璃)。

**前置:** Phase 1+2 后端 API 就绪(/auth/login,/me,/connections 等)。

---

## File Structure
```
frontend/
├── package.json
├── vite.config.ts            # 代理 /api → http://localhost:5001
├── tsconfig.json
├── index.html
└── src/
    ├── main.ts               # 挂载 Naive UI + Pinia + Router
    ├── App.vue
    ├── api/
    │   ├── client.ts         # axios 实例(401 → 跳登录)
    │   └── auth.ts / connections.ts
    ├── stores/
    │   ├── auth.ts           # 登录态 / me
    │   └── theme.ts          # 浅/深 + localStorage
    ├── router/
    │   └── index.ts          # 路由 + 登录守卫
    ├── composables/
    │   └── useTheme.ts
    ├── layouts/
    │   └── AppLayout.vue     # 侧栏 + 顶栏 + <router-view>
    ├── themes/
    │   └── tokens.ts         # 颜色/圆角/阴影 token + Naive UI 主题覆盖
    └── views/
        ├── Login.vue         # C 玻璃质感
        └── Connections.vue    # CRUD
```

---

## Task 1: Vite + Vue3 + TS + Naive UI + Pinia + Router 脚手架 + API 代理 + 构建

**Files:** `frontend/package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.ts`, `src/App.vue`。

- [ ] **Step 1: 在 `frontend/` 下 `npm create vite@latest . -- --template vue-ts`(或手动建文件)。**确认 Node 可用;若沙箱无 Node,报告 BLOCKED。**

- [ ] **Step 2: package.json 依赖**
```json
{
  "name": "db-backup-agent-frontend",
  "private": true,
  "version": "3.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "axios": "^1.7",
    "naive-ui": "^2.40",
    "pinia": "^2.2",
    "vue": "^3.5",
    "vue-router": "^4.4"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1",
    "typescript": "^5.6",
    "vite": "^5.4",
    "vue-tsc": "^2.1"
  }
}
```
`npm install`。

- [ ] **Step 3: vite.config.ts(代理 /api → 后端 5001)**
```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:5001', changeOrigin: true } },
  },
})
```

- [ ] **Step 4: tsconfig.json(Vite vue-ts 默认即可,确保 `"types": ["vite/client"]` 之类)。** index.html 含 `<div id="app">` 与 `/src/main.ts`。

- [ ] **Step 5: src/main.ts(挂载 Naive UI + Pinia + Router)**
```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

createApp(App).use(createPinia()).use(router).mount('#app')
```

- [ ] **Step 6: src/App.vue(仅 `<router-view />`,后续布局由 AppLayout 提供)**
```vue
<template><router-view /></template>
```

- [ ] **Step 7: 验证构建** `npm run build` 产出 `frontend/dist/`。`npm run dev` 能起(报告 URL)。

- [ ] **Step 8: 提交**
```bash
git add frontend/
git commit -m "feat(phase3a): 前端脚手架(Vite+Vue3+TS+Naive UI+Pinia+Router)"
```

> 本任务暂不加 router/stores 的具体内容(后续任务),但要保证 `npm run build` 通过(需 router/index.ts 存在,哪怕只有空路由 —— 先放一个占位 router 使 build 通过)。

---

## Task 2: API 客户端 + auth store + 登录页(C 玻璃)+ 路由守卫

**Files:** `src/api/client.ts`, `src/api/auth.ts`, `src/stores/auth.ts`, `src/router/index.ts`, `src/views/Login.vue`。

- [ ] **Step 1: src/api/client.ts**
```ts
import axios from 'axios'
import router from '../router'

const client = axios.create({ baseURL: '/api/v1', withCredentials: true })

client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) router.push('/login')
    return Promise.reject(err)
  },
)

export default client
```

- [ ] **Step 2: src/api/auth.ts**
```ts
import client from './client'
export const login = (username: string, password: string) =>
  client.post('/auth/login', { username, password })
export const logout = () => client.post('/auth/logout')
export const me = () => client.get('/auth/me')
```

- [ ] **Step 3: src/stores/auth.ts**
```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '../api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<{ id: number; username: string; totp_enabled: boolean } | null>(null)
  const ready = ref(false)

  async function fetchMe() {
    try { user.value = (await authApi.me()).data } catch { user.value = null }
    ready.value = true
  }
  async function doLogin(username: string, password: string) {
    user.value = (await authApi.login(username, password)).data
  }
  async function doLogout() { await authApi.logout(); user.value = null }

  return { user, ready, fetchMe, doLogin, doLogout }
})
```

- [ ] **Step 4: src/router/index.ts(登录守卫)**
```ts
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/Login.vue') },
    { path: '/', component: () => import('../layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/connections' },
        { path: 'connections', component: () => import('../views/Connections.vue') },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.fetchMe()
  if (!auth.user && to.path !== '/login') return '/login'
  if (auth.user && to.path === '/login') return '/'
})

export default router
```

- [ ] **Step 5: src/views/Login.vue(C 玻璃质感登录页)**
```vue
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
```

- [ ] **Step 6: 验证 `npm run build` 通过**(AppLayout/Connections 在后续任务,本任务先放占位:在 router 里临时把 AppLayout/Connections import 指向 Login 或一个占位组件,使 build 通过;Task 3/4 替换)。**或**:本任务先不引 AppLayout/Connections,router 只含 /login;Task 3 加 AppLayout,Task 4 加 Connections。**采用后者**(更干净)。

- [ ] **Step 7: 提交**
```bash
git add frontend/src/api frontend/src/stores frontend/src/router frontend/src/views/Login.vue
git commit -m "feat(phase3a): API 客户端 + auth store + 登录页 + 路由守卫"
```

---

## Task 3: 主题系统(A 浅色默认 + 深色切换)+ 应用布局(侧栏 + 顶栏)

**Files:** `src/themes/tokens.ts`, `src/stores/theme.ts`, `src/composables/useTheme.ts`, `src/layouts/AppLayout.vue`。

- [ ] **Step 1: src/themes/tokens.ts(设计 token + Naive UI 主题覆盖)**
```ts
import type { GlobalThemeOverrides } from 'naive-ui'

export const lightOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#4f46e5', primaryColorHover: '#6366f1', primaryColorPressed: '#4338ca',
    borderRadius: '8px', borderRadiusSmall: '6px',
    fontFamily: '-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  },
}

export const darkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#818cf8', primaryColorHover: '#a5b4fc', primaryColorPressed: '#6366f1',
    borderRadius: '8px',
  },
}
```

- [ ] **Step 2: src/stores/theme.ts**
```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const dark = ref(localStorage.getItem('theme') === 'dark')
  function toggle() { dark.value = !dark.value; localStorage.setItem('theme', dark.value ? 'dark' : 'light') }
  return { dark, toggle }
})
```

- [ ] **Step 3: src/composables/useTheme.ts**
```ts
import { computed } from 'vue'
import { darkTheme, type ConfigProvider } from 'naive-ui'
import { useThemeStore } from '../stores/theme'
import { lightOverrides, darkOverrides } from '../themes/tokens'

export function useTheme() {
  const store = useThemeStore()
  const theme = computed(() => (store.dark ? darkTheme : null))
  const overrides = computed(() => (store.dark ? darkOverrides : lightOverrides))
  return { theme, overrides, dark: computed(() => store.dark), toggle: store.toggle }
}
```

- [ ] **Step 4: src/layouts/AppLayout.vue(侧栏导航 + 顶栏:用户名 / 主题切换 / 登出)**
```vue
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu, NButton, NSpace, NIcon, NConfigProvider } from 'naive-ui'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../composables/useTheme'

const auth = useAuthStore()
const router = useRouter()
const { theme, overrides, dark, toggle } = useTheme()

const menuOptions = [
  { label: '数据库连接', key: 'connections' },
  // 3b 增加:仪表盘 / 备份计划 / 备份 / 历史 / 日志 / 设置
]
function onSelect(key: string) { router.push(`/${key}`) }
async function logout() { await auth.doLogout(); router.push('/login') }
</script>

<template>
  <n-config-provider :theme="theme" :theme-overrides="overrides">
    <n-layout has-sider style="height:100vh">
      <n-layout-sider bordered :width="220" content-style="padding:12px">
        <div class="logo">📦 DB Backup</div>
        <n-menu :options="menuOptions" @update:value="onSelect" :value="$route.path.slice(1)" />
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
  </n-config-provider>
</template>

<style scoped>.logo{font-weight:700;padding:8px 4px 16px;font-size:16px}</style>
```

- [ ] **Step 5: 把 AppLayout 接入 router**(Task 2 的 router 已引用 AppLayout;现在它真实存在)。

- [ ] **Step 6: 验证 `npm run build` 通过。**

- [ ] **Step 7: 提交**
```bash
git add frontend/src/themes frontend/src/stores/theme.ts frontend/src/composables frontend/src/layouts
git commit -m "feat(phase3a): 主题系统(浅色默认+深色)+ 应用布局"
```

---

## Task 4: 数据库连接页(CRUD,接 /api/v1/connections)

**Files:** `src/api/connections.ts`, `src/views/Connections.vue`。

- [ ] **Step 1: src/api/connections.ts**
```ts
import client from './client'
export type Connection = {
  id: number; name: string; type: 'pg'|'mysql'|'mongo'|'redis'|'sqlite'
  host?: string|null; port?: number|null; db_name?: string|null
  username?: string|null; extra?: Record<string,unknown>|null; created_at: string
}
export const listConnections = () => client.get<Connection[]>('/connections')
export const createConnection = (data: Partial<Connection> & { password?: string }) => client.post('/connections', data)
export const updateConnection = (id: number, data: Partial<Connection> & { password?: string }) => client.put(`/connections/${id}`, data)
export const deleteConnection = (id: number) => client.delete(`/connections/${id}`)
```

- [ ] **Step 2: src/views/Connections.vue(列表 + 新增/编辑 Modal + 删除确认)**
实现:表格列(name/type/host:port/db_name/username/操作);"新增任务"按钮打开 Modal 表单(name/type 下拉/host/port/db_name/username/password);编辑回填(密码留空表示不改);删除用 NPopconfirm。type 下拉选项:pg/mysql/mongo/redis/sqlite。**密码字段不回填,占位提示"留空不改"。**

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NDataTable, NButton, NModal, NForm, NFormItem, NInput, NInputNumber, NSelect, NSpace, NPopconfirm, useMessage } from 'naive-ui'
import * as api from '../api/connections'
import type { Connection } from '../api/connections'

const msg = useMessage()
const data = ref<Connection[]>([])
const loading = ref(false)
const show = ref(false)
const editing = ref<Connection | null>(null)
const form = ref<any>({})

const typeOptions = [
  { label: 'PostgreSQL', value: 'pg' }, { label: 'MySQL', value: 'mysql' },
  { label: 'MongoDB', value: 'mongo' }, { label: 'Redis', value: 'redis' }, { label: 'SQLite', value: 'sqlite' },
]

async function load() { loading.value = true; try { data.value = (await api.listConnections()).data } finally { loading.value = false } }
function openAdd() { editing.value = null; form.value = { type: 'pg', port: 5432 }; show.value = true }
function openEdit(row: Connection) {
  editing.value = row
  form.value = { name: row.name, type: row.type, host: row.host, port: row.port, db_name: row.db_name, username: row.username, password: '' }
  show.value = true
}
async function save() {
  try {
    if (editing.value) await api.updateConnection(editing.value.id, form.value)
    else await api.createConnection(form.value)
    msg.success('已保存'); show.value = false; await load()
  } catch (e:any) { msg.error(e.response?.data?.detail || '保存失败') }
}
async function remove(id: number) { await api.deleteConnection(id); msg.success('已删除'); await load() }

const columns = [
  { title: '名称', key: 'name' },
  { title: '类型', key: 'type' },
  { title: '主机', key: 'host' },
  { title: '端口', key: 'port' },
  { title: '数据库', key: 'db_name' },
  { title: '用户', key: 'username' },
  { title: '操作', key: 'actions',
    render(row: Connection) { /* 编辑/删除按钮 —— 用 h() 或模板 */ return null as any } },
]

onMounted(load)
</script>

<template>
  <n-card title="数据库连接" :bordered="false">
    <template #header-extra><n-button type="primary" @click="openAdd">+ 新增连接</n-button></template>
    <n-data-table :columns="columns" :data="data" :loading="loading" />
  </n-card>

  <n-modal v-model:show="show" preset="card" :title="editing ? '编辑连接' : '新增连接'" style="width:480px">
    <n-form label-placement="top">
      <n-form-item label="名称"><n-input v-model:value="form.name" /></n-form-item>
      <n-form-item label="类型"><n-select v-model:value="form.type" :options="typeOptions" /></n-form-item>
      <n-space>
        <n-form-item label="主机"><n-input v-model:value="form.host" /></n-form-item>
        <n-form-item label="端口"><n-input-number v-model:value="form.port" /></n-form-item>
      </n-space>
      <n-form-item label="数据库名"><n-input v-model:value="form.db_name" /></n-form-item>
      <n-form-item label="用户名"><n-input v-model:value="form.username" /></n-form-item>
      <n-form-item :label="editing ? '密码(留空不改)' : '密码'"><n-input v-model:value="form.password" type="password" /></n-form-item>
      <n-space justify="end"><n-button @click="show=false">取消</n-button><n-button type="primary" @click="save">保存</n-button></n-space>
    </n-form>
  </n-modal>
</template>
```

> "操作"列的编辑/删除按钮:实现者用 `h(NButton, {...})` 或自定义渲染补全(编辑 → openEdit(row);删除 → NPopconfirm 包裹 → remove(row.id))。这是该页唯一需要补全的渲染细节。

- [ ] **Step 3: 把 Connections 接入 router**(Task 2 router 已引用;现在真实存在)。

- [ ] **Step 4: 验证 `npm run build` 通过。**(端到端手测留到后端可跑时:登录 → 看到连接页 → 增删改。)

- [ ] **Step 5: 提交**
```bash
git add frontend/src/api/connections.ts frontend/src/views/Connections.vue
git commit -m "feat(phase3a): 数据库连接页(CRUD)"
```

---

## Phase 3a 完成标准
- `npm run build` 成功产出 `frontend/dist/`。
- `npm run dev` 起服务,代理 /api 到后端;登录页(C 玻璃)可登录;布局(侧栏+顶栏)显示;主题可切换;连接页可 CRUD(需后端运行)。
- 代码结构与设计基调(A 浅色 + 深色 + C 登录)落地。

## 留给 3b / 后续
- Dashboard(ECharts)/ Schedules / Backups(SSE 进度)/ History / Logs / Settings 页面。
- FastAPI 托管 dist/ + Docker 构建前端(生产打包)。
- 端到端手测(需 docker compose 起 redis+pg)。

---

*自检:本计划对应设计文档 §10(前端结构)、§13(主题)。类型一致:`useAuthStore`、`useTheme`、api 函数跨任务一致。前端 TDD 较轻(build 验证为主),与后端(pytest)不同。*
