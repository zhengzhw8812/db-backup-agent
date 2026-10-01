from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, Schedule
from app.core.fsutil import safe_remove
from app.core.clock import utcnow


def run_retention(db: Session, crypto, conn: DbConnection, backup_dir: Path) -> int:
    """删除该连接超过最激进 retention_days 的成功备份(文件+记录)。无计划 → 0。"""
    schedules = (
        db.query(Schedule)
        .filter(Schedule.connection_id == conn.id, Schedule.enabled.is_(True))
        .all()
    )
    if not schedules:
        return 0
    # 至少保留 1 天,避免 retention_days=0 把"刚生成的备份"立即删掉
    days = max(min(s.retention_days for s in schedules), 1)
    cutoff = utcnow() - timedelta(days=days)
    old = (
        db.query(BackupRecord)
        .filter(BackupRecord.connection_id == conn.id,
                BackupRecord.status == "success",
                BackupRecord.started_at < cutoff)
        .all()
    )
    count = 0
    for rec in old:
        if rec.file_path:
            # 云联动先行:云端失败已在内部记日志并继续;随后删本地(文件+记录)
            from app.services.sync_service import delete_cloud_copies
            delete_cloud_copies(db, crypto, conn.id, rec.file_path)
            safe_remove(backup_dir / rec.file_path)
        db.delete(rec)
        count += 1
    db.commit()
    return count
