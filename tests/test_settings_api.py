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


def test_global_notifications_get_put(authed):
    """全局三开关:GET 默认 True 且幂等不建行;PUT 收窄后只管三开关。"""
    from app.db import session as _session
    from app.db.models import NotificationConfig

    r = authed.get("/api/v1/settings/notifications")
    assert r.status_code == 200
    assert r.json() == {"notify_on_success": True, "notify_on_failure": True, "notify_watchdog": True}
    db = _session._SessionLocal()
    try:
        assert db.query(NotificationConfig).count() == 0  # GET 保持只读
    finally:
        db.close()

    r = authed.put("/api/v1/settings/notifications", json={"notify_on_success": False})
    assert r.status_code == 200
    assert r.json() == {"notify_on_success": False, "notify_on_failure": True, "notify_watchdog": True}
    assert authed.get("/api/v1/settings/notifications").json()["notify_on_success"] is False


def test_channel_crud_lifecycle(authed):
    r = authed.post("/api/v1/settings/notification-channels", json={
        "type": "email", "name": "个人邮箱", "enabled": True,
        "config": {"smtp_host": "h", "smtp_port": 465, "recipients": "a@b"},
        "secret": {"password": "pw"},
    })
    assert r.status_code == 201
    out = r.json()
    assert out["type"] == "email" and out["name"] == "个人邮箱" and out["enabled"] is True
    assert out["config"]["smtp_host"] == "h"
    assert "secret" not in out and "secret_enc" not in out  # 密钥永不回传
    cid = out["id"]

    assert [c["id"] for c in authed.get("/api/v1/settings/notification-channels").json()] == [cid]

    r = authed.put(f"/api/v1/settings/notification-channels/{cid}", json={
        "type": "email", "name": "改名", "enabled": False,
        "config": {"smtp_host": "h2", "recipients": "a@b"},
    })
    assert r.status_code == 200
    assert r.json()["name"] == "改名" and r.json()["enabled"] is False
    assert r.json()["config"]["smtp_host"] == "h2"

    assert authed.delete(f"/api/v1/settings/notification-channels/{cid}").status_code == 200
    assert authed.get("/api/v1/settings/notification-channels").json() == []
    assert authed.delete(f"/api/v1/settings/notification-channels/{cid}").status_code == 404


def test_channel_update_secret_blank_keeps_stored(authed):
    """编辑不带 secret → 保留已存密文,不清空。"""
    from app.db import session as _session
    from app.db.models import NotificationChannel

    r = authed.post("/api/v1/settings/notification-channels", json={
        "type": "feishu", "name": "f", "config": {},
        "secret": {"webhook": "https://h", "sign": "s"},
    }).json()

    def _secret_enc():
        db = _session._SessionLocal()
        try:
            return db.get(NotificationChannel, r["id"]).secret_enc
        finally:
            db.close()

    before = _secret_enc()
    rr = authed.put(f"/api/v1/settings/notification-channels/{r['id']}", json={
        "type": "feishu", "name": "f", "enabled": True, "config": {},
    })
    assert rr.status_code == 200
    assert _secret_enc() == before


def test_channel_create_validates_required_config(authed):
    # email 缺 smtp_host/recipients → 422
    assert authed.post("/api/v1/settings/notification-channels", json={
        "type": "email", "name": "e", "config": {"recipients": "a@b"}}).status_code == 422
    # wechat 缺 corp_id/agent_id → 422
    assert authed.post("/api/v1/settings/notification-channels", json={
        "type": "wechat", "name": "w", "config": {"agent_id": "1"}}).status_code == 422
    # feishu 创建缺 secret.webhook → 422
    assert authed.post("/api/v1/settings/notification-channels", json={
        "type": "feishu", "name": "f", "config": {}}).status_code == 422
    # serverchan 创建 secret 为空 → 422
    assert authed.post("/api/v1/settings/notification-channels", json={
        "type": "serverchan", "name": "s", "config": {}, "secret": {}}).status_code == 422


def test_channel_test_endpoint(authed, monkeypatch):
    from app.db import session as _session
    from app.db.models import NotificationChannel
    from app.services import notifications as nm

    monkeypatch.setattr(nm, "_send_feishu", lambda secret, content: None)
    db = _session._SessionLocal()
    ch = NotificationChannel(type="feishu", name="飞书", enabled=True, config_json="{}")
    db.add(ch); db.commit()
    chid = ch.id
    db.close()

    r = authed.post(f"/api/v1/settings/notification-channels/{chid}/test")
    assert r.status_code == 200
    assert r.json() == {"id": chid, "name": "飞书", "type": "feishu", "ok": True, "error": None}

    def boom(secret, content):
        raise RuntimeError("hook unreachable")

    monkeypatch.setattr(nm, "_send_feishu", boom)
    r = authed.post(f"/api/v1/settings/notification-channels/{chid}/test")
    assert r.status_code == 400 and "飞书" in r.json()["detail"]


def test_verify_settings_get_put(authed):
    r = authed.get("/api/v1/settings/verify")
    assert r.status_code == 200
    assert r.json() == {"auto_enabled": False}
    r = authed.put("/api/v1/settings/verify", json={"auto_enabled": True})
    assert r.status_code == 200
    assert r.json() == {"auto_enabled": True}
    assert authed.get("/api/v1/settings/verify").json() == {"auto_enabled": True}


def test_notification_test_endpoint_per_channel(authed, monkeypatch):
    """无启用渠道 → 400;单渠道成功 → 列表逐渠道返回 ok=True。"""
    from app.db import session as _session
    from app.db.models import NotificationChannel
    from app.services import notifications as nm

    r = authed.post("/api/v1/settings/notifications/test")
    assert r.status_code == 400

    monkeypatch.setattr(nm, "_send_feishu", lambda secret, content: None)
    db = _session._SessionLocal()
    ch = NotificationChannel(type="feishu", name="飞书", enabled=True, config_json="{}")
    db.add(ch); db.commit(); db.close()
    r = authed.post("/api/v1/settings/notifications/test")
    assert r.status_code == 200
    assert r.json() == [{"id": ch.id, "name": "飞书", "type": "feishu", "ok": True, "error": None}]


def test_notification_test_endpoint_all_fail(authed):
    from app.db import session as _session
    from app.db.models import NotificationChannel

    db = _session._SessionLocal()
    # 真实发送路径:无 webhook 密文 → 发送失败
    db.add(NotificationChannel(type="feishu", name="坏配置", enabled=True, config_json="{}"))
    db.commit(); db.close()
    r = authed.post("/api/v1/settings/notifications/test")
    assert r.status_code == 400
    assert r.json()["detail"][0]["ok"] is False


def test_channel_update_merges_partial_secret(authed):
    """编辑只填部分密钥(如只换加签)→ 其余密钥保留,不得整包覆盖清掉。"""
    import json as _json
    from app.db import session as _session
    from app.db.models import NotificationChannel

    r = authed.post("/api/v1/settings/notification-channels", json={
        "type": "feishu", "name": "f", "config": {},
        "secret": {"webhook": "https://old", "sign": "s1"},
    }).json()
    rr = authed.put(f"/api/v1/settings/notification-channels/{r['id']}", json={
        "type": "feishu", "name": "f", "enabled": True, "config": {},
        "secret": {"sign": "s2"},   # 只换加签,webhook 留空
    })
    assert rr.status_code == 200
    crypto = authed.app.state.crypto
    db = _session._SessionLocal()
    try:
        ch = db.get(NotificationChannel, r["id"])
        assert _json.loads(crypto.decrypt(ch.secret_enc)) == {"webhook": "https://old", "sign": "s2"}
    finally:
        db.close()


def test_channel_update_rejects_type_change(authed):
    """渠道类型不可修改(旧类型密文残留会污染新类型);换类型应删了重建。"""
    r = authed.post("/api/v1/settings/notification-channels", json={
        "type": "email", "name": "e",
        "config": {"smtp_host": "h", "recipients": "a@b"},
    }).json()
    rr = authed.put(f"/api/v1/settings/notification-channels/{r['id']}", json={
        "type": "feishu", "name": "e", "enabled": True, "config": {},
    })
    assert rr.status_code == 422
    assert "类型" in rr.json()["detail"]
