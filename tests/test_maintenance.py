import json
from datetime import datetime

from sqlalchemy import text

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.services.maintenance import reap_stale_running, migrate_schema


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
                            started_at=datetime.utcnow()))  # db_name 未设 → NULL
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
