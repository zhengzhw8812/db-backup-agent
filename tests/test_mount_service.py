"""挂载服务:mount/umount 参数、SMB 凭据文件、幂等、启动重挂。"""
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import Crypto
from app.db.models import CloudDestination


@pytest.fixture
def crypto(tmp_path, monkeypatch):
    import app.services.mount_service as ms
    monkeypatch.setattr(ms, "MOUNT_ROOT", tmp_path / "mnt")
    return Crypto(Fernet.generate_key())


@pytest.fixture
def fake_run(monkeypatch):
    """替换 subprocess.run,记录 argv;可注入 returncode/stderr。"""
    import app.services.mount_service as ms

    calls = []

    def fake(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(ms.subprocess, "run", fake)
    return calls


def _dest(provider, mount_config, crypto, db, *, password="pw"):
    d = CloudDestination(
        name="share", provider=provider,
        endpoint="", bucket="",
        access_key_enc=crypto.encrypt("AK"), secret_enc=crypto.encrypt("SK"),
        enabled=True,
        mount_config=json.dumps(mount_config),
        mount_password_enc=crypto.encrypt(password) if provider == "smb" else None,
    )
    db.add(d); db.commit(); db.refresh(d)
    return d


def test_mount_nfs_builds_expected_argv(tmp_path, monkeypatch, crypto, fake_run):
    import app.services.mount_service as ms

    db = _session_db(tmp_path)
    d = _dest("nfs", {"server": "nas", "export": "/vol/bk", "version": "nfs4"}, crypto, db)
    ms.mount_destination(d, crypto)
    argv = fake_run[0]
    assert argv[0] == "mount" and "-t" in argv and "nfs4" in argv
    assert any("vers=4.1" in a for a in argv)
    assert "nas:/vol/bk" in argv
    db.close()


def test_mount_smb_uses_creds_file_not_argv(tmp_path, monkeypatch, crypto, fake_run):
    import app.services.mount_service as ms

    db = _session_db(tmp_path)
    d = _dest("smb", {"server": "nas", "share": "bk", "username": "u"}, crypto, db, password="s3cret")
    ms.mount_destination(d, crypto)
    argv = fake_run[0]
    assert "s3cret" not in " ".join(argv)  # 密码绝不进命令行
    cred = [a for a in argv if "credentials=" in a]
    assert cred
    # argv 记录的是格式化后的路径;凭据文件已删除,无法再读 → 断言删除行为
    import glob, os
    assert not glob.glob(str((tmp_path / "mnt" / ".creds" / "dest-*.creds")))
    db.close()


def test_mount_idempotent_when_already_mounted(tmp_path, monkeypatch, crypto, fake_run):
    import app.services.mount_service as ms

    monkeypatch.setattr(ms.os.path, "ismount", lambda p: True)
    db = _session_db(tmp_path)
    d = _dest("nfs", {"server": "nas", "export": "/v"}, crypto, db)
    ms.mount_destination(d, crypto)
    db.close()
    assert fake_run == []  # 已挂载 → 不执行 mount


def test_mount_failure_raises_with_stderr(tmp_path, monkeypatch, crypto):
    import app.services.mount_service as ms

    monkeypatch.setattr(ms.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=32, stderr=b"mount error"))
    monkeypatch.setattr(ms.os.path, "ismount", lambda p: False)
    db = _session_db(tmp_path)
    d = _dest("nfs", {"server": "nas", "export": "/v"}, crypto, db)
    with pytest.raises(RuntimeError) as ei:
        ms.mount_destination(d, crypto)
    db.close()
    assert "mount error" in str(ei.value)


def test_remount_all_logs_and_continues(tmp_path, monkeypatch, crypto):
    import app.services.mount_service as ms
    from app.db.session import init_engine, create_all
    from app.db import session as _session
    import app.db.models  # noqa
    from app.db.models import SystemLog

    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    db = _session._SessionLocal()
    _dest("nfs", {"server": "a", "export": "/v"}, crypto, db)
    d2 = _dest("nfs", {"server": "b", "export": "/w"}, crypto, db)

    real_mount = ms.mount_destination
    def flaky(dest, cr):
        if dest.id == d2.id:
            raise RuntimeError("boom")
    monkeypatch.setattr(ms, "mount_destination", flaky)

    ms.remount_all(db, crypto)
    db.close()
    db = _session._SessionLocal()
    err = db.query(SystemLog).filter(SystemLog.source == "mount", SystemLog.level == "error").all()
    db.close()
    assert len(err) == 1 and "boom" in err[0].message


def _session_db(tmp_path):
    from app.db.session import init_engine, create_all
    from app.db import session as _session
    import app.db.models  # noqa

    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    return _session._SessionLocal()
