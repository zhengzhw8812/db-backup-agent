from __future__ import annotations
import json
import os
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord
from app.core.crypto import Crypto
from app.core.archive import compress_and_hash, sha256_of_file
from app.core.fsutil import safe_remove
from app.adapters.base import ConnectionInfo, get_adapter, BackupCancelled
from app.workers.progress import ProgressReporter
from app.core.clock import utcnow


def _conn_info(conn: DbConnection, crypto: Crypto, db_name: str | None = None) -> ConnectionInfo:
    return ConnectionInfo(
        type=conn.type,
        host=conn.host,
        port=conn.port,
        db_name=db_name,
        username=conn.username,
        password=_decrypt(conn.password_enc, crypto),
    )


def _decrypt(enc: str | None, crypto: Crypto) -> str | None:
    return crypto.decrypt(enc) if enc else None


def _resolve_db_names(conn: DbConnection) -> list[str | None]:
    """决定一次备份要遍历哪些库:
    - db_names 非空(PG 多选/旧 PG 回填) → 取其列表
    - 否则 MySQL → [None](全库,适配器输出 --all-databases)
    - 否则(旧连接/sqlite 等) → [conn.db_name]"""
    names: list[str] = []
    if conn.db_names:
        try:
            parsed = json.loads(conn.db_names)
            if isinstance(parsed, list):
                names = [n for n in parsed if n]
        except (TypeError, ValueError):
            names = []
    if names:
        return names
    if conn.type == "mysql":
        return [None]
    return [conn.db_name]


def enqueue_backup(db: Session, conn: DbConnection, trigger: str, now_fn=utcnow) -> list[BackupRecord]:
    """为连接的每个待备份库各建一条 running BackupRecord(trigger manual/scheduled)。
    供 run_now 与 scheduler 共用;返回创建的记录列表(已 commit)。"""
    names = _resolve_db_names(conn)
    records = []
    if len(names) >= 2:
        # 备份集:多库打包为单记录(db_names 记录实际备份的库)
        r = BackupRecord(connection_id=conn.id, trigger=trigger, status="running",
                         db_name=None, db_names=json.dumps(names), started_at=now_fn())
        db.add(r)
        records.append(r)
    else:
        for name in names:
            r = BackupRecord(connection_id=conn.id, trigger=trigger, status="running",
                             db_name=name, started_at=now_fn())
            db.add(r)
            records.append(r)
    db.commit()
    for r in records:
        db.refresh(r)
    return records


def run_backup(
    db: Session,
    crypto: Crypto,
    conn: DbConnection,
    reporter: ProgressReporter,
    backup_dir: Path,
    record_id: int,
    now_fn=utcnow,
) -> BackupRecord:
    """对一条已存在的 running 记录执行备份:dump → 压缩 → 校验 → 更新(success/failed/cancelled)。
    记录由调用方(Web API)预先创建,record_id 同时作为进度频道与取消锚点。
    每阶段上报进度,阶段间隙检查取消标志。失败捕获异常、清理中间文件并写入 error。"""
    record = db.get(BackupRecord, record_id)
    if record is None:
        raise ValueError(f"备份记录不存在: {record_id}")
    if record.started_at is None:
        record.started_at = now_fn()
    db.commit()

    # 备份集模式:记录带 db_names(≥2 库)→ 打包为单一归档
    set_names: list[str] | None = None
    if record.db_names:
        try:
            parsed = json.loads(record.db_names)
            if isinstance(parsed, list) and len(parsed) >= 2:
                set_names = parsed
        except (TypeError, ValueError):
            set_names = None
    if set_names:
        return _run_backup_set(db, crypto, conn, record, reporter, backup_dir,
                               set_names, now_fn)

    raw_path = backup_dir / f"{conn.type}_{conn.id}_{record.id}.sql"
    gz_path = backup_dir / f"{conn.type}_{conn.id}_{record.id}.sql.gz"
    start = time.monotonic()

    def _check_cancel():
        if reporter.is_cancelled():
            record.status = "cancelled"
            record.finished_at = now_fn()
            record.duration_ms = int((time.monotonic() - start) * 1000)
            db.commit()
            db.refresh(record)
            reporter.report("cancelled")
            return True
        return False

    try:
        if _check_cancel():
            return record

        adapter = get_adapter(conn.type)
        reporter.report("dump")
        effective_db = record.db_name if record.db_name is not None else conn.db_name
        adapter.dump(_conn_info(conn, crypto, effective_db), str(raw_path), is_cancelled=reporter.is_cancelled)

        if _check_cancel():
            safe_remove(raw_path)
            return record

        reporter.report("compress")
        checksum = compress_and_hash(raw_path, gz_path)  # 压缩 + 边写边哈希(单次遍历)
        safe_remove(raw_path)
        size = os.path.getsize(gz_path)

        record.file_path = str(gz_path.relative_to(backup_dir))
        record.size = size
        record.checksum = checksum
        record.status = "success"
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(record)
        reporter.report("success")
        return record
    except BackupCancelled:
        # dump 执行期间被取消:清理中间文件,标记 cancelled(非 failed)
        safe_remove(raw_path)
        safe_remove(gz_path)
        record.status = "cancelled"
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(record)
        reporter.report("cancelled")
        return record
    except Exception as exc:
        safe_remove(raw_path)
        safe_remove(gz_path)
        record.status = "failed"
        record.error = str(exc)
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(record)
        reporter.report("failed", str(exc))
        return record

def _run_backup_set(db: Session, crypto: Crypto, conn: DbConnection, record: BackupRecord,
                    reporter, backup_dir: Path, names: list[str], now_fn=datetime.now) -> BackupRecord:
    """备份集打包:dump_set → 校验和 → 终态。失败清理临时目录。"""
    from app.services.backup_set import dump_set

    start = time.monotonic()
    set_dir = backup_dir / f".set-{record.id}"
    try:
        info = _conn_info(conn, crypto)
        reporter.report("dump", ",".join(names))
        suffix = {".tar.gz": ".tar.gz", ".sql.gz": ".sql.gz", ".archive.gz": ".archive.gz"}.get(
            "", ".tar.gz")
        final_name = f"{conn.type}_{conn.id}_{record.id}.set.tar.gz"
        if conn.type == "mysql":
            final_name = f"mysql_{conn.id}_{record.id}.set.sql.gz"
        elif conn.type == "mongo":
            final_name = f"mongo_{conn.id}_{record.id}.set.archive.gz"
        out = dump_set(info, names, set_dir, final_name)
        # 命名保持 set 语义:pg_x_1.set.tar.gz / mysql_x_2.set.sql.gz / mongo_x_3.set.archive.gz
        final = backup_dir / out.name
        os.replace(out, final)

        reporter.report("compress")
        checksum = sha256_of_file(final)
        record.file_path = str(final.relative_to(backup_dir))
        record.size = final.stat().st_size
        record.checksum = checksum
        record.status = "success"
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit(); db.refresh(record)
        reporter.report("success")
        return record
    except Exception as exc:
        safe_remove(set_dir)
        record.status = "failed"
        record.error = str(exc)
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit(); db.refresh(record)
        reporter.report("failed", str(exc))
        return record
