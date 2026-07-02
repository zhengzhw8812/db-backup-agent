from datetime import datetime
from sqlalchemy import text
from app.db.session import init_engine, create_all
import app.db.models  # noqa
from app.db import session as _session


def test_deleting_connection_cascades_to_schedule(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _session._SessionLocal()
    try:
        from app.db.models import DbConnection, Schedule
        conn = DbConnection(name="c1", type="pg")
        db.add(conn)
        db.flush()
        db.add(Schedule(connection_id=conn.id, cron_expr="* * * * *"))
        db.commit()
        cid = conn.id

        # Raw-SQL delete bypasses the ORM-level cascade="all, delete-orphan"
        # on DbConnection.schedules, so this relies purely on the DB-level
        # ON DELETE CASCADE, which only fires when PRAGMA foreign_keys=ON.
        db.execute(text("DELETE FROM db_connections WHERE id=:i"), {"i": cid})
        db.commit()

        assert db.query(Schedule).count() == 0  # cascaded by DB-level ON DELETE CASCADE
    finally:
        db.close()
