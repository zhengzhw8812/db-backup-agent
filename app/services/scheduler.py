from __future__ import annotations
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import session as _session
from app.db.models import Schedule, BackupRecord, SystemLog, DbConnection
from app.services.locks import has_running_backup
from app.core.clock import utcnow


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
                    rec.finished_at = utcnow()
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
        try:
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            self._sched.add_job(watchdog_check, IntervalTrigger(hours=1),
                                args=[self.app], id="watchdog_check", replace_existing=True)
            self._sched.add_job(auto_verify_weekly,
                                CronTrigger(day_of_week="mon", hour=3, minute=30),
                                args=[self.app], id="auto_verify_weekly", replace_existing=True)
        except Exception:
            pass  # 注册失败不拖垮其余调度(逐条兜底,同既有模式)
        self._sched.start()

    @property
    def running(self) -> bool:
        """调度器是否在运行(健康检查用)。"""
        try:
            return bool(self._sched.running)
        except Exception:
            return False

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

async def auto_verify_weekly(app) -> None:
    """每周自动验证(周一 03:30,由 SchedulerService 注册):
    开关开启时,把全部待验证(success 且从未验证或 verified_at 超过 30 天)记录入队 verify_job。"""
    from datetime import timedelta

    from app.services.settings_service import get_setting

    db = _session._SessionLocal()
    try:
        if not get_setting(db, "verify_auto_enabled", False):
            return
        cutoff = utcnow() - timedelta(days=30)
        eligible = (
            db.query(BackupRecord)
            .filter(
                BackupRecord.status == "success",
                BackupRecord.file_path.isnot(None),
                BackupRecord.verify_status.is_(None)
                | BackupRecord.verified_at.is_(None)
                | (BackupRecord.verified_at < cutoff),
            )
            .all()
        )
        ids = [r.id for r in eligible]
    finally:
        db.close()
    if not ids:
        return
    from app.routers.jobs import _get_arq

    try:
        arq = await _get_arq(app)
        for rid in ids:
            await arq.enqueue_job("verify_job", rid)
    except Exception:
        db2 = _session._SessionLocal()
        try:
            db2.add(SystemLog(level="warning", source="verify",
                              message=f"自动验证入队失败,共 {len(ids)} 条"))
            db2.commit()
        finally:
            db2.close()
        raise

async def watchdog_check(app) -> None:
    """每小时看门狗:对每个启用的计划,若距上次成功备份超过 2×cron 周期
    (周期 = 相邻两次触发时间差;无成功记录看连接创建是否超过 48h),发失联告警。
    同一计划 24h 内不重复告警(app_settings 去重)。cron 非法跳过并记日志。"""
    from datetime import datetime, timedelta

    from apscheduler.triggers.cron import CronTrigger

    from app.bootstrap import bootstrap_keys
    from app.core.crypto import Crypto
    from app.services.notifications import notify_generic
    from app.services.settings_service import get_setting, set_setting

    _, fernet_key = bootstrap_keys()
    crypto = Crypto(fernet_key.encode("ascii"))
    now = utcnow()
    db = _session._SessionLocal()
    try:
        schedules = db.query(Schedule).filter(Schedule.enabled == True).all()  # noqa: E712
        for s in schedules:
            last_alert = get_setting(db, f"watchdog:{s.id}")
            if last_alert:
                try:
                    if now - datetime.fromisoformat(last_alert) < timedelta(hours=24):
                        continue
                except ValueError:
                    pass
            try:
                trigger = CronTrigger.from_crontab(s.cron_expr)
                nxt1 = trigger.get_next_fire_time(None, now)
                nxt2 = trigger.get_next_fire_time(nxt1, nxt1) if nxt1 else None
            except Exception:
                db.add(SystemLog(level="warning", source="watchdog",
                                 message=f"计划 #{s.id} cron 表达式非法,跳过检查:{s.cron_expr}"))
                db.commit()
                continue
            if not nxt1 or not nxt2:
                continue
            threshold = (nxt2 - nxt1) * 2
            last = (
                db.query(BackupRecord.started_at)
                .filter(BackupRecord.connection_id == s.connection_id,
                        BackupRecord.status == "success")
                .order_by(BackupRecord.started_at.desc())
                .first()
            )
            if last and last[0]:
                if (now - last[0]) <= threshold:
                    continue
                overdue_desc = f"距上次成功 {now - last[0]}"
            else:
                conn = db.get(DbConnection, s.connection_id)
                if conn is None or (now - (conn.created_at or now)) <= timedelta(hours=48):
                    continue
                overdue_desc = "从未成功备份"
            conn = db.get(DbConnection, s.connection_id)
            name = conn.name if conn else f"#{s.connection_id}"
            set_setting(db, f"watchdog:{s.id}", now.isoformat())
            try:
                notify_generic(db, crypto, kind="watchdog",
                               subject=f"[备份失联] {name}",
                               content=(f"数据库:{name}\n计划:{s.cron_expr}\n"
                                        f"情况:{overdue_desc},已超过 2× 计划周期未成功备份,请检查容器/调度器。"))
            except Exception:
                pass
    finally:
        db.close()
