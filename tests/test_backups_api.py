import pytest
from app.db import session as _session
from app.db.models import BackupRecord
from app.core.clock import utcnow


@pytest.fixture
def authed(client):
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


def _make_record(file_relpath="pg_1_1.sql.gz", content=b"x"):
    # 函数内读取 settings,确保拿到 conftest reload 后的实例(指向 tmp_path)。
    from app.config import settings
    bdir = settings.data_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / file_relpath).write_bytes(content)
    db = _session._SessionLocal()
    rec = BackupRecord(connection_id=1, trigger="manual", status="success",
                       file_path=file_relpath, size=len(content), checksum="c",
                       started_at=utcnow())
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
    db = _session._SessionLocal()
    rec = db.get(BackupRecord, rid)
    rec.file_path = "../../etc/passwd"
    db.commit(); db.close()
    assert authed.get(f"/api/v1/backups/{rid}/download").status_code == 404


def test_list_pagination(authed):
    for _ in range(3):
        _make_record()
    page1 = authed.get("/api/v1/backups?limit=2&offset=0").json()
    page2 = authed.get("/api/v1/backups?limit=2&offset=2").json()
    assert len(page1) == 2
    assert len(page2) == 1  # 共 3 条,第二页只剩 1 条


def test_manual_delete_deletes_cloud_copies(authed, monkeypatch):
    from app.db.models import CloudDestination, DbConnection, SyncTarget
    from cryptography.fernet import Fernet
    from app.core.crypto import Crypto

    class RecStorage:
        def __init__(self):
            self.deletes = []
        def delete(self, cfg, key):
            self.deletes.append((cfg.bucket, key))
        def upload(self, cfg, local_path, key): return "s3://x/y"
        def test(self, cfg): pass

    storage = RecStorage()
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: storage)
    crypto = authed.app.state.crypto
    db = _session._SessionLocal()
    try:
        conn = db.query(DbConnection).first()
        dest = CloudDestination(name="m", provider="s3", endpoint="h:9000", bucket="bk",
                                access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                                prefix="", secure=False, enabled=True)
        db.add(dest); db.commit(); db.refresh(dest)
        db.add(SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True))
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                           file_path="a.sql.gz", started_at=utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        rid = rec.id
    finally:
        db.close()
    resp = authed.delete(f"/api/v1/backups/{rid}")
    assert resp.status_code == 204
    assert storage.deletes == [("bk", "a.sql.gz")]


def test_verify_endpoint_enqueues(authed, monkeypatch):
    from app.db.models import CloudDestination  # noqa: F401 (保持与上方测试导入一致)

    class FakeArq:
        def __init__(self):
            self.enqueued = []
        async def enqueue_job(self, *args):
            self.enqueued.append(args)

    fake = FakeArq()
    monkeypatch.setattr("app.routers.jobs._get_arq", _async_return(fake))
    db = _session._SessionLocal()
    try:
        from app.db.models import DbConnection
        conn = db.query(DbConnection).first()
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                           file_path="a.sql.gz", checksum="0" * 64, started_at=utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        rid = rec.id
    finally:
        db.close()
    resp = authed.post(f"/api/v1/backups/{rid}/verify")
    assert resp.status_code == 202
    assert resp.json() == {"record_id": rid, "status": "queued"}
    assert fake.enqueued == [("verify_job", rid)]


def test_verify_endpoint_rejects_running(authed):
    db = _session._SessionLocal()
    try:
        from app.db.models import DbConnection
        conn = db.query(DbConnection).first()
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status="running",
                           started_at=utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        rid = rec.id
    finally:
        db.close()
    assert authed.post(f"/api/v1/backups/{rid}/verify").status_code == 409


def _async_return(value):
    import asyncio

    async def _call(app):
        return value
    return _call


class FailDeleteStorage:
    def delete(self, cfg, key):
        raise RuntimeError("cloud down")
    def upload(self, cfg, local_path, key): return "s3://x/y"
    def test(self, cfg): pass


def test_manual_delete_cloud_failure_keeps_record(authed, monkeypatch):
    """手动删除遇云删除失败 → 502,记录与文件保留(可稍后重试)。"""
    from app.db.models import CloudDestination, DbConnection, SyncTarget

    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: FailDeleteStorage())
    crypto = authed.app.state.crypto
    db = _session._SessionLocal()
    try:
        conn = db.query(DbConnection).first()
        dest = CloudDestination(name="m", provider="s3", endpoint="h:9000", bucket="bk",
                                access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                                prefix="", secure=False, enabled=True)
        db.add(dest); db.commit(); db.refresh(dest)
        db.add(SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True))
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                           file_path="b.sql.gz", started_at=utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        rid = rec.id
    finally:
        db.close()
    resp = authed.delete(f"/api/v1/backups/{rid}")
    assert resp.status_code == 502
    db = _session._SessionLocal()
    assert db.get(BackupRecord, rid) is not None  # 记录保留
    db.close()


def test_backup_download_not_double_compressed(authed, monkeypatch, tmp_path):
    """.gz 下载不应用 gzip 传输编码(文件本身已压缩;GZip 中间件按类型排除)。"""
    from app.db.models import DbConnection

    db = _session._SessionLocal()
    try:
        conn = db.query(DbConnection).first()
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                           file_path="c.sql.gz", started_at=utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        rid = rec.id
    finally:
        db.close()
    bdir = authed.app.state.crypto  # noqa: F841 (占位,真实目录如下)
    from app import config as app_config
    bpath = app_config.settings.data_dir / "backups"
    bpath.mkdir(parents=True, exist_ok=True)
    (bpath / "c.sql.gz").write_bytes(b"\x1f\x8b" + b"x" * 2048)  # 最小 gzip 头 + 填充
    resp = authed.get(f"/api/v1/backups/{rid}/download", headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") != "gzip"
    assert resp.headers["content-type"] == "application/gzip"


def test_verify_endpoint_marks_running_and_rejects_duplicate(authed, monkeypatch):
    """发起验证 → 记录进入 running;再次发起 → 409(防重复全文件扫描)。"""
    from app.db.models import DbConnection

    class FakeArq:
        async def enqueue_job(self, *args): pass

    monkeypatch.setattr("app.routers.jobs._get_arq", _async_return(FakeArq()))
    db = _session._SessionLocal()
    try:
        conn = db.query(DbConnection).first()
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                           file_path="a.sql.gz", checksum="0" * 64, started_at=utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        rid = rec.id
    finally:
        db.close()
    assert authed.post(f"/api/v1/backups/{rid}/verify").status_code == 202
    # 任务未执行(假队列)→ 记录应处于 running
    db = _session._SessionLocal()
    assert db.get(BackupRecord, rid).verify_status == "running"
    db.close()
    assert authed.post(f"/api/v1/backups/{rid}/verify").status_code == 409
