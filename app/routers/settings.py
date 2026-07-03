from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import NotificationConfig
from app.deps import get_current_account
from app.schemas.notification import NotificationSettings, NotificationSettingsOut

router = APIRouter()


def _to_out(cfg: NotificationConfig) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        email_enabled=cfg.email_enabled, smtp_host=cfg.smtp_host, smtp_port=cfg.smtp_port,
        smtp_ssl=cfg.smtp_ssl, smtp_starttls=cfg.smtp_starttls, smtp_user=cfg.smtp_user,
        smtp_from=cfg.smtp_from, recipients=cfg.recipients,
        wechat_enabled=cfg.wechat_enabled, wechat_corp_id=cfg.wechat_corp_id,
        wechat_agent_id=cfg.wechat_agent_id, notify_on_success=cfg.notify_on_success,
        notify_on_failure=cfg.notify_on_failure, created_at=cfg.created_at,
    )


@router.get("/settings/notifications", response_model=NotificationSettingsOut)
def get_notifications(db: Session = Depends(get_db), _=Depends(get_current_account)):
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        cfg = NotificationConfig()
        db.add(cfg); db.commit(); db.refresh(cfg)
    return _to_out(cfg)


@router.put("/settings/notifications", response_model=NotificationSettingsOut)
def put_notifications(payload: NotificationSettings, request: Request,
                      db: Session = Depends(get_db), _=Depends(get_current_account)):
    crypto = request.app.state.crypto
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        cfg = NotificationConfig()
        db.add(cfg)
    cfg.email_enabled = payload.email_enabled
    cfg.smtp_host = payload.smtp_host
    cfg.smtp_port = payload.smtp_port
    cfg.smtp_ssl = payload.smtp_ssl
    cfg.smtp_starttls = payload.smtp_starttls
    cfg.smtp_user = payload.smtp_user
    cfg.smtp_from = payload.smtp_from
    cfg.recipients = payload.recipients
    cfg.wechat_enabled = payload.wechat_enabled
    cfg.wechat_corp_id = payload.wechat_corp_id
    cfg.wechat_agent_id = payload.wechat_agent_id
    cfg.notify_on_success = payload.notify_on_success
    cfg.notify_on_failure = payload.notify_on_failure
    # 凭据:非空才更新(避免空串覆盖已存密文)
    if payload.smtp_password:
        cfg.smtp_password_enc = crypto.encrypt(payload.smtp_password)
    if payload.wechat_secret:
        cfg.wechat_secret_enc = crypto.encrypt(payload.wechat_secret)
    db.commit(); db.refresh(cfg)
    return _to_out(cfg)
