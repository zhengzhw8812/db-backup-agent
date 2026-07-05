from __future__ import annotations
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import config
from app.db.session import get_db
from app.db.models import BackupRecord, DbConnection, RestoreRecord
from app.deps import get_current_account
from app.schemas.restore import RestoreRequest, RestoreRunResponse, RestoreOut
from app.services.locks import has_running_restore
from app.workers.progress import request_cancel
from app.routers._sse import event_stream

router = APIRouter()


async def _get_arq(app):
    """惰性创建 arq 连接池(测试里可直接覆盖 app.state.arq)。"""
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        app.state.arq = await create_pool(RedisSettings.from_dsn(config.settings.redis_url))
    return app.state.arq


@router.post("/restore", response_model=RestoreRunResponse, status_code=201)
async def run_restore_route(payload: RestoreRequest, request: Request,
                            db: Session = Depends(get_db), _=Depends(get_current_account)):
    backup = db.get(BackupRecord, payload.backup_record_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if backup.status != "success" or not backup.file_path:
        raise HTTPException(status_code=400, detail="该备份不可用于恢复")
    target = db.get(DbConnection, payload.target_connection_id)
    if target is None:
        raise HTTPException(status_code=404, detail="目标连接不存在")
    # 互斥:同一目标连接已有恢复在运行 → 拒绝
    if has_running_restore(db, target.id) is not None:
        raise HTTPException(status_code=409, detail="该目标连接已有恢复在运行")
    record = RestoreRecord(backup_record_id=backup.id, target_connection_id=target.id,
                           status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    try:
        arq = await _get_arq(request.app)
        await arq.enqueue_job("restore_job", backup.id, target.id, record.id)
    except Exception:
        record.status = "failed"
        record.error = "投递到队列失败"
        record.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="投递到队列失败,请稍后重试")
    return RestoreRunResponse(record_id=record.id, status=record.status)


@router.get("/restore", response_model=list[RestoreOut])
def list_restores(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(RestoreRecord).order_by(RestoreRecord.id.desc()).offset(offset).limit(limit).all()


@router.post("/restore/{record_id}/cancel")
def cancel_restore(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(RestoreRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="恢复任务不存在")
    request_cancel(record_id, kind="restore")
    return {"ok": True}


@router.get("/restore/{record_id}/events")
async def restore_events(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(RestoreRecord, record_id)
    initial = rec.status if rec else None
    return StreamingResponse(event_stream(record_id, "restore", initial), media_type="text/event-stream")
