import json
from datetime import datetime

from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.core.crypto import Crypto
from app.core.archive import compress_file, sha256_of_file
from cryptography.fernet import Fernet
from app.services.restore_service import run_restore
from app.workers.progress import ProgressReporter


class FakeRestoreAdapter:
    type = "pg"

    def __init__(self):
        self.restored = None

    def restore(self, info, src_path):
        with open(src_path, "rb") as f:
            self.restored = f.read()


class FakeRedis:
    def __init__(self, cancelled=False):
        self.published = []
        self._cancelled = cancelled

    def publish(self, channel, msg):
        self.published.append((channel, msg))

    def exists(self, key):
        return self._cancelled

    def set(self, k, v):
        self._cancelled = True


def _setup(tmp_path, monkeypatch, adapter=None):
    """建 DB + 连接 + 一份真实 success 备份(含 gz+checksum) + 一条 running 恢复记录。"""
    monkeypatch.setattr("app.services.restore_service.get_adapter",
                        lambda t: adapter or FakeRestoreAdapter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", host="h", port=5432, db_name="d",
                        username="u", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    bdir = tmp_path / "backups"; bdir.mkdir()
    raw = bdir / "pg.sql"; raw.write_bytes(b"-- dump\n")
    gz_name = "pg_1_1.sql.gz"; gz = bdir / gz_name
    compress_file(raw, gz)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path=gz_name, size=gz.stat().st_size,
                          checksum=sha256_of_file(gz),
                          started_at=datetime.utcnow(), finished_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    restore = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn.id,
                            status="running", started_at=datetime.utcnow())
    db.add(restore); db.commit(); db.refresh(restore)
    return db, conn, crypto, bdir, backup, restore.id


def test_run_restore_success(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    fake = FakeRedis()
    rec = run_restore(db, crypto, backup, conn, ProgressReporter(rid, fake), bdir, rid)
    assert rec.status == "success"
    assert rec.duration_ms is not None
    stages = [json.loads(m)["stage"] for _, m in fake.published]
    assert stages == ["verify", "decompress", "restore", "success"]
    db.close()


def test_run_restore_checksum_mismatch(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    (bdir / backup.file_path).write_bytes(b"tampered")  # 篡改使 checksum 不匹配
    fake = FakeRedis()
    rec = run_restore(db, crypto, backup, conn, ProgressReporter(rid, fake), bdir, rid)
    assert rec.status == "failed"
    assert "校验和" in rec.error
    db.close()


def test_run_restore_cancelled_before(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    rec = run_restore(db, crypto, backup, conn,
                      ProgressReporter(rid, FakeRedis(cancelled=True)), bdir, rid)
    assert rec.status == "cancelled"
    db.close()


def test_run_restore_unknown_record_raises(tmp_path, monkeypatch):
    db, conn, crypto, bdir, backup, rid = _setup(tmp_path, monkeypatch)
    import pytest
    with pytest.raises(ValueError):
        run_restore(db, crypto, backup, conn, ProgressReporter(rid, FakeRedis()), bdir, 999999)
    db.close()


def test_run_restore_sync_wires_service(monkeypatch, tmp_path):
    from app.workers.jobs import _run_restore_sync
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("secret", key))
    monkeypatch.setattr("app.services.restore_service.get_adapter", lambda t: FakeRestoreAdapter())

    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    crypto = Crypto(key.encode("ascii"))
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    raw = bdir / "pg.sql"; raw.write_bytes(b"-- dump\n")
    gz_name = "pg_1_1.sql.gz"; gz = bdir / gz_name
    compress_file(raw, gz)
    backup = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                          file_path=gz_name, size=gz.stat().st_size,
                          checksum=sha256_of_file(gz),
                          started_at=datetime.utcnow(), finished_at=datetime.utcnow())
    db.add(backup); db.commit(); db.refresh(backup)
    restore = RestoreRecord(backup_record_id=backup.id, target_connection_id=conn.id,
                            status="running", started_at=datetime.utcnow())
    db.add(restore); db.commit(); db.refresh(restore)
    bid, cid, rid = backup.id, conn.id, restore.id
    db.close()

    class FakeReporter:
        def report(self, *a, **k): pass
        def is_cancelled(self): return False

    # worker 内构造 ProgressReporter(rid, kind="restore");打桩需接受 kind kwarg
    monkeypatch.setattr("app.workers.jobs.ProgressReporter", lambda rid, **kw: FakeReporter())
    ctx = {"backup_dir": bdir}
    result = _run_restore_sync(ctx, bid, cid, rid)
    assert result["status"] == "success"
    assert result["record_id"] == rid
