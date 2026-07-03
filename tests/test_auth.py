import pytest


@pytest.fixture
def app_with_account(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw12345")
    finally:
        db.close()
    return client


def test_login_success(app_with_account):
    resp = app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "pw12345"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_login_wrong_password(app_with_account):
    resp = app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


def test_me_requires_login(app_with_account):
    resp = app_with_account.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_after_login(app_with_account):
    app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "pw12345"})
    resp = app_with_account.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_logout(app_with_account):
    app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "pw12345"})
    app_with_account.post("/api/v1/auth/logout")
    resp = app_with_account.get("/api/v1/auth/me")
    assert resp.status_code == 401
