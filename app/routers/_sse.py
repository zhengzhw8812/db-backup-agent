from __future__ import annotations
import json

TERMINAL = ("success", "failed", "cancelled")


def _read_status(record_id: int, kind: str) -> str | None:
    """读任务当前状态(kind: job→BackupRecord / restore→RestoreRecord)。

    自建会话:调用点在 SSE 流生成器内,不在请求依赖的作用域中。"""
    from app.db import session as _session
    from app.db.models import BackupRecord, RestoreRecord

    db = _session._SessionLocal()
    try:
        model = BackupRecord if kind == "job" else RestoreRecord
        rec = db.get(model, record_id)
        return rec.status if rec else None
    finally:
        db.close()


async def event_stream(record_id: int, kind: str):
    """SSE 事件流:终态快路径 → 订阅 → 复读 → 监听。

    - 快路径:订阅前已终态,直接推一条并结束(终态是终局值,不会有后续
      事件,因此无需 Redis);
    - 竞态窗口:任务在"首次读取(=running)之后、订阅之前"结束时,终态
      消息会在订阅前发布而丢失——所以订阅后再读一次状态兜底;
    - 订阅之后任务才结束的,终态消息必然进入 pubsub 队列,由监听循环接收。
    三条路径合起来覆盖全部时序,客户端不会永久挂起。"""
    channel = f"{kind}:{record_id}"

    initial = _read_status(record_id, kind)
    if initial in TERMINAL:
        yield f"data: {json.dumps({'stage': initial})}\n\n"
        return

    from app.redis_client import get_async_redis

    pubsub = get_async_redis().pubsub()
    await pubsub.subscribe(channel)
    try:
        status = _read_status(record_id, kind)
        if status in TERMINAL:
            yield f"data: {json.dumps({'stage': status})}\n\n"
            return
        if status:
            yield f"data: {json.dumps({'stage': status})}\n\n"
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                data = msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"]
                yield f"data: {data}\n\n"
                try:
                    if json.loads(data).get("stage") in TERMINAL:
                        return
                except Exception:
                    pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
