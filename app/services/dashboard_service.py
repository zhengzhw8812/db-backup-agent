from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.db.models import BackupRecord, DbConnection


def stats(db: Session) -> dict:
    total = db.query(func.count(BackupRecord.id)).scalar() or 0
    success = db.query(func.count(BackupRecord.id)).filter(BackupRecord.status == "success").scalar() or 0
    failed = db.query(func.count(BackupRecord.id)).filter(BackupRecord.status == "failed").scalar() or 0
    running = db.query(func.count(BackupRecord.id)).filter(BackupRecord.status == "running").scalar() or 0
    storage = db.query(func.coalesce(func.sum(BackupRecord.size), 0)).filter(BackupRecord.status == "success").scalar() or 0
    rate = round(success / total, 4) if total else 0.0
    return {"total": total, "success": success, "failed": failed,
            "success_rate": rate, "storage_bytes": int(storage), "running": running}


def trends(db: Session, days: int = 30) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        func.date(BackupRecord.started_at).label("d"),
        BackupRecord.status,
        func.count(BackupRecord.id),
    ).filter(BackupRecord.started_at >= since).group_by("d", BackupRecord.status).all()
    daily_map: dict[str, dict] = {}
    for d, status, cnt in rows:
        bucket = daily_map.setdefault(str(d), {"date": str(d), "success": 0, "failed": 0})
        if status == "success":
            bucket["success"] = int(cnt)
        elif status == "failed":
            bucket["failed"] = int(cnt)
    daily = sorted(daily_map.values(), key=lambda x: x["date"])

    type_rows = db.query(
        DbConnection.type, func.coalesce(func.sum(BackupRecord.size), 0),
    ).join(BackupRecord, BackupRecord.connection_id == DbConnection.id).filter(
        BackupRecord.status == "success"
    ).group_by(DbConnection.type).all()
    by_type = [{"type": t, "storage_bytes": int(s)} for t, s in type_rows]
    return {"daily": daily, "by_type": by_type}
