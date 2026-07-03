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
    monkeypatch.setattr("app.services.notifications._send_email", lambda cfg, subj, body: called.setdefault("email", (subj, body)))
    monkeypatch.setattr("app.services.notifications._send_wechat", lambda cfg, content: called.setdefault("wechat", content))
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
