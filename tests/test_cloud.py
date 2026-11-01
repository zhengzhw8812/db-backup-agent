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


class _Obj:
    def __init__(self, name):
        self.object_name = name


def test_s3_list_prefix_strips_dest_prefix(monkeypatch):
    class ListMinio(FakeMinio):
        def list_objects(self, bucket, prefix=None, recursive=False):
            assert prefix == "pre/selfbackup/"
            return [_Obj("pre/selfbackup/app-20260101-000000.db.gz"),
                    _Obj("pre/selfbackup/app-20260102-000000.sql")]
    monkeypatch.setattr("app.cloud.s3.Minio", ListMinio)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    cfg = CloudConfig(endpoint="h:9000", access_key="ak", secret_key="sk", bucket="bk", prefix="pre")
    # 返回用户空间 key(已去掉 cfg.prefix),可直接喂给 delete()
    assert a.list_prefix(cfg, "selfbackup/") == [
        "selfbackup/app-20260101-000000.db.gz",
        "selfbackup/app-20260102-000000.sql",
    ]


def test_s3_list_prefix_without_dest_prefix(monkeypatch):
    class ListMinio(FakeMinio):
        def list_objects(self, bucket, prefix=None, recursive=False):
            return [_Obj("selfbackup/a.db.gz")]
    monkeypatch.setattr("app.cloud.s3.Minio", ListMinio)
    from app.cloud.s3 import S3StorageAdapter
    a = S3StorageAdapter()
    cfg = CloudConfig(endpoint="h:9000", access_key="ak", secret_key="sk", bucket="bk", prefix="")
    assert a.list_prefix(cfg, "selfbackup/") == ["selfbackup/a.db.gz"]


def test_shares_list_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.ismount", lambda p: True)
    from app.cloud.shares import ShareStorageAdapter
    a = ShareStorageAdapter("nfs")
    base = tmp_path / "mp" / "pre" / "selfbackup"
    base.mkdir(parents=True)
    (base / "app-20260101-000000.db.gz").write_bytes(b"1")
    (base / "app-20260102-000000.sql").write_bytes(b"2")
    (base / "not-mine.txt").write_bytes(b"3")
    cfg = CloudConfig(endpoint="", access_key="", secret_key="", bucket="",
                      prefix="pre", mount_point=str(tmp_path / "mp"))
    # list_prefix 不做白名单过滤(过滤归调用方),列出前缀下全部文件
    assert a.list_prefix(cfg, "selfbackup/") == [
        "selfbackup/app-20260101-000000.db.gz",
        "selfbackup/app-20260102-000000.sql",
        "selfbackup/not-mine.txt",
    ]
