from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.bootstrap import bootstrap_keys
from app.core.crypto import Crypto
from app.db.session import init_engine, create_all, get_db
from app.services.account_service import ensure_account
from app.routers import health, auth, connections, jobs, backups, schedules, dashboard, restore, cloud, logs
from app.routers import settings as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时补齐新列/回填,再清理上次崩溃残留的 running 记录
    from app.services.maintenance import migrate_schema, reap_stale_running
    db = next(get_db())
    try:
        migrate_schema(db)
        reap_stale_running(db)
    finally:
        db.close()

    from app.services.scheduler import SchedulerService
    sched = SchedulerService(app)
    if settings.scheduler_enabled:
        await sched.start()
    app.state.scheduler = sched  # 始终存在,便于 CRUD(scheduler_enabled=False 时仅不入队触发)
    try:
        yield
    finally:
        sched.stop()


def create_app() -> FastAPI:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "sqlite").mkdir(parents=True, exist_ok=True)
    secret_key, fernet_key = bootstrap_keys()

    init_engine(settings.sqlite_url)
    create_all()
    if settings.initial_admin_password:
        db = next(get_db())
        try:
            ensure_account(db, settings.initial_admin_user, settings.initial_admin_password)
        finally:
            db.close()

    app = FastAPI(title="DB Backup Agent", version="3.0.0", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=secret_key, same_site="lax", https_only=settings.cookie_secure)
    app.state.crypto = Crypto(fernet_key.encode("ascii"))
    app.state.arq = None
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(connections.router, prefix="/api/v1/connections", tags=["connections"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    app.include_router(backups.router, prefix="/api/v1", tags=["backups"])
    app.include_router(schedules.router, prefix="/api/v1", tags=["schedules"])
    app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
    app.include_router(restore.router, prefix="/api/v1", tags=["restore"])
    app.include_router(cloud.router, prefix="/api/v1", tags=["cloud"])
    app.include_router(settings_router.router, prefix="/api/v1", tags=["settings"])
    app.include_router(logs.router, prefix="/api/v1", tags=["logs"])

    # 生产:托管前端 SPA(仅当 static_dir 存在;dev 由 Vite 服务,测试无该目录 → 跳过)
    static_dir = settings.static_dir
    if static_dir.exists():
        from fastapi.responses import FileResponse

        @app.get("/{full_path:path}")
        async def _spa(full_path: str):
            # 仅当解析后路径仍在 static_dir 内且是文件时才返回该文件;
            # 否则一律回退 index.html(客户端路由 + 防 ../../etc/passwd 遍历)。
            base = static_dir.resolve()
            candidate = (static_dir / full_path).resolve()
            if full_path and (candidate == base or base in candidate.parents) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
