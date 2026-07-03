from __future__ import annotations
import asyncio

from app.bootstrap import bootstrap_keys
from app.core.crypto import Crypto
from app.db.models import DbConnection, BackupRecord, RestoreRecord
from app.db import session as _session
from app.services.backup_service import run_backup
from app.services.restore_service import run_restore
from app.workers.progress import ProgressReporter


def _run_backup_sync(ctx, connection_id: int, record_id: int) -> dict:
    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    db = _session._SessionLocal()
    try:
        conn = db.get(DbConnection, connection_id)
        if conn is None:
            raise ValueError(f"连接不存在: {connection_id}")
        reporter = ProgressReporter(record_id)
        rec = run_backup(db, crypto, conn, reporter, ctx["backup_dir"], record_id)
        return {"record_id": rec.id, "status": rec.status}
    finally:
        db.close()


async def backup_job(ctx, connection_id: int, record_id: int) -> dict:
    return await asyncio.to_thread(_run_backup_sync, ctx, connection_id, record_id)


def _run_restore_sync(ctx, backup_record_id: int, target_connection_id: int, restore_record_id: int) -> dict:
    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    db = _session._SessionLocal()
    try:
        backup_record = db.get(BackupRecord, backup_record_id)
        if backup_record is None:
            raise ValueError(f"备份记录不存在: {backup_record_id}")
        target_conn = db.get(DbConnection, target_connection_id)
        if target_conn is None:
            raise ValueError(f"目标连接不存在: {target_connection_id}")
        reporter = ProgressReporter(restore_record_id, kind="restore")
        rec = run_restore(db, crypto, backup_record, target_conn, reporter, ctx["backup_dir"], restore_record_id)
        return {"record_id": rec.id, "status": rec.status}
    finally:
        db.close()


async def restore_job(ctx, backup_record_id: int, target_connection_id: int, restore_record_id: int) -> dict:
    return await asyncio.to_thread(_run_restore_sync, ctx, backup_record_id, target_connection_id, restore_record_id)
