from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import func, select, case
from sqlalchemy.orm import Session
from app.db.models import BackupRecord, DbConnection


def stats(db: Session) -> dict:
    # 一次聚合取出全部计数 + 成功存储总量(原实现 5 次全表扫描)
    row = db.query(
        func.count(BackupRecord.id),
        func.coalesce(func.sum(case((BackupRecord.status == "success", 1), else_=0)), 0),
        func.coalesce(func.sum(case((BackupRecord.status == "failed", 1), else_=0)), 0),
        func.coalesce(func.sum(case((BackupRecord.status == "running", 1), else_=0)), 0),
        func.coalesce(func.sum(case((BackupRecord.status == "success", BackupRecord.size), else_=0)), 0),
    ).one()
    total, success, failed, running, storage = (int(v or 0) for v in row)
    # 成功率分母只计终态(success+failed),不受 running/cancelled 影响
    denom = success + failed
    rate = round(success / denom, 4) if denom else 0.0
    return {"total": total, "success": success, "failed": failed,
            "success_rate": rate, "storage_bytes": storage, "running": running}


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
