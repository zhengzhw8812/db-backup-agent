from __future__ import annotations
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import BackupRecord, DbConnection
from app.deps import get_current_account
from app.schemas.job import JobRunResponse, JobOut
from app.workers.progress import request_cancel

router = APIRouter()


async def _get_arq(app):
    """惰性创建 arq 连接池(测试里可直接覆盖 app.state.arq)。"""
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        app.state.arq = await create_pool(settings.redis_url)
    return app.state.arq


@router.post("/backups/run", response_model=JobRunResponse, status_code=201)
async def run_now(payload: dict, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    conn_id = payload.get("connection_id")
    trigger = payload.get("trigger", "manual")
    conn = db.get(DbConnection, conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    record = BackupRecord(connection_id=conn.id, trigger=trigger, status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    arq = await _get_arq(request.app)
    await arq.enqueue_job("backup_job", conn.id, record.id)
    return JobRunResponse(record_id=record.id, status=record.status)


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
async def events(record_id: int, _=Depends(get_current_account)):
    from app.redis_client import get_async_redis
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"job:{record_id}")

    async def gen():
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                    yield f"data: {data}\n\n"
                    try:
                        if json.loads(data).get("stage") in ("success", "failed", "cancelled"):
                            return
                    except Exception:
                        pass
        finally:
            await pubsub.unsubscribe(f"job:{record_id}")
            await pubsub.close()

    return StreamingResponse(gen(), media_type="text/event-stream")
