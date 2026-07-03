# 设置 + 日志页 (Settings + Logs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development to implement task-by-task.

**Goal:** 补齐前端缺失的两个页面(§10):**Settings.vue**(通知配置表单 → 已有 `/settings/notifications`)与 **Logs.vue**(系统日志表 → 新增 `/logs` 端点)。补齐侧栏 设置/日志 菜单,使所有菜单项均有页面。

**Architecture:** 后端新增 `/logs`(GET,读 SystemLog,可选 level 过滤,限 500 条)。前端 Settings.vue 用 GET/PUT `/settings/notifications`(密码字段写时填、读时空,避免覆盖);Logs.vue 轮询/加载 `/logs`。纯 UI + 一个只读端点,无新表。

**Tech Stack:** FastAPI + Vue3/Naive UI。前置:通知配置端点已就绪(`/settings/notifications`)。

---

## Tasks

### Task 1: /logs 端点(后端)

**Files:** Create `app/schemas/log.py`; Create `app/routers/logs.py`; Modify `app/main.py`; Test `tests/test_logs_api.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_logs_api.py`:
```python
import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    from app.db.models import SystemLog
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(SystemLog(level="info", source="sync", message="ok"))
        db.add(SystemLog(level="error", source="backup", message="boom"))
        db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_logs_require_auth(client):
    assert client.get("/api/v1/logs").status_code == 401


def test_logs_list(authed):
    rows = authed.get("/api/v1/logs").json()
    assert len(rows) == 2
    assert all("message" in r and "level" in r for r in rows)


def test_logs_level_filter(authed):
    rows = authed.get("/api/v1/logs?level=error").json()
    assert len(rows) == 1
    assert rows[0]["level"] == "error"
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_logs_api.py -v` → FAIL(404)。

- [ ] **Step 3: schema** —— 创建 `app/schemas/log.py`:
```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class SystemLogOut(BaseModel):
    id: int
    level: str
    source: str
    message: str
    context: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}
```

- [ ] **Step 4: router** —— 创建 `app/routers/logs.py`:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import SystemLog
from app.deps import get_current_account
from app.schemas.log import SystemLogOut

router = APIRouter()


@router.get("/logs", response_model=list[SystemLogOut])
def list_logs(level: str | None = Query(default=None),
              db: Session = Depends(get_db), _=Depends(get_current_account)):
    q = db.query(SystemLog).order_by(SystemLog.id.desc())
    if level:
        q = q.filter(SystemLog.level == level)
    return q.limit(500).all()
```

- [ ] **Step 5: 挂载** —— `app/main.py`:import 加 `logs`(注意:不要与 python `logging` 混淆;模块名 logs 安全)。把 routers import 行扩为含 `logs`,例如:
```python
from app.routers import health, auth, connections, jobs, backups, schedules, dashboard, restore, cloud, settings as settings_router, logs
```
并追加:
```python
    app.include_router(logs.router, prefix="/api/v1", tags=["logs"])
```

- [ ] **Step 6: 跑测试 + 全量** —— `python3 -m pytest tests/test_logs_api.py -v`(PASS 3);`python3 -m pytest -p no:warnings -q`(全绿,~115 passed)。

- [ ] **Step 7: 提交** —— `git add app/schemas/log.py app/routers/logs.py app/main.py tests/test_logs_api.py && git commit -m "feat(logs): /logs 端点(系统日志列表 + level 过滤)"`

---

### Task 2: 前端 Settings.vue + Logs.vue + api + 路由/菜单

**Files:** Create `frontend/src/api/settings.ts`, `frontend/src/api/logs.ts`, `frontend/src/views/Settings.vue`, `frontend/src/views/Logs.vue`; Modify router, AppLayout

- [ ] **Step 1: api/settings.ts** —— 创建:
```ts
import client from './client'

export interface NotificationSettings {
  email_enabled: boolean
  smtp_host: string | null
  smtp_port: number | null
  smtp_ssl: boolean
  smtp_starttls: boolean
  smtp_user: string | null
  smtp_password: string | null  // 仅写入
  smtp_from: string | null
  recipients: string | null
  wechat_enabled: boolean
  wechat_corp_id: string | null
  wechat_agent_id: string | null
  wechat_secret: string | null  // 仅写入
  notify_on_success: boolean
  notify_on_failure: boolean
}

export const getNotifications = () => client.get<NotificationSettings>('/settings/notifications')
export const putNotifications = (data: NotificationSettings) => client.put<NotificationSettings>('/settings/notifications', data)
```

- [ ] **Step 2: api/logs.ts** —— 创建:
```ts
import client from './client'

export interface SystemLog {
  id: number
  level: string
  source: string
  message: string
  context: string | null
  created_at: string
}

export const listLogs = (level?: string) =>
  client.get<SystemLog[]>('/logs', { params: level ? { level } : {} })
```

- [ ] **Step 3: Settings.vue** —— 创建:
```vue
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
```

- [ ] **Step 4: Logs.vue** —— 创建:
```vue
<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NCard, NDataTable, NTag, NButton, NSpace, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as logsApi from '../api/logs'
import type { SystemLog } from '../api/logs'

const msg = useMessage()
const data = ref<SystemLog[]>([])
const level = ref<string | null>(null)
const levelOpts = [
  { label: '全部', value: '' },
  { label: 'info', value: 'info' },
  { label: 'error', value: 'error' },
  { label: 'warning', value: 'warning' },
]
async function load() {
  try {
    const { data: d } = await logsApi.listLogs(level.value || undefined)
    data.value = d
  } catch (e: any) { msg.error('加载失败') }
}
const tag = (l: string) => {
  const m: Record<string, 'success'|'warning'|'error'|'info'|'default'> = { info: 'info', error: 'error', warning: 'warning' }
  return h(NTag, { size: 'small', bordered: false, type: m[l] || 'default' }, { default: () => l })
}
const columns: DataTableColumns<SystemLog> = [
  { title: '时间', key: 'created_at', render: r => new Date(r.created_at).toLocaleString() },
  { title: '级别', key: 'level', render: r => tag(r.level) },
  { title: '来源', key: 'source' },
  { title: '消息', key: 'message', ellipsis: { tooltip: true } },
]
onMounted(load)
</script>

<template>
  <n-card title="系统日志" :bordered="false">
    <template #header-extra>
      <n-space align="center">
        <n-select v-model:value="level" :options="levelOpts" size="small" style="width:120px" @update:value="load" />
        <n-button size="small" @click="load">刷新</n-button>
      </n-space>
    </template>
    <n-data-table :columns="columns" :data="data" :bordered="false" :pagination="{ pageSize: 20 }" />
  </n-card>
</template>
```

- [ ] **Step 5: 路由** —— `frontend/src/router/index.ts` 在 `cloud` 后加:
```ts
        { path: 'settings', component: () => import('../views/Settings.vue') },
        { path: 'logs', component: () => import('../views/Logs.vue') },
```

- [ ] **Step 6: 菜单** —— `frontend/src/layouts/AppLayout.vue` `menuOptions` 在 `云存储` 后加:
```ts
  { label: '设置', key: 'settings' },
  { label: '日志', key: 'logs' },
```

- [ ] **Step 7: 构建** —— `export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" && npm --prefix frontend run build` → vue-tsc 无错、vite 成功。

- [ ] **Step 8: 提交** —— `git add frontend/src/api/settings.ts frontend/src/api/logs.ts frontend/src/views/Settings.vue frontend/src/views/Logs.vue frontend/src/router/index.ts frontend/src/layouts/AppLayout.vue && git commit -m "feat(settings-logs): Settings.vue + Logs.vue + 路由/菜单"`

---

## 完成标准
- 全量后端测试绿(~115 passed);`npm run build` 通过。
- 侧栏 设置/日志 可用;Settings 能 GET/PUT 通知配置(密码留空不覆盖);Logs 列系统日志 + level 过滤。

## 留给后续
- 账号设置(改密码)区块。
- 日志自动刷新 / SSE 实时日志流。
