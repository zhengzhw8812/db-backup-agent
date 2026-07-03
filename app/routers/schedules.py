from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import get_current_account
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate, ScheduleOut
from app.services import schedule_service as svc

router = APIRouter()


@router.get("/schedules", response_model=list[ScheduleOut])
def list_(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.list_schedules(db)


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create(payload: ScheduleCreate, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.create_schedule(db, payload)


@router.put("/schedules/{sid}", response_model=ScheduleOut)
def update(sid: int, payload: ScheduleUpdate, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.update_schedule(db, sid, payload)


@router.delete("/schedules/{sid}", status_code=204)
def delete(sid: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    svc.delete_schedule(db, sid)
