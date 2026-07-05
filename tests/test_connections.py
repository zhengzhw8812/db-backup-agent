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

    crypto = fastapi_app.state.crypto
    db = _session._SessionLocal()
    try:
        row = db.query(DbConnection).first()
        assert decrypt_password(row, crypto) == "roundtrip"
    finally:
        db.close()


def test_update_and_delete(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg"}).json()["id"]
    r = authed.put(f"/api/v1/connections/{cid}", json={"name": "pg-renamed"})
    assert r.json()["name"] == "pg-renamed"
    assert authed.delete(f"/api/v1/connections/{cid}").status_code == 204
    assert authed.get("/api/v1/connections").json() == []


def test_get_by_id(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "host": "h", "port": 5432}).json()["id"]
    r = authed.get(f"/api/v1/connections/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cid and body["host"] == "h" and body["port"] == 5432
    assert "password" not in body


def test_unknown_id_returns_404(authed):
    assert authed.get("/api/v1/connections/9999").status_code == 404
    assert authed.delete("/api/v1/connections/9999").status_code == 404


def test_sqlite_rejects_path_traversal(authed):
    # 绝对路径(数据目录之外)→ 拒绝,杜绝任意文件读
    r = authed.post("/api/v1/connections", json={"name": "s", "type": "sqlite", "db_name": "/etc/shadow"})
    assert r.status_code == 400
    # 相对遍历 ../ 逃出数据目录 → 拒绝
    r2 = authed.post("/api/v1/connections", json={"name": "s", "type": "sqlite", "db_name": "../evil.db"})
    assert r2.status_code == 400


def test_sqlite_accepts_path_inside_data_dir(authed):
    # 相对路径(落在 data_dir 内)→ 允许
    r = authed.post("/api/v1/connections", json={"name": "s", "type": "sqlite", "db_name": "mydb.sqlite"})
    assert r.status_code == 201
    assert r.json()["db_name"] == "mydb.sqlite"


def test_update_connection_empty_password_keeps_existing(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "password": "pw1"}).json()["id"]
    # 表单重提交常见:password 传空串 → 不应清空已存密码
    authed.put(f"/api/v1/connections/{cid}", json={"name": "renamed", "password": ""})
    from app.db import session as _session
    from app.db.models import DbConnection
    from app.main import app as fastapi_app
    from app.services.connection_service import decrypt_password
    crypto = fastapi_app.state.crypto
    db = _session._SessionLocal()
    try:
        row = db.get(DbConnection, cid)
        assert decrypt_password(row, crypto) == "pw1"  # 仍是旧密码
    finally:
        db.close()


def test_connection_rejects_out_of_range_port(authed):
    # 端口超范围 → schema 层 422(而非存入后连接时才失败)
    assert authed.post("/api/v1/connections",
                       json={"name": "c", "type": "pg", "port": 99999}).status_code == 422
    assert authed.post("/api/v1/connections",
                       json={"name": "c", "type": "pg", "port": 0}).status_code == 422


def test_connection_test_success(authed, monkeypatch):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg"}).json()["id"]
    class FakeAdapter:
        def test(self, info, *, is_cancelled=None): pass
    monkeypatch.setattr("app.services.connection_service.get_adapter", lambda t: FakeAdapter())
    assert authed.post(f"/api/v1/connections/{cid}/test").json() == {"ok": True}


def test_connection_test_failure_returns_400(authed, monkeypatch):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg"}).json()["id"]
    class BadAdapter:
        def test(self, info, *, is_cancelled=None): raise RuntimeError("password authentication failed")
    monkeypatch.setattr("app.services.connection_service.get_adapter", lambda t: BadAdapter())
    r = authed.post(f"/api/v1/connections/{cid}/test")
    assert r.status_code == 400
    assert "password authentication failed" in r.json()["detail"]


def test_connection_test_unsupported_type(authed):
    """Redis/Mongo 暂不支持测试 → 400 + 友好提示(不实际连库)。"""
    cid = authed.post("/api/v1/connections", json={"name": "r", "type": "redis"}).json()["id"]
    r = authed.post(f"/api/v1/connections/{cid}/test")
    assert r.status_code == 400
    assert "暂不支持" in r.json()["detail"]


def test_update_preserves_other_fields_and_reencrypts(authed):
    cid = authed.post("/api/v1/connections", json={
        "name": "pg1", "type": "pg", "host": "h1", "port": 5432, "db_name": "d", "username": "u", "password": "pw1"
    }).json()["id"]
    # partial update: only name → host/port/db_name/username must survive
    authed.put(f"/api/v1/connections/{cid}", json={"name": "renamed"})
    body = authed.get(f"/api/v1/connections/{cid}").json()
    assert body["name"] == "renamed"
    assert body["host"] == "h1" and body["port"] == 5432 and body["db_name"] == "d" and body["username"] == "u"
    # password re-encryption: change password, verify decrypt roundtrips to the NEW value
    authed.put(f"/api/v1/connections/{cid}", json={"password": "pw2"})
    from app.db import session as _session
    from app.db.models import DbConnection
    from app.main import app as fastapi_app
    from app.services.connection_service import decrypt_password

    crypto = fastapi_app.state.crypto
    db = _session._SessionLocal()
    try:
        row = db.get(DbConnection, cid)
        assert decrypt_password(row, crypto) == "pw2"
    finally:
        db.close()


def test_create_pg_connection_persists_db_names(authed):
    body = {"name": "pg1", "type": "pg", "host": "h", "port": 5432,
            "username": "u", "password": "secret", "db_names": ["app", "logs"]}
    r = authed.post("/api/v1/connections", json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["db_names"] == ["app", "logs"]


def test_list_db_names_falls_back_to_db_name(authed):
    """旧连接(只存 db_name)的 ConnectionOut.db_names 应回退为 [db_name]。"""
    from app.db import session as _session
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        db.add(DbConnection(name="old", type="pg", db_name="legacy"))
        db.commit()
    finally:
        db.close()
    r = authed.get("/api/v1/connections")
    row = next(c for c in r.json() if c["name"] == "old")
    assert row["db_names"] == ["legacy"]


def test_update_connection_db_names(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "db_names": ["a"]}).json()["id"]
    r = authed.put(f"/api/v1/connections/{cid}", json={"db_names": ["a", "b"]})
    assert r.json()["db_names"] == ["a", "b"]
