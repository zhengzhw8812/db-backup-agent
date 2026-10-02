"""应用配置库本地自备份与 SQL 导入还原。

- .db.gz 快照:VACUUM INTO 一致性快照(WAL 安全)→ gzip,保留 7 份;
- .sql 导出:VACUUM INTO 临时快照后 iterdump(保证与并发写隔离的一致性),独立保留 7 份;
- SQL 导入还原:临时库校验核心表 → 暂存 → 容器重启时 maybe_restore 在引擎初始化前
  应用(留底 pre-restore-*.db,保留 3 份);与 worker 进程经 flock 协调。
"""
from __future__ import annotations
import fcntl
import gzip
import os
import re
import shutil
import sqlite3 as _sq
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.clock import utcnow

NAME_RE = re.compile(r"^app-\d{8}-\d{6}\.db\.gz$")   # .db.gz 快照白名单
SQL_RE = re.compile(r"^app-\d{8}-\d{6}\.sql$")        # .sql 导出白名单
KEEP = 7
PRE_RESTORE_KEEP = 3
CORE_TABLES = ("account", "db_connections", "backup_records", "schedules", "notification_config")
PENDING = "sqlite/.restore-pending.sql"
VALIDATE_DEADLINE_SECONDS = 10


def self_backup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "selfbackup"


def SystemLogRow(*, level: str, source: str, message: str):
    from app.db.models import SystemLog

    return SystemLog(level=level, source=source, message=message)


@contextmanager
def restore_lock(data_dir: Path):
    """还原互斥锁:web 的 maybe_restore 持有期间,worker 的启动等待被阻塞。"""
    lock_dir = Path(data_dir) / "sqlite"
    lock_dir.mkdir(parents=True, exist_ok=True)
    f = open(lock_dir / ".restore.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


def wait_for_restore(data_dir: Path, timeout: float = 120.0) -> None:
    """worker 启动时调用:若 web 正在还原则等待其完成(最多 timeout 秒)。"""
    lock_dir = Path(data_dir) / "sqlite"
    lock_dir.mkdir(parents=True, exist_ok=True)
    f = open(lock_dir / ".restore.lock", "w")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break  # 拿到锁 = web 已完成还原(释放)
            except BlockingIOError:
                if time.monotonic() > deadline:
                    break  # 超时放行(还原进程自身有超时保护)
                time.sleep(0.5)
        # 拿到锁后立刻释放(worker 只需要等待,不需要持有)
        fcntl.flock(f, fcntl.LOCK_UN)
    finally:
        f.close()


def _guarded_conn(path: Path, *, read_only: bool = False):
    """带回滚保护(禁 ATTACH/DETACH)与执行时限的 sqlite 连接。"""
    conn = _sq.connect(path) if not read_only else _sq.connect(f"file:{path}?mode=ro", uri=True)
    deadline = time.monotonic() + VALIDATE_DEADLINE_SECONDS

    def _auth(action, arg1, arg2, db_name, trigger):
        # 禁 ATTACH/DETACH:导入脚本不得触碰库外文件(含正在运行的 live 库)
        if action in (_sq.SQLITE_ATTACH, _sq.SQLITE_DETACH):
            return _sq.SQLITE_DENY
        return _sq.SQLITE_OK

    conn.set_authorizer(_auth)

    def _progress():
        return 1 if time.monotonic() > deadline else 0  # 非 0 = 中断语句

    conn.set_progress_handler(_progress, 1000)
    return conn


def _validate_script(sql_text: str, workdir: Path) -> None:
    """在临时空库执行脚本,校验核心表存在。不合法 → ValueError。"""
    probe = workdir / ".probe-restore.db"
    try:
        conn = _guarded_conn(probe)
        try:
            conn.executescript(sql_text)
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()
        missing = [t for t in CORE_TABLES if t not in names]
        if missing:
            raise ValueError(f"缺少核心表,不是有效的配置库备份:缺少 {', '.join(missing)}")
    except ValueError:
        raise
    except _sq.Error as exc:
        raise ValueError(f"SQL 无法在空库执行:{exc}") from exc
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def stage_restore(data_dir: Path, sql_text: str) -> Path:
    """校验 SQL 脚本并原子暂存;容器重启时由 maybe_restore 应用。"""
    data_dir = Path(data_dir)
    _validate_script(sql_text, data_dir)
    pending = data_dir / PENDING
    tmp = pending.with_suffix(".tmp")
    tmp.write_text(sql_text)
    os.replace(tmp, pending)  # 原子写:崩溃不会留下半截暂存脚本
    return pending


def _rotate(sdir: Path, keep: int) -> None:
    # .db.gz 与 .sql 各自独立保留 keep 份
    for pattern in ("app-*.db.gz", "app-*.sql"):
        files = sorted(sdir.glob(pattern))
        for old in files[:-keep] if len(files) > keep else []:
            old.unlink(missing_ok=True)


def run_self_backup(data_dir: Path, keep: int = KEEP, db: Session | None = None) -> Path:
    """生成配置库 .db.gz 快照(VACUUM INTO 一致性快照)并轮转保留。"""
    data_dir = Path(data_dir)
    live = data_dir / "sqlite" / "app.db"
    sdir = self_backup_dir(data_dir)
    sdir.mkdir(parents=True, exist_ok=True)

    name = f"app-{utcnow().strftime('%Y%m%d-%H%M%S')}.db.gz"
    out = sdir / name
    tmp_sqlite = sdir / f".snapshot-{name}.db"
    try:
        conn = _sq.connect(live)
        try:
            conn.execute(f"VACUUM INTO '{tmp_sqlite}'")
        finally:
            conn.close()
        with open(tmp_sqlite, "rb") as fin, gzip.open(out, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
    except Exception as exc:
        for p in (tmp_sqlite, out):
            try:
                p.unlink(missing_ok=True)
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


def export_sql_dump(data_dir: Path, keep: int = KEEP, db: Session | None = None) -> Path:
    """导出配置库为纯文本 SQL。先 VACUUM INTO 临时快照再 iterdump:
    保证 dump 内容是单一时点的一致性快照(与 worker 并发写隔离)。"""
    data_dir = Path(data_dir)
    live = data_dir / "sqlite" / "app.db"
    sdir = self_backup_dir(data_dir)
    sdir.mkdir(parents=True, exist_ok=True)

    name = f"app-{utcnow().strftime('%Y%m%d-%H%M%S')}.sql"
    out = sdir / name
    snap = sdir / f".snapshot-{name}.db"
    try:
        conn = _sq.connect(live)
        try:
            conn.execute(f"VACUUM INTO '{snap}'")
        finally:
            conn.close()
        conn = _sq.connect(snap)
        try:
            lines = list(conn.iterdump())
        finally:
            conn.close()
        out.write_text("\n".join(lines) + "\n")
    except Exception as exc:
        for p in (snap, out):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        if db is not None:
            db.add(SystemLogRow(level="error", source="selfbackup",
                                message=f"SQL 导出失败:{exc}"))
            db.commit()
        raise
    finally:
        try:
            snap.unlink(missing_ok=True)
        except OSError:
            pass

    _rotate(sdir, keep)
    if db is not None:
        db.add(SystemLogRow(level="info", source="selfbackup",
                            message=f"SQL 导出完成:{name}({out.stat().st_size} 字节)"))
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


def maybe_restore(data_dir: Path) -> Path | None:
    """启动最早处调用(引擎初始化前):存在暂存脚本则应用之。

    任何异常 → 放弃还原(清标记与中间文件,旧库原样启动),绝不阻断启动。"""
    data_dir = Path(data_dir)
    pending = data_dir / PENDING
    if not pending.exists():
        return None
    tmp_new = data_dir / "sqlite" / ".restore-new.db"
    probe = data_dir / "sqlite" / ".restore-check.db"
    try:
        with restore_lock(data_dir):
            # 复验(含 authorizer/时限):暂存期间配置可能已变化
            _validate_script(pending.read_text(), data_dir)

            live = data_dir / "sqlite" / "app.db"
            if live.exists():
                # 留底当前库:先 checkpoint 把 WAL 收进主文件,留底才完整
                c = _sq.connect(live)
                try:
                    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    c.close()
                keep_dir = self_backup_dir(data_dir)
                keep_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copyfile(live, keep_dir / f"pre-restore-{stamp}.db")
                pres = sorted(keep_dir.glob("pre-restore-*.db"))
                for old in pres[:-PRE_RESTORE_KEEP]:
                    old.unlink(missing_ok=True)

            # 在临时库中构建新库 → 清理旧 WAL/SHM → 原子替换
            conn = _sq.connect(tmp_new)
            try:
                conn.executescript(pending.read_text())
            finally:
                conn.close()
            for suffix in ("-wal", "-shm"):
                try:
                    Path(str(live) + suffix).unlink()
                except OSError:
                    pass
            os.replace(tmp_new, live)
        pending.unlink(missing_ok=True)
        return live
    except Exception:
        # 任何失败:放弃还原,旧库原样启动;清干净中间产物避免下次启动残留
        for p in (pending, tmp_new, probe):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        return None
