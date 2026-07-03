from __future__ import annotations
import json
import redis

from app.config import settings


def _channel(record_id: int) -> str:
    return f"job:{record_id}"


def _cancel_key(record_id: int) -> str:
    return f"cancel:{record_id}"


class ProgressReporter:
    """向 Redis pub/sub 上报进度;同时提供取消检查。"""

    def __init__(self, record_id: int, client: redis.Redis | None = None):
        self.record_id = record_id
        self._client = client or redis.Redis.from_url(settings.redis_url)

    def report(self, stage: str, detail: str = "") -> None:
        self._client.publish(
            _channel(self.record_id),
            json.dumps({"stage": stage, "detail": detail}),
        )

    def is_cancelled(self) -> bool:
        return bool(self._client.exists(_cancel_key(self.record_id)))


def request_cancel(record_id: int, client: redis.Redis | None = None) -> None:
    (client or redis.Redis.from_url(settings.redis_url)).set(_cancel_key(record_id), "1")
