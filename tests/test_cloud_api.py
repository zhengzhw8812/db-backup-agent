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
