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
        def _enable_sqlite_foreign_keys(dbapi_conn, _connection_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
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
