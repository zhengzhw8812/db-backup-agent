from __future__ import annotations
import json

TERMINAL = ("success", "failed", "cancelled")


async def event_stream(record_id: int, kind: str, initial_status: str | None):
    """SSE 事件流:先按 DB 当前状态补一条初始事件,再订阅 Redis pub/sub。

    - 若订阅时任务已终态,推一条并立即结束(防止"订阅时已结束"→ 客户端永久挂起);
    - 否则推一条当前状态后转入 pub/sub,直至收到终态事件。
    Redis 仅用于实时推送;初始状态来自 DB,保证不丢终态。"""
    if initial_status in TERMINAL:
        yield f"data: {json.dumps({'stage': initial_status})}\n\n"
        return

    from app.redis_client import get_async_redis
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"{kind}:{record_id}")
    try:
        if initial_status:
            yield f"data: {json.dumps({'stage': initial_status})}\n\n"
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
        await pubsub.unsubscribe(f"{kind}:{record_id}")
        await pubsub.close()
