from __future__ import annotations
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import config
from app.db.session import get_db
from app.db.models import BackupRecord, DbConnection
from app.deps import get_current_account
from app.schemas.job import JobRunResponse, JobOut, BackupRunRequest
from app.services.locks import has_running_backup
from app.services.backup_service import enqueue_backup
from app.workers.progress import request_cancel
from app.routers._sse import event_stream

router = APIRouter()


async def _get_arq(app):
    """惰性创建 arq 连接池(测试里可直接覆盖 app.state.arq)。"""
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        # arq 0.28 的 create_pool 首参为 RedisSettings,不能直接传 URL 字符串
        # (否则 AttributeError: 'str' object has no attribute 'host')
        app.state.arq = await create_pool(RedisSettings.from_dsn(config.settings.redis_url))
    return app.state.arq


@router.post("/backups/run", response_model=JobRunResponse, status_code=201)
async def run_now(payload: BackupRunRequest, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    conn = db.get(DbConnection, payload.connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    # 互斥:同一连接已有备份在运行 → 拒绝,避免并发 dump 损坏/资源争抢
    if has_running_backup(db, conn.id) is not None:
        raise HTTPException(status_code=409, detail="该连接已有备份在运行")
    records = enqueue_backup(db, conn, payload.trigger)
    try:
        arq = await _get_arq(request.app)
        await arq.enqueue_job("backup_job", conn.id, [r.id for r in records])
    except Exception:
        # 投递失败:把所有刚建的 running 记录翻转为 failed,避免幽灵
        for r in records:
            r.status = "failed"
            r.error = "投递到队列失败"
            r.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="投递到队列失败,请稍后重试")
    return JobRunResponse(
        connection_id=conn.id,
        record_ids=[r.id for r in records],
        records=[{"record_id": r.id, "db_name": r.db_name, "status": r.status} for r in records],
        status="running",
    )


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), _=Depends(get_current_account)):
    rows = db.query(BackupRecord).filter(BackupRecord.status == "running").order_by(BackupRecord.id.desc()).all()
    return rows


@router.post("/jobs/{record_id}/cancel")
def cancel(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    request_cancel(record_id)
    return {"ok": True}


@router.get("/jobs/{record_id}/events")
async def events(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    initial = rec.status if rec else None
    return StreamingResponse(event_stream(record_id, "job", initial), media_type="text/event-stream")
