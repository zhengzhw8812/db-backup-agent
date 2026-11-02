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
    from app.services import mount_service

    rows = db.query(CloudDestination).order_by(CloudDestination.id.desc()).all()
    out = []
    for d in rows:
        item = CloudDestinationOut.model_validate(d)
        item.mounted = (mount_service.is_mounted(d.id) if d.provider in ("nfs", "smb") else None)
        out.append(item)
    return out


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
        mount_config=payload.mount.model_dump_json(exclude_none=True) if payload.mount else None,
        mount_password_enc=crypto.encrypt(payload.mount_password) if payload.mount_password else None,
    )
    db.add(d); db.commit(); db.refresh(d)
    if d.provider in ("nfs", "smb"):
        # 挂载失败 → 回滚整行,避免留下"永远挂不上"的死配置
        from app.services import mount_service

        try:
            mount_service.mount_destination(d, crypto)
        except Exception as exc:
            db.delete(d); db.commit()
            raise HTTPException(status_code=400, detail=str(exc))
    return d


@router.put("/cloud-destinations/{dest_id}", response_model=CloudDestinationOut)
def update_destination(dest_id: int, payload: CloudDestinationCreate, request: Request,
                       db: Session = Depends(get_db), _=Depends(get_current_account)):
    """编辑云目标:凭据(access_key/secret/mount_password)留空=保留已存密文;
    provider 不允许变更;s3↔nfs 属不同类型目标,改型请删除后新建。
    nfs/smb 挂载参数变化时重挂;重挂失败不回滚(配置保留,启动时自动重试)。"""
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    if payload.provider != d.provider:
        raise HTTPException(status_code=422, detail="云目标类型不可修改;如需更换请删除后新建")
    crypto = request.app.state.crypto

    new_mount_json = payload.mount.model_dump_json(exclude_none=True) if payload.mount else None
    remount_needed = d.provider in ("nfs", "smb") and new_mount_json != d.mount_config

    d.name = payload.name
    d.endpoint = payload.endpoint
    d.region = payload.region
    d.bucket = payload.bucket
    d.prefix = payload.prefix
    d.secure = payload.secure
    d.enabled = payload.enabled
    if new_mount_json is not None:
        d.mount_config = new_mount_json
    # 凭据:非空才覆盖(避免空串清掉已存密文)
    if payload.access_key:
        d.access_key_enc = crypto.encrypt(payload.access_key)
    if payload.secret:
        d.secret_enc = crypto.encrypt(payload.secret)
    if payload.mount_password:
        d.mount_password_enc = crypto.encrypt(payload.mount_password)

    warning = None
    mounted = None
    if d.provider in ("nfs", "smb"):
        from app.services import mount_service

        if remount_needed:
            try:
                mount_service.unmount_destination(d.id)  # 旧挂载点参数可能已失效
            except Exception as exc:
                warning = (f"新配置已保存,但旧挂载未能卸载({exc}),"
                           "新配置尚未生效;重启容器后按新配置挂载")
        try:
            mount_service.mount_destination(d, crypto)  # 幂等:已挂载则跳过
        except Exception as exc:
            warning = warning or f"配置已保存,但重新挂载失败:{exc};容器重启时会自动重试"
        mounted = mount_service.is_mounted(d.id)
    db.commit(); db.refresh(d)
    out = CloudDestinationOut.model_validate(d)
    out.mounted = mounted
    out.warning = warning
    return out


@router.post("/cloud-destinations/test")
def test_destination_draft(payload: CloudDestinationCreate,
                           _=Depends(get_current_account)):
    """保存前测试:用表单里的临时凭据直连验证(不落库)。目前支持 s3;
    NFS/SMB 挂载依赖落库 id,请保存后用列表「探针」验证。"""
    if payload.provider != "s3":
        raise HTTPException(status_code=400, detail="共享存储(NFS/SMB)请保存后用列表的测试/探针验证")
    cfg = CloudConfig(
        endpoint=payload.endpoint, access_key=payload.access_key,
        secret_key=payload.secret, bucket=payload.bucket,
        region=payload.region, secure=payload.secure, prefix=payload.prefix,
    )
    try:
        get_storage(payload.provider).test(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.delete("/cloud-destinations/{dest_id}", status_code=204)
def delete_destination(dest_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    if d.provider in ("nfs", "smb"):
        from app.services import mount_service

        try:
            mount_service.unmount_destination(d.id)
        except Exception as exc:
            raise HTTPException(status_code=400,
                                detail=f"卸载失败,目标可能正被备份任务使用:{exc}")
    db.delete(d); db.commit()


@router.post("/cloud-destinations/{dest_id}/test")
def test_destination(dest_id: int, request: Request,
                     db: Session = Depends(get_db), _=Depends(get_current_account)):
    d = db.get(CloudDestination, dest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="云目标不存在")
    crypto = request.app.state.crypto
    if d.provider in ("nfs", "smb"):
        from app.services import mount_service

        mount_service.mount_destination(d, crypto)  # 幂等:已挂载则跳过
        cfg = CloudConfig(endpoint="", access_key="", secret_key="", bucket="",
                          prefix=d.prefix, mount_point=str(mount_service.mount_point(d.id)))
    else:
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
