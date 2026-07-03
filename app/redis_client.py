import redis.asyncio as aioredis
from app.config import settings

_async_pool: aioredis.ConnectionPool | None = None


def get_async_redis() -> aioredis.Redis:
    global _async_pool
    if _async_pool is None:
        _async_pool = aioredis.ConnectionPool.from_url(settings.redis_url)
    return aioredis.Redis(connection_pool=_async_pool)
