from __future__ import annotations
import json
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, NotificationConfig
from app.core.crypto import Crypto


def _send_email(cfg: NotificationConfig, subject: str, body: str) -> None:
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
            server.login(cfg.smtp_user, cfg.smtp_password_enc or "")
        server.sendmail(cfg.smtp_from, recipients, msg.as_string())
    finally:
        server.quit()


def _wechat_token(corp_id: str, secret: str) -> str:
    url = (f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
           f"corpid={urllib.parse.quote(corp_id)}&corpsecret={urllib.parse.quote(secret)}")
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode"):
        raise RuntimeError(f"企业微信 token 失败: {data}")
    return data["access_token"]


def _send_wechat(cfg: NotificationConfig, content: str) -> None:
    token = _wechat_token(cfg.wechat_corp_id, cfg.wechat_secret_enc or "")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = json.dumps({"touser": "@all", "msgtype": "text",
                       "agentid": int(cfg.wechat_agent_id), "text": {"content": content}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode"):
        raise RuntimeError(f"企业微信发送失败: {data}")


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

    sent = {"email": False, "wechat": False}
    if cfg.email_enabled:
        try:
            # 解出 SMTP 密码附到 cfg(发送函数读 _enc 字段——此处先解密回填,避免改 _send_email 签名)
            if cfg.smtp_password_enc:
                # 用临时属性传明文密码:_send_email 读 smtp_password_enc,故直接解密覆写
                cfg.smtp_password_enc = crypto.decrypt(cfg.smtp_password_enc)
            _send_email(cfg, subject, body)
            sent["email"] = True
        except Exception:
            sent["email"] = False
    if cfg.wechat_enabled:
        try:
            if cfg.wechat_secret_enc:
                cfg.wechat_secret_enc = crypto.decrypt(cfg.wechat_secret_enc)
            _send_wechat(cfg, body)
            sent["wechat"] = True
        except Exception:
            sent["wechat"] = False
    return sent
