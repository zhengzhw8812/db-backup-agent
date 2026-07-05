import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(DbConnection(name="c", type="pg")); db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_requires_auth(client):
    assert client.get("/api/v1/schedules").status_code == 401


def test_create_list_update_delete(authed):
    from app.db import session as _session
    from app.db.models import DbConnection
    conn_id = _session._SessionLocal().query(DbConnection).first().id
    r = authed.post("/api/v1/schedules", json={"connection_id": conn_id, "cron_expr": "0 2 * * *"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["cron_expr"] == "0 2 * * *"
    assert len(authed.get("/api/v1/schedules").json()) == 1
    u = authed.put(f"/api/v1/schedules/{sid}", json={"enabled": False})
    assert u.json()["enabled"] is False
    assert authed.delete(f"/api/v1/schedules/{sid}").status_code == 204
    assert authed.get("/api/v1/schedules").json() == []


def test_create_rejects_unknown_connection(authed):
    r = authed.post("/api/v1/schedules", json={"connection_id": 9999, "cron_expr": "0 2 * * *"})
    assert r.status_code == 400


def test_create_rejects_invalid_cron(authed):
    from app.db import session as _session
    from app.db.models import DbConnection
    conn_id = _session._SessionLocal().query(DbConnection).first().id
    # 5 字段但语义非法(周 8)→ 通过 schema 正则,被服务层 APScheduler 校验拒绝
    r = authed.post("/api/v1/schedules", json={"connection_id": conn_id, "cron_expr": "0 2 * * 8"})
    assert r.status_code == 400
    # 合法 cron 仍可创建
    assert authed.post("/api/v1/schedules",
                       json={"connection_id": conn_id, "cron_expr": "0 2 * * *"}).status_code == 201


def test_update_rejects_invalid_cron(authed):
    from app.db import session as _session
    from app.db.models import DbConnection
    conn_id = _session._SessionLocal().query(DbConnection).first().id
    sid = authed.post("/api/v1/schedules",
                      json={"connection_id": conn_id, "cron_expr": "0 2 * * *"}).json()["id"]
    r = authed.put(f"/api/v1/schedules/{sid}", json={"cron_expr": "*/0 * * * *"})
    assert r.status_code == 400
