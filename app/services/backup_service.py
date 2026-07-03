from __future__ import annotations
import os
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord
from app.core.crypto import Crypto
from app.core.archive import compress_file, sha256_of_file
from app.adapters.base import ConnectionInfo, get_adapter
from app.workers.progress import ProgressReporter


def _conn_info(conn: DbConnection, crypto: Crypto) -> ConnectionInfo:
    return ConnectionInfo(
        type=conn.type,
        host=conn.host,
        port=conn.port,
        db_name=conn.db_name,
        username=conn.username,
        password=_decrypt(conn.password_enc, crypto),
    )


def _decrypt(enc: str | None, crypto: Crypto) -> str | None:
    return crypto.decrypt(enc) if enc else None


def run_backup(
    db: Session,
    crypto: Crypto,
    conn: DbConnection,
    trigger: str,
    reporter: ProgressReporter,
    backup_dir: Path,
    now_fn=datetime.utcnow,
    sleep_fn=time.sleep,
) -> BackupRecord:
    """执行一次备份:建记录(running)→ dump → 压缩 → 校验 → 更新(success/failed/cancelled)。
    每阶段上报进度,阶段间隙检查取消标志。失败捕获异常并写入 error。"""
    record = BackupRecord(connection_id=conn.id, trigger=trigger, status="running", started_at=now_fn())
    db.add(record)
    db.commit()
    db.refresh(record)

    def _check_cancel():
        if reporter.is_cancelled():
            record.status = "cancelled"
            record.finished_at = now_fn()
            db.commit()
            db.refresh(record)
            reporter.report("cancelled")
            return True
        return False

    raw_path = backup_dir / f"{conn.type}_{conn.id}_{record.id}.sql"
    gz_path = backup_dir / f"{conn.type}_{conn.id}_{record.id}.sql.gz"
    start = time.monotonic()
    try:
        if _check_cancel():
            return record

        reporter.report("dump")
        adapter = get_adapter(conn.type)
        adapter.dump(_conn_info(conn, crypto), str(raw_path))

        if _check_cancel():
            _safe_remove(raw_path)
            return record

        reporter.report("compress")
        compress_file(raw_path, gz_path)
        _safe_remove(raw_path)
        size = os.path.getsize(gz_path)
        checksum = sha256_of_file(gz_path)

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
    except Exception as exc:
        record.status = "failed"
        record.error = str(exc)
        record.finished_at = now_fn()
        record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(record)
        reporter.report("failed", str(exc))
        return record


def _safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
