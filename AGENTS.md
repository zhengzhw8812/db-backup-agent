# AGENTS.md — 项目导航

本文件为 AI 编码工具与开发者提供本仓库的工作指引。

## 项目概述

**db-backup-agent** 是一个自部署的数据库备份管理工具:单容器运行,提供 Web 界面管理数据库连接、备份计划、备份历史、恢复、云同步与通知。当前为 v3 架构(前端单页应用 + FastAPI 后端)。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 API | FastAPI + Uvicorn,SessionMiddleware 会话认证 |
| ORM / 数据库 | SQLAlchemy 2.0 + SQLite(`$APP_DATA_DIR/sqlite/app.db`) |
| 定时调度 | APScheduler(AsyncIOScheduler,进程内 cron) |
| 任务队列 | arq + Redis(备份/恢复/云同步任务,进度经 Redis pub/sub 推送) |
| 云同步 | MinIO SDK(S3 兼容:MinIO / AWS S3 / R2 / B2) |
| 凭据加密 | cryptography Fernet(密钥首启生成,持久化于 `$APP_DATA_DIR/keys/`) |
| 前端 | Vue 3 + TypeScript + Naive UI + Pinia + Vue Router + ECharts + Vite |

## 常用命令

```bash
# 后端本地开发(仓库根)
pip install -e ".[dev]"                 # 安装依赖(pyproject.toml,无 requirements.txt)
uvicorn app.main:app --port 8000        # 启动 API(同时托管已构建的前端静态文件,若有;容器内由 supervisord 固定 8000)

# 前端(frontend/ 目录下)
npm ci && npm run dev                   # Vite 开发服务器
npm run build                           # vue-tsc 类型检查 + 构建产物 dist/

# 测试(仓库根)
pytest                                  # 全量测试,提交前必须全绿

# Docker(仓库根)
docker compose up -d --build            # 构建+运行(端口 8000:8000,数据卷 ./data:/data)
```

配置经环境变量(`APP_` 前缀)注入,完整清单见 `.env.example`:`APP_DATA_DIR`、`APP_REDIS_URL`、`APP_SECRET_KEY`/`APP_FERNET_KEY`(成对提供,否则首启自动生成)、`APP_INITIAL_ADMIN_USER/PASSWORD`、`APP_SCHEDULER_ENABLED`(多进程部署时只允许一个进程开启)、`APP_COOKIE_SECURE`。## 目录结构

```
app/                    后端(Python 包)
├── main.py             create_app:路由注册、SPA 托管、lifespan(启动迁移/调度器)
├── config.py           pydantic-settings,APP_ 前缀环境变量
├── bootstrap.py        首启密钥生成与原子持久化
├── routers/            API 路由(auth/connections/jobs/backups/schedules/
│                        dashboard/restore/cloud/settings/logs/health,_sse.py 为 SSE 流)
├── schemas/            Pydantic 请求/响应模型
├── services/           业务逻辑(backup/restore/sync/schedule/scheduler/
│                        locks/maintenance/notifications/retention/account/dashboard/connection)
├── workers/            arq 任务定义(jobs.py)、WorkerSettings(app.py)、
│                        进度上报与取消标志(progress.py,Redis pub/sub)
├── adapters/           数据库适配器:postgres/mysql/mongodb/redis_db/sqlite_db,
│                        统一走 base.py 的 run_subprocess(超时+取消+stderr 捕获)
├── cloud/              云存储适配器(base.py 注册制 + s3.py,含指数退避重试)
├── core/               横切工具:crypto(Fernet)、archive(压缩+哈希)、
│                        auth/security、fsutil(安全删除)
└── db/                 models.py(SQLAlchemy 模型)、session.py(引擎与会话)

frontend/               前端(Vue 3 + TS)
└── src/
    ├── views/          页面:Dashboard/Connections/Schedules/Backups/History/
    │                   Restore/CloudSync/Logs/Settings/Login
    ├── api/            后端 API 客户端(axios 封装 client.ts)
    ├── stores/         Pinia(auth/theme)
    ├── composables/    useJobStream(SSE 进度流)/useTheme
    └── layouts/ router/ themes/

deploy/                 容器进程配置(supervisord: redis + uvicorn + arq worker)
tests/                  pytest 全量测试(30 个文件,FastAPI TestClient + 单元测试)
docs/specs/             设计文档
```

## 备份数据流

1. **触发**:APScheduler cron 到点或 Web API 手动触发 → 为连接的每个待备份库各建一条 `running` BackupRecord → 经 arq 入队 `backup_job`;
2. **互斥**:同连接已有 `running` 记录则跳过本轮(计划触发记 SystemLog);
3. **执行**:arq worker 在线程池中解密连接凭据 → 按库类型调用适配器 dump(`pg_dump`/`mysqldump`/`mongodump` 等)→ gzip 压缩并边写边算校验和;
4. **进度/取消**:各阶段经 Redis pub/sub 上报(前端 SSE 消费),取消标志写入 Redis,执行间隙轮询;
5. **收尾**:更新记录终态(success/failed/cancelled,含耗时)→ 保留期清理(删过期文件+记录)→ 通知(邮件/企业微信)→ 云同步(上传至启用的 S3 目标)。通知与保留清理失败不影响备份结果。

**崩溃恢复**:启动时把残留的 `running` 备份/恢复记录翻转为 failed(`maintenance.reap_stale_running`);子进程有强制超时,防止 DB 不可达时永久挂起。

## 测试与提交约定

- 提交前 `pytest` 全绿;测试遵循 TDD(先写失败测试再实现);
- API 测试模式见 `tests/conftest.py`(`client` fixture,`APP_DATA_DIR` 指向临时目录)与 `tests/test_jobs_api.py` 的 `authed` fixture;
- 提交信息:中文,follow 现有 `type(scope): 描述` 风格(type ∈ feat/fix/refactor/docs/chore/test/ci);
- 改动 schema 时检查 `app/services/maintenance.py` 的启动时补列机制(`create_all` 不会给已存在的表加列)。
