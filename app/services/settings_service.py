"""app_settings KV 的读写(JSON 序列化)。"""
from __future__ import annotations
import json

from sqlalchemy.orm import Session

from app.db.models import AppSetting


def get_setting(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    return json.loads(row.value) if row is not None else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(AppSetting, key)
    payload = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(AppSetting(key=key, value=payload))
    else:
        row.value = payload
    db.commit()
