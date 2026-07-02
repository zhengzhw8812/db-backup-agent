from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import settings
from app.db.session import init_engine, create_all
from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "sqlite").mkdir(parents=True, exist_ok=True)
    init_engine(settings.sqlite_url)
    create_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="DB Backup Agent", version="3.0.0", lifespan=lifespan)
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
