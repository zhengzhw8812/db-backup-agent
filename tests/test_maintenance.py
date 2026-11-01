import json
from datetime import datetime

from sqlalchemy import text

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.services.maintenance import reap_stale_running, migrate_schema
from app.core.clock import utcnow


def test_reap_marks_stale_running_as_failed(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    # 一条 running(残留)、一条 success(正常)备份
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="running", started_at=utcnow()))
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=utcnow()))
    db.commit()
    backup_id = db.query(BackupRecord).filter(BackupRecord.status == "success").first().id
    # 一条 running 恢复
    db.add(RestoreRecord(backup_record_id=backup_id, target_connection_id=conn.id,
                         status="running", started_at=utcnow()))
    db.commit()

    n = reap_stale_running(db)
    assert n == 2  # 备份 + 恢复
    assert db.query(BackupRecord).filter(BackupRecord.status == "running").count() == 0
    assert db.query(RestoreRecord).filter(RestoreRecord.status == "running").count() == 0
    # success 备份不受影响
    assert db.query(BackupRecord).filter(BackupRecord.status == "success").count() == 1
    db.close()


def test_reap_noop_when_nothing_stale(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _session._SessionLocal()
    assert reap_stale_running(db) == 0
    db.close()


def test_migrate_schema_backfills_db_names(tmp_path):
    """旧连接(只有 db_name,无 db_names)启动迁移后应回填 db_names=['<db_name>']。"""
    init_engine(f"sqlite:///{tmp_path/'m.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="legacy", type="pg", db_name="legacydb")
        db.add(c); db.commit(); db.refresh(c)

        migrate_schema(db)
        db.refresh(c)
        assert json.loads(c.db_names) == ["legacydb"]

        # 幂等:再跑一次不变
        migrate_schema(db)
        db.refresh(c)
        assert json.loads(c.db_names) == ["legacydb"]
    finally:
        db.close()


def test_migrate_schema_preserves_existing_db_names(tmp_path):
    """已有 db_names 的连接不应被回填覆盖。"""
    init_engine(f"sqlite:///{tmp_path/'p.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        keep = DbConnection(name="keep", type="pg", db_names=json.dumps(["already"]))
        db.add(keep); db.commit(); db.refresh(keep)

        migrate_schema(db)
        db.refresh(keep)
        assert json.loads(keep.db_names) == ["already"]
    finally:
        db.close()


def test_migrate_schema_backfills_record_db_name(tmp_path):
    """旧备份记录(db_name NULL)+ 连接有 db_name → 回填 record.db_name。"""
    init_engine(f"sqlite:///{tmp_path/'rec.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        conn = DbConnection(name="legacy", type="pg", db_name="legacydb")
        db.add(conn); db.commit(); db.refresh(conn)
        db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                            started_at=utcnow()))  # db_name 未设 → NULL
        db.commit()

        migrate_schema(db)
        rec = db.query(BackupRecord).one()
        assert rec.db_name == "legacydb"
    finally:
        db.close()


def test_migrate_schema_adds_missing_columns(tmp_path):
    """模拟旧库(缺新列):migrate_schema 应补上 db_connections.db_names 与 backup_records.db_name。"""
    init_engine(f"sqlite:///{tmp_path/'legacy.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        # 旧连接只有 db_name(先入库,再 DROP——ORM INSERT 列表固定含 db_names)
        db.add(DbConnection(name="legacy", type="pg", db_name="legacydb"))
        db.commit()

        # 模拟升级前:删掉两个新列(SQLite >=3.35 支持 DROP COLUMN)
        db.execute(text("ALTER TABLE db_connections DROP COLUMN db_names"))
        db.execute(text("ALTER TABLE backup_records DROP COLUMN db_name"))
        db.commit()
        db.expire_all()  # 丢弃身份映射里的缓存,强制后续 SELECT 重新读库

        # 补列前应确实不存在
        cols_conn_pre = [r[1] for r in db.execute(text("PRAGMA table_info(db_connections)"))]
        cols_rec_pre = [r[1] for r in db.execute(text("PRAGMA table_info(backup_records)"))]
        assert "db_names" not in cols_conn_pre
        assert "db_name" not in cols_rec_pre

        migrate_schema(db)  # 应补列 + 回填

        cols_conn = [r[1] for r in db.execute(text("PRAGMA table_info(db_connections)"))]
        cols_rec = [r[1] for r in db.execute(text("PRAGMA table_info(backup_records)"))]
        assert "db_names" in cols_conn
        assert "db_name" in cols_rec
        c = db.query(DbConnection).filter_by(name="legacy").one()
        assert json.loads(c.db_names) == ["legacydb"]
    finally:
        db.close()


def _migration_db(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'mig.db'}")
    create_all()
    return _session._SessionLocal()


def test_migrate_legacy_config_creates_channels(tmp_path):
    """旧配置已启用的渠道各生成一行;填了凭据但禁用的(wechat)不迁。"""
    from app.db.models import NotificationConfig, NotificationChannel
    from app.core.crypto import Crypto
    from app.services.maintenance import migrate_notification_channels
    from cryptography.fernet import Fernet

    db = _migration_db(tmp_path)
    crypto = Crypto(Fernet.generate_key())
    db.add(NotificationConfig(
        email_enabled=True, smtp_host="h", smtp_port=465, smtp_ssl=True, smtp_starttls=False,
        smtp_user="u", smtp_from="a@b", recipients="x@y",
        smtp_password_enc=crypto.encrypt("pw"),
        wechat_enabled=False, wechat_corp_id="cid", wechat_agent_id="aid",
        wechat_secret_enc=crypto.encrypt("wsec"),
        feishu_enabled=True, feishu_webhook_enc=crypto.encrypt("https://hook"),
        serverchan_enabled=False))
    db.commit()

    n = migrate_notification_channels(db, crypto)
    assert n == 2
    chs = {c.type: c for c in db.query(NotificationChannel).all()}
    assert set(chs) == {"email", "feishu"}
    assert chs["email"].name == "邮箱" and chs["feishu"].name == "飞书"
    cfg = json.loads(chs["email"].config_json)
    assert cfg["smtp_host"] == "h" and cfg["smtp_port"] == 465 and cfg["recipients"] == "x@y"
    assert cfg["smtp_ssl"] is True and cfg["smtp_starttls"] is False
    assert json.loads(crypto.decrypt(chs["email"].secret_enc)) == {"password": "pw"}
    assert json.loads(crypto.decrypt(chs["feishu"].secret_enc)) == {"webhook": "https://hook"}
    db.close()


def test_migrate_runs_once_marker(tmp_path):
    """一次性标记:重跑 0 行;用户删光渠道后重跑也不复活。"""
    from app.db.models import NotificationConfig, NotificationChannel
    from app.core.crypto import Crypto
    from app.services.maintenance import migrate_notification_channels
    from app.services.settings_service import get_setting
    from cryptography.fernet import Fernet

    db = _migration_db(tmp_path)
    crypto = Crypto(Fernet.generate_key())
    db.add(NotificationConfig(email_enabled=True, smtp_host="h", recipients="x@y"))
    db.commit()

    assert migrate_notification_channels(db, crypto) == 1
    assert migrate_notification_channels(db, crypto) == 0  # 标记生效
    db.query(NotificationChannel).delete(); db.commit()  # 用户删光
    assert migrate_notification_channels(db, crypto) == 0  # 不复活
    assert get_setting(db, "notification_channels_migrated") is True
    db.close()


def test_migrate_noop_without_legacy_config(tmp_path):
    """无旧配置:仍写标记(此后永不迁移)。"""
    from app.core.crypto import Crypto
    from app.services.maintenance import migrate_notification_channels
    from app.services.settings_service import get_setting
    from cryptography.fernet import Fernet

    db = _migration_db(tmp_path)
    crypto = Crypto(Fernet.generate_key())
    assert migrate_notification_channels(db, crypto) == 0
    assert get_setting(db, "notification_channels_migrated") is True
    db.close()
