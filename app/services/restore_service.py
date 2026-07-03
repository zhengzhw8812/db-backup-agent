from __future__ import annotations
import os
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.core.crypto import Crypto
from app.core.archive import decompress_file, sha256_of_file
from app.adapters.base import get_adapter
from app.services.backup_service import _conn_info
from app.workers.progress import ProgressReporter


def _safe_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def run_restore(
    db: Session,
    crypto: Crypto,
    backup_record: BackupRecord,
    target_conn: DbConnection,
    reporter: ProgressReporter,
    backup_dir: Path,
    restore_record_id: int,
    now_fn=datetime.utcnow,
) -> RestoreRecord:
    """对一条已存在的 running 恢复记录执行:校验 → 解压 → 还原,并写入终态。

    校验阶段比对备份文件 SHA-256 与记录 checksum(完整性护栏,不一致即失败)。
    记录由调用方预先创建,restore_record_id 同时作为进度频道与取消锚点。
    每阶段上报进度,阶段间隙检查取消;失败捕获异常;中间 raw 文件统一在 finally 清理。"""
    restore_record = db.get(RestoreRecord, restore_record_id)
    if restore_record is None:
        raise ValueError(f"恢复记录不存在: {restore_record_id}")
    if restore_record.started_at is None:
        restore_record.started_at = now_fn()
    db.commit()

    raw_path = backup_dir / f"restore_{restore_record_id}.sql"
    start = time.monotonic()

    def _check_cancel():
        if reporter.is_cancelled():
            restore_record.status = "cancelled"
            restore_record.finished_at = now_fn()
            restore_record.duration_ms = int((time.monotonic() - start) * 1000)
            db.commit()
            db.refresh(restore_record)
            reporter.report("cancelled")
            return True
        return False

    try:
        if _check_cancel():
            return restore_record

        # 1. 完整性校验
        reporter.report("verify")
        if not backup_record.file_path:
            raise FileNotFoundError("备份记录无文件路径")
        backup_path = (backup_dir / backup_record.file_path).resolve()
        base = backup_dir.resolve()
        if backup_path != base and base not in backup_path.parents:
            raise ValueError("备份文件路径非法")
        if not backup_path.exists():
            raise FileNotFoundError("备份文件不存在")
        if backup_record.checksum and sha256_of_file(backup_path) != backup_record.checksum:
            raise ValueError("校验和不匹配,备份文件可能损坏")

        if _check_cancel():
            return restore_record

        # 2. 解压
        reporter.report("decompress")
        decompress_file(backup_path, raw_path)

        if _check_cancel():
            return restore_record

        # 3. 还原
        reporter.report("restore")
        adapter = get_adapter(target_conn.type)
        adapter.restore(_conn_info(target_conn, crypto), str(raw_path))

        restore_record.status = "success"
        restore_record.finished_at = now_fn()
        restore_record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(restore_record)
        reporter.report("success")
        return restore_record
    except Exception as exc:
        restore_record.status = "failed"
        restore_record.error = str(exc)
        restore_record.finished_at = now_fn()
        restore_record.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
        db.refresh(restore_record)
        reporter.report("failed", str(exc))
        return restore_record
    finally:
        _safe_remove(raw_path)
