import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    from app.db.models import SystemLog
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(SystemLog(level="info", source="sync", message="ok"))
        db.add(SystemLog(level="error", source="backup", message="boom"))
        db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_logs_require_auth(client):
    assert client.get("/api/v1/logs").status_code == 401


def test_logs_list(authed):
    rows = authed.get("/api/v1/logs").json()
    assert len(rows) == 2
    assert all("message" in r and "level" in r for r in rows)


def test_logs_level_filter(authed):
    rows = authed.get("/api/v1/logs?level=error").json()
    assert len(rows) == 1
    assert rows[0]["level"] == "error"
