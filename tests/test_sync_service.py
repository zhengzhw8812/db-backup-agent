from datetime import datetime

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, CloudDestination, SyncTarget
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.sync_service import run_sync
from app.core.clock import utcnow


class FakeStorage:
    """记录 upload 调用,可注入失败。镜像真实 S3StorageAdapter 的前缀拼接行为。"""
    def __init__(self, fail=False):
        self.uploads = []
        self._fail = fail
    def upload(self, cfg, local_path, key):
        if self._fail:
            raise RuntimeError("upload boom")
        full = f"{cfg.prefix}/{key}" if cfg.prefix else key
        self.uploads.append((cfg.bucket, full))
        return f"s3://{cfg.bucket}/{full}"
    def delete(self, cfg, key): pass
    def test(self, cfg): pass


def _setup(tmp_path, monkeypatch, storage=None):
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: storage or FakeStorage())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    bdir = tmp_path / "backups"; bdir.mkdir()
    (bdir / "pg.sql.gz").write_bytes(b"data")
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path="pg.sql.gz", started_at=utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    dest = CloudDestination(name="minio", provider="s3", endpoint="h:9000", bucket="bk",
                            access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                            prefix="pre", secure=False, enabled=True)
    db.add(dest); db.commit(); db.refresh(dest)
    tgt = SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True)
    db.add(tgt); db.commit()
    return db, crypto, bdir, backup


def test_run_sync_uploads_to_targets(tmp_path, monkeypatch):
    storage = FakeStorage()
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    result = run_sync(db, crypto, backup, bdir)
    assert len(result["synced"]) == 1
    assert result["synced"][0]["uri"] == "s3://bk/pre/pg.sql.gz"
    assert storage.uploads == [("bk", "pre/pg.sql.gz")]
    assert result["errors"] == []
    db.close()


def test_run_sync_records_target_failure(tmp_path, monkeypatch):
    storage = FakeStorage(fail=True)
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    result = run_sync(db, crypto, backup, bdir)
    assert result["synced"] == []
    assert len(result["errors"]) == 1
    assert "upload boom" in result["errors"][0]["error"]
    db.close()


def test_run_sync_missing_file_raises(tmp_path, monkeypatch):
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch)
    (bdir / "pg.sql.gz").unlink()
    import pytest
    with pytest.raises(FileNotFoundError):
        run_sync(db, crypto, backup, bdir)
    db.close()


def test_run_sync_sync_wires_service(monkeypatch, tmp_path):
    from app.workers.jobs import _run_sync_sync
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("secret", key))
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: FakeStorage())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    (bdir / "pg.sql.gz").write_bytes(b"data")
    crypto = Crypto(key.encode("ascii"))
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path="pg.sql.gz", started_at=utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    dest = CloudDestination(name="m", provider="s3", endpoint="h:9000", bucket="bk",
                            access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"))
    db.add(dest); db.commit(); db.refresh(dest)
    db.add(SyncTarget(connection_id=conn.id, cloud_destination_id=dest.id, enabled=True))
    db.commit()
    bid = backup.id
    db.close()
    result = _run_sync_sync({"backup_dir": bdir}, bid)
    assert len(result["synced"]) == 1


class RecordingDeleteStorage(FakeStorage):
    """记录 delete 调用;可配置第 N 次抛异常。"""
    def __init__(self, fail_on=0):
        super().__init__()
        self.deletes = []
        self.calls = 0
        self._fail_on = fail_on

    def delete(self, cfg, key):
        self.calls += 1
        if self.calls == self._fail_on:
            raise RuntimeError("delete boom")
        full = f"{cfg.prefix}/{key}" if cfg.prefix else key
        self.deletes.append((cfg.bucket, full))


def _add_dest(db, crypto, conn_id, *, name="m2", bucket="bk2", prefix="", enabled=True, target_enabled=True):
    dest = CloudDestination(name=name, provider="s3", endpoint="h2:9000", bucket=bucket,
                            access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                            prefix=prefix, secure=False, enabled=True)
    db.add(dest); db.commit(); db.refresh(dest)
    db.add(SyncTarget(connection_id=conn_id, cloud_destination_id=dest.id, enabled=target_enabled))
    db.commit()


def test_delete_cloud_copies_removes_from_enabled_targets(tmp_path, monkeypatch):
    from app.services.sync_service import delete_cloud_copies
    storage = RecordingDeleteStorage()
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    conn = db.get(DbConnection, backup.connection_id)
    _add_dest(db, crypto, conn.id, bucket="bk2", prefix="")
    _add_dest(db, crypto, conn.id, bucket="bk3", prefix="p3", target_enabled=False)
    n = delete_cloud_copies(db, crypto, conn.id, "pg.sql.gz")
    db.close()
    assert n == 2
    assert sorted(storage.deletes) == [("bk", "pre/pg.sql.gz"), ("bk2", "pg.sql.gz")]


def test_delete_cloud_copies_continues_on_failure(tmp_path, monkeypatch):
    from app.services.sync_service import delete_cloud_copies
    from app.db.models import SystemLog
    storage = RecordingDeleteStorage(fail_on=1)
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    conn = db.get(DbConnection, backup.connection_id)
    _add_dest(db, crypto, conn.id)
    n = delete_cloud_copies(db, crypto, conn.id, "pg.sql.gz")
    logs = db.query(SystemLog).filter(SystemLog.level == "warning", SystemLog.source == "cloud").all()
    db.close()
    assert n == 1  # 第一个目标失败,第二个仍被删
    assert len(logs) == 1
    assert "delete boom" in (logs[0].context or "") + logs[0].message


def test_retention_deletes_cloud_copies(tmp_path, monkeypatch):
    from app.db.models import Schedule
    from app.services.retention import run_retention
    storage = RecordingDeleteStorage()
    db, crypto, bdir, backup = _setup(tmp_path, monkeypatch, storage)
    conn = db.get(DbConnection, backup.connection_id)
    db.add(Schedule(connection_id=conn.id, cron_expr="0 2 * * *", retention_days=1, enabled=True))
    backup.started_at = utcnow() - __import__("datetime").timedelta(days=2)
    db.commit()
    count = run_retention(db, crypto, conn, bdir)
    db.close()
    assert count == 1
    assert storage.deletes == [("bk", "pre/pg.sql.gz")]
