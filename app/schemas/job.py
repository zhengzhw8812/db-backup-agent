from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class JobRunResponse(BaseModel):
    record_id: int
    status: str


class JobOut(BaseModel):
    id: int
    connection_id: int
    trigger: str
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class BackupFileOut(BaseModel):
    id: int
    connection_id: int
    status: str
    file_path: str | None
    size: int | None
    checksum: str | None
    duration_ms: int | None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}
