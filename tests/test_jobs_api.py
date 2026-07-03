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
        return None


def test_run_requires_auth(client):
    assert client.post("/api/v1/backups/run", json={"connection_id": 1}).status_code == 401


def test_run_creates_record_and_enqueues(authed):
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    conn_id = db.query(DbConnection).first().id
    db.close()
    r = authed.post("/api/v1/backups/run", json={"connection_id": conn_id})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running"
    assert authed.app.state.arq.enqueued
    assert authed.app.state.arq.enqueued[0][0] == "backup_job"
    # enqueue args: ("backup_job", connection_id, record_id) — 3 elements
    assert len(authed.app.state.arq.enqueued[0]) == 3


def test_list_jobs_and_cancel(authed, monkeypatch):
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from datetime import datetime
    db = _session._SessionLocal()
    conn_id = db.query(DbConnection).first().id
    rec = BackupRecord(connection_id=conn_id, trigger="manual", status="running", started_at=datetime.utcnow())
    db.add(rec); db.commit(); rid = rec.id; db.close()
    listed = authed.get("/api/v1/jobs").json()
    assert any(j["id"] == rid for j in listed)
    # request_cancel 会连真实 redis;测试环境无 redis,打桩使端点保持幂等可测。
    monkeypatch.setattr("app.routers.jobs.request_cancel", lambda record_id: None)
    assert authed.post(f"/api/v1/jobs/{rid}/cancel").json() == {"ok": True}
