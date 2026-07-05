import pytest
from app.adapters.base import get_adapter, register_adapter
from app.adapters.postgres import PostgresAdapter
from app.adapters.base import ConnectionInfo
from app.adapters.mysql import MysqlAdapter


class FakeAdapter:
    type = "fake"

    def dump(self, info, dest_path):
        pass


def test_get_unknown_type_raises():
    with pytest.raises(ValueError):
        get_adapter("does-not-exist")


def test_register_and_get(monkeypatch):
    from app.adapters import base
    monkeypatch.setitem(base._REGISTRY, "fake", FakeAdapter())
    assert isinstance(get_adapter("fake"), FakeAdapter)


def test_pg_argv_includes_connection_fields():
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, db_name="shop", username="u", password="secret")
    cmd = a.argv(info)
    assert cmd[0] == "pg_dump"
    assert "-h" in cmd and "h" in cmd
    assert "-p" in cmd and "5432" in cmd
    assert "-U" in cmd and "u" in cmd
    assert "shop" in cmd


def test_pg_argv_has_no_password():
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", password="topsecret")
    cmd = a.argv(info)
    assert "topsecret" not in cmd
    assert "--password" not in cmd


def test_pg_env_carries_password():
    a = PostgresAdapter()
    env = a.env(ConnectionInfo(type="pg", password="topsecret"))
    assert env["PGPASSWORD"] == "topsecret"


def test_mysql_argv_uses_defaults_extra_file():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, db_name="shop", username="u", password="secret")
    cmd = a.argv(info, "/tmp/x.cnf")
    assert cmd[0] == "mysqldump"
    assert "--defaults-extra-file=/tmp/x.cnf" in cmd
    assert "-h" in cmd and "h" in cmd
    assert "-P" in cmd and "3306" in cmd
    assert "shop" in cmd


def test_mysql_argv_has_no_password():
    a = MysqlAdapter()
    cmd = a.argv(ConnectionInfo(type="mysql", password="topsecret"), "/tmp/x.cnf")
    assert "topsecret" not in cmd
    assert "secret" not in " ".join(cmd)


def test_pg_restore_argv_uses_psql_file_flag():
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/dump.sql")
    assert cmd[0] == "psql"
    assert "-f" in cmd and "/tmp/dump.sql" in cmd
    assert "-d" in cmd and "shop" in cmd
    assert "secret" not in cmd
    assert "ON_ERROR_STOP=1" in cmd  # 半恢复时立即失败,避免误判成功


def test_pg_test_argv_runs_select_one(monkeypatch):
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, db_name="shop", username="u", password="secret")
    seen = {}

    class OkProc:
        returncode = 0
        stderr = None
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        return OkProc()

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", fake_popen)
    a.test(info)
    assert "select 1" in seen["argv"]
    assert "secret" not in seen["argv"]  # 密码走 PGPASSWORD env,不上 argv


def test_sqlite_test_checks_file_exists(tmp_path):
    from app.adapters.sqlite_db import SqliteAdapter
    a = SqliteAdapter()
    src = tmp_path / "app.db"
    src.write_bytes(b"SQLite format 3\x00")
    a.test(ConnectionInfo(type="sqlite", db_name=str(src)))  # 存在 → 不抛
    import pytest
    with pytest.raises(FileNotFoundError):
        a.test(ConnectionInfo(type="sqlite", db_name=str(tmp_path / "missing.db")))


def test_redis_and_mongo_test_not_implemented():
    from app.adapters.redis_db import RedisAdapter
    from app.adapters.mongodb import MongoAdapter
    import pytest
    with pytest.raises(NotImplementedError):
        RedisAdapter().test(ConnectionInfo(type="redis"))
    with pytest.raises(NotImplementedError):
        MongoAdapter().test(ConnectionInfo(type="mongo"))


def test_mysql_restore_argv_uses_defaults_extra_file():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/x.cnf")
    assert cmd[0] == "mysql"
    assert "--defaults-extra-file=/tmp/x.cnf" in cmd
    assert "shop" in cmd


class _FakeProc:
    """模拟 Popen:记录 argv/stdin;wait 立即返回成功。"""
    def __init__(self, argv, **kw):
        self.args = argv
        self.returncode = 0
        self.stderr = None
        self._stdin = kw.get("stdin")
    def wait(self, timeout=None):
        return 0


def test_mysql_restore_pipes_file_into_stdin(monkeypatch, tmp_path):
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", db_name="shop", username="u", password="topsecret")
    src = tmp_path / "dump.sql"
    src.write_bytes(b"SELECT 1;\n")
    seen = {}

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        seen["stdin"] = kw.get("stdin")
        return _FakeProc(argv, **kw)

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", fake_popen)
    a.restore(info, str(src))
    assert seen["argv"][0] == "mysql"
    assert seen["stdin"] is not None          # 从文件喂入 stdin
    assert not any("topsecret" in str(c) for c in seen["argv"])  # 密码不在 argv(走 cnf)


def test_run_subprocess_includes_stderr_and_raises(monkeypatch):
    """非零退出时,失败信息应包含 stderr(便于运维定位真实原因)。"""
    import app.adapters.base as base

    class BoomProc:
        returncode = 2
        stderr = __import__("io").BytesIO(b"password authentication failed")
        def wait(self, timeout=None):
            return 2

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: BoomProc())
    with pytest.raises(RuntimeError) as ei:
        base.run_subprocess(["pg_dump"])
    assert "password authentication failed" in str(ei.value)
    assert "退出码 2" in str(ei.value)


def test_run_subprocess_cancel_kills_process(monkeypatch):
    """is_cancelled 返回 True 时,子进程被终止并抛 BackupCancelled。"""
    import app.adapters.base as base

    killed = {"yes": False}

    class HangingProc:
        returncode = None
        stderr = None
        def wait(self, timeout=None):
            raise base.subprocess.TimeoutExpired(cmd=["x"], timeout=1)  # 永不自行结束
        def terminate(self):
            killed["yes"] = True
        def kill(self):
            killed["yes"] = True

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: HangingProc())
    with pytest.raises(base.BackupCancelled):
        base.run_subprocess(["pg_dump"], is_cancelled=lambda: True)
    assert killed["yes"]


def test_run_subprocess_timeout(monkeypatch):
    """超过 timeout 仍未结束 → RuntimeError(命令超时)。"""
    import app.adapters.base as base

    class HangingProc:
        returncode = None
        stderr = None
        def wait(self, timeout=None):
            raise base.subprocess.TimeoutExpired(cmd=["x"], timeout=1)
        def terminate(self): pass
        def kill(self): pass

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: HangingProc())
    with pytest.raises(RuntimeError) as ei:
        base.run_subprocess(["pg_dump"], timeout=1)
    assert "超时" in str(ei.value)


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
    assert "--password" in cmd and "secret" in cmd


def test_mongo_restore_argv_uses_archive_and_fields():
    from app.adapters.mongodb import MongoAdapter
    a = MongoAdapter()
    info = ConnectionInfo(type="mongo", host="h", port=27017, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/dump.archive")
    assert cmd[0] == "mongorestore"
    assert "--archive=/tmp/dump.archive" in cmd
    assert "--host" in cmd and "--db" in cmd and "--username" in cmd


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


def test_run_subprocess_capture_returns_stdout(monkeypatch):
    """list_databases 需要 stdout;capture 变体应返回解码后的 stdout 文本。"""
    import app.adapters.base as base

    class OkProc:
        returncode = 0
        stderr = None
        stdout = __import__("io").BytesIO(b"app\nlogs\n")
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: OkProc())
    out = base.run_subprocess_capture(["psql"])
    assert out == "app\nlogs\n"


def test_run_subprocess_capture_raises_on_nonzero(monkeypatch):
    import app.adapters.base as base

    class BoomProc:
        returncode = 2
        stderr = __import__("io").BytesIO(b"auth failed")
        stdout = __import__("io").BytesIO(b"")
        def wait(self, timeout=None): return 2

    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: BoomProc())
    with pytest.raises(RuntimeError) as ei:
        base.run_subprocess_capture(["psql"])
    assert "auth failed" in str(ei.value)


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


def test_pg_list_databases_argv_and_parse(monkeypatch):
    """list_databases:连维护库 postgres,查 pg_database;密码走 env;解析逐行库名。"""
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", port=5432, username="u", password="secret")
    seen = {}

    class OkProc:
        returncode = 0
        stderr = None
        stdout = __import__("io").BytesIO(b"app\nlogs\nshop\n")
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        seen["env"] = kw.get("env")
        return OkProc()

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", fake_popen)
    names = a.list_databases(info)
    assert names == ["app", "logs", "shop"]
    joined = " ".join(seen["argv"])
    assert "datname" in joined and "pg_database" in joined        # 查 pg_database
    assert "-d" in seen["argv"] and "postgres" in seen["argv"]    # 连维护库 postgres
    assert "secret" not in joined                                 # 密码不上 argv
    assert seen["env"].get("PGPASSWORD") == "secret"             # 走 PGPASSWORD


def test_pg_list_databases_falls_back_to_template1(monkeypatch):
    """postgres 维护库连不上时,回退 template1;仍失败则抛 RuntimeError。"""
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", username="u", password="secret")
    calls = []

    class FailProc:
        returncode = 1
        stderr = __import__("io").BytesIO(b"connection refused")
        stdout = __import__("io").BytesIO(b"")
        def wait(self, timeout=None): return 1

    class OkProc:
        returncode = 0
        stderr = None
        stdout = __import__("io").BytesIO(b"onlydb\n")
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kw):
        calls.append(argv)
        return FailProc() if ("-d" in argv and "postgres" in argv) else OkProc()

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", fake_popen)
    assert a.list_databases(info) == ["onlydb"]
    assert any("template1" in c for c in calls)  # 回退到 template1


def test_pg_list_databases_all_fail_raises(monkeypatch):
    a = PostgresAdapter()
    info = ConnectionInfo(type="pg", host="h", username="u", password="secret")

    class FailProc:
        returncode = 1
        stderr = __import__("io").BytesIO(b"auth failed")
        stdout = __import__("io").BytesIO(b"")
        def wait(self, timeout=None): return 1

    monkeypatch.setattr("app.adapters.base.subprocess.Popen", lambda *a, **k: FailProc())
    with pytest.raises(RuntimeError) as ei:
        a.list_databases(info)
    assert "维护库" in str(ei.value)


def test_mysql_argv_all_databases_when_no_dbname():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, username="u")  # 无 db_name
    cmd = a.argv(info, "/tmp/x.cnf")
    assert "--all-databases" in cmd
    assert "shop" not in cmd


def test_mysql_argv_keeps_single_db_when_dbname():
    """有 db_name 的旧连接保持原行为(只备份该库)。"""
    a = MysqlAdapter()
    cmd = a.argv(ConnectionInfo(type="mysql", db_name="shop"), "/tmp/x.cnf")
    assert "shop" in cmd
    assert "--all-databases" not in cmd
