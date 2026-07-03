from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class SystemLogOut(BaseModel):
    id: int
    level: str
    source: str
    message: str
    context: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}
