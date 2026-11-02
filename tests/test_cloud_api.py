import pytest
from app.core.clock import utcnow


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


def test_create_destination_rejects_unknown_provider(authed):
    r = authed.post("/api/v1/cloud-destinations", json={
        "name": "x", "provider": "s4", "endpoint": "localhost:9000",
        "bucket": "bk", "access_key": "AK", "secret": "SK", "secure": False})
    assert r.status_code == 400


def test_sync_target_duplicate_rejected(authed):
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    db.add(DbConnection(name="c", type="pg")); db.commit()
    conn_id = db.query(DbConnection).first().id
    db.close()
    dest_id = _create_dest(authed)["id"]
    body = {"connection_id": conn_id, "cloud_destination_id": dest_id}
    assert authed.post("/api/v1/sync-targets", json=body).status_code == 201
    # 同一(连接,目标)再次创建 → 409
    assert authed.post("/api/v1/sync-targets", json=body).status_code == 409


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
                          file_path="x.gz", started_at=utcnow())
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
    failed = BackupRecord(connection_id=conn.id, trigger="manual", status="failed", started_at=utcnow())
    db.add(failed); db.commit(); fid = failed.id; db.close()
    assert authed.post("/api/v1/sync/run", json={"backup_record_id": fid}).status_code == 400


def test_create_nfs_destination_mounts_and_lists_mounted(authed, monkeypatch):
    """创建 nfs 目的地:立即挂载;列表返回 mounted 标记;删除触发卸载。"""
    import json as _json
    from app.db.models import CloudDestination

    calls = []
    import app.services.mount_service as ms
    monkeypatch.setattr(ms, "mount_destination", lambda d, cr: calls.append(("mount", d.id)))
    monkeypatch.setattr(ms, "unmount_destination", lambda did: calls.append(("umount", did)))
    monkeypatch.setattr(ms.os.path, "ismount", lambda p: True)

    r = authed.post("/api/v1/cloud-destinations", json={
        "name": "nas", "provider": "nfs",
        "endpoint": "", "bucket": "",
        "access_key": "x", "secret": "x",
        "mount": {"server": "nas", "export": "/vol/bk", "version": "nfs4"},
    })
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    assert ("mount", did) in calls

    listing = authed.get("/api/v1/cloud-destinations").json()
    row = [x for x in listing if x["id"] == did][0]
    assert row["provider"] == "nfs" and row["mounted"] is True

    authed.delete(f"/api/v1/cloud-destinations/{did}")
    assert ("umount", did) in calls


def test_create_nfs_mount_failure_rejected(authed, monkeypatch):
    """挂载失败 → 400,目的地不落库。"""
    import app.services.mount_service as ms

    def boom(d, cr):
        raise RuntimeError("no route to host")

    monkeypatch.setattr(ms, "mount_destination", boom)
    r = authed.post("/api/v1/cloud-destinations", json={
        "name": "bad", "provider": "nfs", "endpoint": "", "bucket": "",
        "access_key": "x", "secret": "x",
        "mount": {"server": "nas", "export": "/v"},
    })
    assert r.status_code == 400
    assert "no route to host" in r.json()["detail"]
    assert authed.get("/api/v1/cloud-destinations").json() == []


# ---------- v3.4.2: 云目标编辑 / 未保存测试 / 错误分类 ----------

def _make_dest(authed, crypto=None, **kw):
    from app.db import session as _session
    from app.db.models import CloudDestination

    body = {"name": kw.pop("name", "d1"), "provider": kw.pop("provider", "s3"),
            "endpoint": kw.pop("endpoint", "h:9000"), "region": None,
            "bucket": kw.pop("bucket", "bk"), "access_key": kw.pop("access_key", "AK"),
            "secret": kw.pop("secret", "SK"), "prefix": "", "secure": False, "enabled": True}
    r = authed.post("/api/v1/cloud-destinations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_update_destination_keeps_blank_secrets(authed):
    """编辑:凭据留空(空串)= 保留已存密文,其余字段更新。"""
    from app.db import session as _session
    from app.db.models import CloudDestination

    d = _make_dest(authed)
    r = authed.put(f"/api/v1/cloud-destinations/{d['id']}", json={
        "name": "改名", "provider": "s3", "endpoint": "h2:9000", "region": "us-east-1",
        "bucket": "bk2", "access_key": "", "secret": "", "prefix": "p", "secure": True, "enabled": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "改名" and r.json()["endpoint"] == "h2:9000"
    db = _session._SessionLocal()
    row = db.get(CloudDestination, d["id"])
    crypto = authed.app.state.crypto
    assert crypto.decrypt(row.access_key_enc) == "AK"   # 留空保留
    assert crypto.decrypt(row.secret_enc) == "SK"
    db.close()


def test_update_destination_rejects_provider_change(authed):
    d = _make_dest(authed)
    r = authed.put(f"/api/v1/cloud-destinations/{d['id']}", json={
        "name": "d1", "provider": "nfs", "endpoint": "", "bucket": "",
        "access_key": "", "secret": "", "prefix": "", "secure": False, "enabled": True,
        "mount": {"server": "nas", "export": "/bk"},
    })
    assert r.status_code == 422
    assert "类型" in str(r.json()["detail"])


def test_update_nfs_remount_failure_keeps_config(authed, monkeypatch):
    """nfs 编辑挂载配置:重挂失败不回滚,配置保留 + mounted False + warning。"""
    from app.db import session as _session
    from app.db.models import CloudDestination
    from app.services import mount_service
    from app.routers import cloud as cloud_router

    monkeypatch.setattr(mount_service, "mount_destination", lambda d, c: None)
    monkeypatch.setattr(mount_service, "unmount_destination", lambda i: None)

    body = {"name": "nas1", "provider": "nfs", "endpoint": "", "bucket": "",
            "access_key": "", "secret": "", "prefix": "", "secure": False, "enabled": True,
            "mount": {"server": "old-nas", "export": "/bk"}}
    d = authed.post("/api/v1/cloud-destinations", json=body).json()

    def boom(d_, c_):
        raise RuntimeError("mount: connection refused")
    monkeypatch.setattr(mount_service, "mount_destination", boom)

    r = authed.put(f"/api/v1/cloud-destinations/{d['id']}", json={
        **body, "name": "nas1", "mount": {"server": "new-nas", "export": "/bk"},
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mount_config"] and "new-nas" in out["mount_config"]   # 新配置已入库
    assert out["mounted"] is False
    assert out.get("warning")
    db = _session._SessionLocal()
    row = db.get(CloudDestination, d["id"])
    assert "new-nas" in row.mount_config
    db.close()


def test_test_destination_draft(authed, monkeypatch):
    """未保存测试:用表单临时凭据直测 s3,不落库;非 s3 → 400。"""
    from app.routers import cloud as cloud_router

    seen = {}
    class FakeStorage:
        def test(self, cfg): seen.update(endpoint=cfg.endpoint, ak=cfg.access_key, bucket=cfg.bucket)
    monkeypatch.setattr(cloud_router, "get_storage", lambda p: FakeStorage())

    r = authed.post("/api/v1/cloud-destinations/test", json={
        "name": "草稿", "provider": "s3", "endpoint": "h:9000", "bucket": "bk",
        "access_key": "TMP-AK", "secret": "TMP-SK", "prefix": "", "secure": False, "enabled": True,
    })
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert seen == {"endpoint": "h:9000", "ak": "TMP-AK", "bucket": "bk"}

    r = authed.post("/api/v1/cloud-destinations/test", json={
        "name": "n", "provider": "nfs", "endpoint": "", "bucket": "",
        "access_key": "", "secret": "", "mount": {"server": "nas"},
    })
    assert r.status_code == 400 and "共享存储" in r.json()["detail"]


def test_s3_test_error_mapping(monkeypatch):
    """S3 test 失败分类为中文指引:连接/认证/桶/TLS 四类。"""
    from app.cloud.base import CloudConfig
    from app.cloud.s3 import S3StorageAdapter

    cfg = CloudConfig(endpoint="h:9000", access_key="a", secret_key="s", bucket="bk", secure=False)
    a = S3StorageAdapter()

    class FakeClient:
        exc: Exception = None
        def bucket_exists(self, b): raise self.exc

    monkeypatch.setattr(a, "_client", lambda c: FakeClient())
    for exc, kw in [
        (Exception("MaxRetryError ... [Errno 111] Connection refused"), "连不上"),
        (Exception("HTTPSConnectionPool ... SSLError certificate verify failed"), "TLS"),
        (Exception("AccessDenied: 403 Forbidden"), "认证失败"),
        (Exception("InvalidAccessKeyId"), "认证失败"),
        (Exception("NoSuchBucket: The specified bucket does not exist"), "桶不存在"),
    ]:
        FakeClient.exc = exc
        try:
            a.test(cfg)
            raise AssertionError(f"应当抛 ValueError: {exc}")
        except ValueError as e:
            assert kw in str(e), (kw, str(e))
