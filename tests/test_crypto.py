import pytest
from cryptography.fernet import Fernet
from app.core.crypto import Crypto


def make_crypto():
    return Crypto(Fernet.generate_key())


def test_round_trip():
    c = make_crypto()
    assert c.decrypt(c.encrypt("hello")) == "hello"


def test_ciphertext_differs_from_plaintext():
    c = make_crypto()
    token = c.encrypt("secret")
    assert "secret" not in token


def test_each_encryption_yields_new_token():
    c = make_crypto()
    assert c.encrypt("x") != c.encrypt("x")


def test_wrong_key_fails():
    c1 = Crypto(Fernet.generate_key())
    token = c1.encrypt("data")
    c2 = Crypto(Fernet.generate_key())
    with pytest.raises(Exception):
        c2.decrypt(token)


def test_verify_password_returns_false_on_corrupt_hash():
    """损坏/格式异常的哈希应返回 False,而非抛异常导致 500。"""
    from app.core.security import verify_password
    assert verify_password("any", "not-a-valid-argon2-hash") is False
    assert verify_password("any", "") is False
