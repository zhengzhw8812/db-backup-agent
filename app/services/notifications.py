"""通知发送:遍历启用的通知渠道(同渠道可多条/多账号),逐渠道独立 try/except。

渠道配置存 notification_channels(config_json 非敏感 + secret_enc 整包 Fernet);
notification_config 仅保留全局开关(成功/失败/失联)。"""
from __future__ import annotations
import base64
import hashlib
import hmac as hmac_mod
import json
import smtplib
import time
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, NotificationConfig, NotificationChannel
from app.core.crypto import Crypto


# 企业微信 access_token 进程级缓存:corp_id -> (token, 过期 epoch)。
# 避免每次发送都重新拉取 token(额外往返 + 触发频率限制)。
_wechat_token_cache: dict[str, tuple[str, float]] = {}
_TOKEN_REFRESH_MARGIN = 300  # 提前 5 分钟视为过期,留刷新余量


def _send_email(config: dict, subject: str, body: str, password: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = config.get("smtp_from") or ""
    recipients = [r.strip() for r in (config.get("recipients") or "").split(",") if r.strip()]
    msg["To"] = ", ".join(recipients)
    if config.get("smtp_ssl"):
        server = smtplib.SMTP_SSL(config.get("smtp_host"), int(config.get("smtp_port") or 25), timeout=30)
    else:
        server = smtplib.SMTP(config.get("smtp_host"), int(config.get("smtp_port") or 25), timeout=30)
        if config.get("smtp_starttls"):
            server.starttls()
    try:
        if config.get("smtp_user"):
            server.login(config["smtp_user"], password or "")
        server.sendmail(config.get("smtp_from") or "", recipients, msg.as_string())
    finally:
        server.quit()


def _wechat_token(corp_id: str, secret: str) -> str:
    now = time.time()
    cached = _wechat_token_cache.get(corp_id)
    if cached and cached[1] > now + _TOKEN_REFRESH_MARGIN:
        return cached[0]
    url = (f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
           f"corpid={urllib.parse.quote(corp_id)}&corpsecret={urllib.parse.quote(secret)}")
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode"):
        raise RuntimeError(f"企业微信 token 失败: {data}")
    token = data["access_token"]
    expires_in = int(data.get("expires_in", 7200) or 7200)
    _wechat_token_cache[corp_id] = (token, now + expires_in)
    return token


def _send_wechat(config: dict, content: str, secret: str) -> None:
    token = _wechat_token(config["corp_id"], secret or "")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = json.dumps({"touser": "@all", "msgtype": "text",
                       "agentid": int(config["agent_id"]), "text": {"content": content}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode"):
        raise RuntimeError(f"企业微信发送失败: {data}")


def _http_post(url: str, *, json_body: dict | None = None, form: dict | None = None) -> None:
    """标准库 HTTP POST(json 或表单),非 2xx 抛异常。避免为两个通知渠道引入 requests 依赖。"""
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(url, data=data)
    else:
        req = urllib.request.Request(url, data=json.dumps(json_body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}")


def _send_feishu(secret: dict, content: str) -> None:
    """飞书自定义机器人:文本消息;配置了加签密钥时附 timestamp+sign。失败抛异常。"""
    webhook = secret["webhook"]
    payload: dict = {"msg_type": "text", "content": {"text": content}}
    if secret.get("sign"):
        timestamp = str(int(time.time()))
        sign = base64.b64encode(
            hmac_mod.new(f"{timestamp}\n{secret['sign']}".encode(), b"", hashlib.sha256).digest()
        ).decode()
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    _http_post(webhook, json_body=payload)


def _send_serverchan(secret: dict, title: str, content: str) -> None:
    """Server酱 Turbo:推送到个人微信。失败抛异常。"""
    _http_post(f"https://sctapi.ftqq.com/{secret['sendkey']}.send", form={"title": title, "desp": content})


def _channel_secret(ch: NotificationChannel, crypto: Crypto) -> dict:
    """解密渠道敏感值;无密文返回空 dict。解密到局部,绝不回写 ORM 列。"""
    if not ch.secret_enc:
        return {}
    return json.loads(crypto.decrypt(ch.secret_enc))


def _send_by_channel(ch: NotificationChannel, crypto: Crypto, *, title: str, content: str) -> None:
    """按渠道类型分派发送;失败抛异常,由调用方捕获记 ok=False。"""
    secret = _channel_secret(ch, crypto)
    config = json.loads(ch.config_json or "{}")
    if ch.type == "email":
        _send_email(config, title, content, secret.get("password", ""))
    elif ch.type == "wechat":
        _send_wechat(config, content, secret.get("secret", ""))
    elif ch.type == "feishu":
        _send_feishu(secret, content)
    elif ch.type == "serverchan":
        _send_serverchan(secret, title, content)
    else:
        raise ValueError(f"未知通知渠道类型:{ch.type}")


def _notify_all(db: Session, crypto: Crypto, *, title: str, content: str) -> list[dict]:
    """向所有启用渠道发送,逐渠道独立 try/except。返回 [{channel_id,name,type,ok}]。"""
    out = []
    channels = db.query(NotificationChannel).filter(NotificationChannel.enabled.is_(True)).all()
    for ch in channels:
        try:
            _send_by_channel(ch, crypto, title=title, content=content)
            ok = True
        except Exception:
            ok = False
        out.append({"channel_id": ch.id, "name": ch.name, "type": ch.type, "ok": ok})
    return out


def notify_backup_result(db: Session, crypto: Crypto, conn: DbConnection, record: BackupRecord) -> list[dict]:
    """按全局开关发送备份结果通知到所有启用渠道。无渠道 → 空列表。"""
    cfg = db.query(NotificationConfig).first()
    success = record.status == "success"
    if cfg is not None:
        if success and not cfg.notify_on_success:
            return []
        if not success and not cfg.notify_on_failure:
            return []

    tag = "成功" if success else "失败"
    subject = f"[备份{tag}] {conn.name}"
    body = (f"数据库:{conn.name} ({conn.type})\n状态:{record.status}\n"
            f"耗时:{record.duration_ms if record.duration_ms is not None else '-'} ms\n"
            f"错误:{record.error or '无'}")
    return _notify_all(db, crypto, title=subject, content=body)


def notify_generic(db: Session, crypto: Crypto, *, kind: str, subject: str, content: str) -> list[dict]:
    """通用通知(看门狗失联告警等)。kind 决定开关列:watchdog→notify_watchdog,
    failure→notify_on_failure。渠道独立 try/except,绝不抛出。"""
    cfg = db.query(NotificationConfig).first()
    if cfg is not None:
        toggle = {"watchdog": cfg.notify_watchdog, "failure": cfg.notify_on_failure}.get(kind, True)
        if not toggle:
            return []
    return _notify_all(db, crypto, title=subject, content=content)
