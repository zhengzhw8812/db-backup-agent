"""应用配置库本地自备份:VACUUM INTO 一致性快照 → gzip → 保留最新 N 份。"""
from __future__ import annotations
import gzip
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.clock import utcnow

NAME_RE = re.compile(r"^app-\d{8}-\d{6}\.db\.gz$")   # .db.gz 快照白名单
SQL_RE = re.compile(r"^app-\d{8}-\d{6}\.sql$")         # .sql 导出白名单
KEEP = 7


def self_backup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "selfbackup"


def export_sql_dump(data_dir: Path, keep: int = KEEP, db: Session | None = None) -> Path:
    """导出配置库为纯文本 SQL(iterdump:建表+数据+自增序列),保留最近 keep 份。"""
    data_dir = Path(data_dir)
    live = data_dir / "sqlite" / "app.db"
    sdir = self_backup_dir(data_dir)
    sdir.mkdir(parents=True, exist_ok=True)

    name = f"app-{utcnow().strftime('%Y%m%d-%H%M%S')}.sql"
    out = sdir / name
    try:
        import sqlite3 as _sq

        conn = _sq.connect(live)
        try:
            lines = list(conn.iterdump())
        finally:
            conn.close()
        out.write_text("\n".join(lines) + "\n")
    except Exception as exc:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        if db is not None:
            db.add(SystemLogRow(level="error", source="selfbackup",
                                message=f"SQL 导出失败:{exc}"))
            db.commit()
        raise

    _rotate(sdir, keep)
    if db is not None:
        db.add(SystemLogRow(level="info", source="selfbackup",
                            message=f"SQL 导出完成:{name}({out.stat().st_size} 字节)"))
        db.commit()
    return out


def _rotate(sdir: Path, keep: int) -> None:
    # .db.gz 与 .sql 各自独立保留 keep 份
    for pattern in ("app-*.db.gz", "app-*.sql"):
        files = sorted(sdir.glob(pattern))
        for old in files[:-keep] if len(files) > keep else []:
            old.unlink(missing_ok=True)


def run_self_backup(data_dir: Path, keep: int = KEEP, db: Session | None = None) -> Path:
    """生成配置库快照并轮转保留。db 传入时写 SystemLog(info/error)。失败抛异常。"""
    data_dir = Path(data_dir)
    live = data_dir / "sqlite" / "app.db"
    sdir = self_backup_dir(data_dir)
    sdir.mkdir(parents=True, exist_ok=True)

    name = f"app-{utcnow().strftime('%Y%m%d-%H%M%S')}.db.gz"
    out = sdir / name
    tmp_sqlite = sdir / f".snapshot-{name}.db"
    try:
        # VACUUM INTO:在线一致性快照(WAL 下安全),比文件拷贝可靠
        import sqlite3 as _sq

        conn = _sq.connect(live)
        conn.execute(f"VACUUM INTO '{tmp_sqlite}'", )
        conn.close()
        with open(tmp_sqlite, "rb") as fin, gzip.open(out, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
    except Exception as exc:
        try:
            tmp_sqlite.unlink(missing_ok=True)
            out.unlink(missing_ok=True)
        except OSError:
            pass
        if db is not None:
            db.add(SystemLogRow(level="error", source="selfbackup",
                                message=f"配置库自备份失败:{exc}"))
            db.commit()
        raise
    finally:
        try:
            tmp_sqlite.unlink(missing_ok=True)
        except OSError:
            pass

    _rotate(sdir, keep)
    if db is not None:
        db.add(SystemLogRow(level="info", source="selfbackup",
                            message=f"配置库自备份完成:{name}({out.stat().st_size} 字节)"))
        db.commit()
    return out


def list_snapshots(data_dir: Path) -> list[dict]:
    sdir = self_backup_dir(data_dir)
    if not sdir.exists():
        return []
    out = []
    for f in sorted(sdir.glob("app-*"), reverse=True):
        m = re.match(r"^app-(\d{8})-(\d{6})\.(db\.gz|sql)$", f.name)
        if not m:
            continue
        out.append({
            "name": f.name,
            "kind": "sql" if m.group(3) == "sql" else "gz",
            "size": f.stat().st_size,
            "created_at": datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=None).isoformat(),
        })
    return out


def SystemLogRow(*, level: str, source: str, message: str):
    from app.db.models import SystemLog
    return SystemLog(level=level, source=source, message=message)
