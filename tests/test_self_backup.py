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


def test_maybe_restore_garbage_marker_boots_old_db(tmp_path):
    """C1:暂存脚本损坏(截断)→ 放弃还原、清标记与中间文件、旧库原样启动。"""
    from app import config as app_config

    (tmp_path / "sqlite").mkdir(exist_ok=True)
    live = tmp_path / "sqlite" / "app.db"
    live.write_bytes(b"OLD-DB-BYTES")
    (tmp_path / "sqlite" / ".restore-pending.sql").write_text("CREATE TABLE accoun")  # 截断
    (tmp_path / "sqlite" / ".restore-new.db").write_bytes(b"stale")  # 上次失败残留

    from app.services import self_backup as sb

    info = sb.maybe_restore(tmp_path)
    assert info is None
    assert live.read_bytes() == b"OLD-DB-BYTES"  # 旧库原样
    assert not (tmp_path / "sqlite" / ".restore-pending.sql").exists()  # 标记清理
    assert not (tmp_path / "sqlite" / ".restore-new.db").exists()  # 中间文件清理


def test_restore_lock_serializes(tmp_path):
    """还原锁:持有期间非阻塞二次获取必须失败(worker 等待语义的基础)。"""
    import fcntl

    from app.services import self_backup as sb

    (tmp_path / "sqlite").mkdir(exist_ok=True)
    with sb.restore_lock(tmp_path):
        lockfile = open(tmp_path / "sqlite" / ".restore.lock")
        with pytest.raises(BlockingIOError):
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lockfile.close()


def test_stage_restore_denies_attach(tmp_path):
    """I4:ATTACH 外部库并破坏其内容的脚本 → 校验拒绝,外部库原样。"""
    import sqlite3

    from app.services import self_backup as sb

    victim = tmp_path / "victim.db"
    c = sqlite3.connect(victim)
    c.execute("CREATE TABLE keepme(x)")
    c.execute("INSERT INTO keepme VALUES (1)")
    c.commit(); c.close()
    sql = f"ATTACH DATABASE '{victim}' AS v; DROP TABLE v.keepme;"
    with pytest.raises(ValueError):
        sb.stage_restore(tmp_path, sql)
    c = sqlite3.connect(victim)
    n = c.execute("SELECT COUNT(*) FROM keepme").fetchone()[0]
    c.close()
    assert n == 1  # 外部库未被破坏


def test_stage_restore_runaway_aborts(tmp_path):
    """I4:失控脚本(递归 CTE)→ 在时限内中断并拒绝。"""
    import time

    from app.services import self_backup as sb

    sql = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT x FROM c;"
    t0 = time.monotonic()
    with pytest.raises(ValueError):
        sb.stage_restore(tmp_path, sql)
    assert time.monotonic() - t0 < 15  # 时限 10s + 开销


def test_upload_import_oversize_413(authed, tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    big = b"-- pad\n" + b"x" * (20 * 1024 * 1024 + 1)
    r = authed.post("/api/v1/self-backup/import",
                    files={"file": ("big.sql", big, "application/sql")})
    assert r.status_code == 413


def test_restore_listed_rejects_gz(authed, tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    sdir = tmp_path / "selfbackup"; sdir.mkdir(exist_ok=True)
    (sdir / "app-20260101-000000.db.gz").write_bytes(b"x")
    assert authed.post("/api/v1/self-backup/app-20260101-000000.db.gz/restore").status_code == 404


def test_restore_listed_rejects_missing_core_tables(authed, tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    sdir = tmp_path / "selfbackup"; sdir.mkdir(exist_ok=True)
    (sdir / "app-20260101-000000.sql").write_text("CREATE TABLE junk(x);")
    r = authed.post("/api/v1/self-backup/app-20260101-000000.sql/restore")
    assert r.status_code == 400
    assert "核心表" in r.json()["detail"]


def test_export_sql_excludes_uncommitted_writes(env):
    """导出走 VACUUM INTO 快照:其他连接未提交的写入不可见。"""
    import sqlite3

    sb, tmp = env
    live = tmp / "sqlite" / "app.db"
    conn2 = sqlite3.connect(live)
    conn2.execute("INSERT INTO t VALUES (999)")  # 不提交
    out = sb.export_sql_dump(tmp)
    conn2.rollback(); conn2.close()
    assert "999" not in out.read_text()


# ---------- 自备份上云 + 云端轮转 + 快照删除(v3.4.0) ----------

class FakeCloudStorage:
    """记录 upload/delete;list_prefix 返回 已上传 ∪ 预置 对象。"""

    def __init__(self, preset=(), fail_upload=False):
        self.uploads = []
        self.deletes = []
        self.preset = list(preset)
        self.fail_upload = fail_upload

    def upload(self, cfg, local_path, key):
        if self.fail_upload:
            raise RuntimeError("upload boom")
        self.uploads.append(key)
        return f"s3://{cfg.bucket}/{key}"

    def delete(self, cfg, key):
        self.deletes.append(key)

    def list_prefix(self, cfg, prefix):
        return sorted(set(self.preset) | {k for k in self.uploads if k.startswith(prefix)})

    def test(self, cfg):
        pass


def _cloud_env(tmp_path, storages):
    """建引擎 + 两个启用云目标(+1 禁用),返回 (db, crypto)。"""
    from app.db.session import init_engine, create_all
    from app.db import session as _session
    import app.db.models  # noqa
    from app.db.models import CloudDestination
    from app.core.crypto import Crypto
    from cryptography.fernet import Fernet

    init_engine(f"sqlite:///{tmp_path}/cloud.db")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    for i, st in enumerate(storages):
        db.add(CloudDestination(name=f"d{i}", provider="s3", endpoint="h:9000", bucket=f"bk{i}",
                                access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                                prefix="", secure=False, enabled=True))
    db.add(CloudDestination(name="off", provider="s3", endpoint="h:9000", bucket="off",
                            access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
                            prefix="", secure=False, enabled=False))
    db.commit()
    return db, crypto


def test_upload_self_backup_uploads_all_enabled_dests(tmp_path, monkeypatch):
    s1, s2 = FakeCloudStorage(), FakeCloudStorage()
    db, crypto = _cloud_env(tmp_path, [s1, s2])
    queue = [s1, s2]
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: queue.pop(0))
    from app.services.sync_service import upload_self_backup, SELFBACKUP_PREFIX

    snap = tmp_path / "app-20260301-000000.db.gz"
    snap.write_bytes(b"x")
    result = upload_self_backup(db, crypto, snap)
    assert [u["destination"] for u in result["synced"]] == ["d0", "d1"]
    assert s1.uploads == [f"{SELFBACKUP_PREFIX}app-20260301-000000.db.gz"]
    assert s2.uploads == [f"{SELFBACKUP_PREFIX}app-20260301-000000.db.gz"]
    db.close()


def test_upload_rotates_beyond_30(tmp_path, monkeypatch):
    preset = [f"selfbackup/app-202601{d:02d}-000000.db.gz" for d in range(1, 32)]  # 31 个白名单
    preset.append("selfbackup/not-mine.txt")
    st = FakeCloudStorage(preset=preset)
    db, crypto = _cloud_env(tmp_path, [st])
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: st)
    from app.services.sync_service import upload_self_backup

    snap = tmp_path / "app-20260301-000000.db.gz"
    snap.write_bytes(b"x")
    upload_self_backup(db, crypto, snap)
    # 白名单共 32(31 旧 + 1 新)→ 删最旧 2 个;非白名单不动
    assert st.deletes == ["selfbackup/app-20260101-000000.db.gz",
                          "selfbackup/app-20260102-000000.db.gz"]
    db.close()


def test_upload_dest_failure_continues(tmp_path, monkeypatch):
    s1, s2 = FakeCloudStorage(fail_upload=True), FakeCloudStorage()
    db, crypto = _cloud_env(tmp_path, [s1, s2])
    queue = [s1, s2]
    monkeypatch.setattr("app.services.sync_service.get_storage", lambda p: queue.pop(0))
    from app.services.sync_service import upload_self_backup
    from app.db.models import SystemLog

    snap = tmp_path / "app-20260301-000000.db.gz"
    snap.write_bytes(b"x")
    result = upload_self_backup(db, crypto, snap)
    assert result["errors"] and "upload boom" in result["errors"][0]["error"]
    assert s2.uploads  # 第二目标仍上传
    warn = db.query(SystemLog).filter(SystemLog.level == "warning",
                                      SystemLog.source == "cloud").first()
    assert warn is not None
    db.close()


def test_delete_snapshot_api_removes_local_and_cloud(authed, tmp_path, monkeypatch):
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    sdir = tmp_path / "selfbackup"; sdir.mkdir(exist_ok=True)
    (sdir / "app-20260101-000000.db.gz").write_bytes(b"data")
    seen = []
    monkeypatch.setattr("app.routers.self_backup.delete_self_backup_cloud",
                        lambda db, crypto, name: seen.append(name))
    r = authed.delete("/api/v1/self-backup/app-20260101-000000.db.gz")
    assert r.status_code == 200 and r.json() == {"deleted": "app-20260101-000000.db.gz"}
    assert not (sdir / "app-20260101-000000.db.gz").exists()
    assert seen == ["app-20260101-000000.db.gz"]


def test_delete_snapshot_rejects_bad_name(authed):
    for bad in ["..%2F..%2Fetc%2Fpasswd", "users.db", "pre-restore-20260101-000000.db"]:
        assert authed.delete(f"/api/v1/self-backup/{bad}").status_code == 404, bad


def test_run_api_triggers_cloud_upload(authed, monkeypatch):
    calls = []
    monkeypatch.setattr("app.routers.self_backup.upload_self_backup",
                        lambda db, crypto, path: calls.append(Path(path).suffix))
    def _boom(db, crypto, path):
        raise RuntimeError("cloud down")

    r = authed.post("/api/v1/self-backup/run?fmt=gz")
    assert r.status_code == 200
    r = authed.post("/api/v1/self-backup/run?fmt=sql")
    assert r.status_code == 200
    assert calls == [".gz", ".sql"]
    # 上云失败不影响自备份结果
    monkeypatch.setattr("app.routers.self_backup.upload_self_backup", _boom)
    assert authed.post("/api/v1/self-backup/run?fmt=gz").status_code == 200


def test_self_backup_daily_uploads(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    from app.db import session as _session
    from app.services import scheduler as sched_mod
    from app.services import self_backup as sb_mod
    from app.services import sync_service as sync_mod
    from app.core.crypto import Crypto
    from cryptography.fernet import Fernet

    fake_path = tmp_path / "app-20260301-000000.db.gz"
    fake_path.write_bytes(b"x")

    class _DB:
        def add(self, *_): pass
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(sb_mod, "run_self_backup", lambda *a, **k: fake_path)
    uploads = []

    def _up(db, crypto, path):
        uploads.append(Path(path).name)

    monkeypatch.setattr(sync_mod, "upload_self_backup", _up)
    monkeypatch.setattr(_session, "_SessionLocal", lambda: _DB())
    crypto = Crypto(Fernet.generate_key())
    asyncio.run(sched_mod.self_backup_daily(
        SimpleNamespace(state=SimpleNamespace(crypto=crypto))))
    assert uploads == [fake_path.name]

    # 上云抛异常:仅日志,不炸每日任务
    def _boom(db, crypto, path):
        raise RuntimeError("cloud down")

    monkeypatch.setattr(sync_mod, "upload_self_backup", _boom)
    asyncio.run(sched_mod.self_backup_daily(
        SimpleNamespace(state=SimpleNamespace(crypto=crypto))))


def test_self_backup_daily_upload_runs_off_event_loop(monkeypatch, tmp_path):
    """云上传是阻塞 IO(退避 sleep/连接超时),必须在 worker 线程执行,不得冻结事件循环。"""
    import asyncio
    import threading
    from types import SimpleNamespace
    from app.db import session as _session
    from app.services import scheduler as sched_mod
    from app.services import self_backup as sb_mod
    from app.services import sync_service as sync_mod
    from app.core.crypto import Crypto
    from cryptography.fernet import Fernet

    fake_path = tmp_path / "app-20260301-000000.db.gz"
    fake_path.write_bytes(b"x")

    class _DB:
        def add(self, *_): pass
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(sb_mod, "run_self_backup", lambda *a, **k: fake_path)
    threads = []
    monkeypatch.setattr(sync_mod, "upload_self_backup",
                        lambda db, crypto, path: threads.append(threading.current_thread()))
    monkeypatch.setattr(_session, "_SessionLocal", lambda: _DB())
    crypto = Crypto(Fernet.generate_key())
    main_thread = threading.current_thread()
    asyncio.run(sched_mod.self_backup_daily(
        SimpleNamespace(state=SimpleNamespace(crypto=crypto))))
    assert threads and threads[0] is not main_thread
