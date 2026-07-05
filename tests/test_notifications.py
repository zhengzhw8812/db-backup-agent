import json
import pytest
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, NotificationConfig
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.notifications import notify_backup_result


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
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
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
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
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
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="failed", error="boom", started_at=datetime.utcnow())
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
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
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
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
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
