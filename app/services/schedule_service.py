from __future__ import annotations
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from apscheduler.triggers.cron import CronTrigger

from app.db.models import Schedule, DbConnection


def _validate_cron(expr: str | None) -> None:
    """提交时即校验 cron,避免一条非法表达式落库后拖垮整个调度器启动。"""
    if not expr:
        raise HTTPException(status_code=400, detail="cron 表达式不能为空")
    try:
        CronTrigger.from_crontab(expr)
    except Exception:
        raise HTTPException(status_code=400, detail=f"无效的 cron 表达式: {expr}")


def _get(db: Session, sid: int) -> Schedule:
    s = db.get(Schedule, sid)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划不存在")
    return s


def list_schedules(db: Session) -> list[Schedule]:
    return db.query(Schedule).order_by(Schedule.id).all()


def create_schedule(db: Session, data) -> Schedule:
    if db.get(DbConnection, data.connection_id) is None:
        raise HTTPException(status_code=400, detail="连接不存在")
    _validate_cron(data.cron_expr)
    s = Schedule(connection_id=data.connection_id, cron_expr=data.cron_expr,
                 enabled=data.enabled, retention_days=data.retention_days)
    db.add(s); db.commit(); db.refresh(s)
    return s


def update_schedule(db: Session, sid: int, data) -> Schedule:
    s = _get(db, sid)
    if data.cron_expr is not None:
        _validate_cron(data.cron_expr)
    for f in ("cron_expr", "enabled", "retention_days"):
        v = getattr(data, f)
        if v is not None:
            setattr(s, f, v)
    db.commit(); db.refresh(s)
    return s


def delete_schedule(db: Session, sid: int) -> None:
    s = _get(db, sid)
    db.delete(s); db.commit()
