from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class MountConfig(BaseModel):
    """NFS/SMB 挂载参数(非密字段;密码走 mount_password)。"""
    server: str
    export: str | None = None      # nfs
    version: str | None = None     # nfs: nfs4(默认)/nfs3
    share: str | None = None       # smb
    domain: str | None = None      # smb 可选
    username: str | None = None    # smb 可选


class CloudDestinationCreate(BaseModel):
    name: str
    provider: str = "s3"
    endpoint: str = ""
    region: str | None = None
    bucket: str = ""
    access_key: str = ""
    secret: str = ""
    prefix: str = ""
    secure: bool = True
    enabled: bool = True
    mount: MountConfig | None = None
    mount_password: str | None = None


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
    mount_config: str | None = None
    mounted: bool | None = None    # nfs/smb 专用;s3 为 null
    created_at: datetime
    # 注意:不含 access_key / secret / mount_password —— 永不回传

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
