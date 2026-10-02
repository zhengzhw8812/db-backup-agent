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


def test_export_sql_creates_executable_dump(env):
    sb, tmp = env
    out = sb.export_sql_dump(tmp)
    assert out.name.startswith("app-") and out.name.endswith(".sql")
    # 在全新空库执行导出的 SQL → 数据被还原
    import sqlite3
    fresh = tmp / "fresh.db"
    c = sqlite3.connect(fresh)
    c.executescript(out.read_text())
    n = c.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    c.close(); fresh.unlink()
    assert n == 10


def test_sql_rotation_independent_of_gz(env):
    sb, tmp = env
    sdir = tmp / "selfbackup"
    sdir.mkdir(exist_ok=True)
    for i in range(8):
        (sdir / f"app-2026010{i}-000000.sql").write_text(f"-- {i}")
        (sdir / f"app-2026010{i}-000000.db.gz").write_bytes(b"x")
    sb.export_sql_dump(tmp)
    sb.run_self_backup(tmp)
    sqls = sorted(sdir.glob("app-*.sql"))
    gzs = list(sdir.glob("app-*.db.gz"))
    assert len(sqls) == 7, [f.name for f in sqls]  # 9 份 → 保留 7,轮转掉最旧 2
    assert len(gzs) == 7


def test_list_and_download_sql(env, authed, monkeypatch):
    from app import config as app_config

    sb, tmp = env
    monkeypatch.setattr(app_config.settings, "data_dir", tmp)
    sb.export_sql_dump(tmp)
    items = authed.get("/api/v1/self-backup").json()
    assert items and items[0]["kind"] == "sql"
    name = items[0]["name"]
    assert authed.get(f"/api/v1/self-backup/{name}/download").status_code == 200


def test_run_api_fmt_sql(authed):
    # authed 已建管理员并登录;数据目录即 client fixture 的临时目录
    r = authed.post("/api/v1/self-backup/run?fmt=sql")
    assert r.status_code == 200
    assert r.json()["name"].endswith(".sql")
    r2 = authed.post("/api/v1/self-backup/run")
    assert r2.json()["name"].endswith(".db.gz")  # 默认 gz 回归


CORE_TABLES_OK = """
CREATE TABLE account (id INTEGER PRIMARY KEY, username TEXT);
CREATE TABLE db_connections (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE backup_records (id INTEGER PRIMARY KEY, status TEXT);
CREATE TABLE schedules (id INTEGER PRIMARY KEY, cron_expr TEXT);
CREATE TABLE notification_config (id INTEGER PRIMARY KEY);
INSERT INTO account VALUES (1, 'admin');
INSERT INTO db_connections VALUES (1, 'nas');
"""


def _live_db_with_marker(tmp_path, marker: str):
    from app import config as app_config

    (tmp_path / "sqlite").mkdir(exist_ok=True)
    live = tmp_path / "sqlite" / "app.db"
    c = sqlite3.connect(live)
    c.execute("CREATE TABLE t(x)")
    c.commit(); c.close()
    (tmp_path / "sqlite" / ".restore-pending.sql").write_text(marker)
    return live


def test_stage_restore_rejects_script_without_core_tables(env):
    sb, tmp = env
    with pytest.raises(ValueError) as ei:
        sb.stage_restore(tmp, "CREATE TABLE junk(x); INSERT INTO junk VALUES (1);")
    assert "核心表" in str(ei.value)
    assert not (tmp / "sqlite" / ".restore-pending.sql").exists()  # 校验失败不落暂存


def test_stage_restore_accepts_valid_script(tmp_path):
    from app import config as app_config

    (tmp_path / "sqlite").mkdir(exist_ok=True)
    live = tmp_path / "sqlite" / "app.db"
    live.write_bytes(b"old")
    from app.services import self_backup as sb

    staged = sb.stage_restore(tmp_path, CORE_TABLES_OK)
    assert staged == tmp_path / "sqlite" / ".restore-pending.sql"
    assert "CREATE TABLE account " in staged.read_text()


def test_maybe_restore_applies_and_archives(tmp_path):
    from app import config as app_config

    live = _live_db_with_marker(tmp_path, CORE_TABLES_OK)
    from app.services import self_backup as sb

    info = sb.maybe_restore(tmp_path)
    assert info and "app.db" in str(info)
    c = sqlite3.connect(live)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    users = c.execute("SELECT username FROM account").fetchall()
    c.close()
    assert "db_connections" in tables and users == [("admin",)]
    assert not (tmp_path / "sqlite" / ".restore-pending.sql").exists()
    # pre-restore 留底生成
    sb_dir = tmp_path / "selfbackup"
    assert any(f.name.startswith("pre-restore-") for f in sb_dir.iterdir())


def test_maybe_restore_noop_without_marker(tmp_path):
    from app.services import self_backup as sb

    (tmp_path / "sqlite").mkdir(exist_ok=True)
    assert sb.maybe_restore(tmp_path) is None


def test_upload_import_stages(authed, tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    (tmp_path / "sqlite").mkdir(exist_ok=True)
    r = authed.post("/api/v1/self-backup/import",
                    files={"file": ("dump.sql", CORE_TABLES_OK.encode(), "application/sql")})
    assert r.status_code == 200
    assert r.json()["staged"] is True


def test_upload_import_rejects_garbage(authed, tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    r = authed.post("/api/v1/self-backup/import",
                    files={"file": ("junk.sql", b"DROP TABLE x;", "application/sql")})
    assert r.status_code == 400
