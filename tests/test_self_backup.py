"""配置库自备份:VACUUM INTO 快照、保留轮转、下载防穿越、调度注册。"""
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    (tmp_path / "sqlite").mkdir(exist_ok=True)
    live = tmp_path / "sqlite" / "app.db"
    c = sqlite3.connect(live)
    c.execute("CREATE TABLE t(x INTEGER)")
    c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(10)])
    c.commit(); c.close()
    from app.services import self_backup as sb
    return sb, tmp_path


def test_run_creates_valid_gz_snapshot(env):
    sb, tmp = env
    out = sb.run_self_backup(tmp)
    assert out.exists() and out.name.startswith("app-") and out.name.endswith(".db.gz")
    import gzip
    with gzip.open(out) as f:
        data = f.read()
    raw = tmp / "unpack.db"
    raw.write_bytes(data)
    c2 = sqlite3.connect(raw)
    assert c2.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 10
    c2.close(); raw.unlink()


def test_retention_keeps_seven(env, monkeypatch):
    sb, tmp = env
    from app.core.clock import utcnow
    import json as _json
    # 造 9 份旧快照(直接放目录)
    sdir = tmp / "selfbackup"
    sdir.mkdir(exist_ok=True)
    for i in range(9):
        (sdir / f"app-2026010{i}-000000.db.gz").write_bytes(b"x")
    out = sb.run_self_backup(tmp)
    files = sorted(sdir.glob("app-*.db.gz"))
    assert len(files) == 7
    assert out in files


def test_run_writes_system_log(env):
    from app.db.session import init_engine, create_all
    from app.db import session as _session
    import app.db.models  # noqa
    from app.db.models import SystemLog

    sb, tmp = env
    init_engine(f"sqlite:///{tmp}/probe.db")
    create_all()
    db = _session._SessionLocal()
    sb.run_self_backup(tmp, db=db)
    row = db.query(SystemLog).filter(SystemLog.source == "selfbackup").first()
    db.close()
    assert row is not None and row.level == "info"


@pytest.fixture
def authed(client):
    from app.services.account_service import ensure_account

    db = _session_db_fixture()
    db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def _session_db_fixture():
    from app.db import session as _session
    from app.services.account_service import ensure_account

    db = _session._SessionLocal()
    ensure_account(db, "admin", "pw")
    db.commit()
    return db


def test_download_name_whitelist(authed, tmp_path, monkeypatch):
    """白名单外名称(穿越/任意文件)→ 404。"""
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    sdir = tmp_path / "selfbackup"; sdir.mkdir(exist_ok=True)
    (sdir / "app-20260101-000000.db.gz").write_bytes(b"data")
    assert authed.get("/api/v1/self-backup").json()[0]["name"] == "app-20260101-000000.db.gz"
    assert authed.get("/api/v1/self-backup/app-20260101-000000.db.gz/download").status_code == 200
    for bad in ["..%2F..%2Fetc%2Fpasswd", "users.db", "app-20260101-000000.db", "x.db.gz"]:
        assert authed.get(f"/api/v1/self-backup/{bad}/download").status_code == 404, bad


def test_scheduler_registers_daily():
    import asyncio
    from types import SimpleNamespace
    from app.services import scheduler as sched_mod

    class FakeSched:
        def __init__(self): self.jobs = []
        def add_job(self, fn, trigger, **kw): self.jobs.append((kw.get("id"), trigger))
        def start(self): pass
        def shutdown(self, wait=False): pass
        def get_job(self, _): return None
        def remove_job(self, _): pass

    monkey_f = FakeSched()
    orig = sched_mod.AsyncIOScheduler
    sched_mod.AsyncIOScheduler = lambda: monkey_f
    try:
        svc = sched_mod.SchedulerService(SimpleNamespace())
        asyncio.run(svc.start())
        ids = [j[0] for j in svc._sched.jobs]
        assert "self_backup_daily" in ids
    finally:
        sched_mod.AsyncIOScheduler = orig
