from __future__ import annotations
import shutil
from typing import Callable

from app.adapters.base import ConnectionInfo, register_adapter


class SqliteAdapter:
    """SQLite 文件级备份:dump=拷贝 db 文件,restore=覆盖回 db 文件。

    info.db_name 即 sqlite 数据库文件路径(须 agent 可访问)。
    注:直接拷贝运行中的文件可能含未刷盘 WAL;spec 本轮按"文件拷贝"。
    路径合法性已在 connection_service 层校验(须位于 data_dir 内)。"""

    type = "sqlite"

    def dump(self, info: ConnectionInfo, dest_path: str, *,
             is_cancelled: Callable[[], bool] | None = None) -> None:
        if not info.db_name:
            raise ValueError("SQLite 连接缺少 db_name(文件路径)")
        shutil.copyfile(info.db_name, dest_path)

    def restore(self, info: ConnectionInfo, src_path: str, *,
                is_cancelled: Callable[[], bool] | None = None) -> None:
        if not info.db_name:
            raise ValueError("SQLite 连接缺少 db_name(文件路径)")
        shutil.copyfile(src_path, info.db_name)

    def test(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> None:
        """SQLite 探测:确认文件存在(路径合法性已在 service 层校验)。"""
        if not info.db_name:
            raise ValueError("SQLite 连接缺少 db_name(文件路径)")
        from pathlib import Path
        if not Path(info.db_name).exists():
            raise FileNotFoundError(f"数据库文件不存在: {info.db_name}")


register_adapter(SqliteAdapter())
