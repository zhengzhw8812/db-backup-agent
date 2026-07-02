import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    from importlib import reload
    from app import config
    reload(config)
    from app import main
    reload(main)
    with TestClient(main.app) as c:
        yield c
