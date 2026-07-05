from __future__ import annotations
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import session as _session
from app.db.models import Schedule, BackupRecord, SystemLog, DbConnection
from app.services.locks import has_running_backup


async def run_scheduled_backup(app, connection_id: int, schedule_id: int) -> None:
    """cron 触发:为每个待备份库建 running 记录(trigger=scheduled)→ 投递 backup_job。

    互斥:若该连接已有 running 备份(手动/上一轮未结束),本轮跳过,记 SystemLog。"""
    from app.services.backup_service import enqueue_backup
    db = _session._SessionLocal()
    try:
        if has_running_backup(db, connection_id) is not None:
            db.add(SystemLog(level="warning", source="scheduler",
                             message=f"连接 #{connection_id} 已有备份在运行,跳过本次计划触发(#{schedule_id})"))
            db.commit()
            return
        conn = db.get(DbConnection, connection_id)
        if conn is None:
            return
        records = enqueue_backup(db, conn, "scheduled")
        record_ids = [r.id for r in records]
    finally:
        db.close()
    from app.routers.jobs import _get_arq
    try:
        arq = await _get_arq(app)
        await arq.enqueue_job("backup_job", connection_id, record_ids)
    except Exception:
        # 投递失败:把刚建的 running 记录翻转成 failed,避免幽灵任务
        db = _session._SessionLocal()
        try:
            for rid in record_ids:
                rec = db.get(BackupRecord, rid)
                if rec is not None:
                    rec.status = "failed"
                    rec.error = "投递到队列失败"
                    rec.finished_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        raise


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
                # 单条计划 cron 异常不应拖垮其余计划:逐条兜底
                try:
                    self._add(s)
                except Exception:
                    pass
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
