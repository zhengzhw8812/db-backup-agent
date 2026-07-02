# Phase 1 — 后端地基 (Backend Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 FastAPI 后端地基:项目脚手架、SQLite 数据模型、Fernet 凭据加密、argon2 密码哈希、单用户会话鉴权、数据库连接 CRUD,以及单容器骨架(Dockerfile + supervisord 托管 redis + uvicorn)。

**Architecture:** FastAPI 应用工厂 + 分层(routers/services/core/db);SQLAlchemy 2.x 同步 ORM;凭据 Fernet 加密落库;单用户账号首启引导;Starlette 签名 cookie 会话(httpOnly + SameSite)。本阶段产出**可运行、可测**的后端,通过 pytest + TestClient 验证。备份执行(worker/适配器/调度)留给 Plan 2,故本阶段 arq worker 进程先不启动。

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2.x, argon2-cffi, cryptography (Fernet), pydantic-settings, redis (客户端,本阶段仅连通), pytest, Docker, supervisord.

**对应设计文档:** `docs/superpowers/specs/2026-07-02-full-rewrite-design.md`

---

## File Structure (本阶段产出)

```
.
├── pyproject.toml                 # 依赖与项目元数据
├── app/
│   ├── __init__.py
│   ├── main.py                    # 应用工厂 create_app() + lifespan + 健康检查
│   ├── config.py                  # Settings(pydantic-settings),数据/密钥路径
│   ├── bootstrap.py               # 首启:生成/加载 secret_key、fernet_key
│   ├── deps.py                    # get_db / get_current_account 依赖
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py             # engine/sessionmaker/create_all
│   │   └── models.py             # SQLAlchemy 表模型
│   ├── core/
│   │   ├── __init__.py
│   │   ├── crypto.py              # Fernet 加解密
│   │   ├── security.py            # argon2 哈希/校验
│   │   └── auth.py                # 会话登录/登出/取当前账号
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── account.py             # Login / AccountOut
│   │   └── connection.py          # ConnectionCreate/Update/Out
│   ├── services/
│   │   ├── __init__.py
│   │   ├── account_service.py     # 账号首启、取账号
│   │   └── connection_service.py  # 连接 CRUD
│   └── routers/
│       ├── __init__.py
│       ├── health.py              # GET /api/v1/health
│       ├── auth.py                # /api/v1/auth/*
│       └── connections.py         # /api/v1/connections/*
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # fixtures: client/tmp app
│   ├── test_crypto.py
│   ├── test_security.py
│   ├── test_auth.py
│   └── test_connections.py
├── deploy/
│   ├── Dockerfile
│   ├── supervisord.conf
│   └── entrypoint.sh
└── .env.example
```

**职责边界:** `core/` 是无依赖纯逻辑(加密/哈希,最易测);`db/` 持久化;`schemas/` 校验;`services/` 业务;`routers/` 薄 IO。`bootstrap.py` 集中首启副作用(密钥生成),避免散落。

---

## Task 1: 项目脚手架 + 配置 + 应用工厂 + 健康检查

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`, `app/config.py`, `app/main.py`, `app/routers/__init__.py`, `app/routers/health.py`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_health.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "db-backup-agent"
version = "3.0.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "argon2-cffi>=23.1",
    "cryptography>=42.0",
    "pydantic-settings>=2.2",
    "redis>=5.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: 安装依赖**

Run: `pip install -e ".[dev]"`
Expected: 成功安装 fastapi/uvicorn/sqlalchemy/argon2-cffi/cryptography/pydantic-settings/redis/pytest/httpx。

- [ ] **Step 3: 写 app/config.py**

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    redis_url: str = "redis://127.0.0.1:6379/0"
    # secret_key 与 fernet_key 由 bootstrap.py 首启生成;此处仅占位,不作为生产默认。
    secret_key: str = ""
    fernet_key: str = ""
    # 测试/开发首启账号(仅当 account 表为空时引导用)
    initial_admin_user: str = "admin"
    initial_admin_password: str = ""

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'sqlite' / 'app.db'}"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"


settings = Settings()
```

- [ ] **Step 4: 写 app/routers/health.py**

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 5: 写 app/main.py(最小应用工厂;密钥与会话中间件用占位值,后续 Task 补)**

```python
from fastapi import FastAPI

from app.config import settings
from app.routers import health


def create_app() -> FastAPI:
    app = FastAPI(title="DB Backup Agent", version="3.0.0")
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 6: 写 tests/conftest.py**

```python
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    # 重新加载 settings 以读取新的 APP_DATA_DIR
    from importlib import reload
    from app import config
    reload(config)
    from app import main
    reload(main)
    with TestClient(main.app) as c:
        yield c
```

- [ ] **Step 7: 写失败的测试 tests/test_health.py**

```python
def test_health_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 8: 运行测试,确认通过**

Run: `pytest tests/test_health.py -v`
Expected: PASS(1 passed)。

- [ ] **Step 9: 提交**

```bash
git add pyproject.toml app/ tests/
git commit -m "feat(phase1): 项目脚手架 + 配置 + 健康检查"
```

---

## Task 2: SQLite 数据模型 + 建表

**Files:**
- Create: `app/db/__init__.py`, `app/db/session.py`, `app/db/models.py`
- Modify: `app/main.py`(lifespan 建表)
- Create: `tests/test_models.py`

- [ ] **Step 1: 写 app/db/session.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def init_engine(db_url: str) -> None:
    global _engine, _SessionLocal
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    _engine = create_engine(db_url, connect_args=connect_args, future=True)
    _SessionLocal = sessionmaker(_engine, autoflush=False, expire_on_commit=False, future=True)


def create_all() -> None:
    from app.db import models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(_engine)


def get_db():
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: 写 app/db/models.py**

```python
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class DbConnection(Base):
    __tablename__ = "db_connections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # pg/mysql/mongo/redis/sqlite
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    db_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet 密文
    extra: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 字符串
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    schedules: Mapped[list["Schedule"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    connection: Mapped["DbConnection"] = relationship(back_populates="schedules")


class BackupRecord(Base):
    __tablename__ = "backup_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("db_connections.id", ondelete="CASCADE"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # manual/scheduled
    status: Mapped[str] = mapped_column(String(16), nullable=False)   # running/success/failed/cancelled
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 3: 写失败的测试 tests/test_models.py**

```python
from sqlalchemy import inspect
from app.db.session import init_engine, create_all, Base
import app.db.models  # noqa


def test_all_tables_created(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    inspector = inspect(Base.metadata.bind)
    tables = set(inspector.get_table_names())
    expected = {"account", "db_connections", "schedules", "backup_records", "system_logs"}
    assert expected.issubset(tables)
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `pytest tests/test_models.py -v`
Expected: PASS。

- [ ] **Step 5: 在 lifespan 中建表 —— 改 app/main.py**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import settings
from app.db.session import init_engine, create_all
from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "sqlite").mkdir(parents=True, exist_ok=True)
    init_engine(settings.sqlite_url)
    create_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="DB Backup Agent", version="3.0.0", lifespan=lifespan)
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 6: 重新跑全部测试,确认通过**

Run: `pytest -v`
Expected: test_health + test_models 全 PASS。

- [ ] **Step 7: 提交**

```bash
git add app/db/ app/main.py tests/test_models.py
git commit -m "feat(phase1): SQLite 数据模型 + 建表"
```

---

## Task 3: Fernet 凭据加密模块

**Files:**
- Create: `app/core/__init__.py`, `app/core/crypto.py`
- Create: `tests/test_crypto.py`

- [ ] **Step 1: 写失败的测试 tests/test_crypto.py**

```python
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
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `pytest tests/test_crypto.py -v`
Expected: FAIL(ImportError: app.core.crypto)。

- [ ] **Step 3: 写实现 app/core/crypto.py**

```python
from cryptography.fernet import Fernet


class Crypto:
    """Fernet 对称加密包装。密钥由 bootstrap 注入。"""

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `pytest tests/test_crypto.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/core/__init__.py app/core/crypto.py tests/test_crypto.py
git commit -m "feat(phase1): Fernet 凭据加密模块"
```

---

## Task 4: argon2 密码哈希

**Files:**
- Create: `app/core/security.py`
- Create: `tests/test_security.py`

- [ ] **Step 1: 写失败的测试 tests/test_security.py**

```python
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
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `pytest tests/test_security.py -v`
Expected: FAIL(ImportError)。

- [ ] **Step 3: 写实现 app/core/security.py**

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except InvalidHash:
        return False
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `pytest tests/test_security.py -v`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/core/security.py tests/test_security.py
git commit -m "feat(phase1): argon2 密码哈希"
```

---

## Task 5: 首启密钥引导 + 单用户账号初始化

**Files:**
- Create: `app/bootstrap.py`
- Create: `app/services/__init__.py`, `app/services/account_service.py`
- Modify: `app/main.py`(lifespan 调用 bootstrap + 账号引导)
- Create: `tests/test_bootstrap.py`

- [ ] **Step 1: 写 app/services/account_service.py**

```python
from sqlalchemy.orm import Session
from app.db.models import Account
from app.core.security import hash_password


def get_account(db: Session) -> Account | None:
    return db.query(Account).first()


def ensure_account(db: Session, username: str, password: str) -> Account:
    acc = get_account(db)
    if acc is not None:
        return acc
    acc = Account(username=username, password_hash=hash_password(password), totp_enabled=False)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
```

- [ ] **Step 2: 写 app/bootstrap.py**

```python
import json
import secrets

from cryptography.fernet import Fernet

from app import config


def bootstrap_keys() -> tuple[str, str]:
    """首次启动生成 secret_key 与 fernet_key,持久化到 data_dir/keys;后续启动加载。
    返回 (secret_key, fernet_key)。绝不在代码里硬编码弱默认。

    通过模块引用 config.settings 读取路径,以便测试 reload(config) 后立即生效。"""
    keys_dir = config.settings.keys_dir
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_file = keys_dir / "keys.json"
    if key_file.exists():
        data = json.loads(key_file.read_text())
        return data["secret_key"], data["fernet_key"]
    secret_key = secrets.token_urlsafe(48)
    fernet_key = Fernet.generate_key().decode("ascii")
    key_file.write_text(json.dumps({"secret_key": secret_key, "fernet_key": fernet_key}))
    # 限制权限(容器内尽力而为)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return secret_key, fernet_key
```

- [ ] **Step 3: 写失败的测试 tests/test_bootstrap.py**

```python
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
    # 再次调用应返回相同的(已持久化)
    s2, f2 = b.bootstrap_keys()
    assert (s1, f1) == (s2, f2)


def test_keys_differ_across_data_dirs(tmp_path, monkeypatch):
    b = _reload(tmp_path / "a", monkeypatch)
    sa, _ = b.bootstrap_keys()
    b = _reload(tmp_path / "b", monkeypatch)
    sb, _ = b.bootstrap_keys()
    assert sa != sb  # 不同实例生成的密钥不同,无全局弱默认
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `pytest tests/test_bootstrap.py -v`
Expected: 2 passed。

- [ ] **Step 5: 重写 app/main.py —— 同步执行 bootstrap + 会话中间件 + 账号引导**

Starlette 中间件需在启动前注册,故 bootstrap 在 `create_app()` 内同步执行(模块导入即生成密钥)。**本阶段只接入 health 路由**;auth/connections 在 Task 6、7 完成后追加(届时修改 import 与 include,不会重写整段)。

```python
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.bootstrap import bootstrap_keys
from app.core.crypto import Crypto
from app.db.session import init_engine, create_all, get_db
from app.services.account_service import ensure_account
from app.routers import health


def create_app() -> FastAPI:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "sqlite").mkdir(parents=True, exist_ok=True)
    secret_key, fernet_key = bootstrap_keys()

    init_engine(settings.sqlite_url)
    create_all()
    if settings.initial_admin_password:
        db = next(get_db())
        try:
            ensure_account(db, settings.initial_admin_user, settings.initial_admin_password)
        finally:
            db.close()

    app = FastAPI(title="DB Backup Agent", version="3.0.0")
    app.add_middleware(SessionMiddleware, secret_key=secret_key, same_site="lax", https_only=False)
    app.state.crypto = Crypto(fernet_key.encode("ascii"))
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 6: 运行全部已有测试,确认通过**

Run: `pytest -v`
Expected: 全 PASS(此时 main.py 仅 include health;Task 2 的 test_models 直接调用 init_engine/create_all,不依赖 main)。

- [ ] **Step 7: 提交**

```bash
git add app/bootstrap.py app/services/ app/main.py tests/test_bootstrap.py
git commit -m "feat(phase1): 首启密钥引导 + 账号初始化"
```

---

## Task 6: 单用户会话鉴权(login/logout + get_current_account)

**Files:**
- Create: `app/schemas/__init__.py`, `app/schemas/account.py`
- Create: `app/core/auth.py`
- Create: `app/deps.py`
- Create: `app/routers/auth.py`
- Modify: `app/main.py`(取消 auth include 注释)
- Create: `tests/test_auth.py`

- [ ] **Step 1: 写 app/schemas/account.py**

```python
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AccountOut(BaseModel):
    id: int
    username: str
    totp_enabled: bool
```

- [ ] **Step 2: 写 app/core/auth.py(会话读写纯函数,便于测试)**

```python
from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session

from app.db.models import Account
from app.services.account_service import get_account
from app.core.security import verify_password

SESSION_KEY = "account_id"


def login(request: Request, db: Session, username: str, password: str) -> Account:
    acc = get_account(db)
    if acc is None or acc.username != username or not verify_password(password, acc.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    request.session[SESSION_KEY] = acc.id
    return acc


def logout(request: Request) -> None:
    request.session.clear()


def current_account_id(request: Request) -> int:
    acc_id = request.session.get(SESSION_KEY)
    if acc_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return acc_id
```

- [ ] **Step 3: 写 app/deps.py**

```python
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Account
from app.core.auth import current_account_id


def get_current_account(request: Request, db: Session = Depends(get_db)) -> Account:
    acc_id = current_account_id(request)
    acc = db.get(Account, acc_id)
    if acc is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")
    return acc
```

- [ ] **Step 4: 写 app/routers/auth.py**

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_account
from app.core.auth import login, logout
from app.schemas.account import LoginRequest, AccountOut

router = APIRouter()


@router.post("/login", response_model=AccountOut)
def do_login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    acc = login(request, db, payload.username, payload.password)
    return acc


@router.post("/logout")
def do_logout(request: Request):
    logout(request)
    return {"ok": True}


@router.get("/me", response_model=AccountOut)
def me(acc=Depends(get_current_account)):
    return acc
```

- [ ] **Step 5: 在 app/main.py 中接入 auth 路由**

① 修改顶部 import,把 `from app.routers import health` 改为:

```python
from app.routers import health, auth
```

② 在 `create_app()` 内、`app.include_router(health.router, ...)` 之后追加:

```python
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
```

- [ ] **Step 6: 写失败的测试 tests/test_auth.py**

```python
import pytest


@pytest.fixture
def app_with_account(client, monkeypatch):
    # 直接通过 service 建账号
    from app.db.session import _SessionLocal
    from app.services.account_service import ensure_account
    db = _SessionLocal()
    try:
        ensure_account(db, "admin", "pw12345")
    finally:
        db.close()
    return client


def test_login_success(app_with_account):
    resp = app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "pw12345"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_login_wrong_password(app_with_account):
    resp = app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401


def test_me_requires_login(app_with_account):
    resp = app_with_account.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_after_login(app_with_account):
    app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "pw12345"})
    resp = app_with_account.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_logout(app_with_account):
    app_with_account.post("/api/v1/auth/login", json={"username": "admin", "password": "pw12345"})
    app_with_account.post("/api/v1/auth/logout")
    resp = app_with_account.get("/api/v1/auth/me")
    assert resp.status_code == 401
```

- [ ] **Step 7: 运行测试,确认通过**

Run: `pytest tests/test_auth.py -v`
Expected: 5 passed。

- [ ] **Step 8: 提交**

```bash
git add app/schemas/ app/core/auth.py app/deps.py app/routers/auth.py app/main.py tests/test_auth.py
git commit -m "feat(phase1): 单用户会话鉴权"
```

---

## Task 7: 数据库连接 CRUD(密码 Fernet 加密)

**Files:**
- Create: `app/schemas/connection.py`
- Create: `app/services/connection_service.py`
- Create: `app/routers/connections.py`
- Modify: `app/main.py`(取消 connections include 注释)
- Create: `tests/test_connections.py`

- [ ] **Step 1: 写 app/schemas/connection.py**

```python
from datetime import datetime
from pydantic import BaseModel, Field


class ConnectionBase(BaseModel):
    name: str
    type: str = Field(..., pattern="^(pg|mysql|mongo|redis|sqlite)$")
    host: str | None = None
    port: int | None = None
    db_name: str | None = None
    username: str | None = None
    password: str | None = None  # 明文入参,服务层加密;返回时不输出
    extra: dict | None = None


class ConnectionCreate(ConnectionBase):
    pass


class ConnectionUpdate(ConnectionBase):
    name: str | None = None
    type: str | None = Field(None, pattern="^(pg|mysql|mongo|redis|sqlite)$")


class ConnectionOut(BaseModel):
    id: int
    name: str
    type: str
    host: str | None
    port: int | None
    db_name: str | None
    username: str | None
    extra: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: 写 app/services/connection_service.py**

```python
import json
from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session

from app.db.models import DbConnection
from app.core.crypto import Crypto


def _crypto(request: Request) -> Crypto:
    return request.app.state.crypto


def _to_out(c: DbConnection) -> DbConnection:
    return c


def create_connection(db: Session, request: Request, data) -> DbConnection:
    c = DbConnection(
        name=data.name,
        type=data.type,
        host=data.host,
        port=data.port,
        db_name=data.db_name,
        username=data.username,
        password_enc=_crypto(request).encrypt(data.password) if data.password else None,
        extra=json.dumps(data.extra) if data.extra is not None else None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def get_connection(db: Session, conn_id: int) -> DbConnection:
    c = db.get(DbConnection, conn_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="连接不存在")
    return c


def list_connections(db: Session) -> list[DbConnection]:
    return db.query(DbConnection).order_by(DbConnection.id).all()


def update_connection(db: Session, request: Request, conn_id: int, data) -> DbConnection:
    c = get_connection(db, conn_id)
    for field in ("name", "type", "host", "port", "db_name", "username"):
        val = getattr(data, field)
        if val is not None:
            setattr(c, field, val)
    if data.password is not None:
        c.password_enc = _crypto(request).encrypt(data.password)
    if data.extra is not None:
        c.extra = json.dumps(data.extra)
    db.commit()
    db.refresh(c)
    return c


def delete_connection(db: Session, conn_id: int) -> None:
    c = get_connection(db, conn_id)
    db.delete(c)
    db.commit()


def decrypt_password(c: DbConnection, request: Request) -> str | None:
    if not c.password_enc:
        return None
    return _crypto(request).decrypt(c.password_enc)
```

- [ ] **Step 3: 写 app/routers/connections.py**

```python
import json
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_account
from app.schemas.connection import ConnectionCreate, ConnectionUpdate, ConnectionOut
from app.services import connection_service as svc

router = APIRouter()


def _serialize(c) -> ConnectionOut:
    return ConnectionOut(
        id=c.id, name=c.name, type=c.type, host=c.host, port=c.port,
        db_name=c.db_name, username=c.username,
        extra=json.loads(c.extra) if c.extra else None, created_at=c.created_at,
    )


@router.get("", response_model=list[ConnectionOut])
def list_(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return [_serialize(c) for c in svc.list_connections(db)]


@router.post("", response_model=ConnectionOut, status_code=201)
def create(payload: ConnectionCreate, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _serialize(svc.create_connection(db, request, payload))


@router.get("/{conn_id}", response_model=ConnectionOut)
def detail(conn_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _serialize(svc.get_connection(db, conn_id))


@router.put("/{conn_id}", response_model=ConnectionOut)
def update(conn_id: int, payload: ConnectionUpdate, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _serialize(svc.update_connection(db, request, conn_id, payload))


@router.delete("/{conn_id}", status_code=204)
def delete(conn_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    svc.delete_connection(db, conn_id)
```

- [ ] **Step 4: 在 app/main.py 中接入 connections 路由**

① 修改顶部 import,把 `from app.routers import health, auth` 改为:

```python
from app.routers import health, auth, connections
```

② 在 `create_app()` 内、auth 的 include 之后追加:

```python
    app.include_router(connections.router, prefix="/api/v1/connections", tags=["connections"])
```

- [ ] **Step 5: 写失败的测试 tests/test_connections.py**

```python
import pytest


@pytest.fixture
def authed(client):
    from app.db.session import _SessionLocal
    from app.services.account_service import ensure_account
    db = _SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def test_requires_auth(client):
    assert client.get("/api/v1/connections").status_code == 401


def test_create_and_list(authed):
    body = {"name": "pg1", "type": "pg", "host": "h", "port": 5432, "db_name": "d", "username": "u", "password": "secret"}
    r = authed.post("/api/v1/connections", json=body)
    assert r.status_code == 201
    created = r.json()
    assert created["name"] == "pg1"
    assert "password" not in created  # 密码不回传
    listed = authed.get("/api/v1/connections").json()
    assert len(listed) == 1 and listed[0]["id"] == created["id"]


def test_password_stored_encrypted(authed):
    authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "password": "topsecret"})
    from app.db.session import _SessionLocal
    from app.db.models import DbConnection
    db = _SessionLocal()
    try:
        row = db.query(DbConnection).first()
        assert row.password_enc is not None
        assert "topsecret" not in row.password_enc  # 落库为密文
    finally:
        db.close()


def test_decrypt_roundtrip(authed):
    authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg", "password": "roundtrip"})
    # 直接用服务层解密,验证"写入密文 → 解出明文"往返一致
    from app.db.session import _SessionLocal
    from app.db.models import DbConnection
    from app.main import app as fastapi_app
    from app.services.connection_service import decrypt_password

    class FakeReq:
        pass  # 只需 .app 属性,服务层用 request.app.state.crypto

    db = _SessionLocal()
    try:
        row = db.query(DbConnection).first()
        fr = FakeReq()
        fr.app = fastapi_app
        assert decrypt_password(row, fr) == "roundtrip"
    finally:
        db.close()


def test_update_and_delete(authed):
    cid = authed.post("/api/v1/connections", json={"name": "pg1", "type": "pg"}).json()["id"]
    r = authed.put(f"/api/v1/connections/{cid}", json={"name": "pg-renamed"})
    assert r.json()["name"] == "pg-renamed"
    assert authed.delete(f"/api/v1/connections/{cid}").status_code == 204
    assert authed.get("/api/v1/connections").json() == []
```

- [ ] **Step 6: 运行测试,确认通过**

Run: `pytest tests/test_connections.py -v`
Expected: 5 passed。

- [ ] **Step 7: 运行全部测试,确认无回归**

Run: `pytest -v`
Expected: 全 PASS。

- [ ] **Step 8: 提交**

```bash
git add app/schemas/connection.py app/services/connection_service.py app/routers/connections.py app/main.py tests/test_connections.py
git commit -m "feat(phase1): 数据库连接 CRUD(凭据 Fernet 加密)"
```

---

## Task 8: 容器骨架(Dockerfile + supervisord + entrypoint)

**Files:**
- Create: `deploy/Dockerfile`
- Create: `deploy/supervisord.conf`
- Create: `deploy/entrypoint.sh`
- Create: `.env.example`
- Modify: `.gitignore`(忽略 data/、.env)

- [ ] **Step 1: 写 .env.example**

```bash
# 数据持久化目录(挂载卷)
APP_DATA_DIR=/data
# Redis 连接
APP_REDIS_URL=redis://127.0.0.1:6379/0
# 首启管理员账号(仅 account 表为空时生效)
APP_INITIAL_ADMIN_USER=admin
APP_INITIAL_ADMIN_PASSWORD=change-me-on-first-login
# 监听端口
APP_PORT=5001
```

- [ ] **Step 2: 写 deploy/supervisord.conf(本阶段仅 redis + uvicorn;worker 在 Plan 2 加入)**

```ini
[supervisord]
nodaemon=true
logfile=/data/logs/supervisord.log
pidfile=/tmp/supervisord.pid
user=root

[program:redis]
command=redis-server --dir /data/redis --appendonly yes
autorestart=true
stdout_logfile=/data/logs/redis.log
stderr_logfile=/data/logs/redis.err.log

[program:web]
command=uvicorn app.main:app --host 0.0.0.0 --port %(ENV_APP_PORT)s
directory=/app
autorestart=true
stdout_logfile=/data/logs/web.log
stderr_logfile=/data/logs/web.err.log
```

- [ ] **Step 3: 写 deploy/entrypoint.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/sqlite /data/redis /data/logs /data/backups

# 加载 .env(若存在)
if [ -f /app/.env ]; then export $(grep -v '^#' /app/.env | xargs); fi

: "${APP_DATA_DIR:=/data}"
: "${APP_PORT:=5001}"
export APP_DATA_DIR APP_PORT

exec supervisord -c /app/deploy/supervisord.conf
```

- [ ] **Step 4: 写 deploy/Dockerfile**

```dockerfile
FROM python:3.12-slim AS base

# 数据库客户端(本阶段 PG + MySQL;Mongo/Redis 客户端在后续阶段加)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates supervisor redis-server \
        postgresql-client default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

COPY app/ ./app/
COPY deploy/ ./deploy/
COPY .env.example ./

ENV APP_DATA_DIR=/data \
    APP_PORT=5001

EXPOSE 5001
RUN chmod +x /app/deploy/entrypoint.sh
CMD ["/app/deploy/entrypoint.sh"]
```

- [ ] **Step 5: 更新 .gitignore(忽略运行时数据与环境)**

追加:
```
data/
.env
__pycache__/
*.pyc
```

- [ ] **Step 6: 验证镜像可构建并启动(手动冒烟)**

Run:
```bash
docker build -f deploy/Dockerfile -t dba:phase1 .
docker run --rm -d -p 5001:5001 -v "$PWD/data:/data" -e APP_INITIAL_ADMIN_PASSWORD=smoke --name dba dba:phase1
sleep 3
curl -s http://localhost:5001/api/v1/health
```
Expected: `{"status":"ok"}`

验证登录:
```bash
curl -s -c /tmp/cj -X POST http://localhost:5001/api/v1/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"smoke"}'
curl -s -b /tmp/cj http://localhost:5001/api/v1/auth/me
```
Expected: 登录返回账号;`/me` 返回 `{"id":1,"username":"admin","totp_enabled":false}`。

清理:`docker stop dba`

- [ ] **Step 7: 提交**

```bash
git add deploy/ .env.example .gitignore
git commit -m "feat(phase1): 容器骨架(supervisord 托管 redis + uvicorn)"
```

---

## Phase 1 完成标准(Definition of Done)

- `pytest -v` 全绿(crypto / security / bootstrap / models / auth / connections / health)。
- `docker build` 成功,容器启动后 `/api/v1/health` 返回 ok,首启账号可登录,`/api/v1/connections` CRUD 受鉴权保护、密码加密落库。
- 密钥首启自动生成并持久化,代码无硬编码弱默认。
- 所有提交按 Task 粒度、信息清晰。

## 留给后续 Plan 的钩子

- `app/routers/connections.py` 的 `test`(连通性探测)端点 → Plan 2(适配器就位后实现)。
- arq worker 进程 → Plan 2(supervisord 增加 `[program:worker]`)。
- 调度(APScheduler)、备份/恢复/云同步 API、SSE、前端 → Plan 2-6。
- TOTP 2FA → 可在 Plan 2 或独立小计划加入(`account.totp_secret` 字段已预留)。

---

*自检:self-review 已完成。spec 覆盖:本阶段对应设计文档 §3(技术栈)、§4(单用户)、§6(后端结构雏形)、§7(account/db_connections/schedules/backup_records 模型)、§11(argon2/Fernet/会话/无弱 secret)。未覆盖部分(执行管线/前端/新能力)按计划在 Plan 2-6 落地。类型一致性:方法名 `encrypt/decrypt/hash_password/verify_password/get_current_account/create_connection` 在各 Task 间一致。*
