# 更多数据库适配器 (MongoDB / Redis / SQLite) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 master spec §9④ 的"更多数据库类型":MongoDB、Redis、SQLite 各一个适配器文件,实现统一 `BackupAdapter` 接口(dump/restore),注册到适配器注册表。注册后备份/恢复管线自动支持新类型(连接 schema 的 type pattern 与前端 type 下拉已包含 `mongo/redis/sqlite`,无需改动)。

**Architecture:** 适配器策略模式 —— 每种 DB 一个文件,实现 `BackupAdapter` 协议(`type`/`dump`/`restore`),在 `adapters/__init__.py` import 即注册。备份管线 `backup_service` 已 `get_adapter(conn.type).dump(...)`,恢复管线 `restore_service` 已 `adapter.restore(...)`,故无需改管线。

**Tech Stack:** Python + subprocess(`create_subprocess_exec`,禁 shell)+ shutil(SQLite 文件级)。

**前置:** Phase 1–4 完成(`BackupAdapter` 协议已有 `restore`;`adapters/base.py` 有 `register_adapter`/`get_adapter`)。

---

## 关键设计决策(已定,文档化)

1. **MongoDB**:dump 用 `mongodump --archive=<path>`(直接写归档,无需 stdout 重定向);restore 用 `mongorestore --archive=<path>`。**密码经 `--username/--password` 上 argv** —— mongotool 不支持密码经 env/配置文件(跨版本不稳定),这是已知权衡(与 pg/mysql 走 env/cnf 不同)。测试断言命令构造正确,**不断言"密码不在 argv"**(因确实在)。

2. **Redis**:dump 用 `redis-cli -h -p --rdb <path>`,**密码经 `REDISCLI_AUTH` 环境变量**(redis 5+,密码不上 argv,与 pg 的 PGPASSWORD 模式一致)。**restore 抛 `NotImplementedError`** —— rdb 还原需"停写→替换 dump.rdb→重启服务",属服务器级运维操作,无法从适配器经 CLI 安全自动化;显式抛错优于半实现危险操作。restore_service 会捕获 → status=failed,前端展示错误信息。

3. **SQLite**:文件级。`info.db_name` 即数据库文件路径。dump = `shutil.copyfile(db_name, dest)`;restore = `shutil.copyfile(src, db_name)`。**WAL 注意**:运行中的 sqlite 文件直接拷贝可能含未刷盘的 WAL;本轮按 spec 做"文件拷贝",WAL 一致性留作未来增强(`sqlite3` 在线备份 API)。db_name 必填,缺失即抛错。

---

## 文件结构

- Create `app/adapters/sqlite_db.py` — SqliteAdapter(文件拷贝)
- Create `app/adapters/mongodb.py` — MongoAdapter(mongodump/mongorestore --archive)
- Create `app/adapters/redis_db.py` — RedisAdapter(redis-cli --rdb + REDISCLI_AUTH;restore NotImplementedError)
- Modify `app/adapters/__init__.py` — import 三个新模块完成注册
- Test: `tests/test_adapters.py`(追加 sqlite/mongo/redis 测试)

---

## Tasks

### Task 1: SQLite 适配器(文件级)

**Files:**
- Create: `app/adapters/sqlite_db.py`
- Test: `tests/test_adapters.py`(追加)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_adapters.py` 末尾:

```python
def test_sqlite_dump_copies_file(tmp_path):
    from app.adapters.sqlite_db import SqliteAdapter
    src = tmp_path / "app.db"
    src.write_bytes(b"SQLite format 3\x00payload")
    a = SqliteAdapter()
    dest = tmp_path / "out.db"
    a.dump(ConnectionInfo(type="sqlite", db_name=str(src)), str(dest))
    assert dest.read_bytes() == src.read_bytes()


def test_sqlite_restore_overwrites_target(tmp_path):
    from app.adapters.sqlite_db import SqliteAdapter
    target = tmp_path / "app.db"
    target.write_bytes(b"old")
    backup = tmp_path / "bk.db"
    backup.write_bytes(b"new-content")
    a = SqliteAdapter()
    a.restore(ConnectionInfo(type="sqlite", db_name=str(target)), str(backup))
    assert target.read_bytes() == b"new-content"


def test_sqlite_dump_missing_db_name_raises():
    from app.adapters.sqlite_db import SqliteAdapter
    import pytest
    a = SqliteAdapter()
    with pytest.raises(ValueError):
        a.dump(ConnectionInfo(type="sqlite"), "/tmp/whatever.db")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_adapters.py -k sqlite -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.adapters.sqlite_db'`.

- [ ] **Step 3: 实现 SqliteAdapter**

创建 `app/adapters/sqlite_db.py`:

```python
from __future__ import annotations
import shutil

from app.adapters.base import ConnectionInfo, register_adapter


class SqliteAdapter:
    """SQLite 文件级备份:dump=拷贝 db 文件,restore=覆盖回 db 文件。

    info.db_name 即 sqlite 数据库文件路径(须 agent 可访问)。
    注:直接拷贝运行中的文件可能含未刷盘 WAL;spec 本轮按"文件拷贝"。"""

    type = "sqlite"

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        if not info.db_name:
            raise ValueError("SQLite 连接缺少 db_name(文件路径)")
        shutil.copyfile(info.db_name, dest_path)

    def restore(self, info: ConnectionInfo, src_path: str) -> None:
        if not info.db_name:
            raise ValueError("SQLite 连接缺少 db_name(文件路径)")
        shutil.copyfile(src_path, info.db_name)


register_adapter(SqliteAdapter())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_adapters.py -k sqlite -v`
Expected: PASS(3 个)。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/sqlite_db.py tests/test_adapters.py
git commit -m "feat(db-adapters): SQLite 文件级适配器(dump/restore 拷贝)"
```

---

### Task 2: MongoDB 适配器

**Files:**
- Create: `app/adapters/mongodb.py`
- Test: `tests/test_adapters.py`(追加)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_adapters.py` 末尾:

```python
def test_mongo_dump_argv_uses_archive_and_fields():
    from app.adapters.mongodb import MongoAdapter
    a = MongoAdapter()
    info = ConnectionInfo(type="mongo", host="h", port=27017, db_name="shop",
                          username="u", password="secret")
    cmd = a.dump_argv(info, "/tmp/dump.archive")
    assert cmd[0] == "mongodump"
    assert "--archive=/tmp/dump.archive" in cmd
    assert "--host" in cmd and "h" in cmd
    assert "--port" in cmd and "27017" in cmd
    assert "--db" in cmd and "shop" in cmd
    assert "--username" in cmd and "u" in cmd
    # 注:mongo 密码确实在 argv(mongotool 限制,非 pg/mysql 的 env/cnf 模式)
    assert "--password" in cmd and "secret" in cmd


def test_mongo_restore_argv_uses_archive_and_fields():
    from app.adapters.mongodb import MongoAdapter
    a = MongoAdapter()
    info = ConnectionInfo(type="mongo", host="h", port=27017, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/dump.archive")
    assert cmd[0] == "mongorestore"
    assert "--archive=/tmp/dump.archive" in cmd
    assert "--host" in cmd and "--db" in cmd and "--username" in cmd
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_adapters.py -k mongo -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.adapters.mongodb'`.

- [ ] **Step 3: 实现 MongoAdapter**

创建 `app/adapters/mongodb.py`:

```python
from __future__ import annotations
import subprocess

from app.adapters.base import ConnectionInfo, register_adapter


class MongoAdapter:
    """MongoDB:mongodump/mongorestore --archive(单文件归档)。

    注:mongotool 不支持密码经 env/配置文件(跨版本不稳定),
    密码经 --username/--password 上 argv —— 与 pg(mysql)的 env(cnf)模式不同,
    是已知安全权衡。"""

    type = "mongo"

    def dump_argv(self, info: ConnectionInfo, dest_path: str) -> list[str]:
        cmd = ["mongodump", f"--archive={dest_path}"]
        if info.host:
            cmd += ["--host", info.host]
        if info.port:
            cmd += ["--port", str(info.port)]
        if info.db_name:
            cmd += ["--db", info.db_name]
        if info.username:
            cmd += ["--username", info.username]
        if info.password:
            cmd += ["--password", info.password]
        return cmd

    def restore_argv(self, info: ConnectionInfo, src_path: str) -> list[str]:
        cmd = ["mongorestore", f"--archive={src_path}", "--drop"]
        if info.host:
            cmd += ["--host", info.host]
        if info.port:
            cmd += ["--port", str(info.port)]
        if info.db_name:
            cmd += ["--db", info.db_name]
        if info.username:
            cmd += ["--username", info.username]
        if info.password:
            cmd += ["--password", info.password]
        return cmd

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        subprocess.run(self.dump_argv(info, dest_path), stderr=subprocess.PIPE, check=True)

    def restore(self, info: ConnectionInfo, src_path: str) -> None:
        subprocess.run(self.restore_argv(info, src_path), stderr=subprocess.PIPE, check=True)


register_adapter(MongoAdapter())
```

> `--drop`(restore 时先删集合再导入)避免重复 key 冲突,保证还原幂等。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_adapters.py -k mongo -v`
Expected: PASS(2 个)。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/mongodb.py tests/test_adapters.py
git commit -m "feat(db-adapters): MongoDB 适配器(mongodump/mongorestore --archive)"
```

---

### Task 3: Redis 适配器(--rdb + REDISCLI_AUTH)

**Files:**
- Create: `app/adapters/redis_db.py`
- Test: `tests/test_adapters.py`(追加)

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_adapters.py` 末尾:

```python
def test_redis_dump_argv_uses_rdb_and_no_password():
    from app.adapters.redis_db import RedisAdapter
    a = RedisAdapter()
    info = ConnectionInfo(type="redis", host="h", port=6379, password="topsecret")
    cmd = a.dump_argv(info, "/tmp/dump.rdb")
    assert cmd[0] == "redis-cli"
    assert "-h" in cmd and "h" in cmd
    assert "-p" in cmd and "6379" in cmd
    assert "--rdb" in cmd and "/tmp/dump.rdb" in cmd
    assert "topsecret" not in cmd  # 密码走 REDISCLI_AUTH env,不上 argv


def test_redis_env_carries_password():
    from app.adapters.redis_db import RedisAdapter
    a = RedisAdapter()
    env = a.env(ConnectionInfo(type="redis", password="topsecret"))
    assert env["REDISCLI_AUTH"] == "topsecret"


def test_redis_restore_not_implemented():
    from app.adapters.redis_db import RedisAdapter
    import pytest
    a = RedisAdapter()
    with pytest.raises(NotImplementedError):
        a.restore(ConnectionInfo(type="redis"), "/tmp/dump.rdb")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_adapters.py -k redis -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.adapters.redis_db'`.

- [ ] **Step 3: 实现 RedisAdapter**

创建 `app/adapters/redis_db.py`:

```python
from __future__ import annotations
import os
import subprocess

from app.adapters.base import ConnectionInfo, register_adapter


class RedisAdapter:
    """Redis:dump 用 redis-cli --rdb;rdb 还原需停写+替换 dump.rdb+重启服务,
    属服务器级运维、无法经 CLI 安全自动化,故 restore 显式抛 NotImplementedError。"""

    type = "redis"

    def _conn_argv(self, info: ConnectionInfo) -> list[str]:
        cmd = ["redis-cli"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-p", str(info.port)]
        return cmd

    def dump_argv(self, info: ConnectionInfo, dest_path: str) -> list[str]:
        return self._conn_argv(info) + ["--rdb", dest_path]

    def env(self, info: ConnectionInfo) -> dict:
        e = os.environ.copy()
        if info.password:
            e["REDISCLI_AUTH"] = info.password
        return e

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        subprocess.run(self.dump_argv(info, dest_path), env=self.env(info),
                       stderr=subprocess.PIPE, check=True)

    def restore(self, info: ConnectionInfo, src_path: str) -> None:
        raise NotImplementedError(
            "Redis 恢复需停写并替换 dump.rdb 后重启服务,暂不支持自动还原"
        )


register_adapter(RedisAdapter())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_adapters.py -k redis -v`
Expected: PASS(3 个)。

- [ ] **Step 5: 提交**

```bash
git add app/adapters/redis_db.py tests/test_adapters.py
git commit -m "feat(db-adapters): Redis 适配器(--rdb + REDISCLI_AUTH;restore 暂不支持)"
```

---

### Task 4: 注册 + 全量回归

**Files:**
- Modify: `app/adapters/__init__.py`

- [ ] **Step 1: 注册三个适配器**

修改 `app/adapters/__init__.py`,把:
```python
from app.adapters import postgres, mysql  # noqa: F401
```
改为:
```python
from app.adapters import postgres, mysql, mongodb, redis_db, sqlite_db  # noqa: F401
```

- [ ] **Step 2: 写注册测试**

追加到 `tests/test_adapters.py` 末尾:

```python
def test_all_adapters_registered():
    from app.adapters.base import get_adapter
    from app.adapters.postgres import PostgresAdapter
    from app.adapters.mysql import MysqlAdapter
    from app.adapters.mongodb import MongoAdapter
    from app.adapters.redis_db import RedisAdapter
    from app.adapters.sqlite_db import SqliteAdapter
    assert isinstance(get_adapter("pg"), PostgresAdapter)
    assert isinstance(get_adapter("mysql"), MysqlAdapter)
    assert isinstance(get_adapter("mongo"), MongoAdapter)
    assert isinstance(get_adapter("redis"), RedisAdapter)
    assert isinstance(get_adapter("sqlite"), SqliteAdapter)
```

- [ ] **Step 3: 跑全量后端测试**

Run: `python3 -m pytest -p no:warnings -q`
Expected: 全绿(原 75 + 新增 sqlite 3 + mongo 2 + redis 3 + 注册 1 = +9 → 84 passed),无回归。

- [ ] **Step 4: 提交**

```bash
git add app/adapters/__init__.py tests/test_adapters.py
git commit -m "feat(db-adapters): 注册 mongo/redis/sqlite 适配器"
```

---

## 完成标准

- 全量后端测试绿(≥ 84 passed,原 75 无回归)。
- `get_adapter("mongo"|"redis"|"sqlite")` 均返回对应适配器。
- SQLite dump/restore 文件拷贝往返一致;Mongo 命令构造正确(--archive + 连接字段);Redis dump 命令构造正确且密码不上 argv、走 REDISCLI_AUTH。
- 端到端:连接 schema 与前端已支持 mongo/redis/sqlite 类型;注册后 backup_service/restore_service 自动适配新类型(无需改管线)。

## 留给后续

- **SQLite WAL 一致性**:改用 sqlite3 在线备份 API(`.backup`),避免拷贝运行中文件的 WAL 不一致。
- **Redis 自动恢复**:设计"停写(BGREWRITEAEROFF/CONFIG SET appendonly no)→ 替换 rdb → 重启"的安全编排(需对目标 redis 的进程控制,可能超出单容器范围)。
- **Mongo 密码离 argv**:若 mongotool 后续支持 `--config`,改走配置文件。
- **适配器契约测试**(testcontainers 起真实容器跑 dump→restore 往返):spec §15 提及,本轮用命令构造单测覆盖。
