"""S3 适配器:重试与客户端缓存的单元测试(不连真实 MinIO)。"""
import os
import app.cloud.s3 as s3mod
from app.cloud.base import CloudConfig


def test_build_client_caches_per_credentials():
    s3mod._build_client.cache_clear()
    c1 = s3mod._build_client("h:9", "ak", "sk", True, "")
    c2 = s3mod._build_client("h:9", "ak", "sk", True, "")
    assert c1 is c2  # 同凭据复用
    c3 = s3mod._build_client("h:9", "ak2", "sk", True, "")  # 不同凭据 → 新实例
    assert c3 is not c1
    s3mod._build_client.cache_clear()


def test_upload_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    class FakeClient:
        def fput_object(self, *a):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("transient 503")

    monkeypatch.setattr(s3mod, "_build_client", lambda *a: FakeClient())
    monkeypatch.setattr(s3mod.time, "sleep", lambda *a: None)
    cfg = CloudConfig(endpoint="h:9", access_key="ak", secret_key="sk", bucket="bk")
    uri = s3mod.S3StorageAdapter().upload(cfg, os.path.abspath(__file__), "k")
    assert attempts["n"] == 3
    assert uri == "s3://bk/k"


def test_upload_exhausts_retries_and_raises(monkeypatch):
    class FakeClient:
        def fput_object(self, *a):
            raise RuntimeError("permanent")
    monkeypatch.setattr(s3mod, "_build_client", lambda *a: FakeClient())
    monkeypatch.setattr(s3mod.time, "sleep", lambda *a: None)
    cfg = CloudConfig(endpoint="h:9", access_key="ak", secret_key="sk", bucket="bk")
    import pytest
    with pytest.raises(RuntimeError):
        s3mod.S3StorageAdapter().upload(cfg, os.path.abspath(__file__), "k")
