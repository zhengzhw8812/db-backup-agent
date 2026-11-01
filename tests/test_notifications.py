"""通知渠道遍历发送(v3.4.0):同渠道多账号、逐渠道隔离失败、全局开关。"""
import json

import pytest
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, NotificationConfig, NotificationChannel
from app.core.crypto import Crypto
from app.core.clock import utcnow
from cryptography.fernet import Fernet


def _db(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    return _session._SessionLocal()


def _crypto():
    return Crypto(Fernet.generate_key())


def _conn(db):
    c = DbConnection(name="c", type="pg")
    db.add(c); db.commit(); db.refresh(c)
    return c


def _record(db, cid, status="success"):
    r = BackupRecord(connection_id=cid, trigger="manual", status=status, started_at=utcnow())
    db.add(r); db.commit(); db.refresh(r)
    return r


def _channel(db, crypto, *, type_, name, enabled=True, config=None, secret=None):
    ch = NotificationChannel(
        type=type_, name=name, enabled=enabled,
        config_json=json.dumps(config or {}, ensure_ascii=False),
        secret_enc=crypto.encrypt(json.dumps(secret or {}, ensure_ascii=False))
        if secret is not None else None)
    db.add(ch); db.commit(); db.refresh(ch)
    return ch


def test_notify_no_channels_is_noop(tmp_path):
    db = _db(tmp_path); crypto = _crypto()
    conn = _conn(db); rec = _record(db, conn.id)
    from app.services.notifications import notify_backup_result
    assert notify_backup_result(db, crypto, conn, rec) == []
    db.close()


def test_notify_iterates_enabled_channels(tmp_path, monkeypatch):
    """3 条渠道(2 email + 1 feishu):第 1 条失败不阻断其余,ok 逐渠道如实上报。"""
    from app.services import notifications as nm

    db = _db(tmp_path); crypto = _crypto()
    conn = _conn(db); rec = _record(db, conn.id)
    c1 = _channel(db, crypto, type_="email", name="个人邮箱",
                  config={"smtp_host": "h", "recipients": "a@b"}, secret={"password": "p1"})
    c2 = _channel(db, crypto, type_="email", name="公司邮箱",
                  config={"smtp_host": "h2", "recipients": "x@y"})
    c3 = _channel(db, crypto, type_="feishu", name="运维群", secret={"webhook": "https://h"})
    _channel(db, crypto, type_="serverchan", name="停用", enabled=False, secret={"sendkey": "K"})

    calls = []

    def fake_email(config, subject, body, password):
        calls.append(("email", config["smtp_host"], password))
        if config["smtp_host"] == "h":
            raise RuntimeError("smtp down")

    def fake_feishu(secret, content):
        calls.append(("feishu", secret["webhook"]))

    monkeypatch.setattr(nm, "_send_email", fake_email)
    monkeypatch.setattr(nm, "_send_feishu", fake_feishu)

    out = nm.notify_backup_result(db, crypto, conn, rec)
    assert out == [
        {"channel_id": c1.id, "name": "个人邮箱", "type": "email", "ok": False},
        {"channel_id": c2.id, "name": "公司邮箱", "type": "email", "ok": True},
        {"channel_id": c3.id, "name": "运维群", "type": "feishu", "ok": True},
    ]
    # 停用渠道未被调用;两次 email 都尝试(隔离失败)
    assert [c[0] for c in calls] == ["email", "email", "feishu"]
    assert calls[1][1] == "h2" and calls[2][1] == "https://h"
    db.close()


def test_notify_respects_global_toggles(tmp_path, monkeypatch):
    from app.services import notifications as nm

    db = _db(tmp_path); crypto = _crypto()
    conn = _conn(db); rec = _record(db, conn.id, status="success")
    db.add(NotificationConfig(notify_on_success=False, notify_on_failure=True))
    db.commit()
    _channel(db, crypto, type_="email", name="e", config={"smtp_host": "h", "recipients": "a@b"})
    called = []
    monkeypatch.setattr(nm, "_send_email", lambda *a: called.append(1))
    assert nm.notify_backup_result(db, crypto, conn, rec) == []
    assert called == []
    # 失败开关开着 → 失败记录仍发送
    rec2 = _record(db, conn.id, status="failed")
    assert nm.notify_backup_result(db, crypto, conn, rec2)[0]["ok"] is True
    db.close()


def test_notify_generic_respects_kind_toggle(tmp_path, monkeypatch):
    from app.services import notifications as nm

    db = _db(tmp_path); crypto = _crypto()
    db.add(NotificationConfig(notify_on_failure=False, notify_watchdog=True))
    db.commit()
    _channel(db, crypto, type_="feishu", name="f", secret={"webhook": "https://h"})
    monkeypatch.setattr(nm, "_send_feishu", lambda *a: None)
    assert nm.notify_generic(db, crypto, kind="failure", subject="s", content="c") == []
    out = nm.notify_generic(db, crypto, kind="watchdog", subject="s", content="c")
    assert out and out[0]["ok"] is True
    db.close()


def test_notify_does_not_mutate_encrypted_columns(tmp_path, monkeypatch):
    """解密后的明文绝不能回写到 ORM secret_enc 列(否则一旦 commit 即明文落库)。"""
    from app.services import notifications as nm

    db = _db(tmp_path); crypto = _crypto()
    conn = _conn(db); rec = _record(db, conn.id)
    ch = _channel(db, crypto, type_="email", name="e",
                  config={"smtp_host": "h", "recipients": "a@b"},
                  secret={"password": "topsecret"})
    enc_before = ch.secret_enc
    monkeypatch.setattr(nm, "_send_email", lambda *a: None)
    nm.notify_backup_result(db, crypto, conn, rec)
    assert ch.secret_enc == enc_before
    assert ch.secret_enc != "topsecret"
    assert nm._channel_secret(ch, crypto) == {"password": "topsecret"}
    db.close()


def test_send_by_channel_unknown_type_raises(tmp_path):
    from app.services.notifications import _send_by_channel

    db = _db(tmp_path); crypto = _crypto()
    ch = _channel(db, crypto, type_="pigeon", name="p")
    with pytest.raises(ValueError):
        _send_by_channel(ch, crypto, title="t", content="c")
    db.close()


def test_wechat_token_is_cached(monkeypatch):
    """同一 corp 第二次取 token 应命中缓存,不再发 HTTP。"""
    import app.services.notifications as n
    n._wechat_token_cache.clear()
    calls = {"n": 0}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            return json.dumps({"access_token": "TOK", "expires_in": 7200}).encode()

    def fake_urlopen(url, timeout):
        calls["n"] += 1
        return FakeResp()
    monkeypatch.setattr(n.urllib.request, "urlopen", fake_urlopen)

    assert n._wechat_token("corp", "secret") == "TOK"
    assert n._wechat_token("corp", "secret") == "TOK"  # 复用缓存
    assert calls["n"] == 1
    n._wechat_token_cache.clear()


class FakePost:
    """捕获 _http_post 调用。"""
    def __init__(self):
        self.calls = []

    def __call__(self, url, *, json_body=None, form=None):
        self.calls.append({"url": url, "json": json_body, "data": form})


def test_send_feishu_posts_text_and_signature(monkeypatch):
    import base64
    import hashlib
    import hmac as hmac_mod

    from app.services.notifications import _send_feishu
    post = FakePost()
    monkeypatch.setattr("app.services.notifications._http_post", post)
    secret = "mysec"
    _send_feishu({"webhook": "https://open.feishu.cn/hook/x", "sign": secret}, "hello")
    call = post.calls[0]
    assert call["url"] == "https://open.feishu.cn/hook/x"
    body = call["json"]
    assert body["msg_type"] == "text" and body["content"]["text"] == "hello"
    ts, sign = body["timestamp"], body["sign"]
    expect = base64.b64encode(hmac_mod.new(
        f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()
    assert sign == expect


def test_send_serverchan_posts_title_desp(monkeypatch):
    from app.services.notifications import _send_serverchan
    post = FakePost()
    monkeypatch.setattr("app.services.notifications._http_post", post)
    _send_serverchan({"sendkey": "SCT123"}, "标题", "内容")
    call = post.calls[0]
    assert call["url"] == "https://sctapi.ftqq.com/SCT123.send"
    assert call["data"] == {"title": "标题", "desp": "内容"}
