"""备份验证:单次遍历(gzip CRC + .gz 压缩字节的 sha256 比对)。"""
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.archive import compress_and_hash
from app.core.crypto import Crypto
from app.core.clock import utcnow
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord
from app.services.verify_service import run_verify


def _setup(tmp_path: Path, *, with_file=True, checksum=None):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    bdir = tmp_path / "backups"; bdir.mkdir()
    ck = None
    if with_file:
        raw = bdir / "raw.sql"
        raw.write_bytes(b"INSERT INTO t VALUES (1);\n" * 400)
        ck = compress_and_hash(raw, bdir / "p.sql.gz")
        raw.unlink()
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                       file_path="p.sql.gz", checksum=checksum if checksum is not None else ck,
                       started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    return db, bdir, rec


def test_verify_passed(tmp_path):
    db, bdir, rec = _setup(tmp_path)
    out = run_verify(db, rec, bdir)
    db.close()
    assert out.verify_status == "passed"
    assert out.verified_at is not None
    assert out.verify_error is None


def test_verify_checksum_mismatch(tmp_path):
    db, bdir, rec = _setup(tmp_path)
    # 用另一份合法 gzip 覆盖:CRC 完好,但内容与记录不符 → checksum 比对失败
    other = bdir / "other.sql"
    other.write_bytes(b"INSERT INTO t VALUES (999);\n" * 400)
    from app.core.archive import compress_file
    compress_file(other, bdir / "p.sql.gz")
    other.unlink()
    out = run_verify(db, rec, bdir)
    db.close()
    assert out.verify_status == "failed"
    assert "校验" in out.verify_error


def test_verify_gzip_corrupted(tmp_path):
    db, bdir, rec = _setup(tmp_path)
    data = (bdir / "p.sql.gz").read_bytes()
    (bdir / "p.sql.gz").write_bytes(data[: len(data) // 2])  # 截断
    out = run_verify(db, rec, bdir)
    db.close()
    assert out.verify_status == "failed"
    assert "gzip" in out.verify_error


def test_verify_missing_file(tmp_path):
    db, bdir, rec = _setup(tmp_path, with_file=False)
    out = run_verify(db, rec, bdir)
    db.close()
    assert out.verify_status == "failed"
    assert "不存在" in out.verify_error


def test_verify_rejects_path_escape(tmp_path):
    db, bdir, rec = _setup(tmp_path)
    rec.file_path = "../escape.sql.gz"
    db.commit()
    with pytest.raises(ValueError):
        run_verify(db, rec, bdir)
    db.close()


def test_verify_failure_notifies(tmp_path, monkeypatch):
    """验证失败 → 经 notify_generic(kind="failure") 发通知,内容含记录号与原因。"""
    from app.db.models import DbConnection
    from app.workers.jobs import _run_verify_sync

    alerts = []
    monkeypatch.setattr("app.services.notifications.notify_generic",
                        lambda db, crypto, *, kind, subject, content:
                        alerts.append((kind, subject, content)) or {"email": False})
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("sk", Fernet.generate_key().decode()))

    db, bdir, rec = _setup(tmp_path)
    name = db.get(DbConnection, rec.connection_id).name
    data = (bdir / "p.sql.gz").read_bytes()
    (bdir / "p.sql.gz").write_bytes(data[: len(data) // 2])  # 截断损坏
    rid = rec.id
    db.close()

    out = _run_verify_sync({"backup_dir": bdir}, rid)
    assert out["status"] == "failed"
    assert len(alerts) == 1
    kind, subject, content = alerts[0]
    assert kind == "failure"
    assert name in subject and str(rid) in content
    assert "gzip" in content


def test_verify_success_does_not_notify(tmp_path, monkeypatch):
    from app.workers.jobs import _run_verify_sync

    alerts = []
    monkeypatch.setattr("app.services.notifications.notify_generic",
                        lambda db, crypto, *, kind, subject, content:
                        alerts.append((kind, subject)) or {"email": False})
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("sk", Fernet.generate_key().decode()))

    db, bdir, rec = _setup(tmp_path)
    rid = rec.id
    db.close()
    _run_verify_sync({"backup_dir": bdir}, rid)
    assert alerts == []


def test_verify_zero_byte_file_fails(tmp_path):
    """0 字节文件不是合法 gzip → failed(而不是 passed)。"""
    db, bdir, rec = _setup(tmp_path, with_file=False)
    (bdir / "p.sql.gz").write_bytes(b"")
    out = run_verify(db, rec, bdir)
    db.close()
    assert out.verify_status == "failed"
