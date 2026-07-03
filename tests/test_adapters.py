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
