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


def test_run_validates_payload(authed):
    # 缺 connection_id → 422(而非进入 handler 后 500)
    assert authed.post("/api/v1/backups/run", json={}).status_code == 422
    # 非法 trigger → 422
    from app.db import session as _session
    from app.db.models import DbConnection
    conn_id = _session._SessionLocal().query(DbConnection).first().id
    r = authed.post("/api/v1/backups/run", json={"connection_id": conn_id, "trigger": "bogus"})
    assert r.status_code == 422


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
    # enqueue args: ("backup_job", connection_id, [record_id]) — 3 elements
    assert len(authed.app.state.arq.enqueued[0]) == 3
    assert body["record_ids"] and len(body["record_ids"]) == 1


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


def test_run_rejects_when_already_running(authed):
    """同一连接已有 running 备份 → 409,且不再投递。"""
    authed.app.state.arq = FakeArq()
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from datetime import datetime
    db = _session._SessionLocal()
    conn = db.query(DbConnection).first()
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="running", started_at=datetime.utcnow()))
    db.commit(); conn_id = conn.id; db.close()
    r = authed.post("/api/v1/backups/run", json={"connection_id": conn_id})
    assert r.status_code == 409
    assert not authed.app.state.arq.enqueued  # 未投递


def test_run_enqueue_failure_marks_record_failed(authed):
    """投递队列失败 → 503,且 running 记录翻转为 failed(不留幽灵)。"""
    class BoomArq:
        async def enqueue_job(self, *a):
            raise RuntimeError("redis down")
    authed.app.state.arq = BoomArq()
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    db = _session._SessionLocal()
    conn_id = db.query(DbConnection).first().id; db.close()
    r = authed.post("/api/v1/backups/run", json={"connection_id": conn_id})
    assert r.status_code == 503
    db = _session._SessionLocal()
    rec = db.query(BackupRecord).filter(BackupRecord.status == "failed").first()
    assert rec is not None and "投递" in (rec.error or "")
    db.close()


def test_events_emits_terminal_state_immediately(authed):
    """任务已终态时,SSE 立即推一条并关闭,不挂起、无需 redis。"""
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from datetime import datetime
    db = _session._SessionLocal()
    conn = db.query(DbConnection).first()
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
    db.add(rec); db.commit(); rid = rec.id; db.close()
    r = authed.get(f"/api/v1/jobs/{rid}/events")
    assert r.status_code == 200
    assert "success" in r.text
