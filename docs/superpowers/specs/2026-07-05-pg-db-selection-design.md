# PostgreSQL 数据库选择备份 — 设计文档

- 日期：2026-07-05
- 状态：已评审，待实现
- 适用代码库：db-backup-agent（FastAPI + Vue 3 / Naive UI 重写版，main 分支）

## 1. 背景与目标

当前一条「数据库连接」固定绑定**单个** `db_name`，备份时直接 dump 这个库。用户希望：对 PostgreSQL，输入连接凭证后能**列出该 PG 用户可备份的所有库**，让用户**多选**若干库，由系统逐一备份。

为此一并明确各类型行为：

- **PostgreSQL**：在新建/编辑连接时拉取库列表、多选；每次备份为每个选中库各产出一条记录、一个文件。
- **MySQL**：默认**全库备份**（`mysqldump --all-databases`），无需选择。
- Mongo / Redis / SQLite：维持现状。

## 2. 核心决策

| 决策点 | 结论 |
|---|---|
| 选择时机 | 新建/编辑连接时多选；不在备份时选 |
| 备份粒度 | 每个选中库一条 BackupRecord + 一个 `.sql.gz`，互相独立、可独立失败、独立保留 |
| 多库名存储 | 新增 `db_names` JSON 数组列（方案 A） |
| MySQL | 不做选择；适配器改用 `--all-databases` |

## 3. 范围

**本期实现：**
- PG `list_databases` 适配器方法 + 多选 UI。
- 多库连接的数据模型与迁移。
- 备份执行流程改造为「一次触发 → 逐库多条记录」。
- MySQL `--all-databases`。
- 前端连接表单按类型分流、Backups 适配多记录、History 展示库名、Restore 按 record.db_name 恢复。

**不做（YAGNI）：**
- MySQL / Mongo / Redis / SQLite 的库选择（MySQL 直接全库）。
- 多库触发的通知汇总（v1 per-record 通知，日后可聚合）。
- 实时进度流的多库聚合（v1 保持按 record）。

## 4. 数据模型与迁移

### 4.1 表结构变更

`DbConnection`（`app/db/models.py`）：
- 新增 `db_names`（Text，nullable，存 JSON 数组字符串，如 `["app","logs"]`）。
- **保留** `db_name` 列以兼容旧路径。读取统一走 helper：优先 `db_names`，为空回退 `db_name`。

`BackupRecord`（`app/db/models.py`）：
- 新增 `db_name`（String(128)，nullable），固化「本条记录备份的具体库」。MySQL 全库 / 旧记录为 null。

### 4.2 迁移

启动迁移（`migrate_db`）：对每条 `DbConnection`，若 `db_names` 为空且 `db_name` 非空，写入 `json.dumps([db_name])`。

### 4.3 Schema（`app/schemas/connection.py`）

- `ConnectionBase`：接收 `db_names: list[str] | None`。
- `ConnectionOut`：暴露 `db_names: list[str]`（由存储的 JSON 解析；旧连接回退为 `[db_name]` 或 `[]`）。

## 5. 适配器层（`app/adapters/`）

### 5.1 PostgreSQL（`postgres.py`）

新增鸭子类型方法（镜像现有 `test()` 约定，**不**进 `BackupAdapter` Protocol）：

```python
def list_databases(self, info: ConnectionInfo, *, is_cancelled=None) -> list[str]:
    # 连维护库 → SELECT datname FROM pg_database
    #   WHERE datistemplate = false AND datallowconn ORDER BY 1
```

要点：
- PG 必须「连到某个库」才能查询。默认连维护库 `postgres`，连不上回退 `template1`，仍失败抛错（前端提示检查用户对维护库的 CONNECT 权限）。
- 现有 `run_subprocess` 只抓 stderr 不返回 stdout，需新增能**捕获 stdout** 的轻量 helper（或直接 `subprocess.run(capture_output=True)`）。
- 密码仅走 `PGPASSWORD` 环境变量，绝不进 argv（与 `dump`/`test` 一致）。
- 参考实现：`legacy/app.py`（约 1935–2003 行）。

### 5.2 MySQL（`mysql.py`）

`argv()`：当无具体 `db_name` 时输出 `--all-databases`（替代位置参数 db_name）。已有带 db_name 的旧连接保持原行为（仍备份那个库），新连接走全库。

### 5.3 其它

Mongo / Redis / SQLite 的 `list_databases` 抛 `NotImplementedError`（与各自 `test()` 现状一致）。

## 6. 服务层（`app/services/connection_service.py`）

- `list_databases_for_payload(payload) -> list[str]`：**保存前**，用表单明文凭证构造 `ConnectionInfo` 调适配器（新建态用）。
- `list_databases_for_connection(db, crypto, conn_id) -> list[str]`：**保存后**，解密已存密码调用（编辑态密码未改时用）。

> 安全：保存前端点传明文密码，但与现有 `create_connection`（创建时也是明文上传再服务端 Fernet 加密）同一通道，不引入新暴露面。

## 7. API 层（`app/routers/connections.py`）

两个端点，均 `Depends(get_current_account)`，失败返回 400 + 错误信息（克隆现有 `/test`）：

- `POST /api/v1/connections/list-databases`，body `{type, host, port, username, password, db_name?}` → `{"databases": [...]}`
- `POST /api/v1/connections/{conn_id}/databases` → `{"databases": [...]}`

## 8. 备份执行流程

核心：**一次触发 = 一个 arq 任务循环遍历所有选中库**，整个循环持有一把连接级锁，逐库创建/更新各自的 BackupRecord。

### 8.1 共用入队 helper

新增 `backup_service.enqueue_backup(db, conn, trigger) -> list[int]`（返回 record id 列表），供 `run_now` 与 scheduler 共用：

1. 解析要备份的库列表：
   - PG → `conn.db_names`
   - MySQL → `[None]`（全库，一条记录）
   - 其它/旧连接 → `[db_name]`（兼容）
2. 为每个库**预先建一条 BackupRecord**（`status='running'`，`db_name` 写对应名 / MySQL 留空）。
3. 检查连接级锁（`has_running_backup`），运行中 → 409。
4. 入队**一个** arq 任务：`backup_job(connection_id, [record_id, ...])`。

### 8.2 `run_now` 返回值

```json
{ "connection_id": 7, "record_ids": [101,102,103],
  "records": [{"record_id":101,"db_name":"app","status":"running"}, ...] }
```

### 8.3 Worker

`backup_job(ctx, connection_id, record_ids: list[int])`——签名统一为列表（单库连接即长度 1）：

1. 获取连接级锁，覆盖整个循环。
2. 逐 record：取其 `db_name` → 构造 `ConnectionInfo`（用该 db_name 覆盖）→ `adapter.dump` → 标记成功/失败。
3. 单库失败 try/except 不中断其它库。
4. 释放锁；按 record 触发通知 / 保留期清理（沿用现有逻辑）。

### 8.4 `run_backup`

增加可选 `db_name` 参数覆盖 `conn.db_name`；MySQL 传 `None` 时适配器输出 `--all-databases`。

### 8.5 连带改动

- arq 入队从 `(conn.id, record.id)` → `(conn.id, [record.id])`；`test_jobs*.py` 同步更新。
- SSE / 实时进度 v1 保持按 record；前端拿到 `record_ids` 后逐条开流或刷新列表。

## 9. 前端

### 9.1 `api/connections.ts`

```ts
listDatabases(payload)                  // POST /connections/list-databases
listDatabasesForConnection(id)          // POST /connections/{id}/databases
```
`Connection` 类型加 `db_names: string[]`；`ConnectionPayload` 接收 `db_names`。

### 9.2 `Connections.vue`

- `type === 'pg'`：`db_name` 自由文本框 → **`n-select multiple filterable`**（带 `loading`）+ 旁置「拉取数据库列表」按钮（沿用 CloudSync「测试」UX）。
  - 点击：新建态 `listDatabases(form)`；编辑态密码非空 `listDatabases(form)`，密码为空 `listDatabasesForConnection(editing.id)`。
  - 成功填充选项并保留已选交集；失败 `msg.error`，可改凭证重试。
  - 选中值绑定 `form.db_names`。
- `type === 'mysql'`：隐藏选择控件，显示静态说明「MySQL 默认备份全部数据库」，`db_names` 提交为空。
- 其它类型维持现状。

### 9.3 `Backups.vue`

`runNow` 适配新返回：拿到 `record_ids` 数组，提示「已创建 N 条备份任务」，刷新列表见多条 running。

### 9.4 `History.vue`

BackupRecord 新增 `db_name` 列展示（如 `连接名 · 库名`，MySQL 显示「全部」）。

### 9.5 `Restore.vue` / restore 流程

恢复用**备份记录自身的 `db_name`**作为目标库（而非目标连接的 db_name）；MySQL 全库 dump 整体恢复。Schedule 仍只绑 `connection_id`，无需改动。

## 10. 测试

后端（pytest + monkeypatch subprocess）：

- **`test_adapters.py`**
  - `test_pg_list_databases_argv`：psql 跑正确查询、密码只在 `PGPASSWORD`、维护库回退。
  - `test_mysql_dump_uses_all_databases_when_no_dbname`。
  - `test_list_databases_unsupported_types`（mongo/redis/sqlite 抛 `NotImplementedError`）。
- **`test_connections.py`**（克隆 `/test` 用例）
  - 保存前端点：成功 / 失败 400 / 不支持类型。
  - 保存后端点：成功 / 失败 400。
- **`test_backup_service.py`**
  - `enqueue_backup` 对 PG 多库连接建 N 条 record（各带 db_name）。
  - `backup_job` 逐 record dump、单库失败不中断。
  - MySQL 连接 → 单条 record、`--all-databases`。
- **`test_jobs_api.py`**：`run_now` 多库返回 `record_ids` 数组。
- **迁移测试**：旧 `db_name='x'` 连接启动后 `db_names == ['x']`。

前端：无单测框架，用 run/webapp-testing 技能手动验证（PG 拉列表多选、MySQL 全库、多库备份产多文件、按库名展示、按 record.db_name 恢复）。

## 11. 关键文件清单

后端：
- `app/adapters/postgres.py`、`app/adapters/mysql.py`、`app/adapters/base.py`
- `app/services/connection_service.py`、`app/services/backup_service.py`、`app/services/scheduler.py`
- `app/routers/connections.py`、`app/routers/jobs.py`
- `app/schemas/connection.py`、`app/schemas/job.py`
- `app/db/models.py`、迁移入口
- `app/workers/jobs.py`

前端：
- `frontend/src/api/connections.ts`
- `frontend/src/views/Connections.vue`、`Backups.vue`、`History.vue`、`Restore.vue`

测试：
- `tests/test_adapters.py`、`tests/test_connections.py`、`tests/test_backup_service.py`、`tests/test_jobs_api.py`
