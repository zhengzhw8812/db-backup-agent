"""看门狗:备份计划失联检测。判定逻辑全在 watchdog_check,通知经 notify_generic。"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.clock import utcnow
from app.core.crypto import Crypto
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, Schedule, NotificationConfig
from app.services import scheduler as sched_mod
from app.services.settings_service import set_setting


class FakeSched:
    """替代 AsyncIOScheduler,记录注册的 job。"""
    def __init__(self):
        self.jobs = []
    def add_job(self, fn, trigger, **kw):
        self.jobs.append((fn, kw.get("id")))
    def start(self): pass
    def shutdown(self, wait=False): pass
    def get_job(self, _): return None
    def remove_job(self, _): pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离引擎 + FakeSched + 通知记录器。"""
    from app import config as app_config

    monkeypatch.setattr(app_config.settings, "data_dir", tmp_path)
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    fake = FakeSched()
    monkeypatch.setattr(sched_mod, "AsyncIOScheduler", lambda: FakeSched())
    alerts = []
    monkeypatch.setattr("app.services.notifications.notify_generic",
                        lambda db, crypto, *, kind, subject, content: alerts.append((kind, subject)) or {"email": False})
    db = _session._SessionLocal()
    conn = DbConnection(name="web-db", type="pg", created_at=utcnow() - timedelta(days=10))
    db.add(conn); db.commit(); db.refresh(conn)
    sched = Schedule(connection_id=conn.id, cron_expr="0 2 * * *", enabled=True)
    db.add(sched); db.commit(); db.refresh(sched)
    yield db, conn, sched, alerts
    db.close()


def _service(app=None):
    return sched_mod.SchedulerService(app or SimpleNamespace())


def test_watchdog_alerts_overdue(env):
    """上次成功超过 2× 周期(0 2 * * * → 24h → 阈值 48h)→ 告警。"""
    db, conn, sched, alerts = env
    db.add(BackupRecord(connection_id=conn.id, trigger="scheduled", status="success",
                        started_at=utcnow() - timedelta(days=3)))
    db.commit()
    asyncio.run(sched_mod.watchdog_check(SimpleNamespace()))
    assert len(alerts) == 1
    assert "web-db" in alerts[0][1]


def test_watchdog_silent_within_threshold(env):
    db, conn, sched, alerts = env
    db.add(BackupRecord(connection_id=conn.id, trigger="scheduled", status="success",
                        started_at=utcnow() - timedelta(hours=24)))  # 0.5×阈值
    db.commit()
    asyncio.run(sched_mod.watchdog_check(SimpleNamespace()))
    assert alerts == []


def test_watchdog_grace_for_never_ran(env):
    """无成功记录且连接创建不足 48h → 宽限静默。"""
    db, conn, sched, alerts = env
    conn.created_at = utcnow() - timedelta(hours=10)
    db.commit()
    asyncio.run(sched_mod.watchdog_check(SimpleNamespace()))
    assert alerts == []


def test_watchdog_never_ran_past_grace_alerts(env):
    db, conn, sched, alerts = env  # created_at = 10 天前,无任何成功记录
    asyncio.run(sched_mod.watchdog_check(SimpleNamespace()))
    assert len(alerts) == 1


def test_watchdog_dedup_24h(env):
    from app.services.settings_service import get_setting
    db, conn, sched, alerts = env
    set_setting(db, f"watchdog:{sched.id}", utcnow().isoformat())  # 刚刚告警过
    db.add(BackupRecord(connection_id=conn.id, trigger="scheduled", status="success",
                        started_at=utcnow() - timedelta(days=3)))
    db.commit()
    asyncio.run(sched_mod.watchdog_check(SimpleNamespace()))
    assert alerts == []


def test_watchdog_skips_disabled(env):
    db, conn, sched, alerts = env
    sched.enabled = False
    db.commit()
    db.add(BackupRecord(connection_id=conn.id, trigger="scheduled", status="success",
                        started_at=utcnow() - timedelta(days=3)))
    db.commit()
    asyncio.run(sched_mod.watchdog_check(SimpleNamespace()))
    assert alerts == []


def test_watchdog_respects_toggle(tmp_path):
    """notify_watchdog=False → notify_generic 内部跳过(配置层静默)。"""
    from app.services import notifications as notif_mod

    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _session._SessionLocal()
    db.add(NotificationConfig(email_enabled=True, notify_watchdog=False))
    db.commit()
    sent = notif_mod.notify_generic(db, Crypto(Fernet.generate_key()), kind="watchdog",
                                    subject="x", content="y")
    db.close()
    assert sent == {"email": False, "wechat": False}


def test_watchdog_registered_hourly(monkeypatch):
    """start() 注册 watchdog_check(每小时)与 auto_verify_weekly(每周一 03:30)。"""
    monkeypatch.setattr(sched_mod, "AsyncIOScheduler", lambda: FakeSched())
    svc = _service()
    asyncio.run(svc.start())
    ids = [j[1] for j in svc._sched.jobs]
    assert "watchdog_check" in ids
    assert "auto_verify_weekly" in ids
    svc.stop()
