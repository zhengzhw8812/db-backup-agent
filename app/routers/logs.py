from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import SystemLog
from app.deps import get_current_account
from app.schemas.log import SystemLogOut

router = APIRouter()


@router.get("/logs", response_model=list[SystemLogOut])
def list_logs(level: str | None = Query(default=None),
              limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), _=Depends(get_current_account)):
    q = db.query(SystemLog).order_by(SystemLog.id.desc())
    if level:
        q = q.filter(SystemLog.level == level)
    return q.offset(offset).limit(limit).all()
