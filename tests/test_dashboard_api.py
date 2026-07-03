from datetime import datetime, timedelta
import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def _seed():
    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    db = _session._SessionLocal()
    pg = DbConnection(name="pg", type="pg"); my = DbConnection(name="my", type="mysql")
    db.add_all([pg, my]); db.commit(); db.refresh(pg); db.refresh(my)
    now = datetime.utcnow()
    db.add_all([
        BackupRecord(connection_id=pg.id, trigger="manual", status="success", size=100, started_at=now),
        BackupRecord(connection_id=pg.id, trigger="manual", status="success", size=200, started_at=now),
        BackupRecord(connection_id=my.id, trigger="scheduled", status="failed", size=None, started_at=now),
    ])
    db.commit(); db.close()


def test_requires_auth(client):
    assert client.get("/api/v1/dashboard/stats").status_code == 401


def test_stats(authed):
    _seed()
    s = authed.get("/api/v1/dashboard/stats").json()
    assert s["total"] == 3
    assert s["success"] == 2 and s["failed"] == 1
    assert s["success_rate"] == round(2 / 3, 4)
    assert s["storage_bytes"] == 300


def test_trends(authed):
    _seed()
    t = authed.get("/api/v1/dashboard/trends").json()
    assert len(t["daily"]) >= 1
    today = t["daily"][-1]
    assert today["success"] == 2 and today["failed"] == 1
    types = {x["type"]: x["storage_bytes"] for x in t["by_type"]}
    assert types.get("pg") == 300
