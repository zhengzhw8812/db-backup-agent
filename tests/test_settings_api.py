import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw"); db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_settings_require_auth(client):
    assert client.get("/api/v1/settings/notifications").status_code == 401


def test_get_returns_defaults_when_empty(authed):
    r = authed.get("/api/v1/settings/notifications").json()
    assert r["email_enabled"] is False
    assert "smtp_password" not in r and "wechat_secret" not in r


def test_get_is_read_only(authed):
    """GET 不应在 DB 建行(保持幂等/只读);建行只在 PUT。"""
    from app.db import session as _session
    from app.db.models import NotificationConfig
    authed.get("/api/v1/settings/notifications")
    db = _session._SessionLocal()
    try:
        assert db.query(NotificationConfig).count() == 0
    finally:
        db.close()


def test_put_updates_and_hides_secrets(authed):
    r = authed.put("/api/v1/settings/notifications", json={
        "email_enabled": True, "smtp_host": "h", "smtp_port": 465, "smtp_ssl": True,
        "smtp_user": "u", "smtp_password": "pw", "smtp_from": "a@b", "recipients": "x@y",
        "wechat_enabled": False, "notify_on_success": True, "notify_on_failure": True,
    }).json()
    assert r["email_enabled"] is True
    assert "smtp_password" not in r
    got = authed.get("/api/v1/settings/notifications").json()
    assert got["smtp_host"] == "h"
    assert "smtp_password" not in got


def test_verify_settings_get_put(authed):
    r = authed.get("/api/v1/settings/verify")
    assert r.status_code == 200
    assert r.json() == {"auto_enabled": False}
    r = authed.put("/api/v1/settings/verify", json={"auto_enabled": True})
    assert r.status_code == 200
    assert r.json() == {"auto_enabled": True}
    assert authed.get("/api/v1/settings/verify").json() == {"auto_enabled": True}


def test_notification_test_endpoint_per_channel(authed, monkeypatch):
    """无任何渠道启用 → 400;仅邮件启用且成功 → email=true 其余 null。"""
    from app.db import session as _session
    from app.db.models import NotificationConfig
    from app.services import notifications as nm

    r = authed.post("/api/v1/settings/notifications/test")
    assert r.status_code == 400

    monkeypatch.setattr(nm, "_send_email", lambda cfg, subject, body, pw: None)
    db = _session._SessionLocal()
    db.add(NotificationConfig(email_enabled=True))
    db.commit(); db.close()
    r = authed.post("/api/v1/settings/notifications/test")
    assert r.status_code == 200
    assert r.json() == {"email": True, "wechat": None, "feishu": None, "serverchan": None}


def test_notification_test_endpoint_all_fail(authed):
    from app.db import session as _session
    from app.db.models import NotificationConfig

    db = _session._SessionLocal()
    db.add(NotificationConfig(email_enabled=True, smtp_host="bad", smtp_port=1,
                              smtp_from="a@b.c", recipients="x@y.z"))
    db.commit(); db.close()
    assert authed.post("/api/v1/settings/notifications/test").status_code == 400
