from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.db.session import get_db
from app.db.models import CloudDestination, SyncTarget, BackupRecord, DbConnection
from app.deps import get_current_account
from app.schemas.cloud import (
    CloudDestinationCreate, CloudDestinationOut,
    SyncTargetCreate, SyncTargetOut, SyncRunRequest,
)
from app.cloud.base import get_storage, CloudConfig, _REGISTRY as CLOUD_REGISTRY

router = APIRouter()


async def _get_arq(app):
    if getattr(app.state, "arq", None) is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        app.state.arq = await create_pool(RedisSettings.from_dsn(config.settings.redis_url))
    return app.state.arq


# ---------- cloud-destinations ----------

@router.get("/cloud-destinations", response_model=list[CloudDestinationOut])
def list_destinations(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(CloudDestination).order_by(CloudDestination.id.desc()).all()


@router.post("/cloud-destinations", response_model=CloudDestinationOut, status_code=201)
def create_destination(payload: CloudDestinationCreate, request: Request,
                       db: Session = Depends(get_db), _=Depends(get_current_account)):
    if payload.provider not in CLOUD_REGISTRY:  # 提交即校验,避免存了非法 provider 到同步时才报错
        raise HTTPException(status_code=400, detail=f"不支持的云存储: {payload.provider}")
    crypto = request.app.state.crypto
    d = CloudDestination(
        name=payload.name, provider=payload.provider, endpoint=payload.endpoint,
        region=payload.region, bucket=payload.bucket,
        access_key_enc=crypto.encrypt(payload.access_key),
        secret_enc=crypto.encrypt(payload.secret),
        prefix=payload.prefix, secure=payload.secure, enabled=payload.enabled,
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


@router.delete("/cloud-destinations/{dest_id}", status_code=204)
def delete_destination(dest_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    db.delete(d); db.commit()


@router.post("/cloud-destinations/{dest_id}/test")
def test_destination(dest_id: int, request: Request,
                     db: Session = Depends(get_db), _=Depends(get_current_account)):
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    crypto = request.app.state.crypto
    cfg = CloudConfig(
        endpoint=d.endpoint, access_key=crypto.decrypt(d.access_key_enc),
        secret_key=crypto.decrypt(d.secret_enc), bucket=d.bucket,
        region=d.region, secure=d.secure, prefix=d.prefix,
    )
    try:
        get_storage(d.provider).test(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


# ---------- sync-targets ----------

@router.get("/sync-targets", response_model=list[SyncTargetOut])
def list_targets(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(SyncTarget).order_by(SyncTarget.id.desc()).all()


@router.post("/sync-targets", response_model=SyncTargetOut, status_code=201)
def create_target(payload: SyncTargetCreate, db: Session = Depends(get_db), _=Depends(get_current_account)):
    if db.get(CloudDestination, payload.cloud_destination_id) is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    if db.get(DbConnection, payload.connection_id) is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    t = SyncTarget(connection_id=payload.connection_id,
                   cloud_destination_id=payload.cloud_destination_id, enabled=payload.enabled)
    db.add(t)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该同步规则已存在")
    db.refresh(t)
    return t


@router.delete("/sync-targets/{target_id}", status_code=204)
def delete_target(target_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    t = db.get(SyncTarget, target_id)
    if t is None:
        raise HTTPException(status_code=404, detail="同步规则不存在")
    db.delete(t); db.commit()


# ---------- sync/run ----------

@router.post("/sync/run")
async def sync_run(payload: SyncRunRequest, request: Request,
                   db: Session = Depends(get_db), _=Depends(get_current_account)):
    backup = db.get(BackupRecord, payload.backup_record_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if backup.status != "success" or not backup.file_path:
        raise HTTPException(status_code=400, detail="该备份不可用于同步")
    arq = await _get_arq(request.app)
    await arq.enqueue_job("sync_job", backup.id)
    return {"ok": True, "backup_record_id": backup.id}
