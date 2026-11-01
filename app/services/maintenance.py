from __future__ import annotations
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import BackupRecord, RestoreRecord, DbConnection, SystemLog
from app.core.clock import utcnow

_STALE_MSG = "进程重启时仍为 running(判定为异常终止)"


def _ensure_column(db: Session, table: str, column: str, ddl: str) -> None:
    """SQLite 的 create_all 不会给已存在的表加列;用 PRAGMA 探测后补 ALTER。"""
    cols = [row[1] for row in db.execute(text(f"PRAGMA table_info({table})"))]
    if column not in cols:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        db.commit()


def _backfill_db_names(db: Session) -> None:
    """旧连接(只有 db_name)回填 db_names=['<db_name>'];幂等。"""
    touched = 0
    for c in db.query(DbConnection).all():
        if not c.db_names and c.db_name:
            c.db_names = json.dumps([c.db_name])
            touched += 1
    if touched:
        db.commit()


def _backfill_record_db_names(db: Session) -> None:
    """旧备份记录(db_name 为 NULL)回填为其连接的 db_name(旧连接都是单库)。
    MySQL 全库 / 无 db_name 连接保持 NULL(前端显示「全部」即正确)。"""
    touched = 0
    for rec in db.query(BackupRecord).filter(BackupRecord.db_name.is_(None)).all():
        conn = db.get(DbConnection, rec.connection_id)
        if conn and conn.db_name:
            rec.db_name = conn.db_name
            touched += 1
    if touched:
        db.commit()


def migrate_schema(db: Session) -> None:
    """启动时补齐 db_connections.db_names / backup_records.db_name 两列并回填。"""
    _ensure_column(db, "db_connections", "db_names", "TEXT")
    _ensure_column(db, "backup_records", "db_name", "TEXT")
    _ensure_column(db, "backup_records", "verify_status", "TEXT")
    _ensure_column(db, "backup_records", "verified_at", "DATETIME")
    _ensure_column(db, "backup_records", "verify_error", "TEXT")
    _ensure_column(db, "backup_records", "db_names", "TEXT")
    _ensure_column(db, "notification_config", "notify_watchdog", "BOOLEAN NOT NULL DEFAULT 1")
    _ensure_column(db, "cloud_destinations", "mount_config", "TEXT")
    _ensure_column(db, "cloud_destinations", "mount_password_enc", "TEXT")
    _ensure_column(db, "notification_config", "feishu_enabled", "BOOLEAN NOT NULL DEFAULT 0")
    _ensure_column(db, "notification_config", "feishu_webhook_enc", "TEXT")
    _ensure_column(db, "notification_config", "feishu_secret_enc", "TEXT")
    _ensure_column(db, "notification_config", "serverchan_enabled", "BOOLEAN NOT NULL DEFAULT 0")
    _ensure_column(db, "notification_config", "serverchan_sendkey_enc", "TEXT")
    _backfill_db_names(db)
    _backfill_record_db_names(db)


def reap_stale_running(db: Session) -> int:
    """启动时把残留的 running 备份/恢复记录标记为 failed,避免永久占位与幽灵任务。

    正常情况下进程退出前会把终态写回;若崩溃/被杀,这些行会永远停在 running,
    污染 /jobs、dashboard 计数,并挡住互斥锁。启动时一次性清理。"""
    count = 0
    for rec in db.query(BackupRecord).filter(BackupRecord.status == "running").all():
        rec.status = "failed"
        rec.error = _STALE_MSG
        rec.finished_at = utcnow()
        count += 1
    for rec in db.query(RestoreRecord).filter(RestoreRecord.status == "running").all():
        rec.status = "failed"
        rec.error = _STALE_MSG
        rec.finished_at = utcnow()
        count += 1
    if count:
        db.commit()
    return count


def migrate_notification_channels(db: Session, crypto) -> int:
    """旧 notification_config 渠道字段一次性迁移为 notification_channels 行。

    以 app_settings 标记 notification_channels_migrated 防复活:标记存在则永不重跑
    (否则用户删光渠道后重启会被旧配置重建)。仅迁移旧配置中**已启用**的渠道;
    填了凭据但未启用的视为用户主动关闭,不迁。返回生成行数。"""
    from app.db.models import NotificationConfig, NotificationChannel
    from app.services.settings_service import get_setting, set_setting

    if get_setting(db, "notification_channels_migrated"):
        return 0
    cfg = db.query(NotificationConfig).first()

    def _secret_enc(secret: dict) -> str:
        return crypto.encrypt(json.dumps(secret, ensure_ascii=False))

    def _plain(enc) -> str | None:
        if not enc:
            return None
        try:
            return crypto.decrypt(enc)
        except Exception:
            # 密文损坏/密钥轮换过:按"无该凭据"处理,迁移绝不阻断启动
            db.add(SystemLog(level="warning", source="selfbackup",
                             message="通知配置迁移:旧凭据解密失败,按未配置处理"))
            db.commit()
            return None

    created = 0
    if cfg is not None:
        if cfg.email_enabled:
            secret = {"password": p} if (p := _plain(cfg.smtp_password_enc)) else None
            db.add(NotificationChannel(
                type="email", name="邮箱", enabled=True,
                config_json=json.dumps({
                    "smtp_host": cfg.smtp_host, "smtp_port": cfg.smtp_port,
                    "smtp_ssl": cfg.smtp_ssl, "smtp_starttls": cfg.smtp_starttls,
                    "smtp_user": cfg.smtp_user, "smtp_from": cfg.smtp_from,
                    "recipients": cfg.recipients}, ensure_ascii=False),
                secret_enc=_secret_enc(secret) if secret else None))
            created += 1
        if cfg.wechat_enabled:
            secret = {"secret": s} if (s := _plain(cfg.wechat_secret_enc)) else None
            db.add(NotificationChannel(
                type="wechat", name="企业微信", enabled=True,
                config_json=json.dumps({"corp_id": cfg.wechat_corp_id,
                                        "agent_id": cfg.wechat_agent_id}, ensure_ascii=False),
                secret_enc=_secret_enc(secret) if secret else None))
            created += 1
        if cfg.feishu_enabled:
            secret: dict = {}
            if (w := _plain(cfg.feishu_webhook_enc)):
                secret["webhook"] = w
            if (sg := _plain(cfg.feishu_secret_enc)):
                secret["sign"] = sg
            db.add(NotificationChannel(
                type="feishu", name="飞书", enabled=True, config_json="{}",
                secret_enc=_secret_enc(secret) if secret else None))
            created += 1
        if cfg.serverchan_enabled:
            secret = {"sendkey": k} if (k := _plain(cfg.serverchan_sendkey_enc)) else None
            db.add(NotificationChannel(
                type="serverchan", name="Server酱", enabled=True, config_json="{}",
                secret_enc=_secret_enc(secret) if secret else None))
            created += 1
        if created:
            db.commit()
    set_setting(db, "notification_channels_migrated", True)
    return created
