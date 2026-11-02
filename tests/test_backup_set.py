"""多库备份集:enqueue 单记录、打包结构、还原顺序与 partial 语义。"""
import gzip
import json
import tarfile
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import Crypto
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import BackupRecord, DbConnection, RestoreRecord
from app.core.clock import utcnow


def _env(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    crypto = Crypto(Fernet.generate_key())
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    bdir = tmp_path / "backups"; bdir.mkdir()
    return db, crypto, conn, bdir


def test_enqueue_multi_db_creates_single_record(tmp_path):
    """勾选多库 → 只建一条记录,db_names 存 JSON,db_name 为 NULL。"""
    from app.services.backup_service import enqueue_backup

    db, crypto, conn, bdir = _env(tmp_path)
    records = enqueue_backup(db, conn, "manual")  # 无 db_names 列的连接 → 单库语义
    # 连接无 db_names → 单记录(None 库)
    assert len(records) == 1

    # 有 db_names 的连接
    conn.db_names = '["app","logs","shop"]'
    db.commit()
    records2 = enqueue_backup(db, conn, "scheduled")
    db.close()
    assert len(records2) == 1  # 备份集:单记录
    assert json.loads(records2[0].db_names) == ["app", "logs", "shop"]
    assert records2[0].db_name is None
    assert records2[0].status == "running"


def test_pg_dump_set_builds_tar_with_manifest(tmp_path, monkeypatch):
    """pg 备份集:逐库 pg_dump → tar.gz(manifest + 每库 .sql)。"""
    import app.adapters.postgres as pgmod
    from app.adapters.base import ConnectionInfo
    from app.adapters.postgres import PostgresAdapter
    from app.services.backup_set import dump_set_pg

    dumped = []
    def fake_dump(argv, **kw):
        dumped.append(list(argv))
        kw["stdout"].write(f"-- dump {argv[-1]}".encode())
    monkeypatch.setattr(pgmod, "run_subprocess", fake_dump)

    set_dir = tmp_path / "set"; set_dir.mkdir()
    info = ConnectionInfo(type="pg", host="h", username="u", password="p")
    dbs = ["app", "logs"]
    out = dump_set_pg(info, dbs, set_dir)

    assert out.name.endswith(".tar.gz") and "set" in out.name  # 中间产物;set 标记名由 _run_backup_set 终命名
    with tarfile.open(out) as tf:
        names = tf.getnames()
        assert "manifest.json" in names
        assert "app.sql" in names and "logs.sql" in names
        manifest = json.load(tf.extractfile("manifest.json"))
    assert manifest["databases"] == ["app", "logs"]
    assert len(dumped) == 2  # 每库一次 pg_dump
    assert dumped[0][-1] == "app"  # pg_dump 以库名为位置参数


def test_mysql_set_argv_has_databases(tmp_path, monkeypatch):
    """mysql 备份集:--databases 列出全部勾选库。"""
    import app.adapters.mysql as mymod
    from app.adapters.base import ConnectionInfo
    from app.adapters.mysql import MysqlAdapter

    captured = {}
    def fake_capture(argv, **kw):
        captured["argv"] = argv
        return "-- dump"
    monkeypatch.setattr(mymod, "run_subprocess_capture", fake_capture)

    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", username="u", password="p")
    out = a.dump_set(info, ["app", "logs"], tmp_path / "out.sql.gz")
    with gzip.open(out) as f:
        assert f.read().decode() == "-- dump"
    joined = " ".join(captured["argv"])
    assert "--databases" in joined and "app" in joined and "logs" in joined
    assert "--all-databases" not in joined


def test_mongo_set_argv_has_nslist(tmp_path, monkeypatch):
    import app.adapters.mongodb as momod
    from app.adapters.base import ConnectionInfo
    from app.adapters.mongodb import MongoAdapter

    captured = {}
    monkeypatch.setattr(momod, "run_subprocess", lambda argv, **kw: captured.update(argv=argv))
    a = MongoAdapter()
    out = a.dump_set(ConnectionInfo(type="mongo", host="h", username="u", password="p"),
                     ["app", "logs"], tmp_path / "out.archive.gz")
    joined = " ".join(captured["argv"])
    assert "--nsList=app,logs" in joined
    assert "--gzip" in joined and "--archive" in joined
    assert out.name.endswith(".archive.gz")


def test_restore_set_pg_creates_db_and_restores_in_order(tmp_path, monkeypatch):
    """pg 集还原:缺库先 CREATE DATABASE;逐库 psql;全部成功 → success。"""
    import app.services.backup_set as bs

    calls = []
    def fake_psql(argv, env=None, **kw):
        calls.append(argv)
        return True

    def fake_capture(argv, env=None):
        calls.append(argv)
        return ""  # 探测:库不存在
    monkeypatch.setattr(bs, "_psql_ok", fake_psql)
    monkeypatch.setattr(bs, "_psql_capture", fake_capture)

    # 构造真实备份集 tar
    set_dir = tmp_path / "set"; set_dir.mkdir()
    for dbn in ["app", "logs"]:
        (set_dir / f"{dbn}.sql").write_text(f"-- {dbn} data")
    (set_dir / "manifest.json").write_text(json.dumps({"databases": ["app", "logs"]}))
    with tarfile.open(set_dir / "s.tar.gz", "w:gz") as tf:
        for f in set_dir.iterdir():
            tf.add(f, arcname=f.name)
    set_file = set_dir / "s.tar.gz"

    db, crypto, conn, bdir = _env(tmp_path)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                       file_path="s.tar.gz", started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    rr = RestoreRecord(backup_record_id=rec.id, target_connection_id=conn.id,
                       status="running", started_at=utcnow())
    db.add(rr); db.commit(); db.refresh(rr)
    rid = rr.id
    db.close()

    out = bs.restore_set_pg(db, crypto, conn, set_file, rid, bdir)
    db2 = _session._SessionLocal()
    final = db2.get(RestoreRecord, rid).status
    db2.close()
    assert final == "success"
    # 顺序:CREATE DATABASE logs 在 psql -d logs 之前;-d app 之前先 app 的 CREATE
    flat = ["-d" in c and c[c.index("-d") + 1] for c in calls if "-d" in c]
    joined = [x for c in calls for x in ([c[c.index("-d")+1]] if "-d" in c else [])]
    assert joined.index("app") < joined.index("logs")


def test_restore_set_partial_status(tmp_path, monkeypatch):
    """第二库还原失败 → partial,错误明细落库。"""
    import app.services.backup_set as bs
    from app.db.models import RestoreRecord

    def fake_psql(argv, env=None, **kw):
        if "-f" in argv and "logs.sql" in " ".join(argv):
            raise RuntimeError("logs restore boom")
        return True

    def fake_capture(argv, env=None):
        return ""  # 探测:库不存在
    monkeypatch.setattr(bs, "_psql_ok", fake_psql)
    monkeypatch.setattr(bs, "_psql_capture", fake_capture)

    set_dir = tmp_path / "set"; set_dir.mkdir()
    for dbn in ["app", "logs"]:
        (set_dir / f"{dbn}.sql").write_text(f"-- {dbn}")
    (set_dir / "manifest.json").write_text(json.dumps({"databases": ["app", "logs"]}))
    with tarfile.open(set_dir / "s.tar.gz", "w:gz") as tf:
        for f in set_dir.iterdir():
            tf.add(f, arcname=f.name)

    db, crypto, conn, bdir = _env(tmp_path)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                       file_path="s.tar.gz", started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    rr = RestoreRecord(backup_record_id=rec.id, target_connection_id=conn.id,
                       status="running", started_at=utcnow())
    db.add(rr); db.commit(); db.refresh(rr)
    rid = rr.id
    db.close()

    out = bs.restore_set_pg(db, crypto, conn, set_dir / "s.tar.gz", rid, bdir)
    db2 = _session._SessionLocal()
    rec = db2.get(RestoreRecord, rid)
    err = rec.error or ""
    db2.close()
    assert rec.status == "partial"
    assert "logs" in err and "boom" in err


def test_dump_set_dispatch_mysql_uses_final_name(tmp_path, monkeypatch):
    """回归(v3.4.0):分发器给 dump_set_mysql 传 final_name 会 TypeError(签名漏改);
    且 mysql 集文件名必须用 final_name(唯一命名),不能硬编码 set.sql.gz。"""
    import gzip

    import app.services.backup_set as bs
    from app.adapters.base import ConnectionInfo

    captured = {}

    class FakeMysqlAdapter:
        def _write_defaults(self, info):
            p = tmp_path / "defaults.cnf"
            p.write_text("[client]\nuser=u\n")
            return str(p)

    def fake_capture(argv, timeout=None):
        captured["argv"] = argv
        return "-- dump"

    monkeypatch.setattr(bs, "get_adapter", lambda t: FakeMysqlAdapter())
    monkeypatch.setattr(bs, "run_subprocess_capture", fake_capture)

    set_dir = tmp_path / "set"
    set_dir.mkdir()
    info = ConnectionInfo(type="mysql", host="h", username="u", password="p")
    out = bs.dump_set(info, ["app", "logs"], set_dir, "dbba-app-20261102.sql.gz")
    assert out.name == "dbba-app-20261102.sql.gz"  # 唯一命名生效
    assert out.exists()
    with gzip.open(out) as f:
        assert f.read().decode() == "-- dump"
    assert "--databases" in " ".join(captured["argv"])


def test_restore_set_failure_writes_system_log(tmp_path, monkeypatch):
    """备份集恢复失败写入系统日志(多库恢复是排查刚需)。"""
    import gzip as _gz

    import app.services.backup_set as bs
    from app.db.models import SystemLog

    class BoomAdapter:
        def restore(self, info, src, *, is_cancelled=None): raise RuntimeError("mysql closed")
    monkeypatch.setattr(bs, "get_adapter", lambda t: BoomAdapter())

    set_file = tmp_path / "mysql_1_1.set.sql.gz"
    with _gz.open(set_file, "wb") as f:
        f.write(b"-- dump")

    db, crypto, conn, bdir = _env(tmp_path)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                       file_path=set_file.name, started_at=utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    rr = RestoreRecord(backup_record_id=rec.id, target_connection_id=conn.id,
                       status="running", started_at=utcnow())
    db.add(rr); db.commit(); db.refresh(rr)

    out = bs.restore_set_mysql(db, crypto, conn, set_file, rr.id, tmp_path)
    assert out.status == "failed"
    row = db.query(SystemLog).filter(SystemLog.source == "restore", SystemLog.level == "error").first()
    assert row is not None and "mysql closed" in (row.context or "")
    db.close()
