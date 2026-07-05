import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """模块级缓存(S3 客户端 lru_cache)在测试间隔离,避免互相污染。"""
    try:
        from app.cloud import s3 as _s3
        _s3._build_client.cache_clear()
    except Exception:
        pass
    yield
    try:
        from app.cloud import s3 as _s3
        _s3._build_client.cache_clear()
    except Exception:
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_INITIAL_ADMIN_PASSWORD", raising=False)
    from importlib import reload
    from app import config
    reload(config)
    from app import main
    reload(main)
    with TestClient(main.app) as c:
        yield c
