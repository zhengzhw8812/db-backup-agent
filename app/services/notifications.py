from __future__ import annotations
import json
import base64
import hashlib
import hmac as hmac_mod
import json as _json
import smtplib
import urllib.parse
import urllib.request
import time
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, NotificationConfig
from app.core.crypto import Crypto


# 企业微信 access_token 进程级缓存:corp_id -> (token, 过期 epoch)。
# 避免每次发送都重新拉取 token(额外往返 + 触发频率限制)。
_wechat_token_cache: dict[str, tuple[str, float]] = {}
_TOKEN_REFRESH_MARGIN = 300  # 提前 5 分钟视为过期,留刷新余量


def _send_email(cfg: NotificationConfig, subject: str, body: str, password: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_from or ""
    recipients = [r.strip() for r in (cfg.recipients or "").split(",") if r.strip()]
    msg["To"] = ", ".join(recipients)
    if cfg.smtp_ssl:
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        if cfg.smtp_starttls:
            server.starttls()
    try:
        if cfg.smtp_user:
            server.login(cfg.smtp_user, password or "")
        server.sendmail(cfg.smtp_from, recipients, msg.as_string())
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


def _send_wechat(cfg: NotificationConfig, content: str, secret: str) -> None:
    token = _wechat_token(cfg.wechat_corp_id, secret or "")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = json.dumps({"touser": "@all", "msgtype": "text",
                       "agentid": int(cfg.wechat_agent_id), "text": {"content": content}}).encode()
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
        req = urllib.request.Request(url, data=_json.dumps(json_body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}")


def _send_feishu(cfg: NotificationConfig, content: str, crypto: Crypto) -> None:
    """飞书自定义机器人:文本消息;配置了加签密钥时附 timestamp+sign。失败抛异常。"""
    webhook = crypto.decrypt(cfg.feishu_webhook_enc)
    payload: dict = {"msg_type": "text", "content": {"text": content}}
    if cfg.feishu_secret_enc:
        secret = crypto.decrypt(cfg.feishu_secret_enc)
        timestamp = str(int(__import__("time").time()))
        sign = base64.b64encode(
            hmac_mod.new(f"{timestamp}\n{secret}".encode(), b"", hashlib.sha256).digest()
        ).decode()
        payload["timestamp"] = timestamp
        payload["sign"] = sign
    _http_post(webhook, json_body=payload)


def _send_serverchan(cfg: NotificationConfig, title: str, content: str, crypto: Crypto) -> None:
    """Server酱 Turbo:推送到个人微信。失败抛异常。"""
    key = crypto.decrypt(cfg.serverchan_sendkey_enc)
    _http_post(f"https://sctapi.ftqq.com/{key}.send", form={"title": title, "desp": content})


def notify_backup_result(db: Session, crypto: Crypto, conn: DbConnection, record: BackupRecord) -> dict:
    """按配置发送备份结果通知。无配置/相应开关关闭 → 跳过。邮件与微信独立 try/except。"""
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        return {"email": False, "wechat": False}
    success = record.status == "success"
    if success and not cfg.notify_on_success:
        return {"email": False, "wechat": False}
    if not success and not cfg.notify_on_failure:
        return {"email": False, "wechat": False}

    tag = "成功" if success else "失败"
    subject = f"[备份{tag}] {conn.name}"
    body = (f"数据库:{conn.name} ({conn.type})\n状态:{record.status}\n"
            f"耗时:{record.duration_ms if record.duration_ms is not None else '-'} ms\n"
            f"错误:{record.error or '无'}")

    sent = {"email": False, "wechat": False, "feishu": False, "serverchan": False}
    if cfg.email_enabled:
        try:
            # 解密到局部变量传入,绝不回写到 ORM *_enc 列(否则一旦 commit 会把明文落库)
            pw = crypto.decrypt(cfg.smtp_password_enc) if cfg.smtp_password_enc else ""
            _send_email(cfg, subject, body, pw)
            sent["email"] = True
        except Exception:
            sent["email"] = False
    if cfg.wechat_enabled:
        try:
            secret = crypto.decrypt(cfg.wechat_secret_enc) if cfg.wechat_secret_enc else ""
            _send_wechat(cfg, body, secret)
            sent["wechat"] = True
        except Exception:
            sent["wechat"] = False
    _send_extras(cfg, crypto, sent, title=subject, content=body)
    return sent


def _send_extras(cfg: NotificationConfig, crypto: Crypto, sent: dict, *, title: str, content: str) -> None:
    """飞书与 Server酱 渠道循环(供 notify_backup_result / notify_generic 共用)。"""
    if cfg.feishu_enabled:
        try:
            _send_feishu(cfg, content, crypto)
            sent["feishu"] = True
        except Exception:
            sent["feishu"] = False
    if cfg.serverchan_enabled:
        try:
            _send_serverchan(cfg, title, content, crypto)
            sent["serverchan"] = True
        except Exception:
            sent["serverchan"] = False


def notify_generic(db: Session, crypto: Crypto, *, kind: str, subject: str, content: str) -> dict:
    """通用通知(看门狗失联告警等)。kind 决定开关列:watchdog→notify_watchdog,
    failure→notify_on_failure。渠道独立 try/except,绝不抛出。"""
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        return {"email": False, "wechat": False}
    toggle = {"watchdog": cfg.notify_watchdog, "failure": cfg.notify_on_failure}.get(kind, True)
    if not toggle:
        return {"email": False, "wechat": False}
    sent = {"email": False, "wechat": False, "feishu": False, "serverchan": False}
    if cfg.email_enabled:
        try:
            pw = crypto.decrypt(cfg.smtp_password_enc) if cfg.smtp_password_enc else ""
            _send_email(cfg, subject, content, pw)
            sent["email"] = True
        except Exception:
            pass
    if cfg.wechat_enabled:
        try:
            secret = crypto.decrypt(cfg.wechat_secret_enc) if cfg.wechat_secret_enc else ""
            _send_wechat(cfg, content, secret)
            sent["wechat"] = True
        except Exception:
            pass
    _send_extras(cfg, crypto, sent, title=subject, content=content)
    return sent
