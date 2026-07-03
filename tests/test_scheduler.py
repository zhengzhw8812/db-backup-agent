import asyncio
from types import SimpleNamespace


def test_run_scheduled_backup_creates_record_and_enqueues(monkeypatch, tmp_path):
    from app.db import session as _session
    import app.db.models  # noqa
    from app.db.models import DbConnection, BackupRecord
    from app.services import scheduler as sched_mod

    _session.init_engine(f"sqlite:///{tmp_path/'t.db'}")
    _session.create_all()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    conn_id = conn.id; db.close()

    enqueued = []
    class FakeArq:
        async def enqueue_job(self, *a):
            enqueued.append(a)
    async def fake_get_arq(app):
        return FakeArq()
    monkeypatch.setattr("app.routers.jobs._get_arq", fake_get_arq)

    asyncio.run(sched_mod.run_scheduled_backup(SimpleNamespace(), conn_id, 1))

    assert enqueued and enqueued[0][0] == "backup_job"
    assert enqueued[0][1] == conn_id and isinstance(enqueued[0][2], int)
    db = _session._SessionLocal()
    rec = db.query(BackupRecord).filter(BackupRecord.trigger == "scheduled").first()
    assert rec is not None and rec.status == "running"
    db.close()


def test_scheduler_upsert_enabled_adds_job():
    from app.services.scheduler import SchedulerService
    svc = SchedulerService(SimpleNamespace())
    added = {}; removed = []
    class FakeJob:
        def __init__(self, nrt): self.next_run_time = nrt
    svc._sched = SimpleNamespace(
        add_job=lambda fn, trigger=None, **kw: added.__setitem__(kw.get("id"), FakeJob("2099-01-01")),
        remove_job=lambda jid: removed.append(jid),
        get_job=lambda jid: added.get(jid),
    )
    s = SimpleNamespace(id=1, connection_id=2, cron_expr="0 2 * * *", enabled=True)
    svc.upsert(s)
    assert "schedule_1" in added
    assert svc.next_run_at(1) == "2099-01-01"
    s.enabled = False
    svc.upsert(s)
    assert "schedule_1" in removed
    svc.remove(99)
