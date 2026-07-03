from datetime import datetime
from pydantic import BaseModel, Field


class ConnectionBase(BaseModel):
    name: str
    type: str = Field(..., pattern="^(pg|mysql|mongo|redis|sqlite)$")
    host: str | None = None
    port: int | None = None
    db_name: str | None = None
    username: str | None = None
    password: str | None = None
    extra: dict | None = None


class ConnectionCreate(ConnectionBase):
    pass


class ConnectionUpdate(ConnectionBase):
    name: str | None = None
    type: str | None = Field(None, pattern="^(pg|mysql|mongo|redis|sqlite)$")


class ConnectionOut(BaseModel):
    id: int
    name: str
    type: str
    host: str | None
    port: int | None
    db_name: str | None
    username: str | None
    extra: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
