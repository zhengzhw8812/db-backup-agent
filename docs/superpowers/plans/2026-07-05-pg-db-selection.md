# PostgreSQL 数据库多选备份 + MySQL 全库备份 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PostgreSQL 连接在新建/编辑时拉取并多选要备份的库（每次触发为每个库各产出一条记录、一个文件）；MySQL 默认全库备份。

**Architecture:** `DbConnection` 新增 `db_names`（JSON 数组），`BackupRecord` 新增 `db_name`（固化每条记录的库）。新增 `PostgresAdapter.list_databases`（psql 查 `pg_database`）+ 两个列出库的 HTTP 端点（保存前/保存后）。备份触发统一走 `enqueue_backup`：解析库列表 → 每库一条 running 记录 → 入队单个 `backup_job(conn_id, [record_ids])`，worker 逐库 dump，单库失败不中断。MySQL 适配器无 db_name 时输出 `--all-databases`。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + arq + Pydantic v2（后端）；Vue 3 + Naive UI + axios（前端）；pytest（测试）。

**Spec:** `docs/superpowers/specs/2026-07-05-pg-db-selection-design.md`

---

## 关键约定（全计划保持一致）

- `db_names`：`DbConnection` 上的 `Text` 列，存 JSON 数组字符串（如 `["app","logs"]`）；空/NULL 表示未设置。
- `db_name`（`BackupRecord` 上，新增）：本条记录备份的具体库；MySQL 全库 / 旧记录为 NULL。
- 解析库列表的单一来源是 `backup_service._resolve_db_names(conn)`，`run_now` 与 `scheduler.run_scheduled_backup` 都通过 `enqueue_backup` 调用它。
- `backup_job` 的 arq 入队签名统一为 `("backup_job", connection_id, record_ids: list[int])`。
- 前端 mock 目标：`app.services.connection_service.get_adapter`（连接层）、`app.services.backup_service.get_adapter`（备份层）、`app.adapters.base.subprocess.Popen`（适配器层）。

---

## Task 1: 数据模型 + 启动迁移

**Files:**
- Modify: `app/db/models.py`（`DbConnection` 加 `db_names`；`BackupRecord` 加 `db_name`）
- Modify: `app/services/maintenance.py`（新增 `migrate_schema`）
- Modify: `app/main.py`（`lifespan` 调用 `migrate_schema`）
- Test: `tests/test_maintenance.py`（已存在，追加 `migrate_schema` 回填用例）

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_maintenance.py` 末尾

```python
def test_migrate_schema_backfills_db_names(tmp_path, monkeypatch):
    """旧连接(只有 db_name,无 db_names)启动迁移后应回填 db_names=['<db_name>']。"""
    from app.db import session as _session
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection
    from app.core.crypto import Crypto
    from cryptography.fernet import Fernet
    from app.services.maintenance import migrate_schema
    import json

    init_engine(f"sqlite:///{tmp_path/'m.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        crypto = Crypto(Fernet.generate_key())
        c = DbConnection(name="legacy", type="pg", host="h", port=5432,
                         db_name="legacydb", username="u",
                         password_enc=crypto.encrypt("pw"), db_names=None)
        db.add(c); db.commit(); db.refresh(c)

        migrate_schema(db)
        db.refresh(c)
        assert json.loads(c.db_names) == ["legacydb"]
    finally:
        db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_maintenance.py::test_migrate_schema_backfills_db_names -x`
Expected: FAIL — `migrate_schema` 不存在（ImportError 或 AttributeError）。

- [ ] **Step 3: 改模型** — `app/db/models.py`

在 `DbConnection` 内、`db_name` 行之后加：

```python
    db_names: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组,如 ["app","logs"];PG 多选
```

在 `BackupRecord` 内、`trigger` 行之后加：

```python
    db_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 本记录备份的具体库;MySQL 全库/旧记录为 NULL
```

- [ ] **Step 4: 实现 `migrate_schema`** — `app/services/maintenance.py`

在文件顶部 import 区追加（与已有 import 合并，勿重复）：

```python
import json
from sqlalchemy import text
from app.db.models import DbConnection
```

在 `reap_stale_running` 之前新增三个函数：

```python
def _ensure_column(db: Session, table: str, column: str, ddl: str) -> None:
    """SQLite 的 create_all 不会给已存在的表加列;用 PRAGMA 探测后补 ALTER。"""
    cols = [row[1] for row in db.execute(text(f"PRAGMA table_info({table})"))]
    if column not in cols:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        db.commit()


def _backfill_db_names(db: Session) -> None:
    """旧连接(只有 db_name)回填 db_names=['<db_name>'];幂等。"""
    for c in db.query(DbConnection).all():
        if not c.db_names and c.db_name:
            c.db_names = json.dumps([c.db_name])
    db.commit()


def migrate_schema(db: Session) -> None:
    """启动时补齐 db_connections.db_names / backup_records.db_name 两列并回填。"""
    _ensure_column(db, "db_connections", "db_names", "TEXT")
    _ensure_column(db, "backup_records", "db_name", "TEXT")
    _backfill_db_names(db)
```

> 若 `Session` 未在 maintenance.py 顶部 import，在 import 区加 `from sqlalchemy.orm import Session`。

- [ ] **Step 5: 在 `lifespan` 接入** — `app/main.py`

把 `lifespan` 开头改为（在 `reap_stale_running` 之前先迁移 schema）：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时补齐新列/回填,再清理上次崩溃残留的 running 记录
    from app.services.maintenance import migrate_schema, reap_stale_running
    from app.db.session import get_db
    db = next(get_db())
    try:
        migrate_schema(db)
        reap_stale_running(db)
    finally:
        db.close()
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_maintenance.py -x`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add app/db/models.py app/services/maintenance.py app/main.py tests/test_maintenance.py
git commit -m "feat(model): db_names/db_name 列 + 启动迁移回填"
```

---

## Task 2: 连接 schema 加 db_names

**Files:**
- Modify: `app/schemas/connection.py`

- [ ] **Step 1: 改 schema** — `app/schemas/connection.py`

`ConnectionBase` 加字段（在 `db_name` 行之后）：

```python
    db_names: list[str] | None = None
```

`ConnectionOut` 加字段（在 `db_name` 行之后）：

```python
    db_names: list[str]
```

> `ConnectionOut.db_names` 是必填（序列化时恒有值，由路由层的 `_db_names_of` 计算得出，见 Task 3）。

新增「列出库」专用的探测 schema（不要求 name，区别于 ConnectionBase）：

```python
class ConnectionProbe(BaseModel):
    """列出可备份库的请求体:只需连接凭证,不需要 name。"""
    type: str = Field(..., pattern="^(pg|mysql|mongo|redis|sqlite)$")
    host: str | None = None
    port: int | None = Field(None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    db_name: str | None = None
```

- [ ] **Step 2: 暂不单独跑测试**（路由 serialize 在 Task 3 改完后整体验证）

- [ ] **Step 3: 暂不提交**（与 Task 3 一起提交，避免中间态 `_serialize` 不输出 `db_names` 导致 schema 校验失败）

---

## Task 3: connection_service 存读 db_names + 路由 serialize

**Files:**
- Modify: `app/services/connection_service.py`
- Modify: `app/routers/connections.py`
- Test: `tests/test_connections.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_connections.py`

```python
def test_create_pg_connection_persists_db_names(authed):
    body = {"name": "pg1", "type": "pg", "host": "h", "port": 5432,
            "username": "u", "password": "secret", "db_names": ["app", "logs"]}
    r = authed.post("/api/v1/connections", json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["db_names"] == ["app", "logs"]


def test_list_db_names_falls_back_to_db_name(authed):
    """旧连接(只存 db_name)的 ConnectionOut.db_names 应回退为 [db_name]。"""
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        db.add(DbConnection(name="old", type="pg", db_name="legacy"))
        db.commit()
    finally:
        db.close()
    r = authed.get("/api/v1/connections")
    row = next(c for c in r.json() if c["name"] == "old")
    assert row["db_names"] == ["legacy"]


def test_update_connection_db_names(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "db_names": ["a"]}).json()["id"]
    r = authed.put(f"/api/v1/connections/{cid}", json={"db_names": ["a", "b"]})
    assert r.json()["db_names"] == ["a", "b"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_connections.py::test_create_pg_connection_persists_db_names -x`
Expected: FAIL — `db_names` 未被持久化/返回（返回值缺失或为 null）。

- [ ] **Step 3: 改 `create_connection`** — `app/services/connection_service.py`

在 `create_connection` 内的 `DbConnection(...)` 构造里，`db_name=data.db_name,` 行之后加：

```python
        db_names=json.dumps(data.db_names) if data.db_names else None,
```

- [ ] **Step 4: 改 `update_connection`** — 同文件

把字段循环之后的 `if data.extra is not None:` 块之前，插入 db_names 处理（db_names 是 list，需 JSON 编码，不能走通用 setattr 循环）：

```python
    if data.db_names is not None:
        c.db_names = json.dumps(data.db_names) if data.db_names else None
```

- [ ] **Step 5: 改路由 serialize** — `app/routers/connections.py`

在 `_serialize` 之前新增 helper：

```python
def _db_names_of(c) -> list[str]:
    """优先 db_names(JSON);为空回退到旧 db_name;再为空返回 []。"""
    if c.db_names:
        try:
            names = json.loads(c.db_names)
            if names:
                return names
        except (TypeError, ValueError):
            pass
    if c.db_name:
        return [c.db_name]
    return []
```

把 `_serialize` 改为（新增 `db_names=...` 一行）：

```python
def _serialize(c) -> ConnectionOut:
    return ConnectionOut(
        id=c.id, name=c.name, type=c.type, host=c.host, port=c.port,
        db_name=c.db_name, db_names=_db_names_of(c),
        username=c.username,
        extra=json.loads(c.extra) if c.extra else None, created_at=c.created_at,
    )
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_connections.py -x`
Expected: PASS（含新三条 + 既有用例）。

- [ ] **Step 7: 提交**

```bash
git add app/schemas/connection.py app/services/connection_service.py app/routers/connections.py tests/test_connections.py
git commit -m "feat(connection): db_names 读写 + 序列化回退"
```

---

## Task 4: base.py 新增 run_subprocess_capture

**Files:**
- Modify: `app/adapters/base.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_adapters.py`

```python
def test_run_subprocess_capture_returns_stdout(monkeypatch):
    """list_databases 需要 stdout;capture 变体应返回解码后的 stdout 文本。"""
    import app.adapters.base as base

    class OkProc:
        returncode = 0
        stderr = None
        stdout = __import__("io").BytesIO(b"app\nlogs\n")
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: OkProc())
    out = base.run_subprocess_capture(["psql"])
    assert out == "app\nlogs\n"


def test_run_subprocess_capture_raises_on_nonzero(monkeypatch):
    import app.adapters.base as base

    class BoomProc:
        returncode = 2
        stderr = __import__("io").BytesIO(b"auth failed")
        stdout = __import__("io").BytesIO(b"")
        def wait(self, timeout=None): return 2

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: BoomProc())
    with pytest.raises(RuntimeError) as ei:
        base.run_subprocess_capture(["psql"])
    assert "auth failed" in str(ei.value)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_adapters.py::test_run_subprocess_capture_returns_stdout -x`
Expected: FAIL — `run_subprocess_capture` 不存在。

- [ ] **Step 3: 实现** — `app/adapters/base.py`

在 `run_subprocess` 函数之后新增（结构镜像 `run_subprocess`，但 stdout=PIPE 并返回解码文本）：

```python
def run_subprocess_capture(
    argv: list[str],
    *,
    env: dict | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
    is_cancelled: Callable[[], bool] | None = None,
) -> str:
    """同 run_subprocess,但捕获并返回 stdout 的解码文本(用于 list_databases 等需读取输出的场景)。
    取消 → BackupCancelled;超时/非零退出 → RuntimeError(含 stderr)。"""
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    start = time.monotonic()
    while True:
        try:
            proc.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            pass
        if is_cancelled is not None and is_cancelled():
            _kill(proc)
            raise BackupCancelled()
        if timeout and time.monotonic() - start > timeout:
            _kill(proc)
            raise RuntimeError(f"命令超时({timeout}s): {argv[0]}")
    if proc.returncode != 0:
        err = b""
        if proc.stderr is not None:
            try:
                err = proc.stderr.read() or b""
            except Exception:
                pass
        detail = err.decode("utf-8", "replace").strip()
        raise RuntimeError(f"命令失败(退出码 {proc.returncode}): {argv[0]}\n{detail}")
    out = b""
    if proc.stdout is not None:
        try:
            out = proc.stdout.read() or b""
        except Exception:
            pass
    return out.decode("utf-8", "replace")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_adapters.py -x`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/base.py tests/test_adapters.py
git commit -m "feat(adapter): run_subprocess_capture 捕获 stdout"
```

---

## Task 5: PostgresAdapter.list_databases

**Files:**
- Modify: `app/adapters/postgres.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_adapters.py`

```python
def test_pg_list_databases_argv_and_parse(monkeypatch):
    """list_databases:连维护库 postgres,查 pg_database;密码走 env;解析逐行库名。"""
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, username="u", password="secret")
    seen = {}

    class OkProc:
        returncode = 0
        stderr = None
        stdout = __import__("io").BytesIO(b"app\nlogs\nshop\n")
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        seen["env"] = kw.get("env")
        return OkProc()

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", fake_popen)
    names = a.list_databases(info)
    assert names == ["app", "logs", "shop"]
    joined = " ".join(seen["argv"])
    assert "datname" in joined and "pg_database" in joined        # 查 pg_database
    assert "-d" in seen["argv"] and "postgres" in seen["argv"]    # 连维护库 postgres
    assert "secret" not in joined                                 # 密码不上 argv
    assert seen["env"].get("PGPASSWORD") == "secret"             # 走 PGPASSWORD


def test_pg_list_databases_falls_back_to_template1(monkeypatch):
    """postgres 维护库连不上时,回退 template1;仍失败则抛 RuntimeError。"""
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", username="u", password="secret")
    calls = []

    class FailProc:
        returncode = 1
        stderr = __import__("io").BytesIO(b"connection refused")
        stdout = __import__("io").BytesIO(b"")
        def wait(self, timeout=None): return 1

    class OkProc:
        returncode = 0
        stderr = None
        stdout = __import__("io").BytesIO(b"onlydb\n")
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kw):
        calls.append(argv)
        return FailProc() if "-d" in argv and "postgres" in argv else OkProc()

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", fake_popen)
    assert a.list_databases(info) == ["onlydb"]
    assert any("template1" in c for c in calls)  # 回退到 template1


def test_pg_list_databases_all_fail_raises(monkeypatch):
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", username="u", password="secret")

    class FailProc:
        returncode = 1
        stderr = __import__("io").BytesIO(b"auth failed")
        stdout = __import__("io").BytesIO(b"")
        def wait(self, timeout=None): return 1

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", lambda *a, **k: FailProc())
    with pytest.raises(RuntimeError) as ei:
        a.list_databases(info)
    assert "维护库" in str(ei.value)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_adapters.py::test_pg_list_databases_argv_and_parse -x`
Expected: FAIL — `list_databases` 不存在。

- [ ] **Step 3: 实现** — `app/adapters/postgres.py`

把第 5 行 import 改为（追加 `run_subprocess_capture`）：

```python
from app.adapters.base import ConnectionInfo, register_adapter, run_subprocess, run_subprocess_capture
```

在 `test` 方法之后、`register_adapter(PostgresAdapter())` 之前新增：

```python
    def list_databases(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> list[str]:
        """列出该用户可连接的非模板库:连维护库 postgres(失败回退 template1)→
        SELECT datname FROM pg_database WHERE datistemplate=false AND datallowconn。
        密码仅走 PGPASSWORD env。"""
        sql = "SELECT datname FROM pg_database WHERE datistemplate = false AND datallowconn ORDER BY 1"
        last_err: Exception | None = None
        for maint in ("postgres", "template1"):
            cmd = ["psql", "--no-password", "-t", "-A"]  # -t 去表头, -A 不对齐
            if info.host:
                cmd += ["-h", info.host]
            if info.port:
                cmd += ["-p", str(info.port)]
            if info.username:
                cmd += ["-U", info.username]
            cmd += ["-d", maint, "-c", sql]
            try:
                out = run_subprocess_capture(cmd, env=self.env(info), timeout=10, is_cancelled=is_cancelled)
                return [ln.strip() for ln in out.splitlines() if ln.strip()]
            except RuntimeError as e:
                last_err = e
                continue
        raise RuntimeError(f"无法连接到维护库 postgres/template1,请检查用户对维护库的 CONNECT 权限: {last_err}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_adapters.py -x`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/postgres.py tests/test_adapters.py
git commit -m "feat(pg): list_databases 列出用户可备份的库"
```

---

## Task 6: MySQL 适配器无 db_name 时全库

**Files:**
- Modify: `app/adapters/mysql.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_adapters.py`

```python
def test_mysql_argv_all_databases_when_no_dbname():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, username="u")  # 无 db_name
    cmd = a.argv(info, "/tmp/x.cnf")
    assert "--all-databases" in cmd
    assert "shop" not in cmd


def test_mysql_argv_keeps_single_db_when_dbname():
    """有 db_name 的旧连接保持原行为(只备份该库)。"""
    a = MysqlAdapter()
    cmd = a.argv(ConnectionInfo(type="mysql", db_name="shop"), "/tmp/x.cnf")
    assert "shop" in cmd
    assert "--all-databases" not in cmd
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_adapters.py::test_mysql_argv_all_databases_when_no_dbname -x`
Expected: FAIL — 当前 argv 无 db_name 时既不加库名也不加 `--all-databases`。

- [ ] **Step 3: 改 `argv`** — `app/adapters/mysql.py`

把 `argv` 方法改为（无 db_name 时输出 `--all-databases`）：

```python
    def argv(self, info: ConnectionInfo, defaults_file: str) -> list[str]:
        cmd = ["mysqldump", f"--defaults-extra-file={defaults_file}"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-P", str(info.port)]
        if info.db_name:
            cmd += [info.db_name]
        else:
            cmd += ["--all-databases"]
        return cmd
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_adapters.py -x`
Expected: PASS（新两条 + 既有 `test_mysql_argv_uses_defaults_extra_file` / `test_mysql_argv_has_no_password` 仍通过，因为它们带 db_name）。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/mysql.py tests/test_adapters.py
git commit -m "feat(mysql): 无指定库时 mysqldump --all-databases"
```

---

## Task 7: 列出库的服务函数 + 两个端点

**Files:**
- Modify: `app/services/connection_service.py`
- Modify: `app/routers/connections.py`
- Test: `tests/test_connections.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_connections.py`

```python
def test_list_databases_pre_save_success(authed, monkeypatch):
    class FakeAdapter:
        def list_databases(self, info, *, is_cancelled=None): return ["app", "logs"]
    monkeypatch.setattr("app.services.connection_service.get_adapter", lambda t: FakeAdapter())
    r = authed.post("/api/v1/connections/list-databases",
                    json={"type": "pg", "host": "h", "port": 5432, "username": "u", "password": "p"})
    assert r.status_code == 200
    assert r.json() == {"databases": ["app", "logs"]}


def test_list_databases_pre_save_failure_returns_400(authed, monkeypatch):
    class BadAdapter:
        def list_databases(self, info, *, is_cancelled=None): raise RuntimeError("password authentication failed")
    monkeypatch.setattr("app.services.connection_service.get_adapter", lambda t: BadAdapter())
    r = authed.post("/api/v1/connections/list-databases",
                    json={"type": "pg", "host": "h", "username": "u", "password": "p"})
    assert r.status_code == 400
    assert "password authentication failed" in r.json()["detail"]


def test_list_databases_unsupported_type(authed):
    """MySQL/Mongo/Redis/SQLite 不支持选库 → 400 + 友好提示。"""
    r = authed.post("/api/v1/connections/list-databases", json={"type": "mysql"})
    assert r.status_code == 400
    assert "不支持" in r.json()["detail"]


def test_list_databases_post_save_success(authed, monkeypatch):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg"}).json()["id"]
    class FakeAdapter:
        def list_databases(self, info, *, is_cancelled=None): return ["app"]
    monkeypatch.setattr("app.services.connection_service.get_adapter", lambda t: FakeAdapter())
    r = authed.post(f"/api/v1/connections/{cid}/databases")
    assert r.status_code == 200
    assert r.json() == {"databases": ["app"]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_connections.py::test_list_databases_pre_save_success -x`
Expected: FAIL — 404（端点不存在）。

- [ ] **Step 3: 服务函数** — `app/services/connection_service.py`

在 `test_connection` 之后新增：

```python
def list_databases_for_payload(data) -> list[str]:
    """保存前:用表单明文凭证列出可备份的库(仅 PG)。其它类型直接抛,由路由转 400。"""
    if data.type != "pg":
        raise NotImplementedError("该类型暂不支持选择数据库;MySQL 默认全库备份,其余类型请直接填写")
    info = ConnectionInfo(
        type=data.type, host=data.host, port=data.port, db_name=data.db_name,
        username=data.username, password=data.password,
    )
    return get_adapter(data.type).list_databases(info)


def list_databases_for_connection(db: Session, crypto: Crypto, conn_id: int) -> list[str]:
    """保存后:解密已存密码列出库(编辑态、密码未改时用)。"""
    c = get_connection(db, conn_id)
    if c.type != "pg":
        raise NotImplementedError("该类型暂不支持选择数据库;MySQL 默认全库备份,其余类型请直接填写")
    info = ConnectionInfo(
        type=c.type, host=c.host, port=c.port, db_name=c.db_name,
        username=c.username, password=decrypt_password(c, crypto),
    )
    return get_adapter(c.type).list_databases(info)
```

- [ ] **Step 4: 路由端点** — `app/routers/connections.py`

把 import 行改为（追加 `ConnectionProbe`）：

```python
from app.schemas.connection import ConnectionProbe, ConnectionCreate, ConnectionUpdate, ConnectionOut
```

在 `test` 端点之后追加两个端点：

```python
@router.post("/list-databases")
def list_databases_pre(payload: ConnectionProbe, request: Request, _=Depends(get_current_account)):
    try:
        dbs = svc.list_databases_for_payload(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"databases": dbs}


@router.post("/{conn_id}/databases")
def list_databases_post(conn_id: int, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    try:
        dbs = svc.list_databases_for_connection(db, request.app.state.crypto, conn_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"databases": dbs}
```

> 注意：`/list-databases` 必须在 `/{conn_id}` 这类路径参数路由之前注册，否则 `list-databases` 会被当作 `conn_id`。本端点紧随 `/test`（同为字面路径），放在文件末尾即可（FastAPI 按声明顺序匹配，但 `/list-databases` 与 `/{conn_id}/databases` 不冲突，前者无 `/databases` 后缀）。

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_connections.py -x`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add app/services/connection_service.py app/routers/connections.py tests/test_connections.py
git commit -m "feat(connection): 列出可备份库的保存前/保存后端点"
```

---

## Task 8: 备份服务 — 解析库列表 / enqueue_backup / run_backup 按 record.db_name

> 本任务把 `_conn_info` 改为显式接收 db_name，并同步更新 `restore_service`（它 import 了 `_conn_info`），避免中间态破坏导入。

**Files:**
- Modify: `app/services/backup_service.py`
- Modify: `app/services/restore_service.py`
- Test: `tests/test_backup_service.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_backup_service.py`（用既有 `FakeAdapter`/`FakeRedis`，无需新 fakes）

```python
def test_resolve_db_names_pg_uses_db_names(tmp_path):
    from app.services.backup_service import _resolve_db_names
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection
    import json
    init_engine(f"sqlite:///{tmp_path/'r.db'}"); create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="c", type="pg", db_names=json.dumps(["app", "logs"]))
        db.add(c)
        assert _resolve_db_names(c) == ["app", "logs"]
    finally:
        db.close()


def test_resolve_db_names_mysql_all_when_empty(tmp_path):
    from app.services.backup_service import _resolve_db_names
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection
    init_engine(f"sqlite:///{tmp_path/'r.db'}"); create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="m", type="mysql")  # 无 db_names / db_name
        db.add(c)
        assert _resolve_db_names(c) == [None]  # MySQL 全库 → [None]
    finally:
        db.close()


def test_enqueue_backup_creates_one_record_per_db(tmp_path, monkeypatch):
    from app.services.backup_service import enqueue_backup
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection, BackupRecord
    import json
    init_engine(f"sqlite:///{tmp_path/'e.db'}"); create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="c", type="pg", db_names=json.dumps(["app", "logs", "shop"]))
        db.add(c); db.commit(); db.refresh(c)
        recs = enqueue_backup(db, c, "manual")
        assert len(recs) == 3
        assert sorted(r.db_name for r in recs) == ["app", "logs", "shop"]
        assert all(r.status == "running" for r in recs)
        assert db.query(BackupRecord).count() == 3
    finally:
        db.close()


def test_run_backup_uses_record_db_name(tmp_path, monkeypatch):
    """run_backup 应按 record.db_name 决定 dump 的库(record 是真实来源)。"""
    db, conn, crypto, bdir, _ = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    from app.db.models import BackupRecord
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="running",
                       db_name="chosen_db", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)

    seen = {}
    class SpyAdapter(FakeAdapter):
        def dump(self, info, dest_path, *, is_cancelled=None):
            seen["db_name"] = info.db_name
            super().dump(info, dest_path, is_cancelled=is_cancelled)
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: SpyAdapter())

    out = run_backup(db, crypto, conn, ProgressReporter(rec.id, FakeRedis()), bdir, rec.id)
    assert out.status == "success"
    assert seen["db_name"] == "chosen_db"   # 用的是 record.db_name,而非 conn.db_name('d')
    db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_backup_service.py::test_resolve_db_names_pg_uses_db_names -x`
Expected: FAIL — `_resolve_db_names` 不存在。

- [ ] **Step 3: 改 `_conn_info` + 新增解析/enqueue + 改 run_backup** — `app/services/backup_service.py`

文件顶部 import 区加 `import json`（若已有则跳过）。

把 `_conn_info` 改为（接收显式 db_name，不再隐式取 conn.db_name）：

```python
def _conn_info(conn: DbConnection, crypto: Crypto, db_name: str | None = None) -> ConnectionInfo:
    return ConnectionInfo(
        type=conn.type,
        host=conn.host,
        port=conn.port,
        db_name=db_name,
        username=conn.username,
        password=_decrypt(conn.password_enc, crypto),
    )
```

在 `_decrypt` 之后新增解析与入队两个函数：

```python
def _resolve_db_names(conn: DbConnection) -> list[str | None]:
    """决定一次备份要遍历哪些库:
    - db_names 非空(PG 多选/旧 PG 回填) → 取其列表
    - 否则 MySQL → [None](全库,适配器输出 --all-databases)
    - 否则(旧连接/sqlite 等) → [conn.db_name]"""
    names: list[str] = []
    if conn.db_names:
        try:
            parsed = json.loads(conn.db_names)
            if isinstance(parsed, list):
                names = [n for n in parsed if n]
        except (TypeError, ValueError):
            names = []
    if names:
        return names
    if conn.type == "mysql":
        return [None]
    return [conn.db_name]


def enqueue_backup(db: Session, conn: DbConnection, trigger: str, now_fn=datetime.utcnow) -> list[BackupRecord]:
    """为连接的每个待备份库各建一条 running BackupRecord(trigger manual/scheduled)。
    供 run_now 与 scheduler 共用;返回创建的记录列表(已 commit)。"""
    names = _resolve_db_names(conn)
    records = []
    for name in names:
        r = BackupRecord(connection_id=conn.id, trigger=trigger, status="running",
                         db_name=name, started_at=now_fn())
        db.add(r)
        records.append(r)
    db.commit()
    for r in records:
        db.refresh(r)
    return records
```

> `Session` 已在文件顶部 import（`from sqlalchemy.orm import Session`）；确认存在，缺则补。

把 `run_backup` 内 `adapter.dump(_conn_info(conn, crypto), ...)` 这一行（在 `reporter.report("dump")` 之后）改为按 record 决定库：

```python
        adapter = get_adapter(conn.type)
        reporter.report("dump")
        effective_db = record.db_name if record.db_name is not None else conn.db_name
        adapter.dump(_conn_info(conn, crypto, effective_db), str(raw_path), is_cancelled=reporter.is_cancelled)
```

- [ ] **Step 4: 同步改 restore_service** — `app/services/restore_service.py`

把第 3 阶段「还原」里的 `adapter.restore(_conn_info(target_conn, crypto), ...)` 改为按备份记录的库恢复（旧记录 db_name 为 NULL 时回退 target_conn.db_name，保持旧行为）：

```python
        # 3. 还原
        reporter.report("restore")
        adapter = get_adapter(target_conn.type)
        restore_db = backup_record.db_name if backup_record.db_name is not None else target_conn.db_name
        adapter.restore(_conn_info(target_conn, crypto, restore_db), str(raw_path), is_cancelled=reporter.is_cancelled)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_backup_service.py tests/test_restore_api.py -x`
Expected: PASS（含新四条 + 既有 run_backup / restore 用例）。

- [ ] **Step 6: 提交**

```bash
git add app/services/backup_service.py app/services/restore_service.py tests/test_backup_service.py
git commit -m "feat(backup): enqueue_backup 多库 + run_backup 按 record.db_name"
```

---

## Task 9: worker 多记录循环 + run_now + scheduler + JobRunResponse

**Files:**
- Modify: `app/schemas/job.py`（`JobRunResponse` 重构 + `JobOut`/`BackupFileOut` 加 db_name）
- Modify: `app/workers/jobs.py`（`backup_job` 收 record_ids 列表）
- Modify: `app/routers/jobs.py`（`run_now` 用 enqueue_backup）
- Modify: `app/services/scheduler.py`（`run_scheduled_backup` 用 enqueue_backup）
- Test: `tests/test_jobs_api.py`

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_jobs_api.py`

```python
def test_run_multi_db_creates_record_per_db(authed, monkeypatch):
    """PG 多库连接:一次 run 为每个库各建一条记录,入队单个 backup_job 带 record_ids 列表。"""
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import DbConnection
    import json
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", db_names=json.dumps(["app", "logs"]))
    db.add(conn); db.commit(); db.refresh(conn); conn_id = conn.id; db.close()

    r = authed.post("/api/v1/backups/run", json={"connection_id": conn_id})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running"
    assert len(body["record_ids"]) == 2
    assert {x["db_name"] for x in body["records"]} == {"app", "logs"}
    # 入队签名:("backup_job", connection_id, [record_ids])
    assert authed.app.state.arq.enqueued[0][0] == "backup_job"
    assert authed.app.state.arq.enqueued[0][1] == conn_id
    assert sorted(authed.app.state.arq.enqueued[0][2]) == sorted(body["record_ids"])
```

并把既有 `test_run_creates_record_and_enqueues` 末尾的 `assert len(...) == 3` 之后，追加（确认新返回字段存在且单库连接返回 1 条）：

```python
    assert body["record_ids"] and len(body["record_ids"]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_jobs_api.py::test_run_multi_db_creates_record_per_db -x`
Expected: FAIL — 返回体无 `record_ids`。

- [ ] **Step 3: 改 schema** — `app/schemas/job.py`

把 `JobRunResponse` 改为：

```python
class JobRecordRef(BaseModel):
    record_id: int
    db_name: str | None = None
    status: str


class JobRunResponse(BaseModel):
    connection_id: int
    record_ids: list[int]
    records: list[JobRecordRef]
    status: str  # 汇总态,初始 "running"
```

`JobOut` 加字段（在 `trigger` 之后）：

```python
    db_name: str | None = None
```

`BackupFileOut` 加字段（在 `trigger` 之后）：

```python
    db_name: str | None = None
```

- [ ] **Step 4: 改 worker** — `app/workers/jobs.py`

把 `_run_backup_sync` 与 `backup_job` 改为接收 `record_ids: list[int]` 并循环：

```python
def _run_backup_sync(ctx, connection_id: int, record_ids: list[int]) -> dict:
    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    db = _session._SessionLocal()
    results = []
    try:
        conn = db.get(DbConnection, connection_id)
        if conn is None:
            raise ValueError(f"连接不存在: {connection_id}")
        for rid in record_ids:
            reporter = ProgressReporter(rid)
            rec = run_backup(db, crypto, conn, reporter, ctx["backup_dir"], rid)
            if rec.status == "success":
                try:
                    run_retention(db, conn, ctx["backup_dir"])
                except Exception:
                    pass  # 保留清理失败不影响备份结果
            try:
                notify_backup_result(db, crypto, conn, rec)
            except Exception:
                pass  # 通知失败不影响备份结果
            results.append({"record_id": rec.id, "status": rec.status})
        return {"results": results}
    finally:
        db.close()


async def backup_job(ctx, connection_id: int, record_ids: list[int]) -> dict:
    return await asyncio.to_thread(_run_backup_sync, ctx, connection_id, record_ids)
```

- [ ] **Step 5: 改 run_now** — `app/routers/jobs.py`

把 `run_now` 改为：

```python
@router.post("/backups/run", response_model=JobRunResponse, status_code=201)
async def run_now(payload: BackupRunRequest, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    conn = db.get(DbConnection, payload.connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    # 互斥:同一连接已有备份在运行 → 拒绝,避免并发 dump 损坏/资源争抢
    if has_running_backup(db, conn.id) is not None:
        raise HTTPException(status_code=409, detail="该连接已有备份在运行")
    records = enqueue_backup(db, conn, payload.trigger)
    try:
        arq = await _get_arq(request.app)
        await arq.enqueue_job("backup_job", conn.id, [r.id for r in records])
    except Exception:
        # 投递失败:把所有刚建的 running 记录翻转为 failed,避免幽灵
        for r in records:
            r.status = "failed"
            r.error = "投递到队列失败"
            r.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="投递到队列失败,请稍后重试")
    return JobRunResponse(
        connection_id=conn.id,
        record_ids=[r.id for r in records],
        records=[{"record_id": r.id, "db_name": r.db_name, "status": r.status} for r in records],
        status="running",
    )
```

并把 import 行改为（追加 `enqueue_backup`）：

```python
from app.services.backup_service import enqueue_backup
```

- [ ] **Step 6: 改 scheduler** — `app/services/scheduler.py`

把 `run_scheduled_backup` 改为（用 `enqueue_backup` 建多条记录，入队列表）：

```python
async def run_scheduled_backup(app, connection_id: int, schedule_id: int) -> None:
    """cron 触发:为每个待备份库建 running 记录(trigger=scheduled)→ 投递 backup_job。

    互斥:若该连接已有 running 备份(手动/上一轮未结束),本轮跳过,记 SystemLog。"""
    from app.services.backup_service import enqueue_backup
    db = _session._SessionLocal()
    try:
        if has_running_backup(db, connection_id) is not None:
            db.add(SystemLog(level="warning", source="scheduler",
                             message=f"连接 #{connection_id} 已有备份在运行,跳过本次计划触发(#{schedule_id})"))
            db.commit()
            return
        conn = db.get(DbConnection, connection_id)
        if conn is None:
            return
        records = enqueue_backup(db, conn, "scheduled")
        record_ids = [r.id for r in records]
    finally:
        db.close()
    from app.routers.jobs import _get_arq
    try:
        arq = await _get_arq(app)
        await arq.enqueue_job("backup_job", connection_id, record_ids)
    except Exception:
        db = _session._SessionLocal()
        try:
            for rid in record_ids:
                rec = db.get(BackupRecord, rid)
                if rec is not None:
                    rec.status = "failed"
                    rec.error = "投递到队列失败"
                    rec.finished_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        raise
```

> `DbConnection` 已在 `scheduler.py` 顶部 import（确认 `from app.db.models import Schedule, BackupRecord, SystemLog, DbConnection`，缺 `DbConnection` 则补）。

- [ ] **Step 7: 跑后端全量测试**

Run: `pytest -x`
Expected: PASS（含 test_jobs_api、test_backup_service、test_restore_api、test_schedules 等全部）。

> 若 `test_schedules*.py` 有断言旧入队签名 `(conn_id, record_id)` 的用例失败：新签名是 `("backup_job", conn_id, [list])` 仍为 3 元素；如断言了第 3 项为 int，则把测试期望改为 list。

- [ ] **Step 8: 提交**

```bash
git add app/schemas/job.py app/workers/jobs.py app/routers/jobs.py app/services/scheduler.py tests/test_jobs_api.py
git commit -m "feat(backup): 多库触发一次入队,worker 逐库循环"
```

---

## Task 10: 前端 — api 层（connections / jobs / backups）

**Files:**
- Modify: `frontend/src/api/connections.ts`
- Modify: `frontend/src/api/jobs.ts`
- Modify: `frontend/src/api/backups.ts`

- [ ] **Step 1: connections.ts** — 加 db_names 字段与两个新方法

把 `Connection` 类型改为（在 `db_name` 之后加 `db_names`）：

```typescript
export type Connection = {
  id: number
  name: string
  type: 'pg' | 'mysql' | 'mongo' | 'redis' | 'sqlite'
  host?: string | null
  port?: number | null
  db_name?: string | null
  db_names?: string[] | null
  username?: string | null
  extra?: Record<string, unknown> | null
  created_at: string
}
```

在文件末尾追加：

```typescript
export type ListDatabasesPayload = {
  type: string
  host?: string | null
  port?: number | null
  username?: string | null
  password?: string
  db_name?: string | null
}

export const listDatabases = (payload: ListDatabasesPayload) =>
  client.post<{ databases: string[] }>('/connections/list-databases', payload)
export const listDatabasesForConnection = (id: number) =>
  client.post<{ databases: string[] }>(`/connections/${id}/databases`)
```

- [ ] **Step 2: jobs.ts** — Job 加 db_name；runBackup 返回类型重构

把整个文件改为：

```typescript
import client from './client'

export interface Job {
  id: number
  connection_id: number
  trigger: string
  status: string
  error: string | null
  db_name: string | null
  started_at: string
  finished_at: string | null
}

export interface JobRecordRef {
  record_id: number
  db_name: string | null
  status: string
}

export interface JobRunResponse {
  connection_id: number
  record_ids: number[]
  records: JobRecordRef[]
  status: string
}

export const runBackup = (connection_id: number) =>
  client.post<JobRunResponse>('/backups/run', { connection_id })
export const listJobs = () => client.get<Job[]>('/jobs')
export const cancelJob = (id: number) => client.post(`/jobs/${id}/cancel`)
```

- [ ] **Step 3: backups.ts** — BackupFile 加 db_name

把 `BackupFile` interface 改为（在 `trigger` 之后加 `db_name`）：

```typescript
export interface BackupFile {
  id: number
  connection_id: number
  trigger: string
  db_name: string | null
  status: string
  file_path: string | null
  size: number | null
  checksum: string | null
  duration_ms: number | null
  started_at: string
  finished_at: string | null
}
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit`（若项目无该脚本则 `npm run build` 见 Task 13）
Expected: 无类型错误（视图层还未用到新字段，但类型已就绪）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/connections.ts frontend/src/api/jobs.ts frontend/src/api/backups.ts
git commit -m "feat(fe-api): db_names 类型 + 列库方法 + 多记录返回"
```

---

## Task 11: 前端 — Connections.vue 多选 + 拉取按钮 + 按类型分流

**Files:**
- Modify: `frontend/src/views/Connections.vue`

- [ ] **Step 1: 改 script** — `frontend/src/views/Connections.vue`

第 5 行 import 追加 `NText`（用于 MySQL 提示）：

```typescript
import {
  NCard, NDataTable, NButton, NModal, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSpace, NPopconfirm, NText, useMessage,
} from 'naive-ui'
```

在 `const form = ref<any>({})` 之后新增：

```typescript
const dbOptions = ref<{ label: string; value: string }[]>([])
const loadingDbs = ref(false)

async function fetchDbs() {
  loadingDbs.value = true
  try {
    let resp
    if (editing.value && !form.value.password) {
      // 编辑态且密码未改:用已存密码
      resp = await api.listDatabasesForConnection(editing.value.id)
    } else {
      resp = await api.listDatabases({
        type: form.value.type, host: form.value.host, port: form.value.port,
        username: form.value.username, password: form.value.password, db_name: form.value.db_name,
      })
    }
    const list = resp.data.databases || []
    dbOptions.value = list.map((d: string) => ({ label: d, value: d }))
    msg.success(`拉取到 ${list.length} 个数据库`)
  } catch (e: any) {
    msg.error(e.response?.data?.detail || '拉取数据库列表失败')
  } finally {
    loadingDbs.value = false
  }
}
```

把 `openAdd` 改为（重置 db_names / dbOptions）：

```typescript
function openAdd() {
  editing.value = null
  form.value = { type: 'pg', port: 5432, db_names: [] }
  dbOptions.value = []
  show.value = true
}
```

把 `openEdit` 改为（回填 db_names 并预置选项）：

```typescript
function openEdit(row: Connection) {
  editing.value = row
  const names = row.db_names ? [...row.db_names] : []
  form.value = {
    name: row.name, type: row.type, host: row.host, port: row.port,
    db_name: row.db_name, db_names: names, username: row.username, password: '',
  }
  dbOptions.value = names.map(d => ({ label: d, value: d }))
  show.value = true
}
```

把列表 `columns` 里 `{ title: '数据库', key: 'db_name' }` 改为展示多库：

```typescript
    { title: '数据库', key: 'db_names', render: row => (row.db_names && row.db_names.length) ? row.db_names.join(', ') : (row.db_name || (row.type === 'mysql' ? '全部' : '—')) },
```

- [ ] **Step 2: 改 template** — 把 `<n-form-item label="数据库名"><n-input v-model:value="form.db_name" /></n-form-item>`（第 110 行）替换为按类型分流：

```vue
        <n-form-item label="数据库">
          <template v-if="form.type === 'pg'">
            <n-space align="center" style="width: 100%">
              <n-select
                v-model:value="form.db_names"
                multiple
                filterable
                :options="dbOptions"
                :loading="loadingDbs"
                placeholder="点击右侧按钮拉取库列表后多选"
                style="width: 260px"
              />
              <n-button :loading="loadingDbs" @click="fetchDbs">拉取数据库列表</n-button>
            </n-space>
          </template>
          <template v-else-if="form.type === 'mysql'">
            <n-text depth="3">MySQL 默认备份全部数据库</n-text>
          </template>
          <template v-else>
            <n-input v-model:value="form.db_name" />
          </template>
        </n-form-item>
```

- [ ] **Step 3: 构建确认无语法错**

Run: `cd frontend && npm run build`
Expected: 构建成功（vite 产出 dist）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/Connections.vue
git commit -m "feat(fe): PG 连接多选库 + 拉取按钮,MySQL 全库提示"
```

---

## Task 12: 前端 — Backups.vue / History.vue 适配多记录与库名列

**Files:**
- Modify: `frontend/src/views/Backups.vue`
- Modify: `frontend/src/views/History.vue`

- [ ] **Step 1: Backups.vue `runNow`** — 适配新返回（多条记录）

把 `runNow` 改为：

```typescript
async function runNow() {
  if (selectedConn.value == null) { msg.warning('请先选择连接'); return }
  try {
    const r = await jobsApi.runBackup(selectedConn.value)
    const ids = r.data.record_ids || []
    showProgress.value = true
    if (ids.length) subscribe(ids[0])  // v1:进度抽屉跟第一条;其余靠下方 poll 刷新
    msg.success(`已创建 ${ids.length} 条备份任务`)
    poll()
  } catch (e: any) { msg.error(e.response?.data?.detail || '启动失败') }
}
```

- [ ] **Step 2: Backups.vue 任务表加库列** — `jobColumns` 在「触发」之后插入：

```typescript
  { title: '库', key: 'db_name', render: r => r.db_name || '全部' },
```

`fileColumns` 同样在「状态」之前插入同一定义（若希望文件表也显示）。

- [ ] **Step 3: History.vue 加库列** — `columns` 在「连接」之后插入：

```typescript
  { title: '数据库', key: 'db_name', render: r => r.db_name || '全部' },
```

- [ ] **Step 4: 构建**

Run: `cd frontend && npm run build`
Expected: 成功。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/Backups.vue frontend/src/views/History.vue
git commit -m "feat(fe): 备份多记录提示 + 库名列"
```

---

## Task 13: 全量验证（后端测试 + 前端构建 + 端到端手测）

- [ ] **Step 1: 后端全量测试**

Run: `pytest`
Expected: 全绿。

- [ ] **Step 2: 前端构建 + 类型检查**

Run: `cd frontend && npm run build`
Expected: 成功，dist 产出。

- [ ] **Step 3: 端到端手测（用 run / webapp-testing 技能驱动真实应用）**

启动应用后验证：
1. 新建 PG 连接：填 host/port/user/password → 点「拉取数据库列表」→ 下拉出现库 → 多选 2 个 → 保存。
2. 「立即备份」该连接 → 提示「已创建 2 条备份任务」→ 备份文件表出现 2 条 success，库名列正确。
3. 新建 MySQL 连接（不显示选库）→ 备份 → 1 条记录、`--all-databases`（可下载查看 dump 含多库）。
4. History 页「数据库」列对 PG 显示具体库、MySQL 显示「全部」。
5. 编辑 PG 连接 → 「拉取数据库列表」用已存密码（密码框留空）能拉到、已选保留。
6. 恢复一条 PG 备份 → 恢复到备份记录自身的 db_name 库。

- [ ] **Step 4: 最终提交（如有手测发现的微调）**

```bash
git add -A
git commit -m "test: 多库备份端到端验证通过"
```

---

## Self-Review 备忘（实现者无需操作）

- **Spec 覆盖**：§4 模型/迁移 → T1；§5 适配器 → T4/T5/T6；§6 服务 → T7/T8；§7 API → T7；§8 备份流程 → T8/T9；§9 前端 → T10/T11/T12；§10 测试 → 各 Task 内。
- **类型一致**：`enqueue_backup`、`_resolve_db_names`、`_conn_info(...,db_name=)`、`backup_job(ctx, conn_id, record_ids)`、`JobRunResponse{connection_id,record_ids,records,status}`、`list_databases_for_payload/_for_connection` 在所有任务中签名一致。
- **向后兼容**：旧连接（仅 db_name）经迁移回填 db_names；旧 BackupRecord.db_name 为 NULL，run_backup/restore 回退 conn.db_name；既有 mysql argv 测试（带 db_name）不受影响。
