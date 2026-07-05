from __future__ import annotations
import json
import smtplib
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
    return sent
