import json
from datetime import datetime
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

    def dump(self, info, dest_path, *, is_cancelled=None):
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
    """建立 DB + 连接 + 一条 running 记录;返回 (db, conn, crypto, backup_dir, record_id)。"""
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: FakeAdapter())
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", host="h", port=5432, db_name="d",
                        username="u", password_enc=crypto.encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    record = BackupRecord(connection_id=conn.id, trigger="manual", status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    return db, conn, crypto, tmp_path / "backups", record.id


def test_run_backup_success_updates_existing_record(tmp_path, monkeypatch):
    db, conn, crypto, bdir, rid = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    reporter = ProgressReporter(rid, FakeRedis())
    rec = run_backup(db, crypto, conn, reporter, bdir, rid)
    assert rec.id == rid  # 更新的是同一条记录,不新建
    assert rec.status == "success"
    assert rec.checksum and len(rec.checksum) == 64
    assert rec.size and rec.size > 0
    assert rec.file_path and rec.file_path.endswith(".sql.gz")
    assert (bdir / rec.file_path).exists()
    db.close()


def test_run_backup_failed(tmp_path, monkeypatch):
    db, conn, crypto, bdir, rid = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    class BoomAdapter(FakeAdapter):
        def dump(self, info, dest, *, is_cancelled=None): raise RuntimeError("pg_dump not found")
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: BoomAdapter())
    reporter = ProgressReporter(rid, FakeRedis())
    rec = run_backup(db, crypto, conn, reporter, bdir, rid)
    assert rec.status == "failed"
    assert "pg_dump not found" in rec.error
    db.close()


def test_run_backup_cancelled_before_dump(tmp_path, monkeypatch):
    db, conn, crypto, bdir, rid = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    reporter = ProgressReporter(rid, FakeRedis(cancelled=True))
    rec = run_backup(db, crypto, conn, reporter, bdir, rid)
    assert rec.status == "cancelled"
    db.close()


class FlippingRedis:
    """先返回未取消;dump 执行后翻转为已取消。"""
    def __init__(self):
        self.cancelled = False
        self.published = []
    def publish(self, channel, msg):
        self.published.append((channel, msg))
    def exists(self, key):
        return self.cancelled
    def set(self, k, v):
        self.cancelled = True


class FlipAfterDumpAdapter:
    type = "pg"
    def __init__(self, redis):
        self.redis = redis
    def dump(self, info, dest_path, *, is_cancelled=None):
        with open(dest_path, "wb") as f:
            f.write(b"-- partial dump\n")
        self.redis.cancelled = True  # 写完 raw 后翻转取消标志


def test_run_backup_cancelled_after_dump_cleans_raw(tmp_path, monkeypatch):
    db, conn, crypto, bdir, rid = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    fake_redis = FlippingRedis()
    monkeypatch.setattr("app.services.backup_service.get_adapter",
                        lambda t: FlipAfterDumpAdapter(fake_redis))
    reporter = ProgressReporter(rid, fake_redis)
    rec = run_backup(db, crypto, conn, reporter, bdir, rid)
    assert rec.status == "cancelled"
    assert rec.duration_ms is not None
    assert not list(bdir.glob("*.sql"))       # raw 已清理
    assert not list(bdir.glob("*.sql.gz"))    # 未生成 gz
    stages = [json.loads(m)["stage"] for _, m in fake_redis.published]
    assert "cancelled" in stages
    db.close()


def test_run_backup_unknown_record_raises(tmp_path, monkeypatch):
    db, conn, crypto, bdir, rid = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    import pytest
    with pytest.raises(ValueError):
        run_backup(db, crypto, conn, ProgressReporter(rid, FakeRedis()), bdir, 999999)
    db.close()


def test_resolve_db_names_pg_uses_db_names(tmp_path):
    from app.services.backup_service import _resolve_db_names
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection
    import json
    init_engine(f"sqlite:///{tmp_path/'r.db'}"); create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="c", type="pg", db_names=json.dumps(["app", "logs"]))
        db.add(c)
        assert _resolve_db_names(c) == ["app", "logs"]
    finally:
        db.close()


def test_resolve_db_names_mysql_all_when_empty(tmp_path):
    from app.services.backup_service import _resolve_db_names
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection
    init_engine(f"sqlite:///{tmp_path/'r.db'}"); create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="m", type="mysql")  # 无 db_names / db_name
        db.add(c)
        assert _resolve_db_names(c) == [None]  # MySQL 全库 → [None]
    finally:
        db.close()


def test_enqueue_backup_creates_one_record_per_db(tmp_path, monkeypatch):
    from app.services.backup_service import enqueue_backup
    from app.db.session import init_engine, create_all
    from app.db.models import DbConnection, BackupRecord
    import json
    init_engine(f"sqlite:///{tmp_path/'e.db'}"); create_all()
    db = _session._SessionLocal()
    try:
        c = DbConnection(name="c", type="pg", db_names=json.dumps(["app", "logs", "shop"]))
        db.add(c); db.commit(); db.refresh(c)
        recs = enqueue_backup(db, c, "manual")
        assert len(recs) == 3
        assert sorted(r.db_name for r in recs) == ["app", "logs", "shop"]
        assert all(r.status == "running" for r in recs)
        assert db.query(BackupRecord).count() == 3
    finally:
        db.close()


def test_run_backup_uses_record_db_name(tmp_path, monkeypatch):
    """run_backup 应按 record.db_name 决定 dump 的库(record 是真实来源)。"""
    db, conn, crypto, bdir, _ = _setup(tmp_path, monkeypatch)
    bdir.mkdir()
    from app.db.models import BackupRecord
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="running",
                       db_name="chosen_db", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)

    seen = {}
    class SpyAdapter(FakeAdapter):
        def dump(self, info, dest_path, *, is_cancelled=None):
            seen["db_name"] = info.db_name
            super().dump(info, dest_path, is_cancelled=is_cancelled)
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: SpyAdapter())

    out = run_backup(db, crypto, conn, ProgressReporter(rec.id, FakeRedis()), bdir, rec.id)
    assert out.status == "success"
    assert seen["db_name"] == "chosen_db"   # 用的是 record.db_name,而非 conn.db_name('d')
    db.close()
