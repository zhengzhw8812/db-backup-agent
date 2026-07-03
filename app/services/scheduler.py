from __future__ import annotations
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import session as _session
from app.db.models import Schedule, BackupRecord


async def run_scheduled_backup(app, connection_id: int, schedule_id: int) -> None:
    """cron 触发:建 running 记录(trigger=scheduled)→ 投递 backup_job。"""
    db = _session._SessionLocal()
    try:
        rec = BackupRecord(connection_id=connection_id, trigger="scheduled",
                           status="running", started_at=datetime.utcnow())
        db.add(rec); db.commit(); db.refresh(rec)
        record_id = rec.id
    finally:
        db.close()
    from app.routers.jobs import _get_arq
    arq = await _get_arq(app)
    await arq.enqueue_job("backup_job", connection_id, record_id)


class SchedulerService:
    def __init__(self, app):
        self.app = app
        self._sched = AsyncIOScheduler()

    def _job_id(self, schedule_id: int) -> str:
        return f"schedule_{schedule_id}"

    def _add(self, schedule: Schedule) -> None:
        self._sched.add_job(
            run_scheduled_backup,
            CronTrigger.from_crontab(schedule.cron_expr),
            args=[self.app, schedule.connection_id, schedule.id],
            id=self._job_id(schedule.id),
            replace_existing=True,
        )

    async def start(self) -> None:
        db = _session._SessionLocal()
        try:
            for s in db.query(Schedule).filter(Schedule.enabled == True).all():  # noqa: E712
                self._add(s)
        finally:
            db.close()
        self._sched.start()

    def stop(self) -> None:
        try:
            self._sched.shutdown(wait=False)
        except Exception:
            pass

    def upsert(self, schedule: Schedule) -> None:
        if schedule.enabled:
            self._add(schedule)
        else:
            self.remove(schedule.id)

    def remove(self, schedule_id: int) -> None:
        try:
            self._sched.remove_job(self._job_id(schedule_id))
        except Exception:
            pass

    def next_run_at(self, schedule_id: int):
        try:
            job = self._sched.get_job(self._job_id(schedule_id))
            return job.next_run_time if job else None
        except Exception:
            return None
