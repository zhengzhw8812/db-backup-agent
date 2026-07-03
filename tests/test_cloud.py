import pytest
from app.cloud.base import CloudConfig, get_storage, register_storage


class FakeMinio:
    """模拟 minio.Minio:记录上传/删除,内存存对象。"""
    def __init__(self, endpoint, access_key=None, secret_key=None, secure=True, region=None):
        self.endpoint = endpoint
        self.objects = {}

    def fput_object(self, bucket, key, path):
        with open(path, "rb") as f:
            self.objects[(bucket, key)] = f.read()
        return key

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)

    def bucket_exists(self, bucket):
        return True


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_storage("nope")


def test_s3_upload_returns_uri_and_prefixes_key(monkeypatch, tmp_path):
    monkeypatch.setattr("app.cloud.s3.Minio", FakeMinio)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    f = tmp_path / "b.gz"
    f.write_bytes(b"payload")
    cfg = CloudConfig(endpoint="localhost:9000", access_key="ak", secret_key="sk",
                      bucket="bk", region=None, secure=False, prefix="pre")
    uri = a.upload(cfg, str(f), "b.gz")
    assert uri == "s3://bk/pre/b.gz"


def test_s3_delete_removes_object(monkeypatch):
    monkeypatch.setattr("app.cloud.s3.Minio", FakeMinio)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    cfg = CloudConfig(endpoint="h:9000", access_key="ak", secret_key="sk", bucket="bk", prefix="")
    # 先放一个对象再删
    a._client(cfg).objects[("bk", "x.gz")] = b"x"
    a.delete(cfg, "x.gz")
    assert ("bk", "x.gz") not in a._client(cfg).objects


def test_s3_test_raises_when_bucket_missing(monkeypatch):
    class NoBucket(FakeMinio):
        def bucket_exists(self, bucket): return False
    monkeypatch.setattr("app.cloud.s3.Minio", NoBucket)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    with pytest.raises(ValueError):
        a.test(CloudConfig(endpoint="h:9000", access_key="ak", secret_key="sk", bucket="missing"))
