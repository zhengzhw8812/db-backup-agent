from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app import config
from app.db.session import get_db
from app.deps import get_current_account
from app.services.self_backup import NAME_RE, SQL_RE, list_snapshots, run_self_backup, export_sql_dump, stage_restore, self_backup_dir

router = APIRouter()


@router.post("/self-backup/run")
def trigger_self_backup(_request: Request, fmt: str = "gz", _=Depends(get_current_account)):
    from app.db import session as _session

    db = _session._SessionLocal()
    try:
        if fmt == "sql":
            out = export_sql_dump(config.settings.data_dir, db=db)
        elif fmt == "gz":
            out = run_self_backup(config.settings.data_dir, db=db)
        else:
            raise HTTPException(status_code=422, detail=f"不支持的格式:{fmt}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"自备份失败:{exc}")
    finally:
        db.close()
    return {"name": out.name, "size": out.stat().st_size, "kind": fmt}


@router.get("/self-backup")
def list_self_backups(_=Depends(get_current_account)):
    return list_snapshots(config.settings.data_dir)


@router.get("/self-backup/{name}/download")
def download_self_backup(name: str, _=Depends(get_current_account)):
    if not (NAME_RE.match(name) or SQL_RE.match(name)):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = self_backup_dir(config.settings.data_dir) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=name, media_type="application/gzip")


@router.post("/self-backup/import")
async def import_sql(file: UploadFile = File(...), _=Depends(get_current_account)):
    """上传 .sql 配置库脚本:临时库校验核心表后暂存,重启容器生效。"""
    from app import config
    from app.services.self_backup import stage_restore

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 20MB 上限")
    try:
        stage_restore(config.settings.data_dir, data.decode("utf-8", "replace"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"staged": True, "message": "已暂存,重启容器后生效"}


@router.post("/self-backup/{name}/restore")
def restore_from_listed(name: str, _=Depends(get_current_account)):
    """还原列表内已导出的 .sql(重启容器生效)。"""
    from app import config

    if not SQL_RE.match(name):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = self_backup_dir(config.settings.data_dir) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    from app.services.self_backup import stage_restore

    try:
        stage_restore(config.settings.data_dir, path.read_text())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"staged": True, "message": "已暂存,重启容器后生效"}
