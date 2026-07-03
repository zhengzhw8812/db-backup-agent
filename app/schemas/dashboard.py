from __future__ import annotations
from pydantic import BaseModel


class DashboardStats(BaseModel):
    total: int
    success: int
    failed: int
    success_rate: float
    storage_bytes: int
    running: int


class DailyPoint(BaseModel):
    date: str
    success: int
    failed: int


class TypeStorage(BaseModel):
    type: str
    storage_bytes: int


class DashboardTrends(BaseModel):
    daily: list[DailyPoint]
    by_type: list[TypeStorage]
