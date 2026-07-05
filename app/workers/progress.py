from __future__ import annotations
import json
import redis

from app.config import settings


def _channel(record_id: int, kind: str = "job") -> str:
    return f"{kind}:{record_id}"


def _cancel_key(record_id: int, kind: str = "job") -> str:
    return f"{kind}:cancel:{record_id}"


class ProgressReporter:
    """向 Redis pub/sub 上报进度;同时提供取消检查。

    kind 区分备份(job)/恢复(restore)频道 —— 两张记录表 id 各自递增,
    不加命名空间会撞车(backup id=5 与 restore id=5 共用 job:5)。"""

    def __init__(self, record_id: int, client: redis.Redis | None = None, kind: str = "job"):
        self.record_id = record_id
        self.kind = kind
        self._client = client or redis.Redis.from_url(settings.redis_url)

    def report(self, stage: str, detail: str = "") -> None:
        # 进度上报是"尽力而为":Redis 瞬时不可用不应让正在执行的备份失败
        try:
            self._client.publish(
                _channel(self.record_id, self.kind),
                json.dumps({"stage": stage, "detail": detail}),
            )
        except Exception:
            pass

    def is_cancelled(self) -> bool:
        # Redis 不可达时假定"不可取消",而不是抛异常让备份失败
        try:
            return bool(self._client.exists(_cancel_key(self.record_id, self.kind)))
        except Exception:
            return False


def request_cancel(record_id: int, client: redis.Redis | None = None, kind: str = "job") -> None:
    (client or redis.Redis.from_url(settings.redis_url)).set(_cancel_key(record_id, kind), "1")
