from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.bootstrap import bootstrap_keys
from app.core.crypto import Crypto
from app.db.session import init_engine, create_all, get_db
from app.services.account_service import ensure_account
from app.routers import health, auth, connections, jobs, backups, schedules


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.scheduler import SchedulerService
    sched = SchedulerService(app)
    await sched.start()
    app.state.scheduler = sched
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
    app.add_middleware(SessionMiddleware, secret_key=secret_key, same_site="lax", https_only=False)
    app.state.crypto = Crypto(fernet_key.encode("ascii"))
    app.state.arq = None
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(connections.router, prefix="/api/v1/connections", tags=["connections"])
    app.include_router(jobs.router, prefix="/api/v1", tags=["jobs"])
    app.include_router(backups.router, prefix="/api/v1", tags=["backups"])
    app.include_router(schedules.router, prefix="/api/v1", tags=["schedules"])
    return app


app = create_app()
