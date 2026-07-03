from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class CloudDestinationCreate(BaseModel):
    name: str
    provider: str = "s3"
    endpoint: str
    region: str | None = None
    bucket: str
    access_key: str
    secret: str
    prefix: str = ""
    secure: bool = True
    enabled: bool = True


class CloudDestinationOut(BaseModel):
    id: int
    name: str
    provider: str
    endpoint: str
    region: str | None
    bucket: str
    prefix: str
    secure: bool
    enabled: bool
    created_at: datetime
    # 注意:不含 access_key / secret —— 永不回传

    model_config = {"from_attributes": True}


class SyncTargetCreate(BaseModel):
    connection_id: int
    cloud_destination_id: int
    enabled: bool = True


class SyncTargetOut(BaseModel):
    id: int
    connection_id: int
    cloud_destination_id: int
    enabled: bool

    model_config = {"from_attributes": True}


class SyncRunRequest(BaseModel):
    backup_record_id: int
