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


def test_requires_auth(client):
    assert client.get("/api/v1/connections").status_code == 401


def test_create_and_list(authed):
    body = {"name": "pg1", "type": "pg", "host": "h", "port": 5432, "db_name": "d", "username": "u", "password": "secret"}
    r = authed.post("/api/v1/connections", json=body)
    assert r.status_code == 201
    created = r.json()
    assert created["name"] == "pg1"
    assert "password" not in created  # 密码不回传
    listed = authed.get("/api/v1/connections").json()
    assert len(listed) == 1 and listed[0]["id"] == created["id"]


def test_password_stored_encrypted(authed):
    authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "password": "topsecret"})
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        row = db.query(DbConnection).first()
        assert row.password_enc is not None
        assert "topsecret" not in row.password_enc  # 落库为密文
    finally:
        db.close()


def test_decrypt_roundtrip(authed):
    authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "password": "roundtrip"})
    # 直接用服务层解密,验证"写入密文 → 解出明文"往返一致
    from app.db import session as _session
    from app.db.models import DbConnection
    from app.main import app as fastapi_app
    from app.services.connection_service import decrypt_password

    class FakeReq:
        pass  # 只需 .app 属性,服务层用 request.app.state.crypto

    db = _session._SessionLocal()
    try:
        row = db.query(DbConnection).first()
        fr = FakeReq()
        fr.app = fastapi_app
        assert decrypt_password(row, fr) == "roundtrip"
    finally:
        db.close()


def test_update_and_delete(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg"}).json()["id"]
    r = authed.put(f"/api/v1/connections/{cid}", json={"name": "pg-renamed"})
    assert r.json()["name"] == "pg-renamed"
    assert authed.delete(f"/api/v1/connections/{cid}").status_code == 204
    assert authed.get("/api/v1/connections").json() == []
