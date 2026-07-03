# 通知 + 保留策略 (Notifications + Retention) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 补齐备份管线缺失的两步(spec §8 第 7、8 步):**保留策略**(成功后按计划 retention_days 清理旧备份)与**结果通知**(成功/失败按配置发邮件 / 企业微信)。新增单行 `notification_config` 表(Fernet 加密 SMTP/微信凭据)+ 通知服务(stdlib smtplib/urllib,不引入新运行时依赖)+ 保留服务 + worker 编排 + 配置路由。

**Architecture:** `backup_service` 已验证(Phase 2a,不改)。在 **worker**(`_run_backup_sync`)成功后调 `run_retention` 清理、并在终态(success/failed)调 `notify_backup_result` 通知 —— 把副作用放在 worker 编排层,保持 backup_service 单一职责。通知用 stdlib:邮件 `smtplib`(SSL/STARTTLS)、企业微信 `urllib.request`(gettoken→message/send)。

**Tech Stack:** stdlib smtplib + urllib(无新依赖)+ FastAPI + SQLAlchemy。

**关键决策(文档化 MVP 边界):**
- 通知/保留在 worker 内**同步**执行(备份本就在 worker 线程);spec §6 的独立 `notify_job` 异步化为未来增强。
- 企业微信 token **每次发送现取**(不做跨请求缓存;token 接口配额充足,缓存留后续)。
- 保留:取连接所有 enabled 计划里**最小** retention_days(最激进),删过期 success 备份(文件+记录);无计划的连接不清理。
- 手动备份也会触发保留清理(按连接的计划 retention);若连接无计划则跳过。

**前置:** Phase 1–Cloud Sync 完成。`backup_service`/worker/`Schedule`(有 `retention_days`)/`BackupRecord`/`SystemLog`/`Crypto` 均就绪。

---

## 文件结构
- Modify `app/db/models.py` — `NotificationConfig`(单行)
- Create `app/schemas/notification.py` — 配置 in/out(凭据不回传)
- Create `app/services/notifications.py` — `notify_backup_result` + 邮件/微信发送(stdlib)
- Create `app/services/retention.py` — `run_retention`
- Modify `app/workers/jobs.py` — `_run_backup_sync` 成功后调 retention + 终态调 notify
- Create `app/routers/settings.py` — `GET/PUT /settings/notifications`
- Modify `app/main.py` — 挂载 settings 路由
- Tests: test_models、test_notifications(新)、test_retention(新)、test_jobs、test_settings_api(新)

---

## Tasks

### Task 1: NotificationConfig 模型 + schema

**Files:** Modify `app/db/models.py`; Create `app/schemas/notification.py`; Test `tests/test_models.py`

- [ ] **Step 1: 写失败测试** —— `tests/test_models.py` 的 `expected` 加 `"notification_config"`,并追加:
```python
def test_notification_config_persists(tmp_path):
    from app.db.models import NotificationConfig
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    from app.db.session import _SessionLocal
    db = _SessionLocal()
    cfg = NotificationConfig(email_enabled=False, wechat_enabled=False,
                             notify_on_success=True, notify_on_failure=True)
    db.add(cfg); db.commit(); db.refresh(cfg)
    assert db.get(NotificationConfig, cfg.id).notify_on_success is True
    db.close()
```
(`expected` 集合加 `"notification_config"`。)

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_models.py -v` → FAIL。

- [ ] **Step 3: 实现模型** —— `app/db/models.py` 末尾追加:
```python
class NotificationConfig(Base):
    __tablename__ = "notification_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_ssl: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smtp_starttls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smtp_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)   # Fernet
    smtp_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipients: Mapped[str | None] = mapped_column(Text, nullable=True)           # 逗号分隔
    wechat_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wechat_corp_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wechat_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wechat_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)    # Fernet
    notify_on_success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 4: 实现 schema** —— 创建 `app/schemas/notification.py`:
```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class NotificationSettings(BaseModel):
    email_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_ssl: bool = False
    smtp_starttls: bool = True
    smtp_user: str | None = None
    smtp_password: str | None = None        # 仅写入;Out 不返回
    smtp_from: str | None = None
    recipients: str | None = None
    wechat_enabled: bool = False
    wechat_corp_id: str | None = None
    wechat_agent_id: str | None = None
    wechat_secret: str | None = None        # 仅写入;Out 不返回
    notify_on_success: bool = True
    notify_on_failure: bool = True


class NotificationSettingsOut(BaseModel):
    email_enabled: bool
    smtp_host: str | None
    smtp_port: int | None
    smtp_ssl: bool
    smtp_starttls: bool
    smtp_user: str | None
    smtp_from: str | None
    recipients: str | None
    wechat_enabled: bool
    wechat_corp_id: str | None
    wechat_agent_id: str | None
    notify_on_success: bool
    notify_on_failure: bool
    created_at: datetime
    # 不含 smtp_password / wechat_secret

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: 跑测试确认通过** —— `python3 -m pytest tests/test_models.py -v` → PASS。

- [ ] **Step 6: 提交** —— `git add app/db/models.py app/schemas/notification.py tests/test_models.py && git commit -m "feat(notify): NotificationConfig 模型 + schema"`

---

### Task 2: notifications 服务(邮件 + 企业微信)

**Files:** Create `app/services/notifications.py`; Test `tests/test_notifications.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_notifications.py`:
```python
import pytest
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, NotificationConfig
from app.core.crypto import Crypto
from cryptography.fernet import Fernet
from app.services.notifications import notify_backup_result


def _db(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    return _session._SessionLocal()


def test_notify_no_config_is_noop(tmp_path):
    db = _db(tmp_path)
    crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg")
    db.add(conn); db.commit(); db.refresh(conn)
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
    # 无 NotificationConfig —— 不应抛错
    assert notify_backup_result(db, crypto, conn, rec) == {"email": False, "wechat": False}
    db.close()


def test_notify_success_respects_flag(tmp_path, monkeypatch):
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(NotificationConfig(email_enabled=True, wechat_enabled=False, notify_on_success=True, notify_on_failure=True,
                              smtp_host="h", smtp_port=25, smtp_from="a@b", recipients="x@y"))
    db.commit()
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    called = {}
    monkeypatch.setattr("app.services.notifications._send_email", lambda cfg, subj, body: called.setdefault("email", (subj, body)))
    monkeypatch.setattr("app.services.notifications._send_wechat", lambda cfg, content: called.setdefault("wechat", content))
    result = notify_backup_result(db, crypto, conn, rec)
    assert result["email"] is True and result["wechat"] is False
    assert "成功" in called["email"][0]
    db.close()


def test_notify_failure_when_flag_off_skips(tmp_path, monkeypatch):
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(NotificationConfig(email_enabled=True, notify_on_success=False, notify_on_failure=False,
                              smtp_host="h", smtp_port=25, smtp_from="a@b", recipients="x@y"))
    db.commit()
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="failed", error="boom", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    monkeypatch.setattr("app.services.notifications._send_email", lambda *a: None)
    assert notify_backup_result(db, crypto, conn, rec)["email"] is False
    db.close()


def test_notify_one_channel_failure_does_not_break_other(tmp_path, monkeypatch):
    db = _db(tmp_path); crypto = Crypto(Fernet.generate_key())
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(NotificationConfig(email_enabled=True, wechat_enabled=True, smtp_host="h", smtp_port=25,
                              smtp_from="a@b", recipients="x@y", wechat_corp_id="cid", wechat_agent_id="aid"))
    db.commit()
    from datetime import datetime
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success", started_at=datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    def boom_email(*a): raise RuntimeError("smtp down")
    monkeypatch.setattr("app.services.notifications._send_email", boom_email)
    monkeypatch.setattr("app.services.notifications._send_wechat", lambda *a: None)
    result = notify_backup_result(db, crypto, conn, rec)
    assert result["email"] is False      # 邮件失败
    assert result["wechat"] is True      # 微信仍发送
    db.close()
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_notifications.py -v` → FAIL(模块不存在)。

- [ ] **Step 3: 实现 notifications.py** —— 创建 `app/services/notifications.py`:
```python
from __future__ import annotations
import json
import smtplib
import urllib.parse
import urllib.request
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, NotificationConfig
from app.core.crypto import Crypto


def _send_email(cfg: NotificationConfig, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_from or ""
    recipients = [r.strip() for r in (cfg.recipients or "").split(",") if r.strip()]
    msg["To"] = ", ".join(recipients)
    if cfg.smtp_ssl:
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        if cfg.smtp_starttls:
            server.starttls()
    try:
        if cfg.smtp_user:
            server.login(cfg.smtp_user, cfg.smtp_password_enc or "")
        server.sendmail(cfg.smtp_from, recipients, msg.as_string())
    finally:
        server.quit()


def _wechat_token(corp_id: str, secret: str) -> str:
    url = (f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
           f"corpid={urllib.parse.quote(corp_id)}&corpsecret={urllib.parse.quote(secret)}")
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode"):
        raise RuntimeError(f"企业微信 token 失败: {data}")
    return data["access_token"]


def _send_wechat(cfg: NotificationConfig, content: str) -> None:
    token = _wechat_token(cfg.wechat_corp_id, cfg.wechat_secret_enc or "")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = json.dumps({"touser": "@all", "msgtype": "text",
                       "agentid": int(cfg.wechat_agent_id), "text": {"content": content}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode"):
        raise RuntimeError(f"企业微信发送失败: {data}")


def notify_backup_result(db: Session, crypto: Crypto, conn: DbConnection, record: BackupRecord) -> dict:
    """按配置发送备份结果通知。无配置/相应开关关闭 → 跳过。邮件与微信独立 try/except。"""
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        return {"email": False, "wechat": False}
    success = record.status == "success"
    if success and not cfg.notify_on_success:
        return {"email": False, "wechat": False}
    if not success and not cfg.notify_on_failure:
        return {"email": False, "wechat": False}

    tag = "成功" if success else "失败"
    subject = f"[备份{tag}] {conn.name}"
    body = (f"数据库:{conn.name} ({conn.type})\n状态:{record.status}\n"
            f"耗时:{record.duration_ms if record.duration_ms is not None else '-'} ms\n"
            f"错误:{record.error or '无'}")

    sent = {"email": False, "wechat": False}
    if cfg.email_enabled:
        try:
            # 解出 SMTP 密码附到 cfg(发送函数读 _enc 字段——此处先解密回填,避免改 _send_email 签名)
            if cfg.smtp_password_enc:
                # 用临时属性传明文密码:_send_email 读 smtp_password_enc,故直接解密覆写
                cfg.smtp_password_enc = crypto.decrypt(cfg.smtp_password_enc)
            _send_email(cfg, subject, body)
            sent["email"] = True
        except Exception:
            sent["email"] = False
    if cfg.wechat_enabled:
        try:
            if cfg.wechat_secret_enc:
                cfg.wechat_secret_enc = crypto.decrypt(cfg.wechat_secret_enc)
            _send_wechat(cfg, body)
            sent["wechat"] = True
        except Exception:
            sent["wechat"] = False
    return sent
```
> 注:为不改动 `_send_email`/`_send_wechat` 的字段读取(它们读 `smtp_password_enc`/`wechat_secret_enc`),发送前在内存对象上把密文解为明文覆写。该 cfg 是本次查询的临时对象,不 commit,不影响库。

- [ ] **Step 4: 跑测试确认通过** —— `python3 -m pytest tests/test_notifications.py -v` → PASS(4 个)。

- [ ] **Step 5: 提交** —— `git add app/services/notifications.py tests/test_notifications.py && git commit -m "feat(notify): 通知服务(邮件 smtplib + 企业微信 urllib)"`

---

### Task 3: retention 服务

**Files:** Create `app/services/retention.py`; Test `tests/test_retention.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_retention.py`:
```python
from datetime import datetime, timedelta
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.db.models import DbConnection, BackupRecord, Schedule
from app.services.retention import run_retention


def _setup(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    db.add(Schedule(connection_id=conn.id, cron_expr="0 2 * * *", retention_days=7, enabled=True))
    db.commit()
    return db, conn, bdir


def _mk(db, conn, bdir, file_name, days_old):
    from app.core.archive import compress_file
    raw = bdir / "x.sql"; raw.write_bytes(b"d")
    gz = bdir / file_name; compress_file(raw, gz)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="success",
                       file_path=file_name, size=1, checksum="c",
                       started_at=datetime.utcnow() - timedelta(days=days_old),
                       finished_at=datetime.utcnow() - timedelta(days=days_old))
    db.add(rec); db.commit(); db.refresh(rec)
    return rec


def test_retention_deletes_old_backups(tmp_path):
    db, conn, bdir = _setup(tmp_path)
    old = _mk(db, conn, bdir, "old.sql.gz", days_old=30)
    fresh = _mk(db, conn, bdir, "fresh.sql.gz", days_old=1)
    count = run_retention(db, conn, bdir)
    assert count == 1
    assert db.get(BackupRecord, old.id) is None
    assert db.get(BackupRecord, fresh.id) is not None
    assert not (bdir / "old.sql.gz").exists()
    assert (bdir / "fresh.sql.gz").exists()
    db.close()


def test_retention_no_schedule_skips(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}"); create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg"); db.add(conn); db.commit(); db.refresh(conn)
    assert run_retention(db, conn, bdir) == 0   # 无计划 → 不清理
    db.close()


def test_retention_only_cleans_success(tmp_path):
    db, conn, bdir = _setup(tmp_path)
    from app.core.archive import compress_file
    raw = bdir / "x.sql"; raw.write_bytes(b"d"); gz = bdir / "f.sql.gz"; compress_file(raw, gz)
    rec = BackupRecord(connection_id=conn.id, trigger="manual", status="running",
                       file_path="f.sql.gz",
                       started_at=datetime.utcnow() - timedelta(days=30))
    db.add(rec); db.commit()
    assert run_retention(db, conn, bdir) == 0   # 非 success 不删
    db.close()
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_retention.py -v` → FAIL。

- [ ] **Step 3: 实现 retention.py** —— 创建 `app/services/retention.py`:
```python
from __future__ import annotations
import os
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session

from app.db.models import DbConnection, BackupRecord, Schedule


def _safe_unlink(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def run_retention(db: Session, conn: DbConnection, backup_dir: Path) -> int:
    """删除该连接超过最激进 retention_days 的成功备份(文件+记录)。无计划 → 0。"""
    schedules = (
        db.query(Schedule)
        .filter(Schedule.connection_id == conn.id, Schedule.enabled.is_(True))
        .all()
    )
    if not schedules:
        return 0
    days = min(s.retention_days for s in schedules)
    cutoff = datetime.utcnow() - timedelta(days=days)
    old = (
        db.query(BackupRecord)
        .filter(BackupRecord.connection_id == conn.id,
                BackupRecord.status == "success",
                BackupRecord.started_at < cutoff)
        .all()
    )
    count = 0
    for rec in old:
        if rec.file_path:
            _safe_unlink(backup_dir / rec.file_path)
        db.delete(rec)
        count += 1
    db.commit()
    return count
```

- [ ] **Step 4: 跑测试确认通过** —— `python3 -m pytest tests/test_retention.py -v` → PASS(3 个)。

- [ ] **Step 5: 提交** —— `git add app/services/retention.py tests/test_retention.py && git commit -m "feat(retention): 保留策略(按计划 retention_days 清理旧备份)"`

---

### Task 4: worker 编排(retention + notify)

**Files:** Modify `app/workers/jobs.py`; Test `tests/test_jobs.py`(追加)

- [ ] **Step 1: 写失败测试** —— 追加到 `tests/test_jobs.py`:
```python
def test_backup_worker_runs_retention_and_notify(monkeypatch, tmp_path):
    """worker 成功后应调用 retention 与 notify(monkeypatch 验证调用 + 现有断言不破)。"""
    from app.workers.jobs import _run_backup_sync
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr("app.workers.jobs.bootstrap_keys", lambda: ("secret", key))
    monkeypatch.setattr("app.services.backup_service.get_adapter", lambda t: FakeAdapter())
    monkeypatch.setattr("app.workers.jobs.ProgressReporter", lambda rid: FakeReporter())
    calls = {}
    monkeypatch.setattr("app.workers.jobs.run_retention", lambda db, conn, bdir: calls.setdefault("retention", True) or 0)
    monkeypatch.setattr("app.workers.jobs.notify_backup_result", lambda *a: calls.setdefault("notify", True) or {"email": False, "wechat": False})
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    bdir = tmp_path / "backups"; bdir.mkdir()
    db = _session._SessionLocal()
    conn = DbConnection(name="c", type="pg", password_enc=Crypto(key.encode("ascii")).encrypt("pw"))
    db.add(conn); db.commit(); db.refresh(conn)
    record = BackupRecord(connection_id=conn.id, trigger="manual", status="running", started_at=datetime.utcnow())
    db.add(record); db.commit(); db.refresh(record)
    conn_id, record_id = conn.id, record.id
    db.close()
    result = _run_backup_sync({"backup_dir": bdir}, conn_id, record_id)
    assert result["status"] == "success"
    assert calls.get("retention") is True
    assert calls.get("notify") is True
```
> 需在 `tests/test_jobs.py` 顶部确保已 import:`Fernet`、`Crypto`、`init_engine`/`create_all`、`_session`、`DbConnection`/`BackupRecord`、`datetime`、`FakeAdapter`/`FakeReporter`(该文件已有这些——参考现有 `test_run_backup_sync_wires_service`)。

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_jobs.py::test_backup_worker_runs_retention_and_notify -v` → FAIL(`run_retention`/`notify_backup_result` 未导入/未调用)。

- [ ] **Step 3: 改 worker** —— `app/workers/jobs.py`:
  - 顶部 import 补(在现有 restore/sync import 区):
    ```python
    from app.services.retention import run_retention
    from app.services.notifications import notify_backup_result
    ```
  - 在 `_run_backup_sync` 的 `rec = run_backup(...)` 之后、`return` 之前插入:
    ```python
        if rec.status == "success":
            try:
                run_retention(db, conn, ctx["backup_dir"])
            except Exception:
                pass  # 保留清理失败不影响备份结果
        try:
            notify_backup_result(db, crypto, conn, rec)
        except Exception:
            pass  # 通知失败不影响备份结果
    ```
    (放在现有 `return {"record_id": rec.id, "status": rec.status}` 之前。)

- [ ] **Step 4: 跑测试确认通过** —— `python3 -m pytest tests/test_jobs.py tests/test_backup_service.py -v` → PASS(worker 新测试 + 现有 worker/backup_service 测试不破)。

- [ ] **Step 5: 提交** —— `git add app/workers/jobs.py tests/test_jobs.py && git commit -m "feat(notify): worker 成功后跑保留 + 终态通知"`

---

### Task 5: /settings/notifications 路由

**Files:** Create `app/routers/settings.py`; Modify `app/main.py`; Test `tests/test_settings_api.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_settings_api.py`:
```python
import pytest


@pytest.fixture
def authed(client):
    from app.db import session as _session
    from app.services.account_service import ensure_account
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw"); db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_settings_require_auth(client):
    assert client.get("/api/v1/settings/notifications").status_code == 401


def test_get_returns_defaults_when_empty(authed):
    r = authed.get("/api/v1/settings/notifications").json()
    assert r["email_enabled"] is False
    assert "smtp_password" not in r and "wechat_secret" not in r


def test_put_updates_and_hides_secrets(authed):
    r = authed.put("/api/v1/settings/notifications", json={
        "email_enabled": True, "smtp_host": "h", "smtp_port": 465, "smtp_ssl": True,
        "smtp_user": "u", "smtp_password": "pw", "smtp_from": "a@b", "recipients": "x@y",
        "wechat_enabled": False, "notify_on_success": True, "notify_on_failure": True,
    }).json()
    assert r["email_enabled"] is True
    assert "smtp_password" not in r
    got = authed.get("/api/v1/settings/notifications").json()
    assert got["smtp_host"] == "h"
    assert "smtp_password" not in got
```

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_settings_api.py -v` → FAIL(404)。

- [ ] **Step 3: 实现 routers/settings.py** —— 创建:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import NotificationConfig
from app.deps import get_current_account
from app.schemas.notification import NotificationSettings, NotificationSettingsOut

router = APIRouter()


def _to_out(cfg: NotificationConfig) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        email_enabled=cfg.email_enabled, smtp_host=cfg.smtp_host, smtp_port=cfg.smtp_port,
        smtp_ssl=cfg.smtp_ssl, smtp_starttls=cfg.smtp_starttls, smtp_user=cfg.smtp_user,
        smtp_from=cfg.smtp_from, recipients=cfg.recipients,
        wechat_enabled=cfg.wechat_enabled, wechat_corp_id=cfg.wechat_corp_id,
        wechat_agent_id=cfg.wechat_agent_id, notify_on_success=cfg.notify_on_success,
        notify_on_failure=cfg.notify_on_failure, created_at=cfg.created_at,
    )


@router.get("/settings/notifications", response_model=NotificationSettingsOut)
def get_notifications(db: Session = Depends(get_db), _=Depends(get_current_account)):
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        cfg = NotificationConfig()
        db.add(cfg); db.commit(); db.refresh(cfg)
    return _to_out(cfg)


@router.put("/settings/notifications", response_model=NotificationSettingsOut)
def put_notifications(payload: NotificationSettings, request: Request,
                      db: Session = Depends(get_db), _=Depends(get_current_account)):
    crypto = request.app.state.crypto
    cfg = db.query(NotificationConfig).first()
    if cfg is None:
        cfg = NotificationConfig()
        db.add(cfg)
    cfg.email_enabled = payload.email_enabled
    cfg.smtp_host = payload.smtp_host
    cfg.smtp_port = payload.smtp_port
    cfg.smtp_ssl = payload.smtp_ssl
    cfg.smtp_starttls = payload.smtp_starttls
    cfg.smtp_user = payload.smtp_user
    cfg.smtp_from = payload.smtp_from
    cfg.recipients = payload.recipients
    cfg.wechat_enabled = payload.wechat_enabled
    cfg.wechat_corp_id = payload.wechat_corp_id
    cfg.wechat_agent_id = payload.wechat_agent_id
    cfg.notify_on_success = payload.notify_on_success
    cfg.notify_on_failure = payload.notify_on_failure
    # 凭据:非空才更新(避免空串覆盖已存密文)
    if payload.smtp_password:
        cfg.smtp_password_enc = crypto.encrypt(payload.smtp_password)
    if payload.wechat_secret:
        cfg.wechat_secret_enc = crypto.encrypt(payload.wechat_secret)
    db.commit(); db.refresh(cfg)
    return _to_out(cfg)
```

- [ ] **Step 4: 挂载** —— `app/main.py`:import 加 `settings`(`from app.routers import health, auth, connections, jobs, backups, schedules, dashboard, restore, cloud, settings`),并 `app.include_router(settings.router, prefix="/api/v1", tags=["settings"])`。

- [ ] **Step 5: 跑测试 + 全量回归** —— `python3 -m pytest tests/test_settings_api.py -v`(PASS 3 个);`python3 -m pytest -p no:warnings -q`(全绿,~108 passed)。

- [ ] **Step 6: 提交** —— `git add app/routers/settings.py app/main.py tests/test_settings_api.py && git commit -m "feat(notify): /settings/notifications 路由(GET/PUT,凭据不回传)"`

---

## 完成标准
- 全量后端测试绿(~108 passed,原 100 + 新增,无回归)。
- 备份成功后:worker 跑保留清理(按计划 retention_days)+ 按配置发通知(成功/失败)。
- 通知凭据(SMTP 密码、微信 secret)Fernet 加密落库,API 不回传。
- 邮件用 stdlib smtplib(SSL/STARTTLS);企业微信用 stdlib urllib(gettoken→send)。

## 留给后续
- 独立 `notify_job`(异步通知,spec §6)+ 企业微信 token 内存缓存。
- 通知发送测试覆盖(真实 SMTP/微信需凭据;本轮用 monkeypatch 打桩 `_send_email`/`_send_wechat`)。
- Settings.vue / Logs.vue 前端页 + `/logs` 路由(下一阶段)。
- 手动备份是否触发保留的开关(当前按连接计划 retention,无计划则跳过)。
