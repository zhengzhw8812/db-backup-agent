# db-backup-agent 完全重写设计文档

- **日期**: 2026-07-02
- **状态**: 已确认(brainstorming 阶段完成,待实现计划)
- **作者**: Zheng Zhiwen + Claude
- **范围**: 对 db-backup-agent 进行完全重写(全新技术栈),覆盖界面重设计、功能重设计、安全加固与性能优化

---

## 1. 背景与动机

现有版本(Flask 3.0 单体 + 原生 JS + Jinja2 + SQLite,通过系统 cron + bash 脚本执行备份)存在以下根本性问题:

- **可维护性差**:`app.py` 单文件 2027 行,所有路由与逻辑混杂,大量重复代码,硬编码 Docker 路径(`importlib` 加载 `/app/notifications.py`)。
- **严重安全漏洞**:11 个路由无登录校验(任何人可触发备份、删库配置、改通知/SMTP 密码、读全部日志);删除连接存在越权(IDOR);通知配置全局共享而非按用户隔离;密码用未加盐 SHA-256;生产环境 `debug=True`;硬编码弱 secret_key 回退;`shell=True` 拼接子进程存在 RCE 隐患;路径穿越校验过弱。
- **体验落后**:浅蓝渐变 header + 扁平卡片 + emoji 按钮的"工具型"界面,缺乏现代设计感与实时反馈。
- **能力受限**:只能备份不能恢复;无云存储异地容灾;无数据可视化;仅支持 PG/MySQL。

本次重写从零构建,目标是打造一个**安全、现代、可扩展、有高级感(professional/premium)**的数据库备份管理平台。

## 2. 目标与非目标

### 目标
- 全新现代技术栈,清晰的分层架构与可测试性。
- 彻底修复所有已知安全问题,采用现代安全最佳实践。
- 全新 UI:专业克制(A 风格)为默认 + 内置深色模式 + 玻璃质感(C)点缀登录页。
- 四大新能力:**一键恢复**、**云存储同步**、**富仪表盘**、**更多数据库类型**。
- 单容器部署,数据卷持久化,删容器不丢数据。
- 实时任务进度、可取消、失败自动告警。

### 非目标(YAGNI)
- 多用户 / 团队 / RBAC 角色(明确改为**单用户**,见 §4)。
- 增量 / 差异备份(本轮不做,保留扩展位)。
- 数据从旧版迁移(明确**全新开始**,无迁移脚本)。
- 反向代理 / 多服务编排(保持单容器;compose 仅作可选)。

## 3. 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端框架 | **FastAPI**(Python,异步) | 保留 Python 编排 dump 工具的能力;自动生成 OpenAPI 文档;原生异步 |
| ORM | **SQLAlchemy 2.x** | 参数化查询,防 SQL 注入 |
| 任务队列 | **arq + Redis** | 异步 job、重试、定时;worker 与 Web 分离 |
| 调度器 | **APScheduler** | 进程内 cron,替代系统 cron |
| 数据库 | **SQLite** | 配置/历史/账号(数据量级小,零运维) |
| 缓存/队列 | **Redis**(内嵌同容器) | 任务队列 + pub/sub 进度 + 缓存 + 限流 |
| 前端框架 | **Vue 3 + Vite + TypeScript** | SPA,响应式 |
| UI 组件库 | **Naive UI** | 现代克制,原生支持主题(浅/深) |
| 状态管理 | **Pinia** | |
| 图表 | **ECharts** | 仪表盘可视化 |
| 实时通信 | **SSE**(Server-Sent Events) | 任务进度推送(单向、轻量,优于 WebSocket) |
| 容器编排 | **supervisord** | 同容器内托管 redis + uvicorn + arq worker |

**新增数据库类型**:PostgreSQL、MySQL、MongoDB、Redis、SQLite。
**云存储**:S3 兼容(AWS S3 / MinIO / Cloudflare R2 / Backblaze B2)、阿里云 OSS、腾讯云 COS。

## 4. 用户模型:单用户

- 唯一管理员账号,**无注册功能**;首次启动通过环境变量或引导页初始化账号。
- **整库无 `user_id` 字段**,从架构层面消灭旧版多用户隔离类 bug(IDOR、全局通知等)。
- 保留强认证:**argon2** 密码哈希 + 可选 **TOTP 2FA**。
- 仍保持"操作前校验资源归属"的代码习惯,为未来可选的多用户留余地。

## 5. 系统架构

**单容器、三进程、任务队列驱动、数据卷持久化。**

- 容器由 `supervisord` 守护三个进程:
  1. **redis-server** —— 任务队列 + pub/sub 进度 + 缓存 + 限流。
  2. **uvicorn(FastAPI)** —— Web/API、APScheduler 定时触发、认证、SSE 推送。**永不直接执行长任务**,只把 job 投入队列后立即返回。
  3. **arq worker** —— 实际执行 backup/restore/sync/notify 等重任务。
- `/data` 卷(挂载持久化):
  - `sqlite/` 配置/历史/账号
  - `redis/` RDB 持久化(队列不丢)
  - `backups/` 备份文件
  - `logs/` 运行日志
- 外部依赖:目标数据库(PG/MySQL/Mongo/Redis/SQLite)、云存储(S3/OSS/COS)、通知(邮件/企业微信)。

**核心价值**:Web 永不卡顿(长任务异步化);职责清晰(Web 管"说",worker 管"做");worker 崩溃不影响 Web,可自动重启;实时进度通过 Redis pub/sub → SSE 推送;部署仍是单容器。

## 6. 后端模块结构(分层 + 适配器模式)

```
app/
├── main.py                # 应用工厂 + 中间件 + lifespan(建表、起调度器)
├── config.py              # pydantic-settings:环境变量/路径/密钥
├── deps.py                # 依赖注入:get_db / get_current_account
├── db/models.py           # SQLAlchemy 表模型
├── core/
│   ├── security.py        # argon2 / TOTP / 会话
│   └── crypto.py          # Fernet 凭据加密
├── routers/               # 薄路由(按域拆分,替代 2000 行 app.py)
│   ├── auth.py  connections.py  schedules.py  backups.py
│   ├── restore.py  sync.py  dashboard.py  history.py  logs.py  settings.py
├── services/              # 业务逻辑(路由无关、可单测)
│   ├── backup_service.py  restore_service.py  sync_service.py
│   ├── scheduler.py  notifications.py  retention.py
├── workers/
│   ├── tasks.py           # backup_job / restore_job / sync_job / notify_job
│   └── progress.py        # Redis pub/sub 进度上报
├── adapters/              # ⭐ 每种数据库一个文件(策略模式)
│   ├── base.py            # BackupAdapter 接口:dump/restore/list
│   ├── postgres.py  mysql.py  mongodb.py  redis_db.py  sqlite_db.py
└── cloud/                 # ⭐ 每种云存储一个文件
    ├── base.py            # StorageAdapter 接口:upload/delete
    ├── s3.py  oss.py  cos.py
```

**关键设计**:
- **三层分工**:Router(解析请求)→ Service(业务逻辑)→ Adapter(具体执行)。路由极薄,逻辑在 Service 层,可脱离 HTTP 单测。
- **适配器模式(扩展性核心)**:新增数据库类型 = 在 `adapters/` 加一个实现 `BackupAdapter` 接口的文件;新增云 = 在 `cloud/` 加一个实现 `StorageAdapter` 的文件。**不改任何现有代码**。前端"数据库类型"下拉自动列出已注册适配器(插件式注册表)。

## 7. 数据模型(SQLite)

单用户 → 无 `user_id`。所有凭据 Fernet 加密落库。

| 表 | 作用 | 关键字段 |
|---|---|---|
| `account` | 唯一管理员(单行) | username, password_hash(argon2), totp_secret?, totp_enabled |
| `db_connections` | 数据库连接 | name, type(pg/mysql/mongo/redis/sqlite), host, port, db_name, username, password_enc, extra(JSON: ssl 等) |
| `schedules` | 备份计划(按连接) | connection_id(FK), cron_expr, enabled, retention_days, next_run_at |
| `backup_records` | 备份历史/状态 | connection_id, trigger(手动/计划), status(running/success/failed/cancelled), file_path, size, checksum(sha256), duration_ms, error, started_at, finished_at |
| `restore_records` | 还原记录 | backup_record_id(FK), target_connection_id, status, error, started_at, finished_at |
| `cloud_destinations` | 云存储目标 | name, provider(s3/oss/cos), endpoint, region, bucket, access_key_enc, secret_enc, prefix, enabled |
| `sync_targets` | 连接↔云同步关系 | connection_id, cloud_destination_id, enabled |
| `notification_config` | 通知配置(单行) | email_enabled, smtp_*, wechat_*(凭据加密), notify_on_success/failure |
| `system_logs` | 系统日志 | level, source, message, context(JSON), created_at |

**安全要点**:DB 密码、云 AK/SK、SMTP/企业微信密钥全部 Fernet 加密;备份文件附 SHA-256 校验和,用于下载/恢复前完整性校验。

## 8. 任务执行模型(生命周期)

所有长任务(备份/恢复/同步/通知)统一走 arq job 机制。

**备份流水线**(worker 依次执行,每步往 Redis pub/sub 推进度):

1. (Web 侧)校验 → 建 `backup_record(status=running)` → 投入 arq 队列 → **立即返回 job_id**(界面不卡)
2. 取连接配置、解密密码、选定适配器
3. 适配器执行导出(`pg_dump` / `mysqldump` / `mongodump` / `redis --rdb` / SQLite 文件拷贝)
4. gzip 压缩 + 计算 SHA-256
5. 写入 `backups/`,更新记录(路径/大小/校验和)
6. 若配云同步 → 分块上传 + 断点续传 + 指数退避重试
7. 保留策略:删除过期备份(本地 + 云端)
8. 按结果发通知

**实时通道**:worker 每步写 Redis pub/sub → FastAPI 经 SSE 推前端 → 进度条/日志实时跳动。
**可取消**:用户点取消 → 设 cancel 标志 → worker 在阶段间隙检查并优雅中止 → `status=cancelled`。
**终态**:`success` / `failed`(任意阶段失败,捕获错误 + 通知) / `cancelled`。

恢复(`RestoreJob`)、云同步(`SyncJob`)走同一套进度/取消机制。

## 9. 四大新能力

### ① 一键恢复 (Restore)
- 历史选备份 → 选目标连接(可与源不同)→ 触发 `RestoreJob`。
- 适配器还原:PG(`pg_restore`/`psql`)、MySQL(`mysql <`)、Mongo(`mongorestore`)、Redis(停写→替换 rdb)、SQLite(替换文件)。
- **安全护栏**:强制二次确认;危险操作需手动输入连接名;可选"恢复前先备份当前数据";恢复前校验文件 SHA-256。

### ② 云存储同步 (Cloud Sync)
- 每个连接可挂 0~N 个云目标(`sync_targets`),支持"本地 + 多云"多副本容灾。
- 分块上传 + 断点续传 + 失败指数退避重试;上传完记录 `remote_uri` 并远端校验。
- 支持"仅云端不留本地"省磁盘;可手动补传历史备份。

### ③ 富仪表盘 (Dashboard)
- KPI 卡:今日备份、成功率(7/30 天)、存储占用、下次计划。
- ECharts:近 30 天成功/失败趋势(堆叠)、按数据库类型的存储分布、计划日历视图。
- 最近任务列表(跑着的带实时进度条)。

### ④ 更多数据库类型
- `adapters/` 下各一文件实现统一 `BackupAdapter` 接口;前端类型下拉自动列出已注册适配器(插件式)。
- 本次:PostgreSQL、MySQL、MongoDB(`mongodump`)、Redis(`--rdb`)、SQLite(文件级)。

## 10. 前端结构(Vue 3 + Vite + Pinia + Naive UI)

```
frontend/src/
├── router/            # 路由 + 登录守卫
├── stores/            # Pinia: auth / theme / settings
├── api/               # REST 客户端 + SSE 封装
├── composables/       # useJobProgress(SSE)/useTheme/useConfirm
├── views/
│   ├── Login.vue        # 玻璃质感登录页(C 风格点缀)
│   ├── Dashboard.vue    # KPI + ECharts
│   ├── Connections.vue  # 数据库连接 CRUD
│   ├── Schedules.vue    # 备份计划
│   ├── Backups.vue      # 文件列表 + 立即备份 + 实时进度
│   ├── Restore.vue      # 一键恢复
│   ├── CloudSync.vue    # 云目标 + 同步规则
│   ├── History.vue / Logs.vue / Settings.vue
├── components/        # JobProgressDrawer / StatusBadge / StatCard / DBTypeIcon…
└── themes/            # 浅色(默认)+ 深色,Naive UI 主题覆盖
```

构建:Vite 打包 → FastAPI 托管(SPA fallback),仍是单容器。
亮点:全局任务进度抽屉(任何页面可见运行中任务);破坏性操作统一二次确认;响应式。

## 11. 安全方案

| 旧版问题 | 新版方案 |
|---|---|
| 11 个路由无鉴权 | FastAPI 依赖注入统一鉴权,根级强制 `get_current_account`,无裸奔路由 |
| 不加盐 SHA-256 | argon2 密码哈希 |
| 凭据明文落库 | Fernet 加密所有凭据(密钥来自环境变量) |
| `shell=True` RCE 隐患 | 子进程一律 `create_subprocess_exec`(参数数组,禁用 shell) |
| 路径穿越弱检查 | `pathlib` 严格边界校验 + 白名单 |
| `debug=True` + 弱默认 secret | 生产关闭 debug;secret 必须由环境变量提供,无弱默认 |
| 多用户越权(IDOR/全局通知) | 单用户模型天然消灭;仍保持操作前归属校验 |

新增:httpOnly + SameSite cookie 会话(防 XSS,服务端会话存 Redis);登录速率限制(Redis 防爆破);保留可选 TOTP 2FA;写操作 SameSite cookie 防 CSRF。

## 12. API 设计(REST,`/api/v1`,OpenAPI 自动生成)

| 域 | 端点 |
|---|---|
| 认证 | `POST /auth/login` · `…/login/verify`(2FA) · `…/logout` · `…/2fa/*` |
| 连接 | `GET/POST /connections` · `…/{id}` · `…/{id}/test` · `…/{id}/databases` |
| 计划 | `GET/POST /schedules` · `…/{id}` |
| 备份 | `POST /backups/run`→job_id · `GET /backups` · `…/{id}/download` · `DELETE …/{id}` |
| 任务 | `GET /jobs` · `POST /jobs/{id}/cancel` · **`GET /jobs/{id}/events`(SSE)** |
| 恢复 | `POST /restore`(backup_id + target)→job_id |
| 云存储 | `…/cloud-destinations` · `…/test` · `/sync-targets` · `POST /sync/run` |
| 仪表盘 | `GET /dashboard/stats` · `…/trends` |
| 其他 | `/history` · `/logs` · `/settings/{notifications,retention,account}` |

所有端点(除 login)受统一鉴权依赖保护。生产环境 `/docs` 关闭或置于鉴权之后。

## 13. 主题与设计系统

- **默认主题 = A 专业克制(浅色)**:大量留白、细边框、靛蓝点缀,对标 Linear/Vercel。
- **内置深色模式**(B 风格):一键切换,Naive UI 主题覆盖,localStorage 记忆偏好。
- **登录页 = C 玻璃质感点缀**:渐变 + 毛玻璃,出效果但不影响日常数据密集页可读性。
- 统一设计 token(颜色/间距/圆角/阴影),组件高度一致。

## 14. 部署

- 单容器:`docker run -v ./data:/data -p 8000:8000 ...`(端口由旧版 5001 调整为 8000,FastAPI 惯例;可在文档注明)。
- `supervisord.conf` 托管 redis + uvicorn + arq worker,进程崩溃自动重启。
- 首次启动引导:设置管理员账号/密码(环境变量优先,否则首次访问引导页)。
- 多架构镜像:amd64 + arm64(沿用旧版 buildx 流程);Dockerfile 中按架构安装各 DB 客户端工具(pg_dump、mysqldump/mariadb、mongodump、redis-cli)。

## 15. 测试策略

- **Service / Adapter 层单测**(pytest):核心业务逻辑与每种适配器的命令构造、参数安全。
- **Adapter 契约测试**:用 testcontainers 起真实 PG/MySQL/Mongo/Redis 容器,验证 dump→restore 往返一致。
- **API 集成测试**(FastAPI TestClient):覆盖鉴权、关键端点、job 投递。
- **安全测试**:验证未登录访问被拒、注入/路径穿越被拦截、子进程无 shell。

## 16. 风险与对策

| 风险 | 对策 |
|---|---|
| 单容器内多进程复杂度 | supervisord 成熟稳定;进程崩溃自动重启;日志统一收集 |
| Redis 数据丢失 | 开启 AOF/RDB 持久化到 `/data` 卷;job 状态以 SQLite 为准 |
| 新增 DB 类型客户端安装增大镜像 | 多阶段构建 + 按架构选择轻量客户端;清理缓存 |
| 云上传大文件不稳 | 分块 + 断点续传 + 指数退避;失败可重试 |
| 重写工作量大 | 分阶段交付(见实现计划):脚手架 → 核心备份 → 恢复 → 云同步 → 仪表盘 → 打磨 |

## 17. 未来扩展(本轮不做)

增量/差异备份;多用户/RBAC;Webhook 通知通道;备份加密(gpg);监控告警集成(Prometheus)。

---

*本文档由 brainstorming 流程产出,下一步进入 writing-plans 制定实现计划。*
