from fastapi import FastAPI

from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="DB Backup Agent", version="3.0.0")
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
