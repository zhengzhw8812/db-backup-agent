"""SSE 事件流:订阅时序、终态短路、记录缺失 404。"""
import json

import pytest

from app.db import session as _session
from app.db.models import BackupRecord, DbConnection


class FakePubSub:
    """模拟 redis asyncio pubsub:记录调用顺序,回放预置消息。"""

    def __init__(self, calls: list, messages: list[str]):
        self._calls = calls
        self._messages = messages

    async def subscribe(self, channel):
        self._calls.append(("subscribe", channel))

    async def unsubscribe(self, channel):
        self._calls.append(("unsubscribe", channel))

    async def close(self):
        self._calls.append(("close",))

    async def listen(self):
        # 真实 redis 的 listen() 会先吐订阅确认消息,再吐 channel 消息
        yield {"type": "subscribe", "channel": "sub-confirmation"}
        for m in self._messages:
            yield {"type": "message", "data": m.encode()}


class FakeRedis:
    def __init__(self, calls: list, messages: list[str]):
        self._calls = calls
        self._messages = messages

    def pubsub(self):
        return FakePubSub(self._calls, self._messages)


@pytest.fixture
def authed(client):
    from app.services.account_service import ensure_account

    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(DbConnection(name="c", type="pg"))
        db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def _make_backup_record(status: str) -> int:
    db = _session._SessionLocal()
    try:
        conn = db.query(DbConnection).first()
        rec = BackupRecord(connection_id=conn.id, trigger="manual", status=status)
        db.add(rec)
        db.commit()
        db.refresh(rec)
        return rec.id
    finally:
        db.close()


def test_subscribe_happens_before_final_status_read(authed, monkeypatch):
    """终态竞态修复:对 running 任务,订阅必须先于最后一次状态读取。

    若最后一次读在订阅前,任务在其后、订阅前结束的话,终态事件丢失,
    客户端永久挂起。"""
    calls: list = []
    terminal = json.dumps({"stage": "success", "detail": ""})
    fake_redis = FakeRedis(calls, [terminal])

    import app.redis_client as redis_client
    import app.routers._sse as sse

    monkeypatch.setattr(redis_client, "get_async_redis", lambda: fake_redis)

    real_read = sse._read_status

    def spy(record_id, kind):
        calls.append(("read", record_id))
        return real_read(record_id, kind)

    monkeypatch.setattr(sse, "_read_status", spy)

    rid = _make_backup_record("running")
    resp = authed.get(f"/api/v1/jobs/{rid}/events")
    assert resp.status_code == 200
    assert calls[0] == ("read", rid)  # 快路径先读一次(非终态才继续)
    subs = calls.index(("subscribe", f"job:{rid}"))
    last_read = max(i for i, c in enumerate(calls) if c[0] == "read")
    assert subs < last_read  # 最后一次读在订阅之后 → 竞态窗口闭合
    # 初始 running 事件 + 队列中的终态 success 事件都到达客户端
    assert '"stage": "running"' in resp.text
    assert '"stage": "success"' in resp.text
    assert ("unsubscribe", f"job:{rid}") in calls and ("close",) in calls


def test_terminal_in_db_needs_no_redis(authed, monkeypatch):
    """订阅前已终态:直接推一条终态并结束,全程不触达 Redis。"""
    import app.redis_client as redis_client

    def boom(*a, **k):
        raise AssertionError("已终态任务不应触达 Redis")

    monkeypatch.setattr(redis_client, "get_async_redis", boom)

    rid = _make_backup_record("success")
    resp = authed.get(f"/api/v1/jobs/{rid}/events")
    assert resp.status_code == 200
    assert resp.text.count("data:") == 1
    assert '"stage": "success"' in resp.text


def test_events_404_for_missing_record(authed):
    """记录不存在:404,而不是挂起等待永远不会来的事件。"""
    assert authed.get("/api/v1/jobs/999999/events").status_code == 404
    assert authed.get("/api/v1/restore/999999/events").status_code == 404
