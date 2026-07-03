from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ScheduleBase(BaseModel):
    connection_id: int
    cron_expr: str = Field(..., pattern=r"^[^\s]+(\s+[^\s]+){4}$")  # 5 字段 cron
    enabled: bool = True
    retention_days: int = Field(7, ge=1)


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    cron_expr: str | None = Field(None, pattern=r"^[^\s]+(\s+[^\s]+){4}$")
    enabled: bool | None = None
    retention_days: int | None = Field(None, ge=1)


class ScheduleOut(BaseModel):
    id: int
    connection_id: int
    cron_expr: str
    enabled: bool
    retention_days: int
    next_run_at: datetime | None
    model_config = {"from_attributes": True}
