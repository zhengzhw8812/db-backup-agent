from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    # 任何 argon2 失败统一视为校验失败,而非抛 500。
    # 注意 InvalidHashError 继承自 ValueError(非 Argon2Error),需单独捕获。
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        return False
