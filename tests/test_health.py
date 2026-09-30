def test_health_ok(client, monkeypatch):
    async def fake_redis_ok():
        return True

    monkeypatch.setattr("app.routers.health._redis_ok", fake_redis_ok)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["components"] == {"db": True, "redis": True, "scheduler": True}
    assert body["version"]


def test_health_still_200_when_redis_down(client, monkeypatch):
    """Redis 不可达:仍返回 200 + degraded(docker healthcheck 依赖 200,不能 5xx)。"""
    async def fake_redis_ok():
        return False

    monkeypatch.setattr("app.routers.health._redis_ok", fake_redis_ok)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["components"]["redis"] is False
    assert body["components"]["db"] is True
