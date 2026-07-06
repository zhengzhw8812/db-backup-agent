# 登录页两版改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现两个登录页变体（SoybeanAdmin 分屏风 + tsparticles 粒子背景风），用 `?style=` query 切换对比，零后端改动。

**Architecture:** 提取共用认证逻辑到 `useLogin` composable；新增 `LoginSoybean.vue` / `LoginParticles.vue` 两个纯 UI 组件；`Login.vue` 改为按 `route.query.style` 分派的薄壳 + 「看另一版」切换按钮；`main.ts` 注册 `@tsparticles/vue3` 插件。最后 `docker compose up -d --build` 重建 :8000 并用 Playwright 截两版图对比。

**Tech Stack:** Vue 3 (`<script setup>`) + Naive UI + vue-router + Pinia + `@tsparticles/vue3` + `@tsparticles/slim` + Vite。

**Spec:** `docs/superpowers/specs/2026-07-06-login-redesign-design.md`

**Node:** 本仓库 node 在 `/tmp/node-v20.18.1-linux-x64`。所有 npm 命令前加 `PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH"`，且 `cd frontend`。

---

## 关键约定

- 认证逻辑单一来源：`composables/useLogin.ts`（两版共用）。
- 变体组件不直接接 router query；由父 `Login.vue` 用 `<component :is>` 分派，并通过 `@toggle` 事件切换 query。
- tsparticles 仅 `LoginParticles.vue` 使用；插件在 `main.ts` 全局注册一次。
- 验证手段：`npm run build`（vue-tsc 类型检查 + vite 构建）。本仓库无前端单测框架，最终用 Playwright 对两版各截一张桌面截图。
- 每个 Task 结束提交一次。

---

## Task 1: 安装 tsparticles 依赖

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`（由 npm 自动更新）

- [ ] **Step 1: 安装依赖**

```bash
cd frontend
PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm install @tsparticles/vue3 @tsparticles/slim
```
Expected: `package.json` 的 dependencies 增加 `@tsparticles/vue3` 与 `@tsparticles/slim`；`package-lock.json` 同步。

- [ ] **Step 2: 确认包已可解析**

```bash
PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" node -e "require('@tsparticles/vue3'); require('@tsparticles/slim'); console.log('ok')"
```
Expected: 打印 `ok`（包存在）。

- [ ] **Step 3: 构建仍通过（此刻还没用到，仅确认依赖装入不破坏构建）**

```bash
PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm run build
```
Expected: `✓ built`。

- [ ] **Step 4: 提交**

```bash
cd /home/tony/workspace/db-backup-agent
git add frontend/package.json frontend/package-lock.json
git commit -m "feat(fe): 引入 @tsparticles/vue3 + slim 依赖"
```

---

## Task 2: 注册 tsparticles 插件 + 全局组件类型 shim

**Files:**
- Modify: `frontend/src/main.ts`
- Create: `frontend/src/vue-particles-shim.d.ts`

- [ ] **Step 1: 改 main.ts**

把 `frontend/src/main.ts` 整体替换为：

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Particles from '@tsparticles/vue3'
import { loadSlim } from '@tsparticles/slim'
import App from './App.vue'
import router from './router'

createApp(App)
  .use(createPinia())
  .use(router)
  .use(Particles, { init: async (engine) => { await loadSlim(engine) } })
  .mount('#app')
```

> 说明：`@tsparticles/vue3` 默认导出 Vue 插件，注册后全局组件 `<vue-particles>` 可用。`loadSlim` 注入精简粒子引擎。若安装的版本默认导出或 init 签名不同（构建报错时），读 `node_modules/@tsparticles/vue3/README.md` 校准签名后调整这两行，**不要**改其它逻辑。

- [ ] **Step 2: 新建类型 shim（让 vue-tsc 认识全局 `<vue-particles>`）**

Create `frontend/src/vue-particles-shim.d.ts`:

```typescript
import type { DefineComponent } from 'vue'
declare module 'vue' {
  interface GlobalComponents {
    VueParticles: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  }
}
```

- [ ] **Step 3: 构建**

```bash
cd frontend && PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm run build
```
Expected: `✓ built`，无类型错误。

- [ ] **Step 4: 提交**

```bash
cd /home/tony/workspace/db-backup-agent
git add frontend/src/main.ts frontend/src/vue-particles-shim.d.ts
git commit -m "feat(fe): main.ts 注册 tsparticles 插件 + 全局组件 shim"
```

---

## Task 3: 提取共用认证 composable（DRY）

**Files:**
- Create: `frontend/src/composables/useLogin.ts`

- [ ] **Step 1: 新建 composable**

Create `frontend/src/composables/useLogin.ts`:

```typescript
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useMessage } from 'naive-ui'

/** 登录表单的共用状态 + 提交逻辑（两个登录变体共用，避免重复）。 */
export function useLogin() {
  const username = ref('')
  const password = ref('')
  const loading = ref(false)
  const auth = useAuthStore()
  const router = useRouter()
  const msg = useMessage()

  async function submit() {
    if (!username.value.trim() || !password.value) {
      msg.warning('请输入用户名和密码')
      return
    }
    loading.value = true
    try {
      await auth.doLogin(username.value, password.value)
      router.push('/')
    } catch {
      msg.error('用户名或密码错误')
    } finally {
      loading.value = false
    }
  }

  return { username, password, loading, submit }
}
```

- [ ] **Step 2: 构建**

```bash
cd frontend && PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm run build
```
Expected: `✓ built`。

- [ ] **Step 3: 提交**

```bash
cd /home/tony/workspace/db-backup-agent
git add frontend/src/composables/useLogin.ts
git commit -m "feat(fe): useLogin composable 抽出登录表单共用逻辑"
```

---

## Task 4: Variant A — SoybeanAdmin 分屏风

**Files:**
- Create: `frontend/src/views/login/LoginSoybean.vue`

- [ ] **Step 1: 新建组件**

Create `frontend/src/views/login/LoginSoybean.vue`:

```vue
<script setup lang="ts">
import { NForm, NFormItem, NInput, NButton } from 'naive-ui'
import { useLogin } from '../../composables/useLogin'

defineEmits<{ (e: 'toggle'): void }>()
const { username, password, loading, submit } = useLogin()
</script>

<template>
  <div class="login-shell">
    <!-- 左：品牌区 -->
    <div class="brand">
      <div class="brand-inner">
        <div class="logo">▦</div>
        <h1>数据库备份管理器</h1>
        <p class="en">Database Backup Agent</p>
        <p class="desc">多数据库 · 自动调度 · 加密云同步 · 一键恢复<br />专注、可靠、可视化的备份运维平台。</p>
        <div class="dots"><span /><span /><span /></div>
      </div>
    </div>

    <!-- 右：表单区 -->
    <div class="form-side">
      <button class="switch-btn" type="button" @click="$emit('toggle')">看粒子版 →</button>
      <div class="card">
        <h2>欢迎回来</h2>
        <p class="sub">登录以继续</p>
        <n-form @submit.prevent="submit" label-placement="top">
          <n-form-item label="用户名">
            <n-input v-model:value="username" placeholder="admin" size="large" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="password" type="password" show-password-on="click"
                     placeholder="请输入密码" size="large" @keyup.enter="submit" />
          </n-form-item>
          <n-button type="primary" block size="large" :loading="loading" @click="submit">登 录</n-button>
        </n-form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-shell { display:flex; min-height:100vh; }
.brand {
  flex: 1.2; color:#fff; padding:64px 56px; display:flex; align-items:center;
  background: linear-gradient(135deg, #1e3a8a 0%, #4f46e5 45%, #7c3aed 100%);
  position: relative; overflow:hidden;
}
.brand::after {
  content:''; position:absolute; right:-120px; top:-120px; width:360px; height:360px;
  border-radius:50%; background:rgba(255,255,255,.08);
}
.brand-inner { position:relative; z-index:1; }
.logo { font-size:48px; line-height:1; margin-bottom:18px; opacity:.9; }
.brand h1 { font-size:34px; margin:0 0 6px; font-weight:700; letter-spacing:1px; }
.brand .en { margin:0 0 28px; opacity:.75; font-size:14px; letter-spacing:2px; }
.brand .desc { line-height:1.9; opacity:.85; font-size:14px; max-width:340px; }
.dots { margin-top:36px; display:flex; gap:10px; }
.dots span { width:28px; height:6px; border-radius:3px; background:rgba(255,255,255,.5); }
.dots span:first-child { background:#fbbf24; }

.form-side {
  flex: 1; display:flex; align-items:center; justify-content:center;
  background:#f8fafc; position:relative; padding:48px 24px;
}
.switch-btn {
  position:absolute; top:20px; right:24px; border:1px solid #e2e8f0; background:#fff;
  color:#475569; padding:6px 12px; border-radius:999px; font-size:13px; cursor:pointer;
}
.switch-btn:hover { background:#f1f5f9; }
.card { width:100%; max-width:360px; }
.card h2 { margin:0 0 4px; font-size:24px; color:#0f172a; }
.card .sub { margin:0 0 28px; color:#94a3b8; font-size:14px; }

@media (max-width: 768px) {
  .login-shell { flex-direction:column; }
  .brand { flex:none; padding:36px 28px; }
  .brand h1 { font-size:24px; }
  .brand .desc, .dots { display:none; }
  .form-side { flex:1; }
}
</style>
```

- [ ] **Step 2: 构建**

```bash
cd frontend && PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm run build
```
Expected: `✓ built`（组件尚未被引用，但需类型/语法无误）。

- [ ] **Step 3: 提交**

```bash
cd /home/tony/workspace/db-backup-agent
git add frontend/src/views/login/LoginSoybean.vue
git commit -m "feat(fe): Variant A — SoybeanAdmin 分屏登录页"
```

---

## Task 5: Variant B — tsparticles 粒子背景风

**Files:**
- Create: `frontend/src/views/login/LoginParticles.vue`

- [ ] **Step 1: 新建组件**

Create `frontend/src/views/login/LoginParticles.vue`:

```vue
<script setup lang="ts">
import { NForm, NFormItem, NInput, NButton } from 'naive-ui'
import { useLogin } from '../../composables/useLogin'

defineEmits<{ (e: 'toggle'): void }>()
const { username, password, loading, submit } = useLogin()

// 粒子配置：深色基调 + 连线 + 鼠标 grab
const options = {
  background: { color: { value: '#0f172a' } },
  fpsLimit: 60,
  particles: {
    color: { value: ['#60a5fa', '#a78bfa', '#f472b6'] },
    links: { enable: true, color: '#64748b', distance: 140, opacity: 0.4, width: 1 },
    move: { enable: true, speed: 1.1, outModes: 'out' as const },
    number: { value: 70, density: { enable: true } },
    opacity: { value: 0.6 },
    shape: { type: 'circle' },
    size: { value: { min: 1, max: 3 } },
  },
  interactivity: {
    events: { onHover: { enable: true, mode: 'grab' } },
    modes: { grab: { distance: 160, links: { opacity: 0.7 } } },
  },
  detectRetina: true,
}
</script>

<template>
  <div class="login-particles">
    <vue-particles id="tsparticles" :options="options" class="bg" />
    <button class="switch-btn" type="button" @click="$emit('toggle')">看分屏版 →</button>
    <div class="card">
      <div class="logo">▦</div>
      <h1>数据库备份管理器</h1>
      <p class="en">Database Backup Agent</p>
      <n-form @submit.prevent="submit" label-placement="top">
        <n-form-item label="用户名">
          <n-input v-model:value="username" placeholder="admin" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input v-model:value="password" type="password" show-password-on="click"
                   placeholder="请输入密码" @keyup.enter="submit" />
        </n-form-item>
        <n-button type="primary" block :loading="loading" @click="submit">登 录</n-button>
      </n-form>
    </div>
  </div>
</template>

<style scoped>
.login-particles { position:relative; min-height:100vh; display:flex; align-items:center; justify-content:center; }
.bg { position:fixed; inset:0; z-index:0; }
.switch-btn {
  position:fixed; top:20px; right:24px; z-index:2;
  border:1px solid rgba(255,255,255,.3); background:rgba(255,255,255,.08);
  color:#e2e8f0; padding:6px 12px; border-radius:999px; font-size:13px; cursor:pointer;
  backdrop-filter: blur(6px);
}
.switch-btn:hover { background:rgba(255,255,255,.16); }
.card {
  position:relative; z-index:1; width:100%; max-width:380px; margin:24px;
  padding:40px 36px; border-radius:18px; color:#fff;
  background:rgba(15,23,42,.45); border:1px solid rgba(255,255,255,.18);
  backdrop-filter: blur(14px); box-shadow:0 12px 40px rgba(0,0,0,.35);
}
.logo { font-size:40px; opacity:.9; }
.card h1 { margin:8px 0 2px; font-size:22px; font-weight:700; }
.card .en { margin:0 0 24px; opacity:.7; font-size:13px; letter-spacing:2px; }
</style>
```

- [ ] **Step 2: 构建**

```bash
cd frontend && PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm run build
```
Expected: `✓ built`，`<vue-particles>` 由 Task 2 的 shim 识别、无类型错误。若仍报 `vue-particles` 未知，复核 shim 文件在 `src/` 下且 tsconfig 含 `src/**/*.d.ts`。

- [ ] **Step 3: 提交**

```bash
cd /home/tony/workspace/db-backup-agent
git add frontend/src/views/login/LoginParticles.vue
git commit -m "feat(fe): Variant B — tsparticles 粒子背景登录页"
```

---

## Task 6: Login.vue 改为薄壳（query 分派 + 切换）

**Files:**
- Modify: `frontend/src/views/Login.vue`

- [ ] **Step 1: 用薄壳整体替换 `Login.vue`**

把 `frontend/src/views/Login.vue` 整体替换为：

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LoginSoybean from './login/LoginSoybean.vue'
import LoginParticles from './login/LoginParticles.vue'

const route = useRoute()
const router = useRouter()
const style = computed<'soybean' | 'particles'>(() =>
  route.query.style === 'particles' ? 'particles' : 'soybean'
)
function toggle() {
  router.replace({ path: '/login', query: { style: style.value === 'soybean' ? 'particles' : 'soybean' } })
}
</script>

<template>
  <component :is="style === 'particles' ? LoginParticles : LoginSoybean" @toggle="toggle" />
</template>
```

> 这移除了原 `Login.vue` 的内联认证逻辑（已迁移到 `useLogin`）与玻璃卡片样式（由两版各自承担）。路由守卫对 `/login` 不重定向，`?style=` query 会被保留。

- [ ] **Step 2: 构建**

```bash
cd frontend && PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" npm run build
```
Expected: `✓ built`，dist 产出。

- [ ] **Step 3: 提交**

```bash
cd /home/tony/workspace/db-backup-agent
git add frontend/src/views/Login.vue
git commit -m "feat(fe): Login.vue 改为 ?style= 分派 + 看另一版切换"
```

---

## Task 7: 重建 :8000 镜像 + Playwright 截两版对比图

**Files:** （无源码改动；验证 + 产出截图）

- [ ] **Step 1: 重建并启动容器**

```bash
cd /home/tony/workspace/db-backup-agent
docker compose up -d --build
```
Expected: 末尾 `Container db-backup-agent Started`（Dockerfile 内 `npm ci` 会按更新后的 lock 拉取 tsparticles）。

- [ ] **Step 2: 等待 healthy + 验证 health**

```bash
for i in $(seq 1 40); do
  curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1 \
    && { echo "ready: $(curl -s http://127.0.0.1:8000/api/v1/health)"; break; }
  sleep 2
done
```
Expected: `ready: {"status":"ok"}`。

- [ ] **Step 3: Playwright 截两版**

脚本 `/tmp/login_shots.py`（API-cookie 登录拿会话后访问两个 login URL 截图）：

```python
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8000"
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    ctx=b.new_context(viewport={"width":1280,"height":800})
    pg=ctx.new_page()
    # 已登录态访问 /login?style=... 会被守卫重定向到 /,所以先登出/清会话再访问
    pg.goto(BASE+"/login?style=soybean"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(800)
    pg.screenshot(path="/tmp/login_soybean.png")
    pg.goto(BASE+"/login?style=particles"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1500)  # 等粒子渲染
    pg.screenshot(path="/tmp/login_particles.png")
    # 用 fresh context 模拟未登录(确保看到的是登录页而不是重定向后的 dashboard)
    ctx2=b.new_context(viewport={"width":1280,"height":800})
    g2=ctx2.new_page()
    g2.goto(BASE+"/login?style=soybean"); g2.wait_for_load_state("networkidle"); g2.wait_for_timeout(600)
    g2.screenshot(path="/tmp/login_soybean2.png")
    g2.goto(BASE+"/login?style=particles"); g2.wait_for_load_state("networkidle"); g2.wait_for_timeout(1500)
    g2.screenshot(path="/tmp/login_particles2.png")
    b.close(); print("done")
```

Run: `python3 /tmp/login_shots.py`
Expected: `done`；产出 `/tmp/login_soybean2.png` 与 `/tmp/login_particles2.png`（fresh context = 未登录，看到真登录页）。

> 用 `analyze_image`（mcp）核对两张「fresh」截图确实分别呈现分屏表单 / 粒子背景 + 中央卡片。

- [ ] **Step 4: 报告对比**

把两张截图的关键差异讲给用户（布局/动效/主题色），让用户二选一。选定后另起一轮收尾（删另一版 + 固定 `/login`），不在本计划内。

- [ ] **Step 5: 若截图中途有迭代微调（颜色/留白/粒子密度），改动后重跑 Step 1-3；最终一起提交（如有源码微调）**

```bash
cd /home/tony/workspace/db-backup-agent
git add -A
git commit -m "style(fe): 登录页两版微调(对比定稿前)" || echo "no source changes"
```

---

## Self-Review 备忘（实现者无需操作）

- **Spec 覆盖**：§2 共用逻辑 → T3；§3 SoybeanAdmin → T4；§4 粒子 → T5；§5 query 对比 → T6；§6 集成/构建 → T1/T2/T7。
- **类型一致**：`useLogin()` 返回 `{username,password,loading,submit}` 在 T3/T4/T5 一致；`@toggle` 事件在 T4/T5/T6 一致；`style` 取值 `'soybean'|'particles'` 在 T6 内一致。
- **向后**：原 Login.vue 内联逻辑被 T3 composable 取代、T6 薄壳替换；登录功能等价（admin 输入 → doLogin → 跳 /）。
