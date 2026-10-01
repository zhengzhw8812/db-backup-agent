import asyncio
from types import SimpleNamespace
from app.core.clock import utcnow


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
    assert enqueued[0][1] == conn_id and isinstance(enqueued[0][2], list)
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


def test_run_scheduled_backup_skips_when_already_running(monkeypatch, tmp_path):
    """同一连接已有 running 备份 → 计划触发跳过(不建新记录、不投递)。"""
    from app.db import session as _session
    import app.db.models  # noqa
    from app.db.models import DbConnection, BackupRecord
    from app.services import scheduler as sched_mod
    from datetime import datetime

    _session.init_engine(f"sqlite:///{tmp_path/'t.db'}")
    _session.create_all()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    conn_id = conn.id
    db.add(BackupRecord(connection_id=conn_id, trigger="manual", status="running", started_at=utcnow()))
    db.commit(); db.close()

    enqueued = []
    class FakeArq:
        async def enqueue_job(self, *a):
            enqueued.append(a)
    async def fake_get_arq(app):
        return FakeArq()
    monkeypatch.setattr("app.routers.jobs._get_arq", fake_get_arq)

    asyncio.run(sched_mod.run_scheduled_backup(SimpleNamespace(), conn_id, 1))

    assert not enqueued  # 跳过,未投递
    db = _session._SessionLocal()
    scheduled = db.query(BackupRecord).filter(BackupRecord.trigger == "scheduled").all()
    assert scheduled == []  # 未新建 scheduled 记录
    db.close()


def test_auto_verify_enqueues_eligible(client, monkeypatch, tmp_path):
    """未验证的 success 记录入队;30 天内已验证的不入队;开关关 → 不入队。"""
    from datetime import timedelta

    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from app.services import scheduler as sched_mod
    from app.services.settings_service import set_setting

    class FakeArq:
        def __init__(self):
            self.enqueued = []
        async def enqueue_job(self, *args):
            self.enqueued.append(args)

    fake = FakeArq()

    async def fake_get_arq(app):
        return fake

    monkeypatch.setattr("app.routers.jobs._get_arq", fake_get_arq)

    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    old = utcnow() - timedelta(days=40)
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                        file_path="p.sql.gz", checksum="0" * 64, started_at=utcnow()))
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                        started_at=old, verify_status="passed", verified_at=utcnow()))
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="failed", started_at=utcnow()))
    db.commit()

    set_setting(db, "verify_auto_enabled", True)
    import asyncio
    asyncio.run(sched_mod.auto_verify_weekly(client.app))
    assert [a[1] for a in fake.enqueued] and all(a[0] == "verify_job" for a in fake.enqueued)
    n_enabled = len(fake.enqueued)

    set_setting(db, "verify_auto_enabled", False)
    asyncio.run(sched_mod.auto_verify_weekly(client.app))
    assert len(fake.enqueued) == n_enabled  # 关闭后不再入队
    db.close()


def test_auto_verify_respects_30day_window(client, monkeypatch):
    from datetime import timedelta

    from app.db import session as _session
    from app.db.models import DbConnection, BackupRecord
    from app.services import scheduler as sched_mod
    from app.services.settings_service import set_setting

    class FakeArq:
        def __init__(self):
            self.enqueued = []
        async def enqueue_job(self, *args):
            self.enqueued.append(args)

    fake = FakeArq()

    async def fake_get_arq(app):
        return fake

    monkeypatch.setattr("app.routers.jobs._get_arq", fake_get_arq)

    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    db.add(BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                        started_at=utcnow(), verify_status="passed",
                        verified_at=utcnow() - timedelta(days=10)))  # 10 天前验证过 → 跳过
    db.commit()
    set_setting(db, "verify_auto_enabled", True)
    import asyncio
    asyncio.run(sched_mod.auto_verify_weekly(client.app))
    assert fake.enqueued == []
    db.close()
