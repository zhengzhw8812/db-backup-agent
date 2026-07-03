from sqlalchemy import inspect
from app.db.session import init_engine, create_all
import app.db.models  # noqa  确保模型已注册


def test_all_tables_created(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    from app.db.session import _engine  # init_engine 之后才非 None
    inspector = inspect(_engine)
    tables = set(inspector.get_table_names())
    expected = {"account", "db_connections", "schedules", "backup_records",
                "restore_records", "system_logs"}
    assert expected.issubset(tables)


def test_restore_record_persists(tmp_path):
    from datetime import datetime
    from app.db.models import DbConnection, BackupRecord, RestoreRecord
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    from app.db.session import _SessionLocal  # init_engine 之后才非 None
    db = _SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          started_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    rec = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn.id,
                        status="running", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    got = db.get(RestoreRecord, rec.id)
    assert got is not None
    assert got.backup_record_id == backup.id
    assert got.status == "running"
    db.close()
