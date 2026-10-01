import json
from types import SimpleNamespace
import pytest
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, NotificationConfig
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.notifications import notify_backup_result
from app.core.clock import utcnow


def _db(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    return _session._SessionLocal()


def test_notify_no_config_is_noop(tmp_path):
    db = _db(tmp_path)
    crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=utcnow())
    # 无 NotificationConfig —— 不应抛错
    assert notify_backup_result(db, crypto, conn, rec) == {"email": False, "wechat": False}
    db.close()


def test_notify_success_respects_flag(tmp_path, monkeypatch):
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(NotificationConfig(email_enabled=True, wechat_enabled=False, notify_on_success=True, notify_on_failure=True,
                              smtp_host="h", smtp_port=25, smtp_from="a@b", recipients="x@y"))
    db.commit()
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    called = {}
    monkeypatch.setattr("app.services.notifications._send_email", lambda cfg, subj, body, password: called.setdefault("email", (subj, body)))
    monkeypatch.setattr("app.services.notifications._send_wechat", lambda cfg, content, secret: called.setdefault("wechat", content))
    result = notify_backup_result(db, crypto, conn, rec)
    assert result["email"] is True and result["wechat"] is False
    assert "成功" in called["email"][0]
    db.close()


def test_notify_failure_when_flag_off_skips(tmp_path, monkeypatch):
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(NotificationConfig(email_enabled=True, notify_on_success=False, notify_on_failure=False,
                              smtp_host="h", smtp_port=25, smtp_from="a@b", recipients="x@y"))
    db.commit()
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="failed", error="boom", started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    monkeypatch.setattr("app.services.notifications._send_email", lambda *a: None)
    assert notify_backup_result(db, crypto, conn, rec)["email"] is False
    db.close()


def test_notify_one_channel_failure_does_not_break_other(tmp_path, monkeypatch):
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(NotificationConfig(email_enabled=True, wechat_enabled=True, smtp_host="h", smtp_port=25,
                              smtp_from="a@b", recipients="x@y", wechat_corp_id="cid", wechat_agent_id="aid"))
    db.commit()
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    def boom_email(*a): raise RuntimeError("smtp down")
    monkeypatch.setattr("app.services.notifications._send_email", boom_email)
    monkeypatch.setattr("app.services.notifications._send_wechat", lambda *a: None)
    result = notify_backup_result(db, crypto, conn, rec)
    assert result["email"] is False      # 邮件失败
    assert result["wechat"] is True      # 微信仍发送
    db.close()


def test_notify_does_not_mutate_encrypted_columns(tmp_path, monkeypatch):
    """解密后的明文绝不能回写到 ORM *_enc 列(否则一旦 commit 即明文落库)。"""
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    enc_pw = crypto.encrypt("topsecret")
    cfg = NotificationConfig(email_enabled=True, smtp_host="h", smtp_port=25,
                             smtp_from="a@b", recipients="x@y", smtp_user="u", smtp_password_enc=enc_pw)
    db.add(cfg); db.commit(); db.refresh(cfg)
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    monkeypatch.setattr("app.services.notifications._send_email", lambda *a: None)
    notify_backup_result(db, crypto, conn, rec)
    # 列仍应是原始密文,且不是明文
    assert cfg.smtp_password_enc == enc_pw
    assert cfg.smtp_password_enc != "topsecret"
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


@pytest.fixture
def crypto():
    return Crypto(Fernet.generate_key())


class FakePost:
    """捕获 requests.post 调用。"""
    def __init__(self):
        self.calls = []

    def __call__(self, url, json=None, data=None, timeout=None):
        self.calls.append({"url": url, "json": json, "data": data})
        return SimpleNamespace(ok=True, raise_for_status=lambda: None)


def _cfg_with(crypto, **kw):
    cfg = NotificationConfig(email_enabled=False, wechat_enabled=False, **kw)
    return cfg


def test_send_feishu_posts_text_and_signature(crypto, monkeypatch):
    import base64
    import hashlib
    import hmac as hmac_mod

    from app.services.notifications import _send_feishu
    post = FakePost()
    monkeypatch.setattr("app.services.notifications.requests.post", post)
    secret = "mysec"
    cfg = _cfg_with(crypto, feishu_enabled=True,
                    feishu_webhook_enc=crypto.encrypt("https://open.feishu.cn/hook/x"),
                    feishu_secret_enc=crypto.encrypt(secret))
    _send_feishu(cfg, "hello", crypto)
    call = post.calls[0]
    assert call["url"] == "https://open.feishu.cn/hook/x"
    body = call["json"]
    assert body["msg_type"] == "text" and body["content"]["text"] == "hello"
    ts, sign = body["timestamp"], body["sign"]
    expect = base64.b64encode(hmac_mod.new(
        f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()
    assert sign == expect


def test_send_serverchan_posts_title_desp(crypto, monkeypatch):
    from app.services.notifications import _send_serverchan
    post = FakePost()
    monkeypatch.setattr("app.services.notifications.requests.post", post)
    cfg = _cfg_with(crypto, serverchan_enabled=True,
                    serverchan_sendkey_enc=crypto.encrypt("SCT123"))
    _send_serverchan(cfg, "标题", "内容", crypto)
    call = post.calls[0]
    assert call["url"] == "https://sctapi.ftqq.com/SCT123.send"
    assert call["data"] == {"title": "标题", "desp": "内容"}


def test_dispatcher_includes_new_channels(crypto, monkeypatch):
    """notify_backup_result 分发到飞书与 Server酱,受成功/失败开关约束。"""
    from app.services import notifications as nm

    sent = {}
    monkeypatch.setattr(nm, "_send_feishu", lambda cfg, content, cr: sent.setdefault("feishu", content))
    monkeypatch.setattr(nm, "_send_serverchan", lambda cfg, title, content, cr: sent.setdefault("serverchan", title))

    db = _session_db()
    cfg = _cfg_with(crypto, feishu_enabled=True,
                    feishu_webhook_enc=crypto.encrypt("https://h"),
                    serverchan_enabled=True,
                    serverchan_sendkey_enc=crypto.encrypt("K"))
    db.add(cfg); db.commit()
    conn = _conn(db)
    rec = _record(db, conn.id, status="success")

    out = nm.notify_backup_result(db, crypto, conn, rec)
    db.close()
    assert out["feishu"] and out["serverchan"]
    assert "feishu" in sent and "serverchan" in sent


def _session_db():
    import tempfile
    from pathlib import Path as _P
    from app.db.session import init_engine, create_all
    from app.db import session as _session
    import app.db.models  # noqa

    init_engine(f"sqlite:///{_P(tempfile.mkdtemp())/'t.db'}")
    create_all()
    return _session._SessionLocal()


def _conn(db):
    from app.db.models import DbConnection

    c = DbConnection(name="c", type="pg")
    db.add(c); db.commit(); db.refresh(c)
    return c


def _record(db, cid, status):
    from app.db.models import BackupRecord
    from app.core.clock import utcnow

    r = BackupRecord(connection_id=cid, trigger="manual", status=status, started_at=utcnow())
    db.add(r); db.commit(); db.refresh(r)
    return r
