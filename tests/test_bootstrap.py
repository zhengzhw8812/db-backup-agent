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
    assert (tmp_path / "keys" / "keys.json").exists()
    s2, f2 = b.bootstrap_keys()
    assert (s1, f1) == (s2, f2)


def test_keys_differ_across_data_dirs(tmp_path, monkeypatch):
    b = _reload(tmp_path / "a", monkeypatch)
    sa, _ = b.bootstrap_keys()
    b = _reload(tmp_path / "b", monkeypatch)
    sb, _ = b.bootstrap_keys()
    assert sa != sb  # 不同实例生成的密钥不同,无全局弱默认


def test_env_provided_keys_take_precedence(tmp_path, monkeypatch):
    fkey = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("APP_SECRET_KEY", "operator-provided-secret")
    monkeypatch.setenv("APP_FERNET_KEY", fkey)
    b = _reload(tmp_path, monkeypatch)
    s, f = b.bootstrap_keys()
    assert s == "operator-provided-secret"
    assert f == fkey
    assert not (tmp_path / "keys" / "keys.json").exists()  # env 提供时不落盘


def test_partial_env_keys_raises(tmp_path, monkeypatch):
    """只提供一对中的一个 → 硬报错(避免另一个悄悄回落到生成值)。"""
    monkeypatch.setenv("APP_SECRET_KEY", "only-one")
    b = _reload(tmp_path, monkeypatch)
    import pytest
    with pytest.raises(RuntimeError):
        b.bootstrap_keys()


def test_env_bootstrap_creates_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_INITIAL_ADMIN_USER", "admin")
    monkeypatch.setenv("APP_INITIAL_ADMIN_PASSWORD", "env-pw")
    from importlib import reload
    from app import config, main
    reload(config)
    reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "env-pw"})
        assert r.status_code == 200
        assert r.json()["username"] == "admin"
