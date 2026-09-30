from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def init_engine(db_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    _engine = create_engine(db_url, connect_args=connect_args, future=True)

    if db_url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _tune_sqlite(dbapi_conn, _connection_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            # WAL:读写不互斥;busy_timeout:写锁等待 5s 而非立刻报 database is locked;
            # synchronous=NORMAL:WAL 下的安全持久化折中。Web/worker/调度器多进程共写同一库。
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    _SessionLocal = sessionmaker(_engine, autoflush=False, expire_on_commit=False, future=True)


def create_all() -> None:
    from app.db import models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(_engine)


def get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
