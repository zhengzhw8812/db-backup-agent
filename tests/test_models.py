from sqlalchemy import inspect
from app.db.session import init_engine, create_all
import app.db.models  # noqa  确保模型已注册


def test_all_tables_created(tmp_path):
    init_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all()
    from app.db.session import _engine  # init_engine 之后才非 None
    inspector = inspect(_engine)
    tables = set(inspector.get_table_names())
    expected = {"account", "db_connections", "schedules", "backup_records", "system_logs"}
    assert expected.issubset(tables)
