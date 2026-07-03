# Phase 4 — 一键恢复 (Restore) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 master spec §9① 的"一键恢复":从一份成功备份还原到任意目标连接,服务端校验 SHA-256 完整性,经 arq 异步执行,通过 SSE(restore 命名空间)实时推送 verify/decompress/restore 阶段进度,可取消;前端提供 Restore.vue(危险操作强制输入连接名二次确认)。

**Architecture:** 完全复用 Phase 2a 已验证的备份管线模式 —— 新增 `RestoreRecord` 表 + `restore_service.run_restore`(校验→解压→还原三态 + 取消)、`restore_job` worker、`/restore` 路由(SSE/cancel 复刻 `/jobs`)。关键安全点:`BackupRecord` 与 `RestoreRecord` 是两张独立表,id 序列各自递增,直接复用 `job:{id}` 频道会撞车,因此给 `ProgressReporter`/`request_cancel` 增加 `kind` 命名空间(默认 `"job"` 保持备份行为零变化,恢复用 `"restore"`)。适配器层在 `BackupAdapter` 协议上新增 `restore(info, src_path)`,PG 用 `psql -f`、MySQL 用 `mysql < file`。

**Tech Stack:** FastAPI + SQLAlchemy + arq + Redis pub/sub + Vue3 + Naive UI + EventSource(SSE)。

**前置:** Phase 1–3b 已完成并验证(59 测试绿,前端构建通过)。本计划只新增恢复能力,不改动已验证的备份主流程行为(仅给 progress 加可选参数)。

---

## 环境运行说明(本机执行环境)

执行 agent 在本机同一环境运行,需注意以下工具链事实:

- **后端依赖**已安装到用户站点(`~/.local`),直接 `python3 -m pytest` 即可;无需 sudo。
- **pip 受 SOCKS 代理影响**:任何 pip 调用前先 `unset ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy`。
- **Node/npm** 位于 `/tmp/node-v20.18.1-linux-x64/bin`(不在默认 PATH),前端命令前需 `export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH"`。

---

## 文件结构

**后端(新增/修改):**
- 修改 `app/db/models.py` — 新增 `RestoreRecord` 表模型。
- 新增 `app/schemas/restore.py` — `RestoreRequest` / `RestoreRunResponse` / `RestoreOut`。
- 修改 `app/workers/progress.py` — 给频道/取消键加 `kind` 命名空间(默认 `"job"`)。
- 修改 `app/core/archive.py` — 新增 `decompress_file`(gunzip)。
- 修改 `app/adapters/base.py` — `BackupAdapter` 协议新增 `restore` 方法。
- 修改 `app/adapters/postgres.py` — 实现 `restore`(psql -f)。
- 修改 `app/adapters/mysql.py` — 实现 `restore`(mysql < file)。
- 新增 `app/services/restore_service.py` — `run_restore`(校验→解压→还原 + 取消 + 终态)。
- 修改 `app/workers/jobs.py` — 新增 `_run_restore_sync` + `restore_job`。
- 修改 `app/workers/app.py` — `WorkerSettings.functions` 注册 `restore_job`。
- 新增 `app/routers/restore.py` — `POST /restore`、`GET /restore`、`GET /restore/{id}/events`(SSE)、`POST /restore/{id}/cancel`。
- 修改 `app/main.py` — 挂载 restore 路由。

**后端测试(新增/修改):**
- 修改 `tests/test_models.py` — expected 表集合加 `restore_records`。
- 修改 `tests/test_progress.py` — 加 restore 命名空间隔离测试。
- 修改 `tests/test_archive.py` — 加 `decompress_file` 往返测试。
- 修改 `tests/test_adapters.py` — 加 PG/MySQL restore argv 测试。
- 新增 `tests/test_restore_service.py` — service 成功/校验失败/取消/未知记录 + worker 串联。
- 新增 `tests/test_restore_api.py` — 鉴权/建记录入队/拒绝非 success 备份/列表+取消。

**前端(新增/修改):**
- 新增 `frontend/src/api/restore.ts` — REST + `eventsUrl`。
- 修改 `frontend/src/composables/useJobStream.ts` — `subscribe` 接受可选 `urlFor` 构造器。
- 新增 `frontend/src/views/Restore.vue` — 选备份+选目标+二次确认+进度抽屉+历史表。
- 修改 `frontend/src/router/index.ts` — 加 `/restore` 路由。
- 修改 `frontend/src/layouts/AppLayout.vue` — 侧栏加"恢复"菜单项。

---

## Tasks

### Task 1: RestoreRecord 模型 + schemas

**Files:**
- Modify: `app/db/models.py`(文件末尾追加 `RestoreRecord`)
- Create: `app/schemas/restore.py`
- Test: `tests/test_models.py`(更新 expected 集合)

- [ ] **Step 1: 写失败测试 —— 表被创建 + 字段持久化往返**

修改 `tests/test_models.py`,把 expected 集合扩为含 `restore_records`,并加一个持久化往返测试:

```python
from sqlalchemy import inspect
from app.db.session import init_engine, create_all, _SessionLocal
import app.db.models  # noqa  确保模型已注册


def test_all_tables_created(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    from app.db.session import _engine  # init_engine 之后才非 None
    inspector = inspect(_engine)
    tables = set(inspector.get_table_names())
    expected = {"account", "db_connections", "schedules", "backup_records",
                "restore_records", "system_logs"}
    assert expected.issubset(tables)


def test_restore_record_persists(tmp_path):
    from datetime import datetime
    from app.db.models import DbConnection, BackupRecord, RestoreRecord
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          started_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    rec = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn.id,
                        status="running", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    got = db.get(RestoreRecord, rec.id)
    assert got is not None
    assert got.backup_record_id == backup.id
    assert got.status == "running"
    db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: FAIL —— `ImportError: cannot import name 'RestoreRecord'`(模型尚未定义),且 `restore_records` 不在表集合中。

- [ ] **Step 3: 实现 RestoreRecord 模型**

在 `app/db/models.py` 文件末尾(`SystemLog` 之后)追加:

```python
class RestoreRecord(Base):
    __tablename__ = "restore_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backup_record_id: Mapped[int] = mapped_column(ForeignKey("backup_records.id", ondelete="CASCADE"), nullable=False)
    target_connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # running/success/failed/cancelled
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

> 说明:`ForeignKey`/`Text`/`Integer`/`String`/`DateTime` 均已在文件顶部 import;`datetime` 已 import;`Base` 来自 `app.db.session`。无需新增 import。

- [ ] **Step 4: 实现 schemas/restore.py**

创建 `app/schemas/restore.py`:

```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class RestoreRequest(BaseModel):
    backup_record_id: int
    target_connection_id: int


class RestoreRunResponse(BaseModel):
    record_id: int
    status: str


class RestoreOut(BaseModel):
    id: int
    backup_record_id: int
    target_connection_id: int
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: PASS(2 个测试)。

- [ ] **Step 6: 提交**

```bash
git add app/db/models.py app/schemas/restore.py tests/test_models.py
git commit -m "feat(phase4): RestoreRecord 模型 + restore schemas"
```

---

### Task 2: progress.py 频道命名空间(kind)

**Files:**
- Modify: `app/workers/progress.py`
- Test: `tests/test_progress.py`(新增隔离测试,已有 2 个测试保持不变)

> 设计要点:`client` 必须仍是第 2 个位置参数(现有 `test_progress.py` 以 `ProgressReporter(42, fake)` / `request_cancel(7, fake)` 调用),`kind` 放在其后并给默认值 `"job"`,这样备份主流程行为与现有测试零变化;恢复用 `kind="restore"`。

- [ ] **Step 1: 写失败测试 —— restore 命名空间与 job 隔离**

在 `tests/test_progress.py` 末尾追加:

```python
def test_restore_namespace_is_isolated():
    fake = FakeRedis()
    ProgressReporter(5, fake, kind="restore").report("verify")
    ProgressReporter(5, fake).report("dump")
    channels = [ch for ch, _ in fake.published]
    assert "restore:5" in channels
    assert "job:5" in channels
    # 同一 record_id 不同命名空间互不干扰
    request_cancel(5, fake, kind="restore")
    assert ProgressReporter(5, fake, kind="restore").is_cancelled() is True
    assert ProgressReporter(5, fake).is_cancelled() is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_progress.py::test_restore_namespace_is_isolated -v`
Expected: FAIL —— `TypeError: ProgressReporter.__init__() got an unexpected keyword argument 'kind'`。

- [ ] **Step 3: 重写 progress.py 加入 kind**

用以下内容**整体替换** `app/workers/progress.py`:

```python
from __future__ import annotations
import json
import redis

from app.config import settings


def _channel(record_id: int, kind: str = "job") -> str:
    return f"{kind}:{record_id}"


def _cancel_key(record_id: int, kind: str = "job") -> str:
    return f"{kind}:cancel:{record_id}"


class ProgressReporter:
    """向 Redis pub/sub 上报进度;同时提供取消检查。

    kind 区分备份(job)/恢复(restore)频道 —— 两张记录表 id 各自递增,
    不加命名空间会撞车(backup id=5 与 restore id=5 共用 job:5)。"""

    def __init__(self, record_id: int, client: redis.Redis | None = None, kind: str = "job"):
        self.record_id = record_id
        self.kind = kind
        self._client = client or redis.Redis.from_url(settings.redis_url)

    def report(self, stage: str, detail: str = "") -> None:
        self._client.publish(
            _channel(self.record_id, self.kind),
            json.dumps({"stage": stage, "detail": detail}),
        )

    def is_cancelled(self) -> bool:
        return bool(self._client.exists(_cancel_key(self.record_id, self.kind)))


def request_cancel(record_id: int, client: redis.Redis | None = None, kind: str = "job") -> None:
    (client or redis.Redis.from_url(settings.redis_url)).set(_cancel_key(record_id, kind), "1")
```

> 行为变化说明:备份的取消键由 `cancel:{id}` 变为 `job:cancel:{id}`(写/读均走默认 kind,内部自洽,无持久化依赖);频道名 `job:{id}` 不变,故 `test_report_publishes_to_record_channel` 与 `test_cancel_flag_roundtrip` 仍绿。

- [ ] **Step 4: 跑全套 progress 测试确认通过**

Run: `python3 -m pytest tests/test_progress.py -v`
Expected: PASS(3 个测试,含原有 2 个)。

- [ ] **Step 5: 提交**

```bash
git add app/workers/progress.py tests/test_progress.py
git commit -m "feat(phase4): progress 加 kind 命名空间(默认 job,restore 隔离)"
```

---

### Task 3: archive.decompress_file(gunzip)

**Files:**
- Modify: `app/core/archive.py`(追加 `decompress_file`)
- Test: `tests/test_archive.py`(追加往返测试)

- [ ] **Step 1: 写失败测试 —— 压缩后解压还原一致**

在 `tests/test_archive.py` 末尾追加:

```python
from app.core.archive import compress_file, decompress_file


def test_decompress_roundtrips_compress(tmp_path):
    raw = tmp_path / "a.sql"
    raw.write_bytes(b"CREATE TABLE t (id int);\nINSERT INTO t VALUES (1);\n")
    gz = tmp_path / "a.sql.gz"
    out = tmp_path / "out.sql"
    compress_file(raw, gz)
    decompress_file(gz, out)
    assert out.read_bytes() == raw.read_bytes()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_archive.py::test_decompress_roundtrips_compress -v`
Expected: FAIL —— `ImportError: cannot import name 'decompress_file'`。

- [ ] **Step 3: 实现 decompress_file**

在 `app/core/archive.py` 的 `sha256_of_file` 之后追加:

```python
def decompress_file(src: Path | str, dest: Path | str) -> None:
    """gzip 解压 src → dest(还原出原始未压缩 dump,供 restore 喂入适配器)。"""
    with gzip.open(src, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)
```

> `gzip` / `shutil` / `Path` 均已在文件顶部 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_archive.py -v`
Expected: PASS(含新增 + 原有测试)。

- [ ] **Step 5: 提交**

```bash
git add app/core/archive.py tests/test_archive.py
git commit -m "feat(phase4): archive 新增 decompress_file(gunzip)"
```

---

### Task 4: 适配器 restore 方法

**Files:**
- Modify: `app/adapters/base.py`(`BackupAdapter` 协议加 `restore`)
- Modify: `app/adapters/postgres.py`(实现 `restore` + `restore_argv`)
- Modify: `app/adapters/mysql.py`(实现 `restore` + `restore_argv`)
- Test: `tests/test_adapters.py`(追加 PG/MySQL restore argv 测试)

- [ ] **Step 1: 写失败测试 —— PG/MySQL restore 命令构造 + 无密码泄漏**

在 `tests/test_adapters.py` 末尾追加:

```python
def test_pg_restore_argv_uses_psql_file_flag():
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/dump.sql")
    assert cmd[0] == "psql"
    assert "-f" in cmd and "/tmp/dump.sql" in cmd
    assert "-d" in cmd and "shop" in cmd
    assert "secret" not in cmd


def test_mysql_restore_argv_uses_defaults_extra_file():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/x.cnf")
    assert cmd[0] == "mysql"
    assert "--defaults-extra-file=/tmp/x.cnf" in cmd
    assert "shop" in cmd


def test_mysql_restore_pipes_file_into_stdin(monkeypatch, tmp_path):
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", db_name="shop", username="u", password="topsecret")
    src = tmp_path / "dump.sql"
    src.write_bytes(b"SELECT 1;\n")
    seen = {}

    def fake_run(argv, *a, **k):
        seen["argv"] = argv
        seen["stdin"] = k.get("stdin")
        return None

    monkeypatch.setattr("app.adapters.mysql.subprocess.run", fake_run)
    a.restore(info, str(src))
    assert seen["argv"][0] == "mysql"
    assert seen["stdin"] is not None          # 从文件喂入 stdin
    assert not any("topsecret" in str(c) for c in seen["argv"])  # 密码不在 argv(走 cnf)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_adapters.py -v`
Expected: FAIL —— `AttributeError: 'PostgresAdapter' object has no attribute 'restore_argv'`。

- [ ] **Step 3: base.py 协议加 restore 方法**

在 `app/adapters/base.py` 的 `BackupAdapter` 协议里,`dump` 方法之后追加:

```python
    def restore(self, info: ConnectionInfo, src_path: str) -> None:
        """从 src_path(未压缩的原始 dump)执行还原。失败抛异常。"""
        ...
```

- [ ] **Step 4: postgres.py 实现 restore**

在 `app/adapters/postgres.py` 的 `PostgresAdapter.dump` 方法之后追加:

```python
    def restore_argv(self, info: ConnectionInfo, src_path: str) -> list[str]:
        cmd = ["psql", "--no-password"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-p", str(info.port)]
        if info.username:
            cmd += ["-U", info.username]
        if info.db_name:
            cmd += ["-d", info.db_name]
        cmd += ["-f", src_path]
        return cmd

    def restore(self, info: ConnectionInfo, src_path: str) -> None:
        subprocess.run(
            self.restore_argv(info, src_path),
            env=self.env(info),
            stderr=subprocess.PIPE,
            check=True,
        )
```

> `pg_dump` 默认输出纯文本 SQL,`psql -f file` 执行该文件即完成还原;密码仍走 `env()` 的 `PGPASSWORD`,不经 argv。

- [ ] **Step 5: mysql.py 实现 restore**

在 `app/adapters/mysql.py` 的 `MysqlAdapter.dump` 方法之后、`register_adapter(...)` 之前追加:

```python
    def restore_argv(self, info: ConnectionInfo, defaults_file: str) -> list[str]:
        cmd = ["mysql", f"--defaults-extra-file={defaults_file}"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-P", str(info.port)]
        if info.db_name:
            cmd += [info.db_name]
        return cmd

    def restore(self, info: ConnectionInfo, src_path: str) -> None:
        defaults_file = self._write_defaults(info)
        try:
            argv = self.restore_argv(info, defaults_file)
            with open(src_path, "rb") as f:
                subprocess.run(argv, stdin=f, stderr=subprocess.PIPE, check=True)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass
```

> `mysqldump` 产出的 SQL 流喂给 `mysql`(经 stdin)即还原;密码走 `defaults-extra-file` 临时文件,用后即删。

- [ ] **Step 6: 跑测试确认通过**

Run: `python3 -m pytest tests/test_adapters.py -v`
Expected: PASS(含新增 3 个 + 原有测试)。

- [ ] **Step 7: 提交**

```bash
git add app/adapters/base.py app/adapters/postgres.py app/adapters/mysql.py tests/test_adapters.py
git commit -m "feat(phase4): 适配器 restore 方法(psql -f / mysql < file)"
```

---

### Task 5: restore_service.run_restore

**Files:**
- Create: `app/services/restore_service.py`
- Test: `tests/test_restore_service.py`(service 层)

- [ ] **Step 1: 写失败测试**

创建 `tests/test_restore_service.py`:

```python
import json
from datetime import datetime

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.core.crypto import Crypto
from app.core.archive import compress_file, sha256_of_file
from cryptography.fernet import Fernet
from app.services.restore_service import run_restore
from app.workers.progress import ProgressReporter


class FakeRestoreAdapter:
    type = "pg"

    def __init__(self):
        self.restored = None

    def restore(self, info, src_path):
        with open(src_path, "rb") as f:
            self.restored = f.read()


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


def _setup(tmp_path, monkeypatch, adapter=None):
    """建 DB + 连接 + 一份真实 success 备份(含 gz+checksum) + 一条 running 恢复记录。"""
    monkeypatch.setattr("app.services.restore_service.get_adapter",
                        lambda t: adapter or FakeRestoreAdapter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", host="h", port=5432, db_name="d",
                        username="u", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    bdir = tmp_path / "backups"; bdir.mkdir()
    raw = bdir / "pg.sql"; raw.write_bytes(b"-- dump\n")
    gz_name = "pg_1_1.sql.gz"; gz = bdir / gz_name
    compress_file(raw, gz)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path=gz_name, size=gz.stat().st_size,
                          checksum=sha256_of_file(gz),
                          started_at=datetime.utcnow(), finished_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    restore = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn.id,
                            status="running", started_at=datetime.utcnow())
    db.add(restore); db.commit(); db.refresh(restore)
    return db, conn, crypto, bdir, backup, restore.id


def test_run_restore_success(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    fake = FakeRedis()
    rec = run_restore(db, crypto, backup, conn, ProgressReporter(rid, fake), bdir, rid)
    assert rec.status == "success"
    assert rec.duration_ms is not None
    stages = [json.loads(m)["stage"] for _, m in fake.published]
    assert stages == ["verify", "decompress", "restore", "success"]
    db.close()


def test_run_restore_checksum_mismatch(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    (bdir / backup.file_path).write_bytes(b"tampered")  # 篡改使 checksum 不匹配
    fake = FakeRedis()
    rec = run_restore(db, crypto, backup, conn, ProgressReporter(rid, fake), bdir, rid)
    assert rec.status == "failed"
    assert "校验和" in rec.error
    db.close()


def test_run_restore_cancelled_before(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    rec = run_restore(db, crypto, backup, conn,
                      ProgressReporter(rid, FakeRedis(cancelled=True)), bdir, rid)
    assert rec.status == "cancelled"
    db.close()


def test_run_restore_unknown_record_raises(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    import pytest
    with pytest.raises(ValueError):
        run_restore(db, crypto, backup, conn, ProgressReporter(rid, FakeRedis()), bdir, 999999)
    db.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_restore_service.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.restore_service'`。

- [ ] **Step 3: 实现 restore_service.py**

创建 `app/services/restore_service.py`:

```python
from __future__ import annotations
import os
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.core.crypto import Crypto
from app.core.archive import decompress_file, sha256_of_file
from app.adapters.base import get_adapter
from app.services.backup_service import _conn_info
from app.workers.progress import ProgressReporter


def _safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def run_restore(
    db: Session,
    crypto: Crypto,
    backup_record: BackupRecord,
    target_conn: DbConnection,
    reporter: ProgressReporter,
    backup_dir: Path,
    restore_record_id: int,
    now_fn=datetime.utcnow,
) -> RestoreRecord:
    """对一条已存在的 running 恢复记录执行:校验 → 解压 → 还原,并写入终态。

    校验阶段比对备份文件 SHA-256 与记录 checksum(完整性护栏,不一致即失败)。
    记录由调用方(Web API)预先创建,restore_record_id 同时作为进度频道与取消锚点。
    每阶段上报进度,阶段间隙检查取消;失败捕获异常;中间 raw 文件统一在 finally 清理。"""
    restore_record = db.get(RestoreRecord, restore_record_id)
    if restore_record is None:
        raise ValueError(f"恢复记录不存在: {restore_record_id}")
    if restore_record.started_at is None:
        restore_record.started_at = now_fn()
    db.commit()

    raw_path = backup_dir / f"restore_{restore_record_id}.sql"
    start = time.monotonic()

    def _check_cancel():
        if reporter.is_cancelled():
            restore_record.status = "cancelled"
            restore_record.finished_at = now_fn()
            restore_record.duration_ms = int((time.monotonic() - start) * 1000)
            db.commit()
            db.refresh(restore_record)
            reporter.report("cancelled")
            return True
        return False

    try:
        if _check_cancel():
            return restore_record

        # 1. 完整性校验
        reporter.report("verify")
        if not backup_record.file_path:
            raise FileNotFoundError("备份记录无文件路径")
        backup_path = (backup_dir / backup_record.file_path).resolve()
        base = backup_dir.resolve()
        if backup_path != base and base not in backup_path.parents:
            raise ValueError("备份文件路径非法")
        if not backup_path.exists():
            raise FileNotFoundError("备份文件不存在")
        if backup_record.checksum and sha256_of_file(backup_path) != backup_record.checksum:
            raise ValueError("校验和不匹配,备份文件可能损坏")

        if _check_cancel():
            return restore_record

        # 2. 解压
        reporter.report("decompress")
        decompress_file(backup_path, raw_path)

        if _check_cancel():
            return restore_record

        # 3. 还原
        reporter.report("restore")
        adapter = get_adapter(target_conn.type)
        adapter.restore(_conn_info(target_conn, crypto), str(raw_path))

        restore_record.status = "success"
        restore_record.finished_at = now_fn()
        restore_record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(restore_record)
        reporter.report("success")
        return restore_record
    except Exception as exc:
        restore_record.status = "failed"
        restore_record.error = str(exc)
        restore_record.finished_at = now_fn()
        restore_record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(restore_record)
        reporter.report("failed", str(exc))
        return restore_record
    finally:
        _safe_remove(raw_path)
```

> `_conn_info` 直接复用 `backup_service` 的实现(DRY),逻辑完全一致(解密密码 + 组装 ConnectionInfo)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_restore_service.py -v`
Expected: PASS(4 个测试)。

- [ ] **Step 5: 提交**

```bash
git add app/services/restore_service.py tests/test_restore_service.py
git commit -m "feat(phase4): restore_service(校验/解压/还原 + 取消三态)"
```

---

### Task 6: worker restore_job + 注册

**Files:**
- Modify: `app/workers/jobs.py`(新增 `_run_restore_sync` + `restore_job`)
- Modify: `app/workers/app.py`(注册到 `WorkerSettings.functions`)
- Test: `tests/test_restore_service.py`(追加 worker 串联测试)

- [ ] **Step 1: 写失败测试 —— worker 串联 service**

在 `tests/test_restore_service.py` 末尾追加:

```python
def test_run_restore_sync_wires_service(monkeypatch, tmp_path):
    from app.workers.jobs import _run_restore_sync
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("secret", key))
    monkeypatch.setattr("app.services.restore_service.get_adapter", lambda t: FakeRestoreAdapter())

    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    crypto = Crypto(key.encode("ascii"))
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    raw = bdir / "pg.sql"; raw.write_bytes(b"-- dump\n")
    gz_name = "pg_1_1.sql.gz"; gz = bdir / gz_name
    compress_file(raw, gz)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path=gz_name, size=gz.stat().st_size,
                          checksum=sha256_of_file(gz),
                          started_at=datetime.utcnow(), finished_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    restore = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn.id,
                            status="running", started_at=datetime.utcnow())
    db.add(restore); db.commit(); db.refresh(restore)
    bid, cid, rid = backup.id, conn.id, restore.id
    db.close()

    class FakeReporter:
        def report(self, *a, **k): pass
        def is_cancelled(self): return False

    # worker 内构造 ProgressReporter(rid, kind="restore");打桩需接受 kind kwarg
    monkeypatch.setattr("app.workers.jobs.ProgressReporter", lambda rid, **kw: FakeReporter())
    ctx = {"backup_dir": bdir}
    result = _run_restore_sync(ctx, bid, cid, rid)
    assert result["status"] == "success"
    assert result["record_id"] == rid
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_restore_service.py::test_run_restore_sync_wires_service -v`
Expected: FAIL —— `ImportError: cannot import name '_run_restore_sync'`。

- [ ] **Step 3: 实现 worker restore_job**

在 `app/workers/jobs.py` 末尾追加(并在顶部 import 区补充 `BackupRecord`/`RestoreRecord`/`run_restore`):

顶部 import 调整 —— 把现有的:
```python
from app.db.models import DbConnection
from app.db import session as _session
from app.services.backup_service import run_backup
from app.workers.progress import ProgressReporter
```
改为:
```python
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.db import session as _session
from app.services.backup_service import run_backup
from app.services.restore_service import run_restore
from app.workers.progress import ProgressReporter
```

在文件末尾(`backup_job` 之后)追加:

```python
def _run_restore_sync(ctx, backup_record_id: int, target_connection_id: int, restore_record_id: int) -> dict:
    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    db = _session._SessionLocal()
    try:
        backup_record = db.get(BackupRecord, backup_record_id)
        if backup_record is None:
            raise ValueError(f"备份记录不存在: {backup_record_id}")
        target_conn = db.get(DbConnection, target_connection_id)
        if target_conn is None:
            raise ValueError(f"目标连接不存在: {target_connection_id}")
        reporter = ProgressReporter(restore_record_id, kind="restore")
        rec = run_restore(db, crypto, backup_record, target_conn, reporter, ctx["backup_dir"], restore_record_id)
        return {"record_id": rec.id, "status": rec.status}
    finally:
        db.close()


async def restore_job(ctx, backup_record_id: int, target_connection_id: int, restore_record_id: int) -> dict:
    return await asyncio.to_thread(_run_restore_sync, ctx, backup_record_id, target_connection_id, restore_record_id)
```

> `ProgressReporter(restore_record_id, kind="restore")` —— 恢复走 restore 命名空间,与备份频道的 id 撞车彻底隔离。`asyncio`/`bootstrap_keys`/`Crypto` 已在文件顶部 import。

- [ ] **Step 4: 注册 restore_job 到 WorkerSettings**

修改 `app/workers/app.py`,把:
```python
from app.workers.jobs import backup_job
```
改为:
```python
from app.workers.jobs import backup_job, restore_job
```
并把:
```python
    functions = [backup_job]
```
改为:
```python
    functions = [backup_job, restore_job]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_restore_service.py tests/test_jobs.py -v`
Expected: PASS(restore service 5 个测试 + 原有 backup worker 测试不变)。

- [ ] **Step 6: 提交**

```bash
git add app/workers/jobs.py app/workers/app.py tests/test_restore_service.py
git commit -m "feat(phase4): restore_job worker + 注册到 WorkerSettings"
```

---

### Task 7: /restore 路由 + 挂载

**Files:**
- Create: `app/routers/restore.py`
- Modify: `app/main.py`(挂载路由)
- Test: `tests/test_restore_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_restore_api.py`:

```python
import pytest
from datetime import datetime


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    from app.db.models import DbConnection, BackupRecord
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        conn = DbConnection(name="c", type="pg")
        db.add(conn); db.commit(); db.refresh(conn)
        backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                              file_path="pg.sql.gz", checksum="x", started_at=datetime.utcnow())
        db.add(backup); db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


class FakeArq:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, *args):
        self.enqueued.append(args)
        return None


def test_restore_requires_auth(client):
    r = client.post("/api/v1/restore", json={"backup_record_id": 1, "target_connection_id": 1})
    assert r.status_code == 401


def test_restore_creates_record_and_enqueues(authed):
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import BackupRecord, DbConnection
    db = _session._SessionLocal()
    backup_id = db.query(BackupRecord).first().id
    conn_id = db.query(DbConnection).first().id
    db.close()
    r = authed.post("/api/v1/restore", json={"backup_record_id": backup_id, "target_connection_id": conn_id})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running"
    assert authed.app.state.arq.enqueued
    assert authed.app.state.arq.enqueued[0][0] == "restore_job"
    # ("restore_job", backup_id, conn_id, restore_id) — 4 元素
    assert len(authed.app.state.arq.enqueued[0]) == 4


def test_restore_rejects_non_success_backup(authed):
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import BackupRecord, DbConnection
    db = _session._SessionLocal()
    conn_id = db.query(DbConnection).first().id
    failed = BackupRecord(connection_id=conn_id, trigger="manual", status="failed", started_at=datetime.utcnow())
    db.add(failed); db.commit(); fid = failed.id
    db.close()
    r = authed.post("/api/v1/restore", json={"backup_record_id": fid, "target_connection_id": conn_id})
    assert r.status_code == 400


def test_list_and_cancel(authed, monkeypatch):
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import BackupRecord, DbConnection, RestoreRecord
    db = _session._SessionLocal()
    backup = db.query(BackupRecord).first()
    conn_id = db.query(DbConnection).first().id
    rec = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn_id,
                        status="running", started_at=datetime.utcnow())
    db.add(rec); db.commit(); rid = rec.id; db.close()
    listed = authed.get("/api/v1/restore").json()
    assert any(r["id"] == rid for r in listed)
    # request_cancel 会连真实 redis;打桩使端点幂等可测(需接受 kind kwarg)
    monkeypatch.setattr("app.routers.restore.request_cancel", lambda record_id, **kw: None)
    assert authed.post(f"/api/v1/restore/{rid}/cancel").json() == {"ok": True}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_restore_api.py -v`
Expected: FAIL —— 路由不存在,`404`(TestClient 对未挂载路由返回 404)。

- [ ] **Step 3: 实现 routers/restore.py**

创建 `app/routers/restore.py`:

```python
from __future__ import annotations
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import config
from app.db.session import get_db
from app.db.models import BackupRecord, DbConnection, RestoreRecord
from app.deps import get_current_account
from app.schemas.restore import RestoreRequest, RestoreRunResponse, RestoreOut
from app.workers.progress import request_cancel

router = APIRouter()


async def _get_arq(app):
    """惰性创建 arq 连接池(测试里可直接覆盖 app.state.arq)。"""
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        app.state.arq = await create_pool(config.settings.redis_url)
    return app.state.arq


@router.post("/restore", response_model=RestoreRunResponse, status_code=201)
async def run_restore_route(payload: RestoreRequest, request: Request,
                            db: Session = Depends(get_db), _=Depends(get_current_account)):
    backup = db.get(BackupRecord, payload.backup_record_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if backup.status != "success" or not backup.file_path:
        raise HTTPException(status_code=400, detail="该备份不可用于恢复")
    target = db.get(DbConnection, payload.target_connection_id)
    if target is None:
        raise HTTPException(status_code=404, detail="目标连接不存在")
    record = RestoreRecord(backup_record_id=backup.id, target_connection_id=target.id,
                           status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    arq = await _get_arq(request.app)
    await arq.enqueue_job("restore_job", backup.id, target.id, record.id)
    return RestoreRunResponse(record_id=record.id, status=record.status)


@router.get("/restore", response_model=list[RestoreOut])
def list_restores(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(RestoreRecord).order_by(RestoreRecord.id.desc()).all()


@router.post("/restore/{record_id}/cancel")
def cancel_restore(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(RestoreRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="恢复任务不存在")
    request_cancel(record_id, kind="restore")
    return {"ok": True}


@router.get("/restore/{record_id}/events")
async def restore_events(record_id: int, _=Depends(get_current_account)):
    from app.redis_client import get_async_redis
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"restore:{record_id}")

    async def gen():
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                    yield f"data: {data}\n\n"
                    try:
                        if json.loads(data).get("stage") in ("success", "failed", "cancelled"):
                            return
                    except Exception:
                        pass
        finally:
            await pubsub.unsubscribe(f"restore:{record_id}")
            await pubsub.close()

    return StreamingResponse(gen(), media_type="text/event-stream")
```

> SSE/cancel 端点复刻 `routers/jobs.py`,仅频道名换 `restore:{id}`、取消键走 `kind="restore"`,与 worker 的 `ProgressReporter(rid, kind="restore")` 自洽。

- [ ] **Step 4: main.py 挂载路由**

修改 `app/main.py`:
- 把 `from app.routers import health, auth, connections, jobs, backups, schedules, dashboard` 改为追加 `restore`:
```python
from app.routers import health, auth, connections, jobs, backups, schedules, dashboard, restore
```
- 在 `app.include_router(dashboard.router, ...)` 之后追加:
```python
    app.include_router(restore.router, prefix="/api/v1", tags=["restore"])
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_restore_api.py -v`
Expected: PASS(4 个测试)。

- [ ] **Step 6: 跑后端全套回归**

Run: `python3 -m pytest -q`
Expected: 全绿(原 59 + 新增,总数应 ≥ 70,无回归)。

- [ ] **Step 7: 提交**

```bash
git add app/routers/restore.py app/main.py tests/test_restore_api.py
git commit -m "feat(phase4): /restore 路由(run/list/events SSE/cancel)+ 挂载"
```

---

### Task 8: 前端 api/restore.ts + useJobStream 泛化

**Files:**
- Create: `frontend/src/api/restore.ts`
- Modify: `frontend/src/composables/useJobStream.ts`(`subscribe` 加可选 `urlFor`)
- (无独立前端测试,Task 10 的 `npm run build` 统一校验类型)

- [ ] **Step 1: 新增 api/restore.ts**

创建 `frontend/src/api/restore.ts`:

```ts
import client from './client'

export interface Restore {
  id: number
  backup_record_id: number
  target_connection_id: number
  status: string
  error: string | null
  started_at: string
  finished_at: string | null
  duration_ms: number | null
}

export const runRestore = (backup_record_id: number, target_connection_id: number) =>
  client.post<{ record_id: number; status: string }>('/restore', { backup_record_id, target_connection_id })
export const listRestores = () => client.get<Restore[]>('/restore')
export const cancelRestore = (id: number) => client.post(`/restore/${id}/cancel`)
export const eventsUrl = (id: number) => `/api/v1/restore/${id}/events`
```

- [ ] **Step 2: useJobStream.subscribe 加可选 urlFor**

把 `frontend/src/composables/useJobStream.ts` 的 `subscribe` 函数签名与第一行改为:

```ts
  function subscribe(recordId: number, urlFor: (id: number) => string = (id) => `/api/v1/jobs/${id}/events`) {
    close()
    events.value = []
    status.value = 'running'
    es = new EventSource(urlFor(recordId), { withCredentials: true })
```

> 其余函数体不变(仍 `es.onmessage` / `es.onerror` 等)。默认 `urlFor` 生成 jobs URL,故 `Backups.vue` 现有 `subscribe(r.data.record_id)` 调用零改动。

- [ ] **Step 3: 暂不提交(与 Task 9 一起)**

> 类型正确性留待 Task 10 的 `vue-tsc` 统一校验;此处不单独提交,避免中间态引用了尚未创建的 `Restore.vue` 之外的孤立改动。

---

### Task 9: Restore.vue + 路由 + 菜单

**Files:**
- Create: `frontend/src/views/Restore.vue`
- Modify: `frontend/src/router/index.ts`(加 `/restore`)
- Modify: `frontend/src/layouts/AppLayout.vue`(侧栏加"恢复")

- [ ] **Step 1: 新增 Restore.vue**

创建 `frontend/src/views/Restore.vue`:

```vue
<script setup lang="ts">
import { ref, h, computed, onMounted, onUnmounted } from 'vue'
import {
  NCard, NDataTable, NSelect, NSpace, NButton, NDrawer, NDrawerContent,
  NTag, NModal, NInput, NSteps, NStep, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as bkApi from '../api/backups'
import type { BackupFile } from '../api/backups'
import * as connApi from '../api/connections'
import type { Connection } from '../api/connections'
import * as rsApi from '../api/restore'
import type { Restore } from '../api/restore'
import { useJobStream } from '../composables/useJobStream'

const msg = useMessage()
const backups = ref<BackupFile[]>([])
const conns = ref<Connection[]>([])
const restores = ref<Restore[]>([])
const selectedBackup = ref<number | null>(null)
const selectedConn = ref<number | null>(null)
const showConfirm = ref(false)
const confirmText = ref('')
const showProgress = ref(false)
const currentRestoreId = ref<number | null>(null)
const { events, status, subscribe } = useJobStream()
let pollTimer: number | undefined

const successBackups = computed(() => backups.value.filter(b => b.status === 'success'))
function connLabel(id: number) { return conns.value.find(c => c.id === id)?.name ?? `#${id}` }
const backupOptions = () => successBackups.value.map(b => ({
  label: `#${b.id} · ${connLabel(b.connection_id)} · ${fmtBytes(b.size)}`,
  value: b.id,
}))
const connOptions = () => conns.value.map(c => ({ label: `${c.name} (${c.type})`, value: c.id }))
const targetConn = computed(() => conns.value.find(c => c.id === selectedConn.value))
const canSubmit = computed(() => selectedBackup.value != null && selectedConn.value != null)
const confirmMatches = computed(() => targetConn.value != null && confirmText.value === targetConn.value.name)

async function load() {
  const [b, c, r] = await Promise.all([bkApi.listBackups(), connApi.listConnections(), rsApi.listRestores()])
  backups.value = b.data; conns.value = c.data; restores.value = r.data
}

function openConfirm() {
  if (selectedBackup.value == null) { msg.warning('请先选择备份'); return }
  if (selectedConn.value == null) { msg.warning('请先选择目标连接'); return }
  confirmText.value = ''
  showConfirm.value = true
}

async function doRestore() {
  if (selectedBackup.value == null || selectedConn.value == null || !confirmMatches.value) return
  showConfirm.value = false
  try {
    const r = await rsApi.runRestore(selectedBackup.value, selectedConn.value)
    currentRestoreId.value = r.data.record_id
    showProgress.value = true
    subscribe(r.data.record_id, rsApi.eventsUrl)
    poll()
  } catch (e: any) { msg.error(e.response?.data?.detail || '启动恢复失败') }
}

function poll() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    await load()
    if (['success', 'failed', 'cancelled'].includes(status.value)) {
      window.clearInterval(pollTimer); pollTimer = undefined
    }
  }, 2000)
}

async function cancelCurrent() {
  if (currentRestoreId.value == null) return
  await rsApi.cancelRestore(currentRestoreId.value)
  msg.success('已请求取消')
  await load()
}

const STAGES = ['verify', 'decompress', 'restore', 'success']
function currentStep() {
  if (status.value === 'success') return STAGES.length
  if (status.value === 'failed') {
    return STAGES.indexOf(events.value.filter(e => e.stage !== 'failed').slice(-1)[0]?.stage ?? '') + 1
  }
  const last = events.value.filter(e => STAGES.includes(e.stage)).slice(-1)[0]?.stage
  return last ? STAGES.indexOf(last) + 1 : 0
}

const fmtBytes = (n?: number | null) => { if (!n) return '—'; const u = ['B','KB','MB','GB']; const i = Math.floor(Math.log(n)/Math.log(1024)); return (n/Math.pow(1024,i)).toFixed(1)+' '+u[i] }
const fmtMs = (ms?: number | null) => (ms == null ? '—' : (ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`))
const statusTag = (s: string) => {
  const m: Record<string, 'success'|'warning'|'error'|'info'|'default'> = { success:'success', failed:'error', running:'info', cancelled:'default' }
  return h(NTag, { type: m[s] || 'default', size: 'small', bordered: false }, { default: () => s })
}

const restoreColumns: DataTableColumns<Restore> = [
  { title: '记录', key: 'id' },
  { title: '源备份', key: 'backup_record_id' },
  { title: '目标连接', key: 'target_connection_id', render: r => connLabel(r.target_connection_id) },
  { title: '状态', key: 'status', render: r => statusTag(r.status) },
  { title: '耗时', key: 'duration_ms', render: r => fmtMs(r.duration_ms) },
  { title: '错误', key: 'error', ellipsis: { tooltip: true } },
]

onMounted(load)
onUnmounted(() => { if (pollTimer) window.clearInterval(pollTimer) })
</script>

<template>
  <n-space vertical :size="16">
    <n-card title="一键恢复" :bordered="false">
      <n-space vertical :size="12">
        <n-space align="center">
          <n-select v-model:value="selectedBackup" :options="backupOptions()" placeholder="选择一份成功备份" style="width:380px" filterable />
        </n-space>
        <n-space align="center">
          <n-select v-model:value="selectedConn" :options="connOptions()" placeholder="选择目标连接" style="width:380px" filterable />
          <n-button type="error" :disabled="!canSubmit" @click="openConfirm">恢复</n-button>
        </n-space>
        <n-text depth="3">恢复会把备份写入目标连接并覆盖同名数据,操作不可撤销;执行前服务端会校验 SHA-256 完整性。</n-text>
      </n-space>
    </n-card>

    <n-card title="恢复历史" :bordered="false">
      <n-data-table :columns="restoreColumns" :data="restores" :bordered="false" />
    </n-card>
  </n-space>

  <n-modal v-model:show="showConfirm" preset="card" title="危险操作确认" style="width:460px">
    <n-space vertical :size="12">
      <n-text>即将把备份恢复到目标连接 <b>{{ targetConn?.name }}</b>,<b>覆盖同名数据</b>。</n-text>
      <n-text depth="3">请输入目标连接名 <b>{{ targetConn?.name }}</b> 以确认:</n-text>
      <n-input v-model:value="confirmText" placeholder="输入连接名" />
      <n-button type="error" block :disabled="!confirmMatches" @click="doRestore">确认恢复</n-button>
    </n-space>
  </n-modal>

  <n-drawer v-model:show="showProgress" :width="420" placement="right">
    <n-drawer-content title="恢复进度" closable>
      <n-steps
        :current="currentStep()"
        :status="status === 'failed' ? 'error' : (status === 'success' ? 'finish' : 'process')"
      >
        <n-step title="完整性校验 (verify)" />
        <n-step title="解压 (decompress)" />
        <n-step title="还原 (restore)" />
        <n-step title="完成 (success)" />
      </n-steps>
      <div style="margin-top:16px">
        <n-space align="center" justify="space-between">
          <n-text depth="3">实时日志:</n-text>
          <n-button size="small" :disabled="!['success','failed','cancelled'].includes(status)" @click="cancelCurrent">取消</n-button>
        </n-space>
        <div class="log">
          <div v-for="(e, i) in events" :key="i">
            • {{ e.stage }} <span v-if="e.detail" style="opacity:.6">— {{ e.detail }}</span>
          </div>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.log { margin-top: 8px; font-family: ui-monospace, monospace; font-size: 13px; max-height: 300px; overflow: auto; }
</style>
```

- [ ] **Step 2: router 加 /restore**

修改 `frontend/src/router/index.ts`,在 `{ path: 'backups', ... }` 之后追加一行:

```ts
        { path: 'restore', component: () => import('../views/Restore.vue') },
```

- [ ] **Step 3: 侧栏加"恢复"菜单项**

修改 `frontend/src/layouts/AppLayout.vue` 的 `menuOptions`,在 `{ label: '备份', key: 'backups' }` 之后追加:

```ts
  { label: '恢复', key: 'restore' },
```

- [ ] **Step 4: 暂不提交(与 Task 10 一起校验后提交)**

---

### Task 10: 全量校验 + 提交前端

**Files:** 无(仅运行校验 + 提交 Task 8/9 的前端改动)

- [ ] **Step 1: 后端全量测试**

Run:
```bash
unset ALL_PROXY all_proxy HTTPS_PROXY https_proxy HTTP_PROXY http_proxy
python3 -m pytest -q
```
Expected: 全绿(原 59 + Phase 4 新增,总数 ≥ 70)。

- [ ] **Step 2: 前端类型检查 + 构建**

Run:
```bash
export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH"
npm --prefix frontend run build
```
Expected: `vue-tsc` 无类型错误,`vite build` 成功(输出 `dist/`,build 完成)。

- [ ] **Step 3: 提交前端改动**

```bash
git add frontend/src/api/restore.ts frontend/src/composables/useJobStream.ts frontend/src/views/Restore.vue frontend/src/router/index.ts frontend/src/layouts/AppLayout.vue
git commit -m "feat(phase4): Restore.vue(二次确认+SSE进度)+ 路由/菜单/api"
```

---

## Phase 4 完成标准

- 后端全套测试绿(≥ 70,含 restore service/api/adapter/progress/archive/models 新增,且原 59 无回归)。
- `npm run build` 通过(vue-tsc 类型检查 + vite 构建)。
- 恢复链路自洽:`POST /restore` → `restore_job`(restore 命名空间)→ SSE `restore:{id}`;cancel 写 `restore:cancel:{id}`,worker 读同一键。
- 安全护栏到位:服务端 SHA-256 校验(完整性)、前端强制输入连接名二次确认(防误操作)、仅 `status=success` 备份可恢复。

## 留给后续 Phase

- **"恢复前先备份当前数据"可选开关**(spec §9① 第三项护栏):需在 restore 前先触发一次目标连接的 backup_job 并等待其完成,再执行 restore。逻辑链路较长,单列后续。
- **更多 DB 适配器的 restore**(MongoDB `mongorestore` / Redis rdb 替换 / SQLite 文件替换):随"更多数据库适配器"Phase 一起补。
- **端到端验证**:需真实 Redis + 真实 PG/MySQL 容器跑一次 dump→restore 往返(本轮用单测 + 适配器命令构造测试覆盖)。

---

*本计划由 writing-plans 流程产出,基于已确认的 master spec(2026-07-02-full-rewrite-design.md)。*
