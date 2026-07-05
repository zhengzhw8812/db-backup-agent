from __future__ import annotations
import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import BackupRecord, RestoreRecord, DbConnection

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
        rec.finished_at = datetime.utcnow()
        count += 1
    for rec in db.query(RestoreRecord).filter(RestoreRecord.status == "running").all():
        rec.status = "failed"
        rec.error = _STALE_MSG
        rec.finished_at = datetime.utcnow()
        count += 1
    if count:
        db.commit()
    return count
