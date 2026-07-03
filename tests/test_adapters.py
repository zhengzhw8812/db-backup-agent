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


def test_mysql_restore_argv_uses_defaults_extra_file():
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", host="h", port=3306, db_name="shop", username="u", password="secret")
    cmd = a.restore_argv(info, "/tmp/x.cnf")
    assert cmd[0] == "mysql"
    assert "--defaults-extra-file=/tmp/x.cnf" in cmd
    assert "shop" in cmd


def test_mysql_restore_pipes_file_into_stdin(monkeypatch, tmp_path):
    a = MysqlAdapter()
    info = ConnectionInfo(type="mysql", db_name="shop", username="u", password="topsecret")
    src = tmp_path / "dump.sql"
    src.write_bytes(b"SELECT 1;\n")
    seen = {}

    def fake_run(argv, *a, **k):
        seen["argv"] = argv
        seen["stdin"] = k.get("stdin")
        return None

    monkeypatch.setattr("app.adapters.mysql.subprocess.run", fake_run)
    a.restore(info, str(src))
    assert seen["argv"][0] == "mysql"
    assert seen["stdin"] is not None          # 从文件喂入 stdin
    assert not any("topsecret" in str(c) for c in seen["argv"])  # 密码不在 argv(走 cnf)


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
