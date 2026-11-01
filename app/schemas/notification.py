from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NotificationGlobal(BaseModel):
    """全局通知开关(notification_config 仅保留这三列,渠道配置在 channels)。"""
    notify_on_success: bool = True
    notify_on_failure: bool = True
    notify_watchdog: bool = True


class NotificationChannelIn(BaseModel):
    """创建/更新通知渠道。config 为该类型非敏感配置;secret 仅写入、永不回传,
    更新时留空(None)表示保留已存密文。"""
    type: Literal["email", "wechat", "feishu", "serverchan"]
    name: str = Field(min_length=1, max_length=50)
    enabled: bool = True
    config: dict = {}
    secret: dict | None = None


class NotificationChannelOut(BaseModel):
    id: int
    type: str
    name: str
    enabled: bool
    config: dict = {}
    created_at: datetime


class VerifySettings(BaseModel):
    auto_enabled: bool = False
