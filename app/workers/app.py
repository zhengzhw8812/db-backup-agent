from arq.connections import RedisSettings

from app.config import settings
from app.db.session import init_engine, create_all
from app.workers.jobs import backup_job, restore_job, sync_job, verify_job


async def on_startup(ctx):
    # web 进程可能在启动时执行 SQL 导入还原:等其完成再打开引擎,避免写到被替换的旧 inode
    from app.services.self_backup import wait_for_restore

    wait_for_restore(settings.data_dir)
    init_engine(settings.sqlite_url)
    create_all()
    ctx["backup_dir"] = settings.data_dir / "backups"


class WorkerSettings:
    functions = [backup_job, restore_job, sync_job, verify_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
