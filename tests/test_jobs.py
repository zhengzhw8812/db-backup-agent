from datetime import datetime
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.workers.jobs import _run_backup_sync


class FakeAdapter:
    type = "pg"
    def dump(self, info, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"-- dump\n")


class FakeReporter:
    def report(self, *a, **k): pass
    def is_cancelled(self): return False


def test_run_backup_sync_wires_service(monkeypatch, tmp_path):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("secret", key))
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: FakeAdapter())
    monkeypatch.setattr("app.workers.jobs.ProgressReporter", lambda rid: FakeReporter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()

    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", password_enc=Crypto(key.encode("ascii")).encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    record = BackupRecord(connection_id=conn.id, trigger="manual", status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    conn_id, record_id = conn.id, record.id
    db.close()

    ctx = {"backup_dir": bdir}
    result = _run_backup_sync(ctx, conn_id, record_id)
    assert result["status"] == "success"
    assert result["record_id"] == record_id
