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
