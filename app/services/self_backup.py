"""应用配置库本地自备份:VACUUM INTO 一致性快照 → gzip → 保留最新 N 份。"""
from __future__ import annotations
import gzip
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.clock import utcnow

NAME_RE = re.compile(r"^app-\d{8}-\d{6}\.db\.gz$")  # 下载白名单(防穿越)
KEEP = 7


def self_backup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "selfbackup"


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


def _rotate(sdir: Path, keep: int) -> None:
    files = sorted(sdir.glob("app-*.db.gz"))
    for old in files[:-keep] if len(files) > keep else []:
        old.unlink(missing_ok=True)


def list_snapshots(data_dir: Path) -> list[dict]:
    sdir = self_backup_dir(data_dir)
    if not sdir.exists():
        return []
    out = []
    for f in sorted(sdir.glob("app-*.db.gz"), reverse=True):
        m = re.match(r"^app-(\d{8})-(\d{6})\.db\.gz$", f.name)
        if not m:
            continue
        out.append({
            "name": f.name,
            "size": f.stat().st_size,
            "created_at": datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=None).isoformat(),
        })
    return out


def SystemLogRow(*, level: str, source: str, message: str):
    from app.db.models import SystemLog
    return SystemLog(level=level, source=source, message=message)
