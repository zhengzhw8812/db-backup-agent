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
