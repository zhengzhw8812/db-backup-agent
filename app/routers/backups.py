from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
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
def list_backups(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return db.query(BackupRecord).order_by(BackupRecord.id.desc()).all()


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
    try:
        _resolve(rec).unlink()
    except HTTPException:
        pass  # 文件已不在也允许删记录
    db.delete(rec); db.commit()
