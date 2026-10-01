"""NFS/SMB 存储适配器:落到挂载点的 test/upload/delete。"""
import pytest

from app.cloud.base import CloudConfig
from app.cloud.shares import ShareStorageAdapter


def _cfg(tmp_path):
    return CloudConfig(endpoint="", access_key="", secret_key="", bucket="",
                       mount_point=str(tmp_path))


def test_share_probe_writes_and_reads(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    a = ShareStorageAdapter("nfs")
    a.test(_cfg(tmp_path))
    assert list(tmp_path.iterdir()) == []  # 探针文件已清理


def test_share_upload_with_prefix_and_delete(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    a = ShareStorageAdapter("smb")
    src = tmp_path / "src.sql.gz"
    src.write_bytes(b"data")
    cfg = _cfg(tmp_path)
    cfg.prefix = "pre"
    uri = a.upload(cfg, str(src), "k.sql.gz")
    assert uri.startswith("share://pre/")
    assert (tmp_path / "pre" / "k.sql.gz").read_bytes() == b"data"
    a.delete(cfg, "k.sql.gz")
    assert not (tmp_path / "pre" / "k.sql.gz").exists()


def test_share_test_requires_mountpoint(tmp_path):
    """挂载点不存在(未挂载)→ test 报错。"""
    a = ShareStorageAdapter("nfs")
    with pytest.raises(RuntimeError):
        a.test(_cfg(tmp_path / "nope"))
