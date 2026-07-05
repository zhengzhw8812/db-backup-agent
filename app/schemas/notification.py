from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class NotificationSettings(BaseModel):
    email_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int | None = Field(None, ge=1, le=65535)
    smtp_ssl: bool = False
    smtp_starttls: bool = True
    smtp_user: str | None = None
    smtp_password: str | None = None        # 仅写入;Out 不返回
    smtp_from: str | None = None
    recipients: str | None = None
    wechat_enabled: bool = False
    wechat_corp_id: str | None = None
    wechat_agent_id: str | None = None
    wechat_secret: str | None = None        # 仅写入;Out 不返回
    notify_on_success: bool = True
    notify_on_failure: bool = True


class NotificationSettingsOut(BaseModel):
    email_enabled: bool
    smtp_host: str | None
    smtp_port: int | None
    smtp_ssl: bool
    smtp_starttls: bool
    smtp_user: str | None
    smtp_from: str | None
    recipients: str | None
    wechat_enabled: bool
    wechat_corp_id: str | None
    wechat_agent_id: str | None
    notify_on_success: bool
    notify_on_failure: bool
    created_at: datetime
    # 不含 smtp_password / wechat_secret

    model_config = {"from_attributes": True}
