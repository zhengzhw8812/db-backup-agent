from fastapi import APIRouter, Request
from sqlalchemy import text

from app.config import settings

router = APIRouter()


def _db_ok() -> bool:
    try:
        from app.db import session as _session

        db = _session._SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return True
    except Exception:
        return False


async def _redis_ok() -> bool:
    try:
        from app.redis_client import get_async_redis

        return bool(await get_async_redis().ping())
    except Exception:
        return False


@router.get("/health")
async def health(request: Request):
    """组件级健康状态。恒 200(docker healthcheck 依赖非 5xx),
    具体健康度经 status/components 表达,不泄露细节。"""
    sched = getattr(request.app.state, "scheduler", None)
    # 刻意关闭调度器(APP_SCHEDULER_ENABLED=false)不视为降级
    scheduler_ok = (not settings.scheduler_enabled) or bool(getattr(sched, "running", False))
    components = {
        "db": _db_ok(),
        "redis": await _redis_ok(),
        "scheduler": scheduler_ok,
    }
    return {
        "status": "ok" if all(components.values()) else "degraded",
        "components": components,
        "version": request.app.version,
    }
