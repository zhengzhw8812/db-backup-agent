"""app_settings KV 设置服务。"""
import pytest
from cryptography.fernet import Fernet

from app.core.crypto import Crypto
from app.db.session import init_engine, create_all
from app.db import session as _session
import app.db.models  # noqa
from app.services.settings_service import get_setting, set_setting


@pytest.fixture
def db(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    _ = Crypto(Fernet.generate_key())
    return _session._SessionLocal()


def test_set_get_roundtrip(db):
    set_setting(db, "verify_auto_enabled", True)
    assert get_setting(db, "verify_auto_enabled", False) is True


def test_get_missing_returns_default(db):
    assert get_setting(db, "nope", "dft") == "dft"


def test_set_overwrites(db):
    set_setting(db, "k", 1)
    set_setting(db, "k", 2)
    assert get_setting(db, "k", 0) == 2
    db.close()
