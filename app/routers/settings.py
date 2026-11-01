from __future__ import annotations
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import NotificationConfig, NotificationChannel
from app.deps import get_current_account
from app.schemas.notification import (
    NotificationGlobal, NotificationChannelIn, NotificationChannelOut, VerifySettings,
)
from app.services.settings_service import get_setting, set_setting

router = APIRouter()


def _global_out(cfg: NotificationConfig | None) -> NotificationGlobal:
    if cfg is None:
        return NotificationGlobal()  # 只读返回默认,不在 GET 里建行
    return NotificationGlobal(notify_on_success=cfg.notify_on_success,
                              notify_on_failure=cfg.notify_on_failure,
                              notify_watchdog=cfg.notify_watchdog)


@router.get("/settings/notifications", response_model=NotificationGlobal)
def get_notifications(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _global_out(db.query(NotificationConfig).first())


@router.put("/settings/notifications", response_model=NotificationGlobal)
def put_notifications(payload: NotificationGlobal,
                      db: Session = Depends(get_db), _=Depends(get_current_account)):
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        cfg = NotificationConfig()
        db.add(cfg)
    cfg.notify_on_success = payload.notify_on_success
    cfg.notify_on_failure = payload.notify_on_failure
    cfg.notify_watchdog = payload.notify_watchdog
    db.commit(); db.refresh(cfg)
    return _global_out(cfg)


def _channel_out(ch: NotificationChannel) -> NotificationChannelOut:
    return NotificationChannelOut(id=ch.id, type=ch.type, name=ch.name, enabled=ch.enabled,
                                  config=json.loads(ch.config_json or "{}"),
                                  created_at=ch.created_at)


def _validate_channel_payload(payload: NotificationChannelIn, *, creating: bool) -> None:
    """按类型校验必填项;创建时密钥类渠道必须首次提供 secret。违例 → 422。"""
    cfg, secret = payload.config, payload.secret or {}
    if payload.type == "email":
        if not cfg.get("smtp_host") or not cfg.get("recipients"):
            raise HTTPException(status_code=422,
                                detail="email 渠道必填 config.smtp_host 与 config.recipients")
    elif payload.type == "wechat":
        if not cfg.get("corp_id") or not cfg.get("agent_id"):
            raise HTTPException(status_code=422,
                                detail="wechat 渠道必填 config.corp_id 与 config.agent_id")
    elif payload.type == "feishu":
        if creating and not secret.get("webhook"):
            raise HTTPException(status_code=422, detail="feishu 渠道创建时必填 secret.webhook")
    elif payload.type == "serverchan":
        if creating and not secret.get("sendkey"):
            raise HTTPException(status_code=422, detail="serverchan 渠道创建时必填 secret.sendkey")


@router.get("/settings/notification-channels", response_model=list[NotificationChannelOut])
def list_channels(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return [_channel_out(ch)
            for ch in db.query(NotificationChannel).order_by(NotificationChannel.id).all()]


@router.post("/settings/notification-channels", response_model=NotificationChannelOut, status_code=201)
def create_channel(payload: NotificationChannelIn, request: Request,
                   db: Session = Depends(get_db), _=Depends(get_current_account)):
    _validate_channel_payload(payload, creating=True)
    ch = NotificationChannel(
        type=payload.type, name=payload.name, enabled=payload.enabled,
        config_json=json.dumps(payload.config, ensure_ascii=False))
    if payload.secret is not None:
        ch.secret_enc = request.app.state.crypto.encrypt(
            json.dumps(payload.secret, ensure_ascii=False))
    db.add(ch); db.commit(); db.refresh(ch)
    return _channel_out(ch)


@router.put("/settings/notification-channels/{channel_id}", response_model=NotificationChannelOut)
def update_channel(channel_id: int, payload: NotificationChannelIn, request: Request,
                   db: Session = Depends(get_db), _=Depends(get_current_account)):
    ch = db.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    _validate_channel_payload(payload, creating=False)
    ch.type = payload.type
    ch.name = payload.name
    ch.enabled = payload.enabled
    ch.config_json = json.dumps(payload.config, ensure_ascii=False)
    # 凭据:提供 secret 才更新(None 保留已存密文,不清空)
    if payload.secret is not None:
        ch.secret_enc = request.app.state.crypto.encrypt(
            json.dumps(payload.secret, ensure_ascii=False))
    db.commit(); db.refresh(ch)
    return _channel_out(ch)


@router.delete("/settings/notification-channels/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    ch = db.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    db.delete(ch); db.commit()
    return {"deleted": channel_id}


@router.post("/settings/notification-channels/{channel_id}/test")
def test_channel(channel_id: int, request: Request,
                 db: Session = Depends(get_db), _=Depends(get_current_account)):
    """向单个渠道发一条测试消息。失败 → 400(带渠道名与错误)。"""
    from app.services.notifications import _send_by_channel

    ch = db.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    subject, body = "[测试] db-backup-agent", "这是一条测试通知,收到即表示渠道配置正确。"
    try:
        _send_by_channel(ch, request.app.state.crypto, title=subject, content=body)
        return {"id": ch.id, "name": ch.name, "type": ch.type, "ok": True, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{ch.name} 发送失败:{exc}")


@router.get("/settings/verify", response_model=VerifySettings)
def get_verify_settings(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return VerifySettings(auto_enabled=bool(get_setting(db, "verify_auto_enabled", False)))


@router.put("/settings/verify", response_model=VerifySettings)
def put_verify_settings(payload: VerifySettings, db: Session = Depends(get_db), _=Depends(get_current_account)):
    set_setting(db, "verify_auto_enabled", payload.auto_enabled)
    return VerifySettings(auto_enabled=payload.auto_enabled)


@router.post("/settings/notifications/test")
def test_notifications(request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    """向所有启用渠道各发一条测试消息,逐渠道返回 [{id,name,type,ok,error}]。全部失败 → 400。"""
    from app.services.notifications import _send_by_channel
    from app.db.models import NotificationChannel

    crypto = request.app.state.crypto
    channels = db.query(NotificationChannel).filter(NotificationChannel.enabled.is_(True)).all()
    if not channels:
        raise HTTPException(status_code=400, detail="尚未配置任何通知渠道")
    subject, body = "[测试] db-backup-agent", "这是一条测试通知,收到即表示渠道配置正确。"
    out = []
    for ch in channels:
        try:
            _send_by_channel(ch, crypto, title=subject, content=body)
            out.append({"id": ch.id, "name": ch.name, "type": ch.type, "ok": True, "error": None})
        except Exception as exc:
            out.append({"id": ch.id, "name": ch.name, "type": ch.type, "ok": False, "error": str(exc)})
    if not any(r["ok"] for r in out):
        raise HTTPException(status_code=400, detail=out)
    return out
