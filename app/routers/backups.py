from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import config
from app.db.session import get_db
from app.db.models import BackupRecord
from app.deps import get_current_account
from app.schemas.job import BackupFileOut

router = APIRouter()


def _backup_dir() -> Path:
    # 经由模块读取,保证 reload 后仍指向当前 settings(conftest 测试会 reload)。
    return config.settings.data_dir / "backups"


def _resolve(record: BackupRecord) -> Path:
    """安全解析备份文件路径,防穿越。"""
    if not record.file_path:
        raise HTTPException(status_code=404, detail="文件不存在")
    base = _backup_dir().resolve()
    path = (base / record.file_path).resolve()
    if path != base and base not in path.parents:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return path


@router.get("/backups", response_model=list[BackupFileOut])
def list_backups(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(BackupRecord).order_by(BackupRecord.id.desc()).offset(offset).limit(limit).all()


@router.get("/backups/{record_id}/download")
def download(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    path = _resolve(rec)
    return FileResponse(path, filename=path.name)


@router.delete("/backups/{record_id}", status_code=204)
def delete_backup(record_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    rec = db.get(BackupRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    # 先删记录再删文件:若 commit 失败,文件仍在,记录也仍在(一致);反之会留指向缺失文件的记录
    file_path = None
    if rec.file_path:
        try:
            file_path = _resolve(rec)
        except HTTPException:
            file_path = None  # 文件已不在也允许删记录
    db.delete(rec); db.commit()
    if file_path is not None:
        try:
            file_path.unlink()
        except OSError:
            pass  # 文件已不在也算成功
