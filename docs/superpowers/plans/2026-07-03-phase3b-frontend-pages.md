# Phase 3b — 前端核心页面(仪表盘/计划/备份/历史)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development。

**Goal:** 把核心备份管理 UX 全部接到前端:仪表盘(KPI + ECharts 趋势)、备份计划 CRUD、**备份页(立即备份 + SSE 实时进度抽屉 + 取消)**、历史记录。补齐所需的后端聚合/日志端点。

**Architecture:** 前端 4 页 + 1 个后端小任务(仪表盘统计/趋势端点)。Backups 页用 EventSource 订阅 `/api/v1/jobs/{id}/events` 实时显示 dump/compress/success 等阶段。Pinia/axios/router 已就绪(3a)。

**Tech Stack:** Vue3 + Naive UI + ECharts(vue-echarts)+ EventSource(SSE)。

**前置:** Phase 3a 完成(脚手架/登录/布局/主题/连接页)。后端 /backups、/jobs、/schedules、/backups/run、/jobs/{id}/events 就绪。

---

## Tasks

### Task 1(后端): 仪表盘统计 + 趋势端点
`app/routers/dashboard.py`:`GET /api/v1/dashboard/stats`(总备份数、成功率、总存储、running 数)、`GET /api/v1/dashboard/trends`(近 30 天每日成功/失败计数,按 type 的存储分布)。简单 SQLAlchemy 聚合。接入 main。`tests/test_dashboard_api.py`(建几条 BackupRecord,断言聚合)。鉴权。

### Task 2(前端): 仪表盘页(Dashboard.vue)
加 `echarts` + `vue-echarts` 依赖。KPI 卡(总备份/成功率/存储/进行中)+ 近 30 天成功/失败堆叠柱状图 + 按 DB 类型存储饼图。侧栏菜单加"仪表盘",路由 `/`。API `api/dashboard.ts`。

### Task 3(前端): 备份计划页(Schedules.vue)
表格(connection→cron_expr→enabled→retention→next_run_at)+ 新增/编辑 Modal(cron 表达式输入 + 连接下拉 + 保留天数)+ 启用开关 + 删除。接 `/schedules`。`api/schedules.ts`。侧栏菜单 + 路由。

### Task 4(前端): 备份页(Backups.vue)—— 核心体验
顶部"立即备份"(选连接 → POST /backups/run → 拿 record_id → **打开进度抽屉,EventSource 订阅 /jobs/{record_id}/events**,按 stage 显示 dump/compress/success/failed/cancelled 进度条 + 日志;终态关闭并刷新)。任务列表(GET /jobs,running)带取消按钮(POST /jobs/{id}/cancel)。备份文件表(GET /backups:下载/删除)。`api/jobs.ts` + `api/backups.ts` + `composables/useJobStream.ts`(封装 EventSource)。侧栏菜单 + 路由。

### Task 5(前端): 历史页(History.vue)
GET /backups 全量记录表(时间/连接/触发/状态/大小/耗时/校验和/错误),状态色标,可下载。`api/backups.ts` 复用。侧栏菜单 + 路由。

---

## Phase 3b 完成标准
- 后端 dashboard 端点测试通过;全套后端测试绿。
- `npm run build` 通过;4 个新页面可访问。
- Backups 页 SSE 实时进度可工作(需后端 + redis 运行做端到端验证)。
- 侧栏导航完整。

## 留给后续 Phase
- Settings(通知/账号/保留 —— 需对应后端端点)。
- Restore(Phase 4)、Cloud sync(Phase 5)。
- 生产打包(FastAPI 托管 dist + Docker 构建前端)。
