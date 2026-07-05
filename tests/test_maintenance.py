from datetime import datetime

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.services.maintenance import reap_stale_running


def test_reap_marks_stale_running_as_failed(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    # 一条 running(残留)、一条 success(正常)备份
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="running", started_at=datetime.utcnow()))
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow()))
    db.commit()
    backup_id = db.query(BackupRecord).filter(BackupRecord.status == "success").first().id
    # 一条 running 恢复
    db.add(RestoreRecord(backup_record_id=backup_id, target_connection_id=conn.id,
                         status="running", started_at=datetime.utcnow()))
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


def test_migrate_schema_backfills_db_names(tmp_path, monkeypatch):
    """旧连接(只有 db_name,无 db_names)启动迁移后应回填 db_names=['<db_name>']。"""
    from app.db import session as _session
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection
    from app.core.crypto import Crypto
    from cryptography.fernet import Fernet
    from app.services.maintenance import migrate_schema
    import json

    init_engine(f"sqlite:///{tmp_path/'m.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        crypto = Crypto(Fernet.generate_key())
        c = DbConnection(name="legacy", type="pg", host="h", port=5432,
                         db_name="legacydb", username="u",
                         password_enc=crypto.encrypt("pw"), db_names=None)
        db.add(c); db.commit(); db.refresh(c)

        migrate_schema(db)
        db.refresh(c)
        assert json.loads(c.db_names) == ["legacydb"]
    finally:
        db.close()
