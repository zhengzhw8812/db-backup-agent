# v3 清理收尾与稳定性加固设计

- **日期**: 2026-10-01
- **状态**: 待审阅
- **命名约定**: 本文档与后续全部提交信息、计划文档均不出现外部 AI 工具品牌词,统一以"AI 助手"指代;被删除文件按其角色指代(如"旧 AI 导航文件")。这是验收标准(第 8 节)的直接要求。

## 1. 背景

本仓库经历过一轮 v2(Flask 单体)→ v3(FastAPI + Vue 3)的完整重写,当前是"双栈并存"状态:

- 实际部署链路(Dockerfile)只打包 `app/`、`frontend/`、`deploy/`、`pyproject.toml`;
- 根目录仍残留 v2 的 7 个后端模块、旧前端(`templates/`、`static/`)、旧脚本(`scripts/`)、`legacy/`、`requirements.txt`,全部为死代码(经 `grep` 核实新栈零引用);
- `docs/superpowers/`(3 份 spec + 13 份 plan)与根目录旧 AI 导航文件带有 AI 助手署名痕迹;
- 另一根目录 AI 导航文件(文件名本身即品牌痕迹,故不写出)内容仍描述 v2 架构,已完全过时;
- `README.md` 停留在 v2:更新日志止于 v2.3,无任何 v3 内容;
- 代码审查(2026-10-01)发现 6 项稳定性弱点(见第 6 节);
- 测试基线:179 个测试全部通过(Python 3.14 本地,17s)。

## 2. 目标

1. 仓库只保留 v3 单一架构,删除全部 v2 死代码;
2. 彻底清除 AI 助手署名痕迹(工作区 + git 历史);
3. 以 v3 实际代码为准重写导航文档与 README;
4. 完成稳定性加固(不改变功能行为);
5. 清理/加固全程由测试守护,最终交付可构建、可测试、历史干净的单栈仓库。

### 非目标

- 不改变任何功能行为(备份/恢复/通知/云同步逻辑不动);
- 不移除 Redis/arq(架构决策:已建成且被测试覆盖,重写风险大于收益);
- 不引入 Alembic、不更换数据库、不修改前端功能代码;
- 不重拍界面截图(旧截图与新 UI 不符,README 暂不放截图,`Images/` 目录保留)。

## 3. 文件清理清单

### 删除(全部核实为 v2 死代码或署名痕迹)

| 目标 | 说明 |
|---|---|
| 根目录 7 个旧模块 | `config_manager.py`、`backup_lock.py`、`backup_logger.py`、`db_init.py`、`migrate_db.py`、`notifications.py`、`system_logger.py` |
| `requirements.txt` | v2 Flask 依赖清单;镜像构建实际使用 `pyproject.toml` |
| `legacy/` | v2 单体 `app.py` 的残骸 |
| `templates/`、`static/` | v2 Jinja2 前端 |
| `scripts/` | v2 cron 备份脚本(`backup.sh`、`entrypoint.sh`、`backup备份.sh`) |
| `docs/superpowers/` | 历史设计/计划文档,含署名痕迹 |
| 旧 AI 导航文件(根目录) | 内容描述 v2 架构,已过时 |
| `.gitignore` 中 `.superpowers/` 行 | 工作流痕迹 |

### 修改

| 文件 | 改动 |
|---|---|
| `.dockerignore` | 删除 AI 助手配置目录的忽略行(其余保留;`.github`、`docs` 等忽略规则仍正确) |
| `.gitignore` | 删除 `.superpowers/` 行 |

### 保留不动

`app/`、`frontend/`、`tests/`、`deploy/`、`pyproject.toml`、`Dockerfile`、`docker-compose.yml`、`build_and_push.sh`、`Images/`、`.env.example`、`.gitignore`(除上述行)、`.dockerignore`(除上述行)。

## 4. 新增 AGENTS.md(工具中立的项目导航)

全部内容基于 v3 实际代码重写,不沿用旧导航文件的任何段落:

1. **项目概述**: 自部署数据库备份管理工具,单容器运行;
2. **技术栈**: 后端 FastAPI + SQLAlchemy 2 + SQLite + APScheduler(进程内 cron)+ arq(Redis 队列,备份/恢复/同步任务)+ MinIO SDK(S3 云同步);前端 Vue 3 + TypeScript + Naive UI + Pinia + ECharts + Vite;
3. **目录结构表**: `app/` 下 `routers/`(API 路由)、`schemas/`(Pydantic 模型)、`services/`(业务逻辑)、`workers/`(arq 任务与进度上报)、`adapters/`(5 种数据库 dump/restore 适配器)、`cloud/`(S3 兼容存储适配器)、`core/`(加密、压缩、文件工具)、`db/`(模型与会话);`frontend/src/` 与 `deploy/` 概述;
4. **常用命令**: 本地后端(`pip install -e ".[dev]"`、`uvicorn app.main:app`)、前端(`npm run dev` / `build`)、测试(`pytest`)、Docker 构建;
5. **备份数据流**: 调度器/API 建记录 → arq 入队 → worker 线程执行 → 适配器 dump → 压缩+校验 → 保留清理 → 通知 → 云同步;互斥(连接级 running 检查)、取消(Redis 标志)、SSE 进度推送;
6. **测试约定**: `tests/` 全量 FastAPI TestClient + 单元测试,提交前必须全绿;
7. **配置**: `.env.example` 中 `APP_` 前缀环境变量说明。

## 5. 重写 README

- **功能列表按 v3 代码实况**: 5 种数据库(PostgreSQL/MySQL/MongoDB/Redis/SQLite)、计划+手动备份、连接级互斥、保留策略、备份恢复、S3/MinIO 云同步、邮件+企业微信通知、单管理员账号(argon2 哈希)、SSE 实时进度、仪表盘、amd64+arm64 镜像;
- **快速开始**: docker-compose 拉取 `tony5188/db-backup-agent:latest`,保留原有结构但更新为 v3(端口、卷、首次登录);
- **本地开发**: 简述并指向 AGENTS.md;
- **更新日志**: 顶部新增 v3.0.0 条目(全栈重写:FastAPI/Vue 3/任务队列/云同步/恢复),v2 日志作为项目历史保留;
- **不放界面截图**(旧截图对应 v2 UI)。

## 6. 稳定性加固项

### H1 SQLite 并发加固(P1)

`app/db/session.py` 的 sqlite connect 事件中追加:

- `PRAGMA journal_mode=WAL` — 读写不互斥,消除"备份进行中页面卡死"类锁冲突;
- `PRAGMA busy_timeout=5000` — 写锁等待 5s 而非立刻报 `database is locked`;
- `PRAGMA synchronous=NORMAL` — WAL 下安全的持久化折中,减少 fsync 开销。

测试:断言连接后 `journal_mode` 为 `wal`。

### H2 SSE 竞态修复(P1)

`app/routers/_sse.py`:当前先读 DB 状态再订阅 Redis;若任务恰在两步之间结束,终态事件丢失,前端永久挂起。修复:**先订阅、再读 DB 补初始事件**。订阅后任务结束,终态消息会缓存在 pubsub 队列中,listen 循环必然收到;"订阅前已终态"由 DB 状态兜底,两条路径不再有缝隙。

测试:模拟"DB 为 running、终态消息已发布"的时序,断言流能收到终态并结束。

### H3 调度器兜底分支检查(已核实为误报,无代码改动)

`app/services/scheduler.py:run_scheduled_backup` 实施时逐行核实:`record_ids` 在第一个 try/finally(建记录)中赋值,仅被第二个 try/except(队列投递失败翻转记录)引用;后者只在前者完全成功后可达,不存在"引用未初始化变量"的路径。原审计误读了控制流。该函数的既有行为(入队前异常原样传播、投递失败翻转记录后 re-raise)本身正确,以测试守护既有行为,无代码改动。

### H4 `datetime.utcnow()` 全量迁移(P2)

后端 + 测试共 263 处弃用警告(Python 3.12 起弃用,Docker 运行时正是 3.12)。新增 `app/core/clock.py` 提供 `utcnow()`(实现为 `datetime.now(timezone.utc).replace(tzinfo=None)`),全仓替换。

**关键决策**: 返回 naive UTC——存储格式与既有 SQLite 数据完全一致,零迁移、比较逻辑不变;aware 化涉及历史数据回填,收益低风险高,列为未来可选项。

### H5 GitHub Actions CI(P2)

新增 `.github/workflows/ci.yml`,push/PR 触发:

- **backend**: Python 3.12(与镜像一致)→ `pip install -e ".[dev]"` → `pytest`;
- **frontend**: Node 20 → `npm ci` → `npm run build`(含 vue-tsc 类型检查)。

### H6 健康检查增强(P3)

`app/routers/health.py` 返回结构化状态:`{status: "ok"|"degraded", components: {db, redis, scheduler}, version}`。DB 执行 `SELECT 1`,Redis ping,scheduler 读进程内运行标志。保持免认证(docker healthcheck 依赖),只返回布尔状态不泄露细节。同步更新 `tests/test_health.py`。

## 7. 执行顺序

1. **基线**: 已完成 — pytest 179 全绿(2026-10-01,Python 3.14);
2. **commit A**: 文件清理(第 3 节全部)→ pytest 全绿(证明删的是死代码);
3. **commit B**: AGENTS.md 新增 + README 重写;
4. **commit C1..C6**: 加固项逐项提交(H1..H6,每项带测试);
5. **全量验证**: pytest 全绿 + `npm run build` 成功 + `docker build` 成功;
6. **历史清除**(最后执行):
   a. `git bundle create ~/db-backup-agent-pre-purge.bundle --all`(仓库外备份,**绝不推送**);
   b. `git filter-repo --invert-paths` 清除第 3 节全部删除路径(含旧 AI 导航文件与 `docs/superpowers/`),并用 `--replace-message` 将历史中一条含品牌词的提交信息改写为等价的无品牌词表述;
   c. 重建 `origin` remote(filter-repo 会移除),`push --force` main(仓库无 tag,仅 main 一条分支);
   d. 终检:全历史 `git grep -i` + 工作区 grep 零命中。

## 8. 验收标准

1. `pytest` 全绿(含新增测试,数量 ≥ 179);
2. `npm run build` 成功;`docker build` 成功(证明镜像不依赖任何被删文件);
3. 工作区与全部历史中,第 1 节命名约定所述的外部 AI 工具品牌词(大小写不敏感)零命中;
4. GitHub main 与本地一致,删除路径在 GitHub UI 不可见;
5. README 与 AGENTS.md 中每条命令实际可执行;
6. 功能行为不变:与加固项无关的既有测试不改断言即通过;H2/H3/H6 涉及的既有测试按新行为更新后通过。

## 9. 风险与回滚

| 风险 | 缓解 |
|---|---|
| filter-repo 改写全部 commit hash,已有 clone 失效 | 已获用户确认;bundle 备份可随时恢复 |
| GitHub 服务端在 gc 前旧 commit 或可按 SHA 直访 | 仓库为个人私有库,风险可接受;如需彻底可后续联系 GitHub 支持 gc |
| 加固项引入回归 | 逐项独立提交,每项带测试,179 项既有测试守护 |
| UTC 迁移改变存储格式 | 采用 naive UTC 方案,存储零变化 |

**回滚路径**: `git clone ~/db-backup-agent-pre-purge.bundle` 恢复到清理前状态。
