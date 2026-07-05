from datetime import datetime, timedelta
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, Schedule
from app.services.retention import run_retention


def _setup(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(Schedule(connection_id=conn.id, cron_expr="0 2 * * *", retention_days=7, enabled=True))
    db.commit()
    return db, conn, bdir


def _mk(db, conn, bdir, file_name, days_old):
    from app.core.archive import compress_file
    raw = bdir / "x.sql"; raw.write_bytes(b"d")
    gz = bdir / file_name; compress_file(raw, gz)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                       file_path=file_name, size=1, checksum="c",
                       started_at=datetime.utcnow() - timedelta(days=days_old),
                       finished_at=datetime.utcnow() - timedelta(days=days_old))
    db.add(rec); db.commit(); db.refresh(rec)
    return rec


def test_retention_deletes_old_backups(tmp_path):
    db, conn, bdir = _setup(tmp_path)
    old = _mk(db, conn, bdir, "old.sql.gz", days_old=30)
    fresh = _mk(db, conn, bdir, "fresh.sql.gz", days_old=1)
    count = run_retention(db, conn, bdir)
    assert count == 1
    assert db.get(BackupRecord, old.id) is None
    assert db.get(BackupRecord, fresh.id) is not None
    assert not (bdir / "old.sql.gz").exists()
    assert (bdir / "fresh.sql.gz").exists()
    db.close()


def test_retention_no_schedule_skips(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}"); create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    assert run_retention(db, conn, bdir) == 0   # 无计划 → 不清理
    db.close()


def test_retention_only_cleans_success(tmp_path):
    db, conn, bdir = _setup(tmp_path)
    from app.core.archive import compress_file
    raw = bdir / "x.sql"; raw.write_bytes(b"d"); gz = bdir / "f.sql.gz"; compress_file(raw, gz)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="running",
                       file_path="f.sql.gz",
                       started_at=datetime.utcnow() - timedelta(days=30))
    db.add(rec); db.commit()
    assert run_retention(db, conn, bdir) == 0   # 非 success 不删
    db.close()


def test_retention_zero_days_floored_to_one(tmp_path):
    """retention_days=0 不应把刚生成的备份立即删掉——至少保留 1 天。"""
    init_engine(f"sqlite:///{tmp_path/'t.db'}"); create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(Schedule(connection_id=conn.id, cron_expr="0 2 * * *", retention_days=0, enabled=True))
    db.commit()
    fresh = _mk(db, conn, bdir, "fresh.sql.gz", days_old=0)  # 刚生成(几秒前)
    count = run_retention(db, conn, bdir)
    assert count == 0  # 不会被立刻清掉
    assert db.get(BackupRecord, fresh.id) is not None
    db.close()
