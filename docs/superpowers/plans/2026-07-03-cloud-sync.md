# 云存储同步 (Cloud Sync, S3/MinIO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 实现 master spec §9② 的"云存储同步"(MVP):用 S3 兼容适配器(经 minio SDK,主供 MinIO,亦兼容 AWS S3/R2/B2)把一份成功备份上传到该连接配置的云目标;支持云目标 CRUD + 连接测试 + 手动触发同步(arq 异步)+ 前端 CloudSync.vue 管理。

**Architecture:** 新增 `cloud/` 适配器层(策略模式,镜像 `adapters/`)——`StorageAdapter` 接口(upload/delete/test)+ `s3.py`(minio SDK)。`cloud_destinations`/`sync_targets` 两表存配置(凭据 Fernet 加密)。`sync_service` 把备份文件上传到该连接所有启用目标;`sync_job` worker 异步执行并写 SystemLog;`/cloud-destinations`、`/sync-targets`、`/sync/run` 路由;前端管理页。

**Tech Stack:** minio SDK (S3 协议) + FastAPI + SQLAlchemy + arq + Vue3/Naive UI。

**关键决策(用户已定 + 文档化的 MVP 边界):**
- **S3 适配器主供 MinIO**(用户指定),兼容所有 S3 协议存储;endpoint 存 `host:port`,secure 决定 https。
- 凭据(access_key/secret)Fernet 加密落库,**响应 schema 绝不回传**。
- 同步为**手动触发** `POST /sync/run`,arq 异步执行;**本轮不做** 同步 SSE 进度抽屉、备份成功后自动同步、OSS/COS 独立适配器、real-MinIO E2E(单测用 fake 客户端覆盖逻辑)。

**前置:** Phase 1–4 + DB 适配器已完成。`minio>=7.2` 已加入 pyproject 并安装。

---

## 文件结构

**后端:**
- Modify `app/db/models.py` — `CloudDestination`、`SyncTarget` 表
- Create `app/schemas/cloud.py` — 云目标/sync-target/sync-run schemas
- Create `app/cloud/base.py` — `CloudConfig` + `StorageAdapter` 协议 + 注册表
- Create `app/cloud/s3.py` — MinIO/S3 适配器(minio SDK)
- Create `app/cloud/__init__.py` — 导出 + 注册 s3
- Create `app/services/sync_service.py` — `run_sync`(上传到所有目标)
- Modify `app/workers/jobs.py` — `_run_sync_sync` + `sync_job`
- Modify `app/workers/app.py` — 注册 `sync_job`
- Create `app/routers/cloud.py` — `/cloud-destinations`(CRUD+test)、`/sync-targets`(CRUD)、`/sync/run`
- Modify `app/main.py` — 挂载 cloud 路由

**前端:**
- Create `frontend/src/api/cloud.ts`
- Create `frontend/src/views/CloudSync.vue` + 路由 + 菜单

**测试:** test_models、test_cloud(新)、test_sync_service(新)、test_jobs、test_cloud_api(新)

---

## Tasks

### Task 1: CloudDestination / SyncTarget 模型 + schemas

**Files:** Modify `app/db/models.py`; Create `app/schemas/cloud.py`; Test `tests/test_models.py`

- [ ] **Step 1: 写失败测试** —— 在 `tests/test_models.py` 的 `expected` 集合加 `"cloud_destinations", "sync_targets"`,并追加:
```python
def test_cloud_tables_persist(tmp_path):
    from datetime import datetime
    from app.db.models import DbConnection, CloudDestination, SyncTarget
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    from app.db.session import _SessionLocal  # init_engine 之后才非 None
    db = _SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    dest = CloudDestination(name="minio", provider="s3", endpoint="localhost:9000",
                            bucket="bk", access_key_enc="AK", secret_enc="SK", prefix="",
                            secure=False, enabled=True)
    db.add(dest); db.commit(); db.refresh(dest)
    tgt = SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True)
    db.add(tgt); db.commit(); db.refresh(tgt)
    assert db.get(CloudDestination, dest.id).bucket == "bk"
    assert db.get(SyncTarget, tgt.id).cloud_destination_id == dest.id
    db.close()
```
(把 `expected` 改为:`{"account","db_connections","schedules","backup_records","restore_records","cloud_destinations","sync_targets","system_logs"}`)

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_models.py -v` → FAIL(表/类不存在)。

- [ ] **Step 3: 实现模型** —— 在 `app/db/models.py` 末尾(`RestoreRecord` 之后)追加:
```python
class CloudDestination(Base):
    __tablename__ = "cloud_destinations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)   # s3
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)  # host:port
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    access_key_enc: Mapped[str] = mapped_column(Text, nullable=False)   # Fernet 密文
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)       # Fernet 密文
    prefix: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    secure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SyncTarget(Base):
    __tablename__ = "sync_targets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    cloud_destination_id: Mapped[int] = mapped_column(ForeignKey("cloud_destinations.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

- [ ] **Step 4: 实现 schemas** —— 创建 `app/schemas/cloud.py`:
```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class CloudDestinationCreate(BaseModel):
    name: str
    provider: str = "s3"
    endpoint: str
    region: str | None = None
    bucket: str
    access_key: str
    secret: str
    prefix: str = ""
    secure: bool = True
    enabled: bool = True


class CloudDestinationOut(BaseModel):
    id: int
    name: str
    provider: str
    endpoint: str
    region: str | None
    bucket: str
    prefix: str
    secure: bool
    enabled: bool
    created_at: datetime
    # 注意:不含 access_key / secret —— 永不回传

    model_config = {"from_attributes": True}


class SyncTargetCreate(BaseModel):
    connection_id: int
    cloud_destination_id: int
    enabled: bool = True


class SyncTargetOut(BaseModel):
    id: int
    connection_id: int
    cloud_destination_id: int
    enabled: bool

    model_config = {"from_attributes": True}


class SyncRunRequest(BaseModel):
    backup_record_id: int
```

- [ ] **Step 5: 跑测试确认通过** —— `python3 -m pytest tests/test_models.py -v` → PASS。

- [ ] **Step 6: 提交** —— `git add app/db/models.py app/schemas/cloud.py tests/test_models.py && git commit -m "feat(cloud-sync): CloudDestination/SyncTarget 模型 + schemas"`

---

### Task 2: cloud 适配器层(base + s3/MinIO)

**Files:** Create `app/cloud/base.py`, `app/cloud/s3.py`, `app/cloud/__init__.py`; Test `tests/test_cloud.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_cloud.py`:
```python
import pytest
from app.cloud.base import CloudConfig, get_storage, register_storage


class FakeMinio:
    """模拟 minio.Minio:记录上传/删除,内存存对象。"""
    def __init__(self, endpoint, access_key=None, secret_key=None, secure=True, region=None):
        self.endpoint = endpoint
        self.objects = {}

    def fput_object(self, bucket, key, path):
        with open(path, "rb") as f:
            self.objects[(bucket, key)] = f.read()
        return key

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)

    def bucket_exists(self, bucket):
        return True


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_storage("nope")


def test_s3_upload_returns_uri_and_prefixes_key(monkeypatch, tmp_path):
    monkeypatch.setattr("app.cloud.s3.Minio", FakeMinio)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    f = tmp_path / "b.gz"
    f.write_bytes(b"payload")
    cfg = CloudConfig(endpoint="localhost:9000", access_key="ak", secret_key="sk",
                      bucket="bk", region=None, secure=False, prefix="pre")
    uri = a.upload(cfg, str(f), "b.gz")
    assert uri == "s3://bk/pre/b.gz"


def test_s3_delete_removes_object(monkeypatch):
    monkeypatch.setattr("app.cloud.s3.Minio", FakeMinio)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    cfg = CloudConfig(endpoint="h:9000", access_key="ak", secret_key="sk", bucket="bk", prefix="")
    # 先放一个对象再删
    a._client(cfg).objects[("bk", "x.gz")] = b"x"
    a.delete(cfg, "x.gz")
    assert ("bk", "x.gz") not in a._client(cfg).objects


def test_s3_test_raises_when_bucket_missing(monkeypatch):
    class NoBucket(FakeMinio):
        def bucket_exists(self, bucket): return False
    monkeypatch.setattr("app.cloud.s3.Minio", NoBucket)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    with pytest.raises(ValueError):
        a.test(CloudConfig(endpoint="h:9000", access_key="ak", secret_key="sk", bucket="missing"))
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_cloud.py -v` → FAIL(模块不存在)。

- [ ] **Step 3: 实现 base.py** —— 创建 `app/cloud/base.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CloudConfig:
    """已解密的云存储配置(传给适配器执行上传/删除)。"""
    endpoint: str          # host:port(无 scheme)
    access_key: str
    secret_key: str
    bucket: str
    region: str | None = None
    secure: bool = True
    prefix: str = ""


class StorageAdapter(Protocol):
    provider: str

    def upload(self, cfg: CloudConfig, local_path: str, key: str) -> str:
        """上传 local_path 到云,key 为对象名。返回 remote_uri。失败抛异常。"""
        ...

    def delete(self, cfg: CloudConfig, key: str) -> None:
        """删除对象。失败抛异常。"""
        ...

    def test(self, cfg: CloudConfig) -> None:
        """连接/凭据/桶存在性校验。失败抛异常。"""
        ...


_REGISTRY: dict[str, StorageAdapter] = {}


def register_storage(adapter: StorageAdapter) -> None:
    _REGISTRY[adapter.provider] = adapter


def get_storage(provider: str) -> StorageAdapter:
    try:
        return _REGISTRY[provider]
    except KeyError:
        raise ValueError(f"不支持的云存储: {provider}")
```

- [ ] **Step 4: 实现 s3.py** —— 创建 `app/cloud/s3.py`:
```python
from __future__ import annotations

from minio import Minio

from app.cloud.base import CloudConfig, register_storage


class S3StorageAdapter:
    """S3 兼容存储(MinIO / AWS S3 / R2 / B2 等),经 minio SDK。

    endpoint 为 host:port(无 scheme);secure 决定 https。minio SDK 的
    fput_object 对大文件自动分块上传。"""

    provider = "s3"

    def _client(self, cfg: CloudConfig) -> Minio:
        return Minio(cfg.endpoint, access_key=cfg.access_key, secret_key=cfg.secret_key,
                     secure=cfg.secure, region=cfg.region)

    def _key(self, cfg: CloudConfig, key: str) -> str:
        return f"{cfg.prefix}/{key}" if cfg.prefix else key

    def upload(self, cfg: CloudConfig, local_path: str, key: str) -> str:
        full = self._key(cfg, key)
        self._client(cfg).fput_object(cfg.bucket, full, local_path)
        return f"s3://{cfg.bucket}/{full}"

    def delete(self, cfg: CloudConfig, key: str) -> None:
        self._client(cfg).remove_object(cfg.bucket, self._key(cfg, key))

    def test(self, cfg: CloudConfig) -> None:
        if not self._client(cfg).bucket_exists(cfg.bucket):
            raise ValueError(f"存储桶不存在: {cfg.bucket}")


register_storage(S3StorageAdapter())
```

- [ ] **Step 5: 实现 __init__.py** —— 创建 `app/cloud/__init__.py`:
```python
from app.cloud.base import CloudConfig, StorageAdapter, register_storage, get_storage
from app.cloud import s3  # noqa: F401  触发注册
```

- [ ] **Step 6: 跑测试确认通过** —— `python3 -m pytest tests/test_cloud.py -v` → PASS(4 个)。

- [ ] **Step 7: 提交** —— `git add app/cloud/ tests/test_cloud.py && git commit -m "feat(cloud-sync): cloud 适配器层 + S3/MinIO 适配器"`

---

### Task 3: sync_service

**Files:** Create `app/services/sync_service.py`; Test `tests/test_sync_service.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_sync_service.py`:
```python
from datetime import datetime

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, CloudDestination, SyncTarget
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.sync_service import run_sync


class FakeStorage:
    """记录 upload 调用,可注入失败。"""
    def __init__(self, fail=False):
        self.uploads = []
        self._fail = fail
    def upload(self, cfg, local_path, key):
        if self._fail:
            raise RuntimeError("upload boom")
        self.uploads.append((cfg.bucket, key))
        return f"s3://{cfg.bucket}/{key}"
    def delete(self, cfg, key): pass
    def test(self, cfg): pass


def _setup(tmp_path, monkeypatch, storage=None):
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: storage or FakeStorage())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    bdir = tmp_path / "backups"; bdir.mkdir()
    (bdir / "pg.sql.gz").write_bytes(b"data")
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path="pg.sql.gz", started_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    dest = CloudDestination(name="minio", provider="s3", endpoint="h:9000", bucket="bk",
                            access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                            prefix="pre", secure=False, enabled=True)
    db.add(dest); db.commit(); db.refresh(dest)
    tgt = SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True)
    db.add(tgt); db.commit()
    return db, crypto, bdir, backup


def test_run_sync_uploads_to_targets(tmp_path, monkeypatch):
    storage = FakeStorage()
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    result = run_sync(db, crypto, backup, bdir)
    assert len(result["synced"]) == 1
    assert result["synced"][0]["uri"] == "s3://bk/pre/pg.sql.gz"
    assert storage.uploads == [("bk", "pre/pg.sql.gz")]
    assert result["errors"] == []
    db.close()


def test_run_sync_records_target_failure(tmp_path, monkeypatch):
    storage = FakeStorage(fail=True)
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    result = run_sync(db, crypto, backup, bdir)
    assert result["synced"] == []
    assert len(result["errors"]) == 1
    assert "upload boom" in result["errors"][0]["error"]
    db.close()


def test_run_sync_missing_file_raises(tmp_path, monkeypatch):
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch)
    (bdir / "pg.sql.gz").unlink()
    import pytest
    with pytest.raises(FileNotFoundError):
        run_sync(db, crypto, backup, bdir)
    db.close()
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_sync_service.py -v` → FAIL(模块不存在)。

- [ ] **Step 3: 实现 sync_service.py** —— 创建 `app/services/sync_service.py`:
```python
from __future__ import annotations

from pathlib import Path
from sqlalchemy.orm import Session

from app.db.models import BackupRecord, SyncTarget, CloudDestination
from app.core.crypto import Crypto
from app.cloud.base import CloudConfig, get_storage


def _cloud_config(dest: CloudDestination, crypto: Crypto) -> CloudConfig:
    return CloudConfig(
        endpoint=dest.endpoint,
        access_key=crypto.decrypt(dest.access_key_enc),
        secret_key=crypto.decrypt(dest.secret_enc),
        bucket=dest.bucket,
        region=dest.region,
        secure=dest.secure,
        prefix=dest.prefix,
    )


def run_sync(db: Session, crypto: Crypto, backup_record: BackupRecord, backup_dir: Path) -> dict:
    """把一份备份文件上传到其连接所有启用的云目标。返回 {synced, errors}。

    每个目标独立 try/except —— 一个目标失败不影响其余。文件路径做穿越校验。"""
    if not backup_record.file_path:
        raise FileNotFoundError("备份记录无文件路径")
    local_path = (backup_dir / backup_record.file_path).resolve()
    base = backup_dir.resolve()
    if local_path != base and base not in local_path.parents:
        raise ValueError("备份文件路径非法")
    if not local_path.exists():
        raise FileNotFoundError("备份文件不存在")

    key = backup_record.file_path
    targets = (
        db.query(SyncTarget)
        .filter(SyncTarget.connection_id == backup_record.connection_id, SyncTarget.enabled.is_(True))
        .all()
    )
    synced, errors = [], []
    for t in targets:
        dest = db.get(CloudDestination, t.cloud_destination_id)
        if dest is None or not dest.enabled:
            continue
        try:
            cfg = _cloud_config(dest, crypto)
            uri = get_storage(dest.provider).upload(cfg, str(local_path), key)
            synced.append({"target_id": t.id, "destination": dest.name, "uri": uri})
        except Exception as exc:
            errors.append({"target_id": t.id, "destination": dest.name, "error": str(exc)})
    return {"synced": synced, "errors": errors}
```

- [ ] **Step 4: 跑测试确认通过** —— `python3 -m pytest tests/test_sync_service.py -v` → PASS(3 个)。

- [ ] **Step 5: 提交** —— `git add app/services/sync_service.py tests/test_sync_service.py && git commit -m "feat(cloud-sync): sync_service(上传到连接所有云目标)"`

---

### Task 4: sync_job worker + 注册

**Files:** Modify `app/workers/jobs.py`, `app/workers/app.py`; Test `tests/test_sync_service.py`(追加)

- [ ] **Step 1: 写失败测试** —— 追加到 `tests/test_sync_service.py`:
```python
def test_run_sync_sync_wires_service(monkeypatch, tmp_path):
    from app.workers.jobs import _run_sync_sync
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("secret", key))
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: FakeStorage())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    (bdir / "pg.sql.gz").write_bytes(b"data")
    crypto = Crypto(key.encode("ascii"))
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path="pg.sql.gz", started_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    dest = CloudDestination(name="m", provider="s3", endpoint="h:9000", bucket="bk",
                            access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"))
    db.add(dest); db.commit(); db.refresh(dest)
    db.add(SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True))
    db.commit()
    bid = backup.id
    db.close()
    result = _run_sync_sync({"backup_dir": bdir}, bid)
    assert len(result["synced"]) == 1
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_sync_service.py::test_run_sync_sync_wires_service -v` → FAIL(`_run_sync_sync` 不存在)。

- [ ] **Step 3: 实现 worker** —— 在 `app/workers/jobs.py`:
  - import 区补:`from app.db.models import DbConnection, BackupRecord, RestoreRecord`(已有则保留)→ 确保 `BackupRecord` 在;补 `from app.services.sync_service import run_sync`、`from app.db.models import SystemLog`、`import json`。
  - 实际把顶部模型 import 行改为:
    ```python
    from app.db.models import DbConnection, BackupRecord, RestoreRecord, SystemLog
    ```
    并在 `from app.services.restore_service import run_restore` 后加:
    ```python
    from app.services.sync_service import run_sync
    ```
    (文件顶部若无 `import json`,加上。)
  - 文件末尾追加:
```python
def _run_sync_sync(ctx, backup_record_id: int) -> dict:
    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    db = _session._SessionLocal()
    try:
        backup = db.get(BackupRecord, backup_record_id)
        if backup is None:
            raise ValueError(f"备份记录不存在: {backup_record_id}")
        result = run_sync(db, crypto, backup, ctx["backup_dir"])
        level = "error" if result["errors"] and not result["synced"] else "info"
        db.add(SystemLog(
            level=level, source="sync",
            message=f"同步备份 #{backup_record_id}:{len(result['synced'])} 成功,{len(result['errors'])} 失败",
            context=json.dumps(result, ensure_ascii=False),
        ))
        db.commit()
        return result
    finally:
        db.close()


async def sync_job(ctx, backup_record_id: int) -> dict:
    return await asyncio.to_thread(_run_sync_sync, ctx, backup_record_id)
```

- [ ] **Step 4: 注册** —— `app/workers/app.py`:`from app.workers.jobs import backup_job, restore_job, sync_job`;`functions = [backup_job, restore_job, sync_job]`。

- [ ] **Step 5: 跑测试确认通过** —— `python3 -m pytest tests/test_sync_service.py tests/test_jobs.py -v` → PASS。

- [ ] **Step 6: 提交** —— `git add app/workers/jobs.py app/workers/app.py tests/test_sync_service.py && git commit -m "feat(cloud-sync): sync_job worker + SystemLog + 注册"`

---

### Task 5: cloud 路由(/cloud-destinations、/sync-targets、/sync/run)

**Files:** Create `app/routers/cloud.py`; Modify `app/main.py`; Test `tests/test_cloud_api.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_cloud_api.py`:
```python
import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def _create_dest(authed, name="minio"):
    return authed.post("/api/v1/cloud-destinations", json={
        "name": name, "provider": "s3", "endpoint": "localhost:9000",
        "bucket": "bk", "access_key": "AK", "secret": "SK", "secure": False,
    }).json()


def test_cloud_destinations_requires_auth(client):
    assert client.get("/api/v1/cloud-destinations").status_code == 401


def test_create_list_destinations(authed):
    d = _create_dest(authed)
    assert d["id"]
    assert "secret" not in d and "access_key" not in d  # 凭据不回传
    listed = authed.get("/api/v1/cloud-destinations").json()
    assert any(x["id"] == d["id"] for x in listed)


def test_delete_destination(authed):
    d = _create_dest(authed)
    assert authed.delete(f"/api/v1/cloud-destinations/{d['id']}").status_code == 204
    assert authed.get("/api/v1/cloud-destinations").json() == []


def test_test_destination(monkeypatch, authed):
    d = _create_dest(authed)
    monkeypatch.setattr("app.routers.cloud.get_storage",
                        lambda p: type("Fake", (), {"test": lambda self, cfg: None})())
    r = authed.post(f"/api/v1/cloud-destinations/{d['id']}/test")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_sync_targets_crud(authed):
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    db.add(DbConnection(name="c", type="pg")); db.commit()
    conn_id = db.query(DbConnection).first().id
    db.close()
    dest_id = _create_dest(authed)["id"]
    t = authed.post("/api/v1/sync-targets", json={
        "connection_id": conn_id, "cloud_destination_id": dest_id}).json()
    assert t["id"]
    listed = authed.get("/api/v1/sync-targets").json()
    assert any(x["id"] == t["id"] for x in listed)
    assert authed.delete(f"/api/v1/sync-targets/{t['id']}").status_code == 204


def test_sync_run_enqueues(authed):
    class FakeArq:
        def __init__(self): self.enqueued = []
        async def enqueue_job(self, *args): self.enqueued.append(args); return None
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from datetime import datetime
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path="x.gz", started_at=datetime.utcnow())
    db.add(backup); db.commit(); bid = backup.id; db.close()
    r = authed.post("/api/v1/sync/run", json={"backup_record_id": bid})
    assert r.status_code == 200
    assert authed.app.state.arq.enqueued
    assert authed.app.state.arq.enqueued[0][0] == "sync_job"


def test_sync_run_rejects_non_success(authed):
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from datetime import datetime
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    failed = BackupRecord(connection_id=conn.id, trigger="manual", status="failed", started_at=datetime.utcnow())
    db.add(failed); db.commit(); fid = failed.id; db.close()
    assert authed.post("/api/v1/sync/run", json={"backup_record_id": fid}).status_code == 400
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_cloud_api.py -v` → FAIL(路由 404)。

- [ ] **Step 3: 实现 routers/cloud.py** —— 创建:
```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import config
from app.db.session import get_db
from app.db.models import CloudDestination, SyncTarget, BackupRecord
from app.deps import get_current_account
from app.schemas.cloud import (
    CloudDestinationCreate, CloudDestinationOut,
    SyncTargetCreate, SyncTargetOut, SyncRunRequest,
)
from app.cloud.base import get_storage, CloudConfig

router = APIRouter()


async def _get_arq(app):
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        app.state.arq = await create_pool(config.settings.redis_url)
    return app.state.arq


# ---------- cloud-destinations ----------

@router.get("/cloud-destinations", response_model=list[CloudDestinationOut])
def list_destinations(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(CloudDestination).order_by(CloudDestination.id.desc()).all()


@router.post("/cloud-destinations", response_model=CloudDestinationOut, status_code=201)
def create_destination(payload: CloudDestinationCreate, request: Request,
                       db: Session = Depends(get_db), _=Depends(get_current_account)):
    crypto = request.app.state.crypto
    d = CloudDestination(
        name=payload.name, provider=payload.provider, endpoint=payload.endpoint,
        region=payload.region, bucket=payload.bucket,
        access_key_enc=crypto.encrypt(payload.access_key),
        secret_enc=crypto.encrypt(payload.secret),
        prefix=payload.prefix, secure=payload.secure, enabled=payload.enabled,
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


@router.delete("/cloud-destinations/{dest_id}", status_code=204)
def delete_destination(dest_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    db.delete(d); db.commit()


@router.post("/cloud-destinations/{dest_id}/test")
def test_destination(dest_id: int, request: Request,
                     db: Session = Depends(get_db), _=Depends(get_current_account)):
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    crypto = request.app.state.crypto
    cfg = CloudConfig(
        endpoint=d.endpoint, access_key=crypto.decrypt(d.access_key_enc),
        secret_key=crypto.decrypt(d.secret_enc), bucket=d.bucket,
        region=d.region, secure=d.secure, prefix=d.prefix,
    )
    try:
        get_storage(d.provider).test(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


# ---------- sync-targets ----------

@router.get("/sync-targets", response_model=list[SyncTargetOut])
def list_targets(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(SyncTarget).order_by(SyncTarget.id.desc()).all()


@router.post("/sync-targets", response_model=SyncTargetOut, status_code=201)
def create_target(payload: SyncTargetCreate, db: Session = Depends(get_db), _=Depends(get_current_account)):
    if db.get(CloudDestination, payload.cloud_destination_id) is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    t = SyncTarget(connection_id=payload.connection_id,
                   cloud_destination_id=payload.cloud_destination_id, enabled=payload.enabled)
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.delete("/sync-targets/{target_id}", status_code=204)
def delete_target(target_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    t = db.get(SyncTarget, target_id)
    if t is None:
        raise HTTPException(status_code=404, detail="同步规则不存在")
    db.delete(t); db.commit()


# ---------- sync/run ----------

@router.post("/sync/run")
async def sync_run(payload: SyncRunRequest, request: Request,
                   db: Session = Depends(get_db), _=Depends(get_current_account)):
    backup = db.get(BackupRecord, payload.backup_record_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if backup.status != "success" or not backup.file_path:
        raise HTTPException(status_code=400, detail="该备份不可用于同步")
    arq = await _get_arq(request.app)
    await arq.enqueue_job("sync_job", backup.id)
    return {"ok": True, "backup_record_id": backup.id}
```

- [ ] **Step 4: 挂载** —— `app/main.py`:import 加 `cloud`(`from app.routers import health, auth, connections, jobs, backups, schedules, dashboard, restore, cloud`),并 `app.include_router(cloud.router, prefix="/api/v1", tags=["cloud"])`。

- [ ] **Step 5: 跑测试 + 全量回归** —— `python3 -m pytest tests/test_cloud_api.py -v`(PASS 6 个);`python3 -m pytest -p no:warnings -q`(全绿,~95 passed)。

- [ ] **Step 6: 提交** —— `git add app/routers/cloud.py app/main.py tests/test_cloud_api.py && git commit -m "feat(cloud-sync): /cloud-destinations、/sync-targets、/sync/run 路由"`

---

### Task 6: 前端 CloudSync.vue + api + 路由 + 菜单

**Files:** Create `frontend/src/api/cloud.ts`, `frontend/src/views/CloudSync.vue`; Modify router, AppLayout

- [ ] **Step 1: api/cloud.ts** —— 创建:
```ts
import client from './client'

export interface CloudDestination {
  id: number
  name: string
  provider: string
  endpoint: string
  region: string | null
  bucket: string
  prefix: string
  secure: boolean
  enabled: boolean
  created_at: string
}
export interface SyncTarget {
  id: number
  connection_id: number
  cloud_destination_id: number
  enabled: boolean
}
export interface BackupFile { id: number; connection_id: number; status: string; file_path: string | null }

export const listDestinations = () => client.get<CloudDestination[]>('/cloud-destinations')
export const createDestination = (data: Record<string, unknown>) => client.post<CloudDestination>('/cloud-destinations', data)
export const deleteDestination = (id: number) => client.delete(`/cloud-destinations/${id}`)
export const testDestination = (id: number) => client.post(`/cloud-destinations/${id}/test`)
export const listTargets = () => client.get<SyncTarget[]>('/sync-targets')
export const createTarget = (data: Record<string, unknown>) => client.post<SyncTarget>('/sync-targets', data)
export const deleteTarget = (id: number) => client.delete(`/sync-targets/${id}`)
export const syncRun = (backup_record_id: number) => client.post('/sync/run', { backup_record_id })
```

- [ ] **Step 2: CloudSync.vue** —— 创建:
```vue
<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { NCard, NDataTable, NButton, NSpace, NModal, NForm, NFormItem, NInput, NSwitch, NTag, NSelect, NPopconfirm, useMessage } from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as cloudApi from '../api/cloud'
import type { CloudDestination, SyncTarget } from '../api/cloud'
import * as connApi from '../api/connections'
import * as bkApi from '../api/backups'

const msg = useMessage()
const dests = ref<CloudDestination[]>([])
const targets = ref<SyncTarget[]>([])
const connOptions = ref<{ label: string; value: number }[]>([])
const backupOptions = ref<{ label: string; value: number }[]>([])
const showDest = ref(false)
const showTarget = ref(false)
const selConn = ref<number | null>(null)
const selDest = ref<number | null>(null)
const selBackup = ref<number | null>(null)

const destForm = ref({ name: '', provider: 's3', endpoint: '', region: '', bucket: '', access_key: '', secret: '', prefix: '', secure: false, enabled: true })

async function load() {
  const [d, t, c, b] = await Promise.all([cloudApi.listDestinations(), cloudApi.listTargets(), connApi.listConnections(), bkApi.listBackups()])
  dests.value = d.data; targets.value = t.data
  connOptions.value = c.data.map(x => ({ label: `${x.name} (${x.type})`, value: x.id }))
  backupOptions.value = b.data.filter(x => x.status === 'success').map(x => ({ label: `#${x.id}`, value: x.id }))
}
async function saveDest() {
  try {
    await cloudApi.createDestination({ ...destForm.value, region: destForm.value.region || null })
    msg.success('已添加'); showDest.value = false; destForm.value = { name: '', provider: 's3', endpoint: '', region: '', bucket: '', access_key: '', secret: '', prefix: '', secure: false, enabled: true }
    await load()
  } catch (e: any) { msg.error(e.response?.data?.detail || '失败') }
}
async function testDest(id: number) {
  try { await cloudApi.testDestination(id); msg.success('连接成功') }
  catch (e: any) { msg.error(e.response?.data?.detail || '连接失败') }
}
async function rmDest(id: number) { await cloudApi.deleteDestination(id); msg.success('已删除'); await load() }
async function addTarget() {
  if (selConn.value == null || selDest.value == null) { msg.warning('请选连接和云目标'); return }
  await cloudApi.createTarget({ connection_id: selConn.value, cloud_destination_id: selDest.value })
  msg.success('已添加'); showTarget.value = false; await load()
}
async function rmTarget(id: number) { await cloudApi.deleteTarget(id); msg.success('已删除'); await load() }
async function doSync() {
  if (selBackup.value == null) { msg.warning('请选备份'); return }
  try { await cloudApi.syncRun(selBackup.value); msg.success('同步任务已提交') }
  catch (e: any) { msg.error(e.response?.data?.detail || '提交失败') }
}
function destName(id: number) { return dests.value.find(d => d.id === id)?.name ?? `#${id}` }
function connName(id: number) { return connOptions.value.find(c => c.value === id)?.label ?? `#${id}` }

const destCols: DataTableColumns<CloudDestination> = [
  { title: '名称', key: 'name' },
  { title: '类型', key: 'provider' },
  { title: 'Endpoint', key: 'endpoint' },
  { title: '桶', key: 'bucket' },
  { title: '前缀', key: 'prefix' },
  { title: 'HTTPS', key: 'secure', render: r => h(NTag, { size: 'small', bordered: false, type: r.secure ? 'success' : 'warning' }, { default: () => r.secure ? '是' : '否' }) },
  { title: '操作', key: 'a', render: r => h(NSpace, null, { default: () => [
    h(NButton, { size: 'small', onClick: () => testDest(r.id) }, { default: () => '测试' }),
    h(NPopconfirm, { onPositiveClick: () => rmDest(r.id) }, { trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }), default: () => '确认删除?' }),
  ] }) },
]
const targetCols: DataTableColumns<SyncTarget> = [
  { title: '连接', key: 'connection_id', render: r => connName(r.connection_id) },
  { title: '云目标', key: 'cloud_destination_id', render: r => destName(r.cloud_destination_id) },
  { title: '操作', key: 'a', render: r => h(NPopconfirm, { onPositiveClick: () => rmTarget(r.id) }, { trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }), default: () => '确认删除?' }) },
]

onMounted(load)
</script>

<template>
  <n-space vertical :size="16">
    <n-card title="云存储目标" :bordered="false">
      <template #header-extra>
        <n-button type="primary" @click="showDest = true">+ 添加</n-button>
      </template>
      <n-data-table :columns="destCols" :data="dests" :bordered="false" />
    </n-card>

    <n-card title="同步规则(连接 → 云目标)" :bordered="false">
      <template #header-extra>
        <n-button type="primary" @click="showTarget = true">+ 添加</n-button>
      </template>
      <n-data-table :columns="targetCols" :data="targets" :bordered="false" />
    </n-card>

    <n-card title="手动同步" :bordered="false">
      <n-space align="center">
        <n-select v-model:value="selBackup" :options="backupOptions" placeholder="选一份成功备份" style="width:240px" />
        <n-button type="primary" @click="doSync">同步到云</n-button>
      </n-space>
    </n-card>
  </n-space>

  <n-modal v-model:show="showDest" preset="card" title="添加云存储目标(MinIO / S3 兼容)" style="width:520px">
    <n-form label-placement="top">
      <n-form-item label="名称"><n-input v-model:value="destForm.name" /></n-form-item>
      <n-space>
        <n-form-item label="Endpoint (host:port)"><n-input v-model:value="destForm.endpoint" placeholder="localhost:9000" /></n-form-item>
        <n-form-item label="桶名"><n-input v-model:value="destForm.bucket" /></n-form-item>
      </n-space>
      <n-space>
        <n-form-item label="Access Key"><n-input v-model:value="destForm.access_key" /></n-form-item>
        <n-form-item label="Secret"><n-input v-model:value="destForm.secret" type="password" show-password-on="click" /></n-form-item>
      </n-space>
      <n-space>
        <n-form-item label="前缀"><n-input v-model:value="destForm.prefix" placeholder="(可选)" /></n-form-item>
        <n-form-item label="区域"><n-input v-model:value="destForm.region" placeholder="(可选)" /></n-form-item>
      </n-space>
      <n-space align="center">
        <n-form-item label="HTTPS"><n-switch v-model:value="destForm.secure" /></n-form-item>
        <n-form-item label="启用"><n-switch v-model:value="destForm.enabled" /></n-form-item>
      </n-space>
      <n-button type="primary" block @click="saveDest">保存</n-button>
    </n-form>
  </n-modal>

  <n-modal v-model:show="showTarget" preset="card" title="添加同步规则" style="width:460px">
    <n-space vertical :size="12">
      <n-select v-model:value="selConn" :options="connOptions" placeholder="选数据库连接" filterable />
      <n-select v-model:value="selDest" :options="dests.map(d => ({ label: d.name, value: d.id }))" placeholder="选云目标" filterable />
      <n-button type="primary" block @click="addTarget">保存</n-button>
    </n-space>
  </n-modal>
</template>
```

- [ ] **Step 3: 路由** —— `frontend/src/router/index.ts` 在 `restore` 后加:`{ path: 'cloud', component: () => import('../views/CloudSync.vue') },`

- [ ] **Step 4: 菜单** —— `frontend/src/layouts/AppLayout.vue` `menuOptions` 在 `恢复` 后加:`{ label: '云存储', key: 'cloud' },`

- [ ] **Step 5: 构建** —— `export PATH="/tmp/node-v20.18.1-linux-x64/bin:$PATH" && npm --prefix frontend run build` → 期望 `vue-tsc` 无错、`vite build` 成功。

- [ ] **Step 6: 提交** —— `git add frontend/src/api/cloud.ts frontend/src/views/CloudSync.vue frontend/src/router/index.ts frontend/src/layouts/AppLayout.vue && git commit -m "feat(cloud-sync): CloudSync.vue + 路由/菜单/api"`

---

## 完成标准
- 全量后端测试绿(~95 passed,原 84 + cloud 表/适配器/service/worker/api 新增,无回归)。
- `npm run build` 通过。
- 端到端逻辑:配置 MinIO 云目标 → 建同步规则 → 选备份 → POST /sync/run → sync_job 上传;凭据加密落库、不回传。
- S3 适配器用 fake 客户端单测覆盖(upload/delete/test/前缀)。

## 留给后续
- 同步 SSE 实时进度抽屉(spec §8 "同一套进度/取消")—— 需 sync 记录表或复用 job 命名空间。
- 备份成功后**自动**触发同步(backup_job 成功后链式 enqueue sync_job)。
- OSS / COS 独立适配器(各自 SDK 或 S3 兼容端点)。
- real-MinIO E2E(起 minio server 跑真实上传/删除往返)。
- 备份记录回写 `remote_uri`(spec §8 第 6 步"上传完记录 remote_uri 并远端校验")。
