# Phase 2b — 定时调度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 让备份按 cron 表达式自动定时执行: schedules CRUD + APScheduler 在 Web 进程内按 cron 触发 → 创建 running 记录 → 投递 backup_job(复用 Phase 2a 管线)。

**Architecture:** APScheduler `AsyncIOScheduler` 在 FastAPI lifespan 中启停,托管于 Web 进程。每个启用的 schedule 注册为一个 cron job;job 触发时建 `BackupRecord(trigger="scheduled", status="running")` 并经 arq 池投递 `backup_job(connection_id, record_id)`(与手动备份完全一致的下游)。CRUD 操作实时同步调度器(add/remove job)。`next_run_at` 由调度器回写。

**Tech Stack:** APScheduler (AsyncIOScheduler + CronTrigger.from_crontab), FastAPI lifespan。

**前置:** Phase 2a 完成(schedules 表已存在;backup_job + arq 池 + jobs API 已就绪)。

---

## File Structure
```
app/
├── schemas/schedule.py        # ScheduleCreate/Update/Out
├── services/
│   ├── schedule_service.py    # CRUD(纯 DB)
│   └── scheduler.py           # SchedulerService(APScheduler 封装)+ 触发函数
├── routers/schedules.py       # /api/v1/schedules CRUD
└── main.py                    # lifespan 启停调度器;app.state.scheduler
tests/
├── test_schedules_api.py
└── test_scheduler.py
```

---

## Task 1: Schedule schemas + CRUD service + router(TDD)

**Files:** `app/schemas/schedule.py`, `app/services/schedule_service.py`, `app/routers/schedules.py`, modify `app/main.py`(include), `tests/test_schedules_api.py`.

- [ ] **Step 1: app/schemas/schedule.py**
```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ScheduleBase(BaseModel):
    connection_id: int
    cron_expr: str = Field(..., pattern=r"^[^\s]+(\s+[^\s]+){4}$")  # 5 字段 cron
    enabled: bool = True
    retention_days: int = Field(7, ge=1)


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    cron_expr: str | None = Field(None, pattern=r"^[^\s]+(\s+[^\s]+){4}$")
    enabled: bool | None = None
    retention_days: int | None = Field(None, ge=1)


class ScheduleOut(BaseModel):
    id: int
    connection_id: int
    cron_expr: str
    enabled: bool
    retention_days: int
    next_run_at: datetime | None
    model_config = {"from_attributes": True}
```

- [ ] **Step 2: app/services/schedule_service.py**
```python
from __future__ import annotations
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.db.models import Schedule, DbConnection


def _get(db: Session, sid: int) -> Schedule:
    s = db.get(Schedule, sid)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="计划不存在")
    return s


def list_schedules(db: Session) -> list[Schedule]:
    return db.query(Schedule).order_by(Schedule.id).all()


def create_schedule(db: Session, data) -> Schedule:
    if db.get(DbConnection, data.connection_id) is None:
        raise HTTPException(status_code=400, detail="连接不存在")
    s = Schedule(connection_id=data.connection_id, cron_expr=data.cron_expr,
                 enabled=data.enabled, retention_days=data.retention_days)
    db.add(s); db.commit(); db.refresh(s)
    return s


def update_schedule(db: Session, sid: int, data) -> Schedule:
    s = _get(db, sid)
    for f in ("cron_expr", "enabled", "retention_days"):
        v = getattr(data, f)
        if v is not None:
            setattr(s, f, v)
    db.commit(); db.refresh(s)
    return s


def delete_schedule(db: Session, sid: int) -> None:
    s = _get(db, sid)
    db.delete(s); db.commit()
```

- [ ] **Step 3: app/routers/schedules.py**(本任务纯 CRUD;Task 2 加调度器同步)
```python
from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.deps import get_current_account
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate, ScheduleOut
from app.services import schedule_service as svc

router = APIRouter()


@router.get("/schedules", response_model=list[ScheduleOut])
def list_(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.list_schedules(db)


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
def create(payload: ScheduleCreate, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.create_schedule(db, payload)


@router.put("/schedules/{sid}", response_model=ScheduleOut)
def update(sid: int, payload: ScheduleUpdate, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return svc.update_schedule(db, sid, payload)


@router.delete("/schedules/{sid}", status_code=204)
def delete(sid: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    svc.delete_schedule(db, sid)
```

- [ ] **Step 4: app/main.py 加 schedules 路由**(import 加 `schedules`;include `/api/v1`)

- [ ] **Step 5: tests/test_schedules_api.py**
```python
import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(DbConnection(name="c", type="pg")); db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_requires_auth(client):
    assert client.get("/api/v1/schedules").status_code == 401


def test_create_list_update_delete(authed):
    from app.db import session as _session
    from app.db.models import DbConnection
    conn_id = _session._SessionLocal().query(DbConnection).first().id
    r = authed.post("/api/v1/schedules", json={"connection_id": conn_id, "cron_expr": "0 2 * * *"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["cron_expr"] == "0 2 * * *"
    assert len(authed.get("/api/v1/schedules").json()) == 1
    u = authed.put(f"/api/v1/schedules/{sid}", json={"enabled": False})
    assert u.json()["enabled"] is False
    assert authed.delete(f"/api/v1/schedules/{sid}").status_code == 204
    assert authed.get("/api/v1/schedules").json() == []


def test_create_rejects_unknown_connection(authed):
    r = authed.post("/api/v1/schedules", json={"connection_id": 9999, "cron_expr": "0 2 * * *"})
    assert r.status_code == 400
```

- [ ] **Step 6: 运行** `.venv/bin/python -m pytest tests/test_schedules_api.py -v` → 3 passed;全套绿。

- [ ] **Step 7: 提交**
```bash
git add app/schemas/schedule.py app/services/schedule_service.py app/routers/schedules.py app/main.py tests/test_schedules_api.py
git commit -m "feat(phase2b): 备份计划 CRUD"
```

---

## Task 2: APScheduler 集成(lifespan + 触发函数 + CRUD 同步 + next_run_at)

**Files:** modify `pyproject.toml`(加 apscheduler);`app/services/scheduler.py`;modify `app/main.py`(lifespan);modify `app/routers/schedules.py`(同步调度器);`tests/test_scheduler.py`。

- [ ] **Step 1: pyproject 加 `"apscheduler>=3.10"`;`pip install -e ".[dev]"`**

- [ ] **Step 2: app/services/scheduler.py**
```python
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
```

- [ ] **Step 3: app/main.py 加 lifespan(启停调度器)**
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.scheduler import SchedulerService
    sched = SchedulerService(app)
    await sched.start()
    app.state.scheduler = sched
    try:
        yield
    finally:
        sched.stop()
```
在 `create_app()` 中把 `FastAPI(title=..., version=...)` 改为 `FastAPI(title=..., version=..., lifespan=lifespan)`。Phase 1 的同步 bootstrap/init/create_all 保留在 create_app 顶部不动。`app.state.scheduler` 在 lifespan 里设置。

- [ ] **Step 4: app/routers/schedules.py CRUD 同步调度器 + 回写 next_run_at**
create 后:
```python
    request.app.state.scheduler.upsert(s)
    s.next_run_at = request.app.state.scheduler.next_run_at(s.id)
    db.commit(); db.refresh(s)
    return s
```
update 后同理 `request.app.state.scheduler.upsert(s)` + 回写 next_run_at。
delete 前 `request.app.state.scheduler.remove(sid)`。
(需在路由函数签名加 `request: Request`。)

- [ ] **Step 5: tests/test_scheduler.py**(测触发函数;调度器 upsert/remove 用伪造 _sched,不依赖真实 cron/事件循环)

```python
import asyncio
from types import SimpleNamespace


def test_run_scheduled_backup_creates_record_and_enqueues(monkeypatch, tmp_path):
    from app.db.session import init_engine, create_all, _SessionLocal
    import app.db.models  # noqa
    from app.db.models import DbConnection, BackupRecord
    from app.services import scheduler as sched_mod

    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _SessionLocal()
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
    assert enqueued[0][1] == conn_id and isinstance(enqueued[0][2], int)  # record_id
    db = _SessionLocal()
    rec = db.query(BackupRecord).filter(BackupRecord.trigger == "scheduled").first()
    assert rec is not None and rec.status == "running"
    db.close()


def test_scheduler_upsert_enabled_adds_job(monkeypatch):
    """upsert(enabled) → _sched.add_job;remove → _sched.remove_job;不启动真实调度器。"""
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
    svc.upsert(s)  # disabled → remove
    assert "schedule_1" in removed

    svc.remove(99)  # 不存在的 job 不抛异常
```

> 说明:`run_scheduled_backup` 是 async,用 `asyncio.run(...)` 驱动(无需 pytest-asyncio)。`SchedulerService` 测试用 `SimpleNamespace` 伪造 `_sched`,避免启动真实 AsyncIOScheduler(它需要事件循环)。生产代码仍用真实的 `AsyncIOScheduler`。

- [ ] **Step 6: 运行** `.venv/bin/python -m pytest -v` → 全套绿。

- [ ] **Step 7: 提交**
```bash
git add pyproject.toml app/services/scheduler.py app/main.py app/routers/schedules.py tests/test_scheduler.py
git commit -m "feat(phase2b): APScheduler 定时触发 + CRUD 同步 + next_run_at"
```

---

## Phase 2b 完成标准
- `pytest` 全绿。
- schedules CRUD 全端点鉴权;创建/更新同步调度器;删除注销。
- cron 触发建 scheduled 记录并投递 backup_job(单测验证触发函数;真实 cron 定时需运行环境验证)。
- next_run_at 回写。

---

*自检:复用 Phase 2a 的 backup_job/arq 池/记录模型,无新下游。`run_scheduled_backup` 与手动 run 走同一条管线。类型一致:`SchedulerService.upsert/remove/next_run_at`、`run_scheduled_backup(app, connection_id, schedule_id)` 跨任务一致。*
