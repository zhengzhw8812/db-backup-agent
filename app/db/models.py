from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, BigInteger, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class DbConnection(Base):
    __tablename__ = "db_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # pg/mysql/mongo/redis/sqlite
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    db_names: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 数组,如 ["app","logs"];PG 多选
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet 密文
    extra: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 字符串
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    schedules: Mapped[list["Schedule"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    connection: Mapped["DbConnection"] = relationship(back_populates="schedules")
    __table_args__ = (
        Index("ix_schedules_connection_id", "connection_id"),
        Index("ix_schedules_enabled", "enabled"),
    )


class BackupRecord(Base):
    __tablename__ = "backup_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    __table_args__ = (
        Index("ix_backup_records_status", "status"),
        Index("ix_backup_records_connection_id", "connection_id"),
        Index("ix_backup_records_started_at", "started_at"),
    )
    connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # manual/scheduled
    db_name: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 本记录备份的具体库;MySQL 全库/旧记录为 NULL
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # running/success/failed/cancelled
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (Index("ix_system_logs_created_at", "created_at"),)


class RestoreRecord(Base):
    __tablename__ = "restore_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backup_record_id: Mapped[int] = mapped_column(ForeignKey("backup_records.id", ondelete="CASCADE"), nullable=False)
    target_connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # running/success/failed/cancelled
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CloudDestination(Base):
    __tablename__ = "cloud_destinations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)   # s3
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)  # host:port
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    access_key_enc: Mapped[str] = mapped_column(Text, nullable=False)   # Fernet 密文
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)       # Fernet 密文
    prefix: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    secure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SyncTarget(Base):
    __tablename__ = "sync_targets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    cloud_destination_id: Mapped[int] = mapped_column(ForeignKey("cloud_destinations.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (
        UniqueConstraint("connection_id", "cloud_destination_id", name="uq_sync_target"),
    )


class NotificationConfig(Base):
    __tablename__ = "notification_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_ssl: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smtp_starttls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smtp_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)   # Fernet
    smtp_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipients: Mapped[str | None] = mapped_column(Text, nullable=True)           # 逗号分隔
    wechat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wechat_corp_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wechat_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wechat_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)    # Fernet
    notify_on_success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
