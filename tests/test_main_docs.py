"""/docs 暴露面与 GZip 装配(SPA 回归归 E2E)。"""
from importlib import reload

from fastapi.testclient import TestClient


def test_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_enabled_with_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DOCS_ENABLED", "true")
    from app import config
    reload(config)
    from app import main
    reload(main)
    with TestClient(main.app) as c:
        assert c.get("/docs").status_code == 200


def test_gzip_middleware_present(client):
    from starlette.middleware.gzip import GZipMiddleware

    assert any(m.cls is GZipMiddleware for m in client.app.user_middleware)
