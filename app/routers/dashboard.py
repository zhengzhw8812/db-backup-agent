from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import get_current_account
from app.schemas.dashboard import DashboardStats, DashboardTrends
from app.services import dashboard_service as svc

router = APIRouter()


@router.get("/dashboard/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.stats(db)


@router.get("/dashboard/trends", response_model=DashboardTrends)
def get_trends(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.trends(db)
