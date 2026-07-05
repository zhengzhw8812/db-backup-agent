from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class BackupRunRequest(BaseModel):
    connection_id: int
    trigger: str = Field("manual", pattern="^(manual|scheduled)$")


class JobRecordRef(BaseModel):
    record_id: int
    db_name: str | None = None
    status: str


class JobRunResponse(BaseModel):
    connection_id: int
    record_ids: list[int]
    records: list[JobRecordRef]
    status: str  # 汇总态,初始 "running"


class JobOut(BaseModel):
    id: int
    connection_id: int
    trigger: str
    db_name: str | None = None
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}


class BackupFileOut(BaseModel):
    id: int
    connection_id: int
    trigger: str
    db_name: str | None = None
    status: str
    file_path: str | None
    size: int | None
    checksum: str | None
    duration_ms: int | None
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}
