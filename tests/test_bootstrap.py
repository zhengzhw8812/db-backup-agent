from cryptography.fernet import Fernet


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    from importlib import reload
    from app import config, bootstrap
    reload(config)
    reload(bootstrap)
    return bootstrap


def test_keys_generated_and_persisted(tmp_path, monkeypatch):
    b = _reload(tmp_path, monkeypatch)
    s1, f1 = b.bootstrap_keys()
    assert len(s1) > 20
    Fernet(f1.encode("ascii"))  # 是合法 Fernet key,不抛异常
    s2, f2 = b.bootstrap_keys()
    assert (s1, f1) == (s2, f2)


def test_keys_differ_across_data_dirs(tmp_path, monkeypatch):
    b = _reload(tmp_path / "a", monkeypatch)
    sa, _ = b.bootstrap_keys()
    b = _reload(tmp_path / "b", monkeypatch)
    sb, _ = b.bootstrap_keys()
    assert sa != sb  # 不同实例生成的密钥不同,无全局弱默认
