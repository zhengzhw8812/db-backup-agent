# Phase 2a — 核心备份管线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让备份真正能跑:数据库连接 → 触发手动备份 → arq worker 执行 dump/压缩/校验 → 实时进度经 Redis pub/sub + SSE 推前端 → 备份文件可列表/下载/删除,且可取消。

**Architecture:** Web 只负责"投任务"(POST /backups/run 建 backup_record + enqueue arq job)并"读进度"(SSE 订阅 Redis pub/sub);arq worker 在 to_thread 中跑同步的 `backup_service.run_backup`,用适配器(PG/MySQL)执行 dump,经 gzip+sha256 落盘到 `/data/backups`,每步上报进度。取消用 Redis cancel 标志(任务在阶段间隙检查)。所有"任务"以 `backup_record.id` 为锚点(进度频道、取消键、SSE 路径都用它)。

**Tech Stack:** arq (任务队列), redis (sync 发布 + asyncio 订阅), FastAPI StreamingResponse (SSE), subprocess (create_subprocess/run, 禁 shell), gzip/hashlib。

**前置:** Phase 1 完成(app/ 分层后端, Fernet/argon2/单用户鉴权/连接 CRUD, SQLite 5 表含 backup_records, container supervisord 跑 redis+uvicorn)。设计文档 `docs/superpowers/specs/2026-07-02-full-rewrite-design.md` §8(任务执行模型)。

---

## File Structure (本计划产出)

```
app/
├── adapters/
│   ├── __init__.py            # 适配器注册表 get_adapter()
│   ├── base.py                # ConnectionInfo, BackupAdapter
│   ├── postgres.py            # PostgresAdapter
│   └── mysql.py               # MysqlAdapter
├── core/
│   └── archive.py             # compress_file, sha256_of_file
├── services/
│   └── backup_service.py      # run_backup 编排(含取消/失败处理)
├── workers/
│   ├── __init__.py
│   ├── app.py                 # arq WorkerSettings + on_startup(init engine)
│   ├── progress.py            # ProgressReporter(pub/sub + cancel 标志)
│   └── jobs.py                # backup_job (asyncio.to_thread 调 run_backup)
├── routers/
│   ├── jobs.py                # /api/v1/backups/run, /jobs, /jobs/{id}/cancel, /jobs/{id}/events
│   └── backups.py             # /api/v1/backups (list/download/delete)
├── schemas/
│   ├── job.py                 # JobRunResponse, JobOut, BackupFileOut
│   └── ...
├── redis_client.py            # get_async_redis() (SSE 订阅用)
└── main.py                    # 启动建 arq pool → app.state.arq;include jobs/backups 路由
deploy/
├── supervisord.conf           # 新增 [program:worker]
└── Dockerfile                 # 新增 arq 依赖运行
tests/
├── test_adapters.py
├── test_archive.py
├── test_progress.py
├── test_backup_service.py
├── test_jobs_api.py
└── test_backups_api.py
```

**职责边界:** `adapters/` 封装每种 DB 的 dump(策略模式,Phase 后续加 Mongo/Redis/SQLite 只加文件);`core/archive.py` 纯函数(压缩/校验);`services/backup_service.py` 编排(适配器→压缩→记录),无 HTTP 依赖;`workers/` 进程内:进度上报 + arq job;`routers/` 薄 IO。`backup_record.id` 是贯穿 Web↔worker↔前端的唯一任务锚点。

---

## Task 1: arq 依赖 + Redis 客户端 + worker 骨架 + supervisord

**Files:**
- Modify: `pyproject.toml`(加 arq)
- Create: `app/workers/__init__.py`(空), `app/workers/app.py`, `app/redis_client.py`
- Modify: `deploy/supervisord.conf`(加 [program:worker]), `deploy/Dockerfile`(arq 已随 pip install .)

- [ ] **Step 1: 加 arq 依赖到 pyproject.toml**

在 `dependencies` 列表加入 `"arq>=0.26"`(保持字母序),然后 `.venv/bin/pip install -e ".[dev]"`。

- [ ] **Step 2: 写 app/redis_client.py(async redis,供 SSE 订阅)**

```python
import redis.asyncio as aioredis
from app.config import settings

_async_pool: aioredis.ConnectionPool | None = None


def get_async_redis() -> aioredis.Redis:
    global _async_pool
    if _async_pool is None:
        _async_pool = aioredis.ConnectionPool.from_url(settings.redis_url)
    return aioredis.Redis(connection_pool=_async_pool)
```

- [ ] **Step 3: 写 app/workers/app.py(arq WorkerSettings;on_startup 初始化 engine,使 worker 进程能访问 DB)**

```python
from arq.connections import RedisSettings

from app.config import settings
from app.db.session import init_engine, create_all
from app.workers.jobs import backup_job


async def on_startup(ctx):
    init_engine(settings.sqlite_url)
    create_all()
    ctx["backup_dir"] = settings.data_dir / "backups"


class WorkerSettings:
    functions = [backup_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
```

> 注:`backup_job` 在 Task 8 创建;此处先引用会导致 import 失败。本步**先注释 `functions = [backup_job]` 行**,改为 `functions = []`,待 Task 8 写好 backup_job 后取消注释。

- [ ] **Step 4: deploy/supervisord.conf 加 worker 程序**

在 `[program:web]` 段之后追加:

```ini
[program:worker]
command=arq app.workers.app.WorkerSettings
directory=/app
autorestart=true
stdout_logfile=/data/logs/worker.log
stderr_logfile=/data/logs/worker.err.log
```

- [ ] **Step 5: 验证 import 与配置可加载(此时 functions=[] )**

Run: `.venv/bin/python -c "from app.workers.app import WorkerSettings; print(WorkerSettings.functions)"`
Expected: 打印 `[]`(或 `[<function backup_job>]` 在 Task 8 之后)。

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml app/redis_client.py app/workers/ deploy/supervisord.conf
git commit -m "feat(phase2a): arq 依赖 + Redis 客户端 + worker 骨架"
```

---

## Task 2: 适配器框架(ConnectionInfo + BackupAdapter + 注册表)

**Files:**
- Create: `app/adapters/__init__.py`, `app/adapters/base.py`
- Create: `tests/test_adapters.py`(本任务先建文件,仅放 registry 测试;argv 测试在 Task 3/4 加)

- [ ] **Step 1: 写 app/adapters/base.py**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ConnectionInfo:
    """已解密的连接信息(传给适配器执行 dump)。"""
    type: str
    host: str | None = None
    port: int | None = None
    db_name: str | None = None
    username: str | None = None
    password: str | None = None  # 明文(已用 Fernet 解出)


class BackupAdapter(Protocol):
    type: str

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        """执行 dump,把原始(未压缩)字节写入 dest_path。失败抛异常。"""
        ...


_REGISTRY: dict[str, BackupAdapter] = {}


def register_adapter(adapter: BackupAdapter) -> None:
    _REGISTRY[adapter.type] = adapter


def get_adapter(db_type: str) -> BackupAdapter:
    try:
        return _REGISTRY[db_type]
    except KeyError:
        raise ValueError(f"不支持的数据库类型: {db_type}")
```

- [ ] **Step 2: 写 app/adapters/__init__.py(注册各适配器;本任务只放 registry 导出,具体适配器 import 在 Task 3/4 加)**

```python
from app.adapters.base import ConnectionInfo, BackupAdapter, register_adapter, get_adapter

# 具体适配器在各自模块导入时自注册(Task 3/4 后取消注释):
# from app.adapters import postgres, mysql  # noqa
```

- [ ] **Step 3: 写测试 tests/test_adapters.py(registry 行为)**

```python
import pytest
from app.adapters.base import get_adapter, register_adapter


class FakeAdapter:
    type = "fake"

    def dump(self, info, dest_path):
        pass


def test_get_unknown_type_raises():
    with pytest.raises(ValueError):
        get_adapter("does-not-exist")


def test_register_and_get(monkeypatch):
    from app.adapters import base
    monkeypatch.setitem(base._REGISTRY, "fake", FakeAdapter())
    assert isinstance(get_adapter("fake"), FakeAdapter)
```

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_adapters.py -v`
Expected: 2 passed.

- [ ] **Step 5: 提交**

```bash
git add app/adapters/ tests/test_adapters.py
git commit -m "feat(phase2a): 适配器框架 + 注册表"
```

---

## Task 3: PostgreSQL 适配器(argv 单测)

**Files:**
- Create: `app/adapters/postgres.py`
- Modify: `app/adapters/__init__.py`(注册)
- Modify: `tests/test_adapters.py`(加 argv 测试)

- [ ] **Step 1: 写 app/adapters/postgres.py(argv 纯构造 + env + dump;密码走 PGPASSWORD env,绝不进 argv)**

```python
from __future__ import annotations
import os
import subprocess

from app.adapters.base import ConnectionInfo, register_adapter


class PostgresAdapter:
    type = "pg"

    def argv(self, info: ConnectionInfo) -> list[str]:
        cmd = ["pg_dump", "--no-password"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-p", str(info.port)]
        if info.username:
            cmd += ["-U", info.username]
        if info.db_name:
            cmd += [info.db_name]
        return cmd

    def env(self, info: ConnectionInfo) -> dict:
        e = os.environ.copy()
        if info.password:
            e["PGPASSWORD"] = info.password
        return e

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        with open(dest_path, "wb") as f:
            subprocess.run(
                self.argv(info),
                env=self.env(info),
                stdout=f,
                stderr=subprocess.PIPE,
                check=True,
            )


register_adapter(PostgresAdapter())
```

- [ ] **Step 2: 注册 —— app/adapters/__init__.py 取消注释**

```python
from app.adapters.base import ConnectionInfo, BackupAdapter, register_adapter, get_adapter
from app.adapters import postgres  # noqa: F401  触发注册
```

- [ ] **Step 3: 加 argv 测试到 tests/test_adapters.py**

```python
from app.adapters.postgres import PostgresAdapter
from app.adapters.base import ConnectionInfo


def test_pg_argv_includes_connection_fields():
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, db_name="shop", username="u", password="secret")
    cmd = a.argv(info)
    assert cmd[0] == "pg_dump"
    assert "-h" in cmd and "h" in cmd
    assert "-p" in cmd and "5432" in cmd
    assert "-U" in cmd and "u" in cmd
    assert "shop" in cmd


def test_pg_argv_has_no_password():
    """密码绝不能出现在命令行(防止进程列表泄露)。"""
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", password="topsecret")
    cmd = a.argv(info)
    assert "topsecret" not in cmd
    assert "--password" not in cmd


def test_pg_env_carries_password():
    a = PostgresAdapter()
    env = a.env(ConnectionInfo(type="pg", password="topsecret"))
    assert env["PGPASSWORD"] == "topsecret"
```

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_adapters.py -v`
Expected: 5 passed(2 registry + 3 pg)。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/postgres.py app/adapters/__init__.py tests/test_adapters.py
git commit -m "feat(phase2a): PostgreSQL 适配器"
```

---

## Task 4: MySQL 适配器(argv 单测;密码走 defaults-extra-file)

**Files:**
- Create: `app/adapters/mysql.py`
- Modify: `app/adapters/__init__.py`(注册), `tests/test_adapters.py`(加 mysql argv 测试)

- [ ] **Step 1: 写 app/adapters/mysql.py(argv 不含密码;dump 时写临时 defaults-extra-file,用完删除)**

```python
from __future__ import annotations
import os
import subprocess
import tempfile

from app.adapters.base import ConnectionInfo, register_adapter


class MysqlAdapter:
    type = "mysql"

    def argv(self, info: ConnectionInfo, defaults_file: str) -> list[str]:
        cmd = ["mysqldump", f"--defaults-extra-file={defaults_file}"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-P", str(info.port)]
        if info.db_name:
            cmd += [info.db_name]
        return cmd

    def _write_defaults(self, info: ConnectionInfo) -> str:
        fd, path = tempfile.mkstemp(prefix="my.", suffix=".cnf")
        lines = ["[client]"]
        if info.username:
            lines.append(f"user = {info.username}")
        if info.password:
            lines.append(f"password = {info.password}")
        if info.port:
            lines.append(f"port = {info.port}")
        if info.host:
            lines.append(f"host = {info.host}")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)
        return path

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        defaults_file = self._write_defaults(info)
        try:
            argv = self.argv(info, defaults_file)
            with open(dest_path, "wb") as f:
                subprocess.run(argv, stdout=f, stderr=subprocess.PIPE, check=True)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass


register_adapter(MysqlAdapter())
```

- [ ] **Step 2: 注册 —— app/adapters/__init__.py**

```python
from app.adapters.base import ConnectionInfo, BackupAdapter, register_adapter, get_adapter
from app.adapters import postgres, mysql  # noqa: F401
```

- [ ] **Step 3: 加 mysql argv 测试**

```python
from app.adapters.mysql import MysqlAdapter


def test_mysql_argv_uses_defaults_extra_file():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, db_name="shop", username="u", password="secret")
    cmd = a.argv(info, "/tmp/x.cnf")
    assert cmd[0] == "mysqldump"
    assert "--defaults-extra-file=/tmp/x.cnf" in cmd
    assert "-h" in cmd and "h" in cmd
    assert "-P" in cmd and "3306" in cmd
    assert "shop" in cmd


def test_mysql_argv_has_no_password():
    a = MysqlAdapter()
    cmd = a.argv(ConnectionInfo(type="mysql", password="topsecret"), "/tmp/x.cnf")
    assert "topsecret" not in cmd
    assert "secret" not in " ".join(cmd)
```

- [ ] **Step 4: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_adapters.py -v`
Expected: 7 passed。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/mysql.py app/adapters/__init__.py tests/test_adapters.py
git commit -m "feat(phase2a): MySQL 适配器(密码走 defaults-extra-file)"
```

---

## Task 5: 压缩 + 校验工具(core/archive.py)

**Files:**
- Create: `app/core/archive.py`
- Create: `tests/test_archive.py`

- [ ] **Step 1: 写 app/core/archive.py**

```python
from __future__ import annotations
import gzip
import hashlib
import shutil
from pathlib import Path


def compress_file(src: Path | str, dest: Path | str) -> None:
    """gzip 压缩 src → dest。"""
    with open(src, "rb") as fin, gzip.open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def sha256_of_file(path: Path | str) -> str:
    """计算文件内容的 SHA-256(用于完整性校验)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 2: 写测试 tests/test_archive.py**

```python
import gzip
from pathlib import Path
from app.core.archive import compress_file, sha256_of_file


def test_compress_then_gunzip_roundtrips(tmp_path):
    src = tmp_path / "a.sql"
    src.write_bytes(b"CREATE TABLE t (id int);\n")
    dest = tmp_path / "a.sql.gz"
    compress_file(src, dest)
    assert dest.exists()
    with gzip.open(dest, "rb") as f:
        assert f.read() == b"CREATE TABLE t (id int);\n"


def test_sha256_stable_and_distinct(tmp_path):
    a = tmp_path / "a"
    a.write_bytes(b"hello")
    b = tmp_path / "b"
    b.write_bytes(b"world")
    assert sha256_of_file(a) == sha256_of_file(a)  # 稳定
    assert sha256_of_file(a) != sha256_of_file(b)  # 不同内容不同摘要
    assert len(sha256_of_file(a)) == 64
```

- [ ] **Step 3: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_archive.py -v`
Expected: 2 passed.

- [ ] **Step 4: 提交**

```bash
git add app/core/archive.py tests/test_archive.py
git commit -m "feat(phase2a): gzip 压缩 + sha256 校验工具"
```

---

## Task 6: 进度上报 + 取消标志(workers/progress.py)

**Files:**
- Create: `app/workers/progress.py`
- Create: `tests/test_progress.py`

- [ ] **Step 1: 写 app/workers/progress.py(可注入 redis 客户端便于测试;频道与取消键以 record_id 为锚)**

```python
from __future__ import annotations
import json
import redis

from app.config import settings


def _channel(record_id: int) -> str:
    return f"job:{record_id}"


def _cancel_key(record_id: int) -> str:
    return f"cancel:{record_id}"


class ProgressReporter:
    """向 Redis pub/sub 上报进度;同时提供取消检查。"""

    def __init__(self, record_id: int, client: redis.Redis | None = None):
        self.record_id = record_id
        self._client = client or redis.Redis.from_url(settings.redis_url)

    def report(self, stage: str, detail: str = "") -> None:
        self._client.publish(
            _channel(self.record_id),
            json.dumps({"stage": stage, "detail": detail}),
        )

    def is_cancelled(self) -> bool:
        return bool(self._client.exists(_cancel_key(self.record_id)))


def request_cancel(record_id: int, client: redis.Redis | None = None) -> None:
    (client or redis.Redis.from_url(settings.redis_url)).set(_cancel_key(record_id), "1")
```

- [ ] **Step 2: 写测试 tests/test_progress.py(用伪造客户端,不依赖真实 Redis)**

```python
import json
from app.workers.progress import ProgressReporter, request_cancel


class FakeRedis:
    def __init__(self):
        self.published = []
        self._store = {}

    def publish(self, channel, msg):
        self.published.append((channel, msg))
        return 0

    def exists(self, key):
        return key in self._store

    def set(self, key, val):
        self._store[key] = val


def test_report_publishes_to_record_channel():
    fake = FakeRedis()
    ProgressReporter(42, fake).report("dump", "exporting")
    assert fake.published == [("job:42", json.dumps({"stage": "dump", "detail": "exporting"}))]


def test_cancel_flag_roundtrip():
    fake = FakeRedis()
    r = ProgressReporter(7, fake)
    assert r.is_cancelled() is False
    request_cancel(7, fake)
    assert r.is_cancelled() is True
```

- [ ] **Step 3: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_progress.py -v`
Expected: 2 passed.

- [ ] **Step 4: 提交**

```bash
git add app/workers/progress.py tests/test_progress.py
git commit -m "feat(phase2a): 进度上报 + 取消标志(Redis pub/sub)"
```

---

## Task 7: backup_service.run_backup 编排(TDD 用伪造适配器)

**Files:**
- Create: `app/services/backup_service.py`
- Create: `tests/test_backup_service.py`

- [ ] **Step 1: 写 app/services/backup_service.py**

```python
from __future__ import annotations
import os
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord
from app.core.crypto import Crypto
from app.core.archive import compress_file, sha256_of_file
from app.adapters.base import ConnectionInfo, get_adapter
from app.workers.progress import ProgressReporter


def _conn_info(conn: DbConnection, crypto: Crypto) -> ConnectionInfo:
    return ConnectionInfo(
        type=conn.type,
        host=conn.host,
        port=conn.port,
        db_name=conn.db_name,
        username=conn.username,
        password=_decrypt(conn.password_enc, crypto),
    )


def _decrypt(enc: str | None, crypto: Crypto) -> str | None:
    return crypto.decrypt(enc) if enc else None


def run_backup(
    db: Session,
    crypto: Crypto,
    conn: DbConnection,
    trigger: str,
    reporter: ProgressReporter,
    backup_dir: Path,
    now_fn=datetime.utcnow,
    sleep_fn=time.sleep,
) -> BackupRecord:
    """执行一次备份:建记录(running)→ dump → 压缩 → 校验 → 更新(success/failed/cancelled)。
    每阶段上报进度,阶段间隙检查取消标志。失败捕获异常并写入 error。"""
    record = BackupRecord(connection_id=conn.id, trigger=trigger, status="running", started_at=now_fn())
    db.add(record)
    db.commit()
    db.refresh(record)

    def _check_cancel():
        if reporter.is_cancelled():
            record.status = "cancelled"
            record.finished_at = now_fn()
            db.commit()
            db.refresh(record)
            reporter.report("cancelled")
            return True
        return False

    raw_path = backup_dir / f"{conn.type}_{conn.id}_{record.id}.sql"
    gz_path = backup_dir / f"{conn.type}_{conn.id}_{record.id}.sql.gz"
    start = time.monotonic()
    try:
        if _check_cancel():
            return record

        reporter.report("dump")
        adapter = get_adapter(conn.type)
        adapter.dump(_conn_info(conn, crypto), str(raw_path))

        if _check_cancel():
            _safe_remove(raw_path)
            return record

        reporter.report("compress")
        compress_file(raw_path, gz_path)
        _safe_remove(raw_path)
        size = os.path.getsize(gz_path)
        checksum = sha256_of_file(gz_path)

        record.file_path = str(gz_path.relative_to(backup_dir))
        record.size = size
        record.checksum = checksum
        record.status = "success"
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(record)
        reporter.report("success")
        return record
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(record)
        reporter.report("failed", str(exc))
        return record


def _safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
```

- [ ] **Step 2: 写测试 tests/test_backup_service.py(伪造适配器 + 伪造 redis reporter;断言 success / failed / cancelled 三态)**

```python
from pathlib import Path
from app.db.session import init_engine, create_all, _SessionLocal
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.backup_service import run_backup
from app.workers.progress import ProgressReporter


class FakeAdapter:
    type = "pg"

    def __init__(self, content: bytes = b"-- dump\n"):
        self.content = content

    def dump(self, info, dest_path):
        with open(dest_path, "wb") as f:
            f.write(self.content)


class FakeRedis:
    def __init__(self, cancelled=False):
        self.published = []
        self._cancelled = cancelled

    def publish(self, channel, msg):
        self.published.append((channel, msg))

    def exists(self, key):
        return self._cancelled

    def set(self, k, v):
        self._cancelled = True


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: FakeAdapter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _SessionLocal()
    conn = DbConnection(name="c", type="pg", host="h", port=5432, db_name="d",
                        username="u", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    return db, conn, crypto, tmp_path / "backups"


def test_run_backup_success(tmp_path, monkeypatch):
    db, conn, crypto, bdir = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    reporter = ProgressReporter(conn.id, FakeRedis())
    rec = run_backup(db, crypto, conn, "manual", reporter, bdir)
    assert rec.status == "success"
    assert rec.checksum and len(rec.checksum) == 64
    assert rec.size and rec.size > 0
    assert rec.file_path and rec.file_path.endswith(".sql.gz")
    assert (bdir / rec.file_path).exists()
    db.close()


def test_run_backup_failed(tmp_path, monkeypatch):
    db, conn, crypto, bdir = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    class BoomAdapter(FakeAdapter):
        def dump(self, info, dest): raise RuntimeError("pg_dump not found")
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: BoomAdapter())
    reporter = ProgressReporter(conn.id, FakeRedis())
    rec = run_backup(db, crypto, conn, "manual", reporter, bdir)
    assert rec.status == "failed"
    assert "pg_dump not found" in rec.error
    db.close()


def test_run_backup_cancelled(tmp_path, monkeypatch):
    db, conn, crypto, bdir = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    reporter = ProgressReporter(conn.id, FakeRedis(cancelled=True))
    rec = run_backup(db, crypto, conn, "manual", reporter, bdir)
    assert rec.status == "cancelled"
    db.close()
```

- [ ] **Step 3: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_backup_service.py -v`
Expected: 3 passed.

- [ ] **Step 4: 提交**

```bash
git add app/services/backup_service.py tests/test_backup_service.py
git commit -m "feat(phase2a): backup_service 编排(成功/失败/取消三态)"
```

---

## Task 8: arq backup_job(串联 engine+crypto+service+reporter)

**Files:**
- Create: `app/workers/jobs.py`
- Modify: `app/workers/app.py`(取消 functions 注释)

- [ ] **Step 1: 写 app/workers/jobs.py**

```python
from __future__ import annotations
import asyncio

from app.bootstrap import bootstrap_keys
from app.core.crypto import Crypto
from app.db.models import DbConnection
from app.db.session import _SessionLocal
from app.services.backup_service import run_backup
from app.workers.progress import ProgressReporter


def _run_backup_sync(ctx, connection_id: int, trigger: str, record_id: int) -> dict:
    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    db = _SessionLocal()
    try:
        conn = db.get(DbConnection, connection_id)
        if conn is None:
            raise ValueError(f"连接不存在: {connection_id}")
        reporter = ProgressReporter(record_id)
        rec = run_backup(db, crypto, conn, trigger, reporter, ctx["backup_dir"])
        return {"record_id": rec.id, "status": rec.status}
    finally:
        db.close()


async def backup_job(ctx, connection_id: int, trigger: str = "manual", record_id: int = 0) -> dict:
    return await asyncio.to_thread(_run_backup_sync, ctx, connection_id, trigger, record_id)
```

> 注:`record_id` 由 Web 侧在 enqueue 时传入(见 Task 9),作为进度频道与取消锚点。worker 用 `ctx["backup_dir"]`(on_startup 设置)。

- [ ] **Step 2: 取消 app/workers/app.py 的 functions 注释**

```python
    functions = [backup_job]
```

- [ ] **Step 3: 验证 import 与 WorkerSettings 可加载**

Run: `.venv/bin/python -c "from app.workers.app import WorkerSettings; print([f.__name__ for f in WorkerSettings.functions])"`
Expected: 打印 `['backup_job']`。

- [ ] **Step 4: 加一个轻量测试 —— 直接调同步入口验证串联(伪造适配器,不依赖真实 redis/arq)**

追加到 `tests/test_backup_service.py`(复用其 fixtures)—— 实际为 jobs 写单独验证:把以下加到 `tests/test_jobs.py`:

```python
import asyncio
from pathlib import Path
from app.db.session import init_engine, create_all, _SessionLocal
import app.db.models  # noqa
from app.db.models import DbConnection
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.workers.jobs import _run_backup_sync


class FakeAdapter:
    type = "pg"
    def dump(self, info, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"-- dump\n")


def test_run_backup_sync_wires_service(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: FakeAdapter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    crypto = Crypto(Fernet.generate_key())
    db = _SessionLocal()
    conn = DbConnection(name="c", type="pg", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    conn_id = conn.id
    db.close()

    class FakeReporter:
        def report(self, *a, **k): pass
        def is_cancelled(self): return False
    monkeypatch.setattr("app.workers.jobs.ProgressReporter", lambda rid: FakeReporter())

    ctx = {"backup_dir": bdir}
    result = _run_backup_sync(ctx, conn_id, "manual", conn_id)
    assert result["status"] == "success"
```

Run: `.venv/bin/python -m pytest tests/test_jobs.py -v`
Expected: 1 passed.

- [ ] **Step 5: 提交**

```bash
git add app/workers/jobs.py app/workers/app.py tests/test_jobs.py
git commit -m "feat(phase2a): arq backup_job 串联 engine+crypto+service"
```

---

## Task 9: 任务/备份 API(run / jobs / cancel / events SSE / files)

**Files:**
- Create: `app/schemas/job.py`
- Create: `app/routers/jobs.py`, `app/routers/backups.py`
- Modify: `app/main.py`(startup 建 arq pool → app.state.arq;include 两路由)
- Create: `tests/test_jobs_api.py`, `tests/test_backups_api.py`

- [ ] **Step 1: 写 app/schemas/job.py**

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class JobRunResponse(BaseModel):
    record_id: int
    status: str


class JobOut(BaseModel):
    id: int
    connection_id: int
    trigger: str
    status: str
    stage: str | None = None
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class BackupFileOut(BaseModel):
    id: int
    connection_id: int
    status: str
    file_path: str | None
    size: int | None
    checksum: str | None
    duration_ms: int | None
    started_at: datetime
    finished_at: datetime | None
```

- [ ] **Step 2: 写 app/routers/jobs.py**

```python
from __future__ import annotations
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import BackupRecord, DbConnection
from app.deps import get_current_account
from app.schemas.job import JobRunResponse, JobOut
from app.workers.progress import request_cancel

router = APIRouter()


async def _get_arq(app):
    """惰性创建 arq 连接池(测试里可直接覆盖 app.state.arq)。"""
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        app.state.arq = await create_pool(settings.redis_url)
    return app.state.arq


@router.post("/backups/run", response_model=JobRunResponse, status_code=201)
async def run_now(payload: dict, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    conn_id = payload.get("connection_id")
    trigger = payload.get("trigger", "manual")
    conn = db.get(DbConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    record = BackupRecord(connection_id=conn.id, trigger=trigger, status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    arq = await _get_arq(request.app)
    await arq.enqueue_job("backup_job", conn.id, trigger, record.id)
    return JobRunResponse(record_id=record.id, status=record.status)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), _=Depends(get_current_account)):
    rows = db.query(BackupRecord).filter(BackupRecord.status == "running").order_by(BackupRecord.id.desc()).all()
    return [JobOut(id=r.id, connection_id=r.connection_id, trigger=r.trigger, status=r.status,
                   started_at=r.started_at, finished_at=r.finished_at, error=r.error) for r in rows]


@router.post("/jobs/{record_id}/cancel")
def cancel(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    request_cancel(record_id)
    return {"ok": True}


@router.get("/jobs/{record_id}/events")
async def events(record_id: int, _=Depends(get_current_account)):
    """SSE:订阅 job:{record_id} 频道,流式返回进度。"""
    from app.redis_client import get_async_redis
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"job:{record_id}")

    async def gen():
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                    yield f"data: {data}\n\n"
                    if json.loads(data).get("stage") in ("success", "failed", "cancelled"):
                        return
        finally:
            await pubsub.unsubscribe(f"job:{record_id}")
            await pubsub.close()

    from fastapi.responses import StreamingResponse
    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [ ] **Step 3: 写 app/routers/backups.py(列表/下载/删除;严格路径校验防穿越)**

```python
from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import BackupRecord
from app.deps import get_current_account
from app.schemas.job import BackupFileOut

router = APIRouter()


def _backup_dir() -> Path:
    return settings.data_dir / "backups"


def _resolve(record: BackupRecord) -> Path:
    """安全解析备份文件路径,防穿越。"""
    base = _backup_dir().resolve()
    path = (base / record.file_path).resolve() if record.file_path else None
    if path is None or base not in path.parents and path != base:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return path


@router.get("/backups", response_model=list[BackupFileOut])
def list_backups(db: Session = Depends(get_db), _=Depends(get_current_account)):
    rows = db.query(BackupRecord).order_by(BackupRecord.id.desc()).all()
    return rows


@router.get("/backups/{record_id}/download")
def download(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    path = _resolve(rec)
    return FileResponse(path, filename=path.name)


@router.delete("/backups/{record_id}", status_code=204)
def delete_backup(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        path = _resolve(rec)
        path.unlink()
    except HTTPException:
        pass  # 文件已不在也允许删记录
    db.delete(rec); db.commit()
```

- [ ] **Step 4: 改 app/main.py —— include jobs + backups 路由;设置 `app.state.arq = None`(惰性建池)**

① import 增加 `jobs, backups`。② 在 `create_app()` 内(SessionMiddleware 之后)加一行 `app.state.arq = None`。③ include 两路由:
```python
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    app.include_router(backups.router, prefix="/api/v1", tags=["backups"])
```

> **不用 lifespan**:Phase 1 的 create_app 是同步的,且 TestClient 启动时 lifespan 会强连真实 Redis(测试环境没有,会失败/挂起)。改为**惰性建池** —— `run_now` 端点首次需要时才 `await create_pool(...)`,见 Step 2 的 `_get_arq`。测试里直接 `authed.app.state.arq = FakeArq()` 注入伪造池,跳过真实连接。Phase 1 的同步 bootstrap+init_engine+create_all 逻辑保留在 create_app 内不动。

- [ ] **Step 5: 写测试 tests/test_jobs_api.py(run 建记录 + 鉴权 + jobs 列表 + cancel)**

```python
import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(DbConnection(name="c", type="pg"))
        db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


class FakeArq:
    def __init__(self):
        self.enqueued = []
    async def enqueue_job(self, *args):
        self.enqueued.append(args)


def test_run_requires_auth(client):
    assert client.post("/api/v1/backups/run", json={"connection_id": 1}).status_code == 401


def test_run_creates_record_and_enqueues(authed, monkeypatch):
    fake = FakeArq()
    authed.app.state.arq = fake
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    conn_id = db.query(DbConnection).first().id
    db.close()
    r = authed.post("/api/v1/backups/run", json={"connection_id": conn_id})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running"
    assert fake.enqueued and fake.enqueued[0][0] == "backup_job"


def test_list_jobs_and_cancel(authed, monkeypatch):
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    db = _session._SessionLocal()
    conn_id = db.query(DbConnection).first().id
    db.add(BackupRecord(connection_id=conn_id, trigger="manual", status="running"))
    db.commit(); db.close()
    listed = authed.get("/api/v1/jobs").json()
    assert len(listed) == 1
    assert authed.post("/api/v1/jobs/1/cancel").json() == {"ok": True}
```

Run: `.venv/bin/python -m pytest tests/test_jobs_api.py -v`
Expected: 3 passed.

- [ ] **Step 6: 写测试 tests/test_backups_api.py(列表/下载/删除 + 鉴权 + 路径穿越拒绝)**

```python
import pytest
from app.db.session import _SessionLocal
from app.db.models import BackupRecord
from app.config import settings


@pytest.fixture
def authed(client):
    from app.services.account_service import ensure_account
    db = _SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def _make_record(file_relpath="pg_1_1.sql.gz", content=b"x"):
    bdir = settings.data_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / file_relpath).write_bytes(content)
    db = _SessionLocal()
    rec = BackupRecord(connection_id=1, trigger="manual", status="success",
                       file_path=file_relpath, size=len(content), checksum="c")
    db.add(rec); db.commit(); db.refresh(rec)
    rid = rec.id
    db.close()
    return rid


def test_list_and_download(authed):
    rid = _make_record()
    listed = authed.get("/api/v1/backups").json()
    assert any(b["id"] == rid for b in listed)
    r = authed.get(f"/api/v1/backups/{rid}/download")
    assert r.status_code == 200
    assert r.content == b"x"


def test_delete(authed):
    rid = _make_record()
    assert authed.delete(f"/api/v1/backups/{rid}").status_code == 204
    assert authed.get(f"/api/v1/backups/{rid}/download").status_code == 404


def test_traversal_rejected(authed):
    rid = _make_record()
    db = _SessionLocal()
    rec = db.get(BackupRecord, rid)
    rec.file_path = "../../etc/passwd"  # 试图逃逸
    db.commit(); db.close()
    assert authed.get(f"/api/v1/backups/{rid}/download").status_code == 404
```

Run: `.venv/bin/python -m pytest tests/test_backups_api.py -v`
Expected: 3 passed.

- [ ] **Step 7: 运行全部测试,确认无回归**

Run: `.venv/bin/python -m pytest -v`
Expected: 全 PASS。

- [ ] **Step 8: 提交**

```bash
git add app/schemas/job.py app/routers/jobs.py app/routers/backups.py app/main.py tests/test_jobs_api.py tests/test_backups_api.py
git commit -m "feat(phase2a): 任务/备份 API(run/jobs/cancel/SSE/文件列表下载删除)"
```

---

## Phase 2a 完成标准(Definition of Done)

- `pytest -v` 全绿(含 adapters/archive/progress/backup_service/jobs/backups API 测试)。
- 端到端可走通(需真实 Redis + PG):添加连接 → `POST /api/v1/backups/run` → `GET /api/v1/jobs/{id}/events` 看到 dump/compress/success → `GET /api/v1/backups/{id}/download` 下载到 `.sql.gz`,SHA-256 校验一致。
- 取消可工作:`POST /api/v1/jobs/{id}/cancel` → 记录变 cancelled。
- 安全:所有新端点鉴权;适配器密码不进 argv;下载防路径穿越;子进程无 shell。

## 留给 Plan 2b / Phase 3+

- APScheduler 定时(cron → enqueue backup_job)→ Plan 2b。
- 保留策略清理(RetentionJob)→ Plan 2b 或独立。
- 恢复 / 云同步 / 富仪表盘 / 更多数据库类型 → Phase 4-6。
- 真实 DB 往返契约测试(testcontainers)→ 可选加固。

---

*自检:self-review 完成。spec 覆盖:本计划对应设计文档 §8(任务执行模型)与 §9 ④(适配器,本阶段 PG/MySQL)。类型一致:`run_backup`、`ProgressReporter`、`get_adapter`、`_run_backup_sync` 跨任务签名一致;`record_id` 作为统一锚点贯穿 API/job/进度/取消/SSE。*
