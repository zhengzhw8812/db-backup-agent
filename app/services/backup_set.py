"""多库备份集(Backup Set):勾选多库 → 单一归档文件 → 整集还原。

- pg:每库 pg_dump 纯 SQL + manifest.json → tar.gz(还原逐库 CREATE DATABASE + psql)
- mysql:mysqldump --databases(原生自带 CREATE DATABASE)→ gzip
- mongo:mongodump --archive --gzip --nsList(原生多库)
部分库失败 → RestoreRecord.status="partial",error 记明细,其余库继续。
密码不入 argv:pg 走 PGPASSWORD env,mysql 走 defaults-extra-file。"""
from __future__ import annotations
import gzip
import json
import os
import shutil
import tarfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.base import ConnectionInfo, get_adapter, run_subprocess, run_subprocess_capture
from app.core.clock import utcnow
from app.db.models import BackupRecord, RestoreRecord


def _psql_capture(argv: list[str], env: dict | None = None) -> str:
    from app.adapters.postgres import run_subprocess_capture

    return run_subprocess_capture(argv, env=env, timeout=30)


def _psql_ok(argv: list[str], env: dict | None = None) -> bool:
    """跑一条 psql 命令,退出码 0 = True。(测试可替换)"""
    from app.adapters.postgres import run_subprocess

    try:
        run_subprocess(argv, env=env, timeout=60)
        return True
    except Exception:
        return False


def _pg_argv(info: ConnectionInfo, dbname: str, extra: list[str]) -> list[str]:
    from app.adapters.postgres import PostgresAdapter

    return PostgresAdapter().base_argv(info, dbname) + list(extra)


def _info_with_password(conn: DbConnection, crypto: Crypto, db_name: str | None) -> ConnectionInfo:
    from app.services.connection_service import decrypt_password

    return ConnectionInfo(
        type=conn.type, host=conn.host, port=conn.port,
        db_name=db_name, username=conn.username,
        password=decrypt_password(conn, crypto),
    )


def _info_with(info: ConnectionInfo, db_name: str | None) -> ConnectionInfo:
    return ConnectionInfo(
        type=info.type, host=info.host, port=info.port,
        db_name=db_name, username=info.username, password=info.password,
    )


def dump_set_pg(info: ConnectionInfo, db_names: list[str], set_dir: Path,
                final_name: str = "set.tar.gz") -> Path:
    """逐库 pg_dump → manifest.json → tar.gz。返回归档路径。"""
    set_dir.mkdir(parents=True, exist_ok=True)
    adapter = get_adapter("pg")
    for dbn in db_names:
        per_db = set_dir / f"{dbn}.sql"
        adapter.dump(_info_with(info, dbn), str(per_db))
    manifest = {"databases": db_names, "created_at": utcnow().isoformat()}
    (set_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))

    out = set_dir.parent / final_name
    with tarfile.open(out, "w:gz") as tf:
        for f in sorted(set_dir.iterdir()):
            tf.add(f, arcname=f.name)
    return out


def dump_set_mysql(info: ConnectionInfo, db_names: list[str], set_dir: Path) -> Path:
    """mysqldump --databases(原生多库,自带 CREATE DATABASE)→ gzip。"""
    adapter = get_adapter("mysql")
    defaults = adapter._write_defaults(info)
    try:
        argv = ["mysqldump", f"--defaults-extra-file={defaults}", "--databases", *db_names]
        dump_sql = run_subprocess_capture(argv, timeout=None)
    finally:
        try:
            os.unlink(defaults)
        except OSError:
            pass
    out = set_dir.parent / "set.sql.gz"
    with gzip.open(out, "wb", compresslevel=6) as fout:
        fout.write(dump_sql.encode("utf-8"))
    return out


def dump_set_mongo(info: ConnectionInfo, db_names: list[str], set_dir: Path,
                   final_name: str = "set.archive.gz") -> Path:
    """mongodump --archive --gzip --nsList(原生多库单归档)。"""
    out = set_dir.parent / final_name
    get_adapter("mongo").dump_set(info, db_names, str(out))
    return out


def dump_set(info: ConnectionInfo, db_names: list[str], set_dir: Path,
             final_name: str) -> Path:
    """按类型分派备份集打包。返回最终归档文件路径。"""
    set_dir.mkdir(parents=True, exist_ok=True)
    if info.type == "pg":
        return dump_set_pg(info, db_names, set_dir, final_name)
    if info.type == "mysql":
        return dump_set_mysql(info, db_names, set_dir, final_name)
    if info.type == "mongo":
        return dump_set_mongo(info, db_names, set_dir, final_name)
    raise ValueError(f"类型 {info.type} 不支持备份集")


def restore_set_pg(db: Session, crypto: Crypto, conn,
                   set_file: Path, restore_record_id: int, backup_dir: Path,
                   reporter=None) -> RestoreRecord:
    """pg 备份集整集还原:解包 → 缺库 CREATE → 逐库 psql → partial 语义。"""
    from app.adapters.postgres import PostgresAdapter

    rr = db.get(RestoreRecord, restore_record_id)
    work = backup_dir / f".restore-set-{restore_record_id}"
    work.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    restored: list[str] = []

    def _report(stage: str, detail: str = "") -> None:
        if reporter is not None:
            reporter.report(stage, detail)

    try:
        with tarfile.open(set_file) as tf:
            tf.extractall(work)
        manifest = json.loads((work / "manifest.json").read_text())
        dbs: list[str] = manifest["databases"]

        for i, dbn in enumerate(dbs, 1):
            _report("restore", f"{dbn} ({i}/{len(dbs)})")
            try:
                info = _info_with_password(conn, crypto, dbn)
                env = PostgresAdapter().env(info)
                # 库存在性按"结果内容"判断(psql 无行时退出码仍为 0,不能看 rc)
                exists = _psql_capture(
                    _pg_argv(info, "postgres",
                             ["-tAc", f"SELECT 1 FROM pg_database WHERE datname='{dbn}'"]),
                    env=env).strip() == "1"
                if not exists:
                    if not _psql_ok(_pg_argv(info, "postgres",
                                             ["-c", f'CREATE DATABASE "{dbn}"']), env):
                        errors.append(f"{dbn}: CREATE DATABASE 失败")
                        continue
                if _psql_ok(_pg_argv(info, dbn, ["-f", str(work / f"{dbn}.sql")]), env):
                    restored.append(dbn)
                else:
                    errors.append(f"{dbn}: psql 非零退出")
            except Exception as exc:
                errors.append(f"{dbn}: {exc}")

        rr = db.get(RestoreRecord, restore_record_id)
        if not errors:
            rr.status = "success"; rr.error = None
        elif restored:
            rr.status = "partial"; rr.error = "部分库还原失败:" + "; ".join(errors)
        else:
            rr.status = "failed"; rr.error = "全部库还原失败:" + "; ".join(errors)
        rr.finished_at = utcnow()
        db.commit(); db.refresh(rr)
        _report(rr.status, rr.error or "")
        return rr
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restore_set_mysql(db: Session, crypto: Crypto, conn,
                      set_file: Path, restore_record_id: int, backup_dir: Path,
                      reporter=None) -> RestoreRecord:
    """mysql 备份集:解压 → mysql < dump(原生 CREATE DATABASE 自动落库)。"""
    rr = db.get(RestoreRecord, restore_record_id)
    work = backup_dir / f".restore-set-{restore_record_id}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        info = _info_with_password(conn, crypto, None)
        raw = work / "set.sql"
        with gzip.open(set_file) as fin, open(raw, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        adapter = get_adapter("mysql")
        adapter.restore(info, str(raw))
        rr.status = "success"; rr.error = None
    except Exception as exc:
        rr.status = "failed"; rr.error = str(exc)
    rr.finished_at = utcnow()
    db.commit(); db.refresh(rr)
    return rr


def restore_set_mongo(db: Session, crypto: Crypto, conn,
                      set_file: Path, restore_record_id: int, backup_dir: Path,
                      reporter=None) -> RestoreRecord:
    rr = db.get(RestoreRecord, restore_record_id)
    try:
        info = _info_with_password(conn, crypto, None)
        adapter = get_adapter("mongo")
        adapter.restore(info, str(set_file))
        rr.status = "success"; rr.error = None
    except Exception as exc:
        rr.status = "failed"; rr.error = str(exc)
    rr.finished_at = utcnow()
    db.commit(); db.refresh(rr)
    return rr


def restore_set(db: Session, crypto: Crypto, conn,
                record: BackupRecord, restore_record_id: int, backup_dir: Path,
                reporter=None) -> RestoreRecord:
    """按文件后缀分派整集还原。"""
    fp = record.file_path or ""
    set_file = backup_dir / fp
    if fp.endswith(".set.tar.gz"):
        return restore_set_pg(db, crypto, conn, set_file, restore_record_id, backup_dir, reporter)
    if fp.endswith(".set.sql.gz"):
        return restore_set_mysql(db, crypto, conn, set_file, restore_record_id, backup_dir, reporter)
    if fp.endswith(".set.archive.gz"):
        return restore_set_mongo(db, crypto, conn, set_file, restore_record_id, backup_dir, reporter)
    raise ValueError(f"未知备份集格式: {fp}")
