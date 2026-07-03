from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class RestoreRequest(BaseModel):
    backup_record_id: int
    target_connection_id: int


class RestoreRunResponse(BaseModel):
    record_id: int
    status: str


class RestoreOut(BaseModel):
    id: int
    backup_record_id: int
    target_connection_id: int
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None

    model_config = {"from_attributes": True}
