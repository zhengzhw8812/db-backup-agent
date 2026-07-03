from arq.connections import RedisSettings

from app.config import settings
from app.db.session import init_engine, create_all


async def on_startup(ctx):
    init_engine(settings.sqlite_url)
    create_all()
    ctx["backup_dir"] = settings.data_dir / "backups"


class WorkerSettings:
    # Task 8 后改为: functions = [backup_job]  (届时加 from app.workers.jobs import backup_job)
    functions = []
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
