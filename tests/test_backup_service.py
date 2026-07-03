from pathlib import Path
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.backup_service import run_backup
from app.workers.progress import ProgressReporter


class FakeAdapter:
    type = "pg"

    def __init__(self, content: bytes = b"-- dump\n"):
        self.content = content

    def dump(self, info, dest_path):
        with open(dest_path, "wb") as f:
            f.write(self.content)


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


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: FakeAdapter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", host="h", port=5432, db_name="d",
                        username="u", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    return db, conn, crypto, tmp_path / "backups"


def test_run_backup_success(tmp_path, monkeypatch):
    db, conn, crypto, bdir = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    reporter = ProgressReporter(conn.id, FakeRedis())
    rec = run_backup(db, crypto, conn, "manual", reporter, bdir)
    assert rec.status == "success"
    assert rec.checksum and len(rec.checksum) == 64
    assert rec.size and rec.size > 0
    assert rec.file_path and rec.file_path.endswith(".sql.gz")
    assert (bdir / rec.file_path).exists()
    db.close()


def test_run_backup_failed(tmp_path, monkeypatch):
    db, conn, crypto, bdir = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    class BoomAdapter(FakeAdapter):
        def dump(self, info, dest): raise RuntimeError("pg_dump not found")
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: BoomAdapter())
    reporter = ProgressReporter(conn.id, FakeRedis())
    rec = run_backup(db, crypto, conn, "manual", reporter, bdir)
    assert rec.status == "failed"
    assert "pg_dump not found" in rec.error
    db.close()


def test_run_backup_cancelled(tmp_path, monkeypatch):
    db, conn, crypto, bdir = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    reporter = ProgressReporter(conn.id, FakeRedis(cancelled=True))
    rec = run_backup(db, crypto, conn, "manual", reporter, bdir)
    assert rec.status == "cancelled"
    db.close()
