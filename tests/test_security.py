import pytest
from app.core.security import hash_password, verify_password


def test_verify_correct_password():
    h = hash_password("s3cret!")
    assert verify_password("s3cret!", h) is True


def test_verify_wrong_password():
    h = hash_password("s3cret!")
    assert verify_password("wrong", h) is False


def test_hash_differs_each_time():
    assert hash_password("same") != hash_password("same")


def test_hash_does_not_contain_plaintext():
    h = hash_password("plaintext-pw")
    assert "plaintext-pw" not in h
