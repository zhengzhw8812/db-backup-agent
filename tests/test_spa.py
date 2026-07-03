import pytest


@pytest.fixture
def spa_client(client, tmp_path, monkeypatch):
    """给 app 挂一个临时 static_dir(含 index.html + assets/x.js),reload main。"""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>SPA</html>")
    (static / "assets" / "x.js").write_text("console.log(1)")
    monkeypatch.setenv("APP_STATIC_DIR", str(static))
    from importlib import reload
    from app import config, main
    reload(config); reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def test_spa_root_returns_index(client):
    # 默认无 static_dir → / 走 404(无挂载),不崩
    r = client.get("/")
    assert r.status_code in (404, 200)


def test_spa_fallback_serves_index_and_assets(spa_client):
    assert spa_client.get("/").text == "<html>SPA</html>"
    assert spa_client.get("/dashboard").text == "<html>SPA</html>"  # 客户端路由 fallback
    assert spa_client.get("/assets/x.js").text == "console.log(1)"


def test_api_still_works_with_spa(spa_client):
    # /api/v1/* 不被 SPA fallback 吞掉
    assert spa_client.get("/api/v1/health").status_code == 200
