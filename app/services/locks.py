from __future__ import annotations
from sqlalchemy.orm import Session

from app.db.models import BackupRecord, RestoreRecord


def has_running_backup(db: Session, connection_id: int) -> BackupRecord | None:
    """同一连接是否已有 running 备份(用于互斥;靠超时+启动 reap 保证最终释放)。"""
    return (
        db.query(BackupRecord)
        .filter(BackupRecord.connection_id == connection_id, BackupRecord.status == "running")
        .first()
    )


def has_running_restore(db: Session, target_connection_id: int) -> RestoreRecord | None:
    """同一目标连接是否已有 running 恢复。"""
    return (
        db.query(RestoreRecord)
        .filter(RestoreRecord.target_connection_id == target_connection_id,
                RestoreRecord.status == "running")
        .first()
    )
