from sqlalchemy import text

from app.db import session as db_session


def test_sqlite_wal_busy_timeout_synchronous(tmp_path):
    db_session.init_engine(f"sqlite:///{tmp_path}/t.db")
    with db_session._engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert c.execute(text("PRAGMA synchronous")).scalar() == 1  # 1=NORMAL
