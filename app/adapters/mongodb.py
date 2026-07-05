from __future__ import annotations
from typing import Callable

from app.adapters.base import ConnectionInfo, register_adapter, run_subprocess


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

    def dump(self, info: ConnectionInfo, dest_path: str, *,
             is_cancelled: Callable[[], bool] | None = None) -> None:
        run_subprocess(self.dump_argv(info, dest_path), is_cancelled=is_cancelled)

    def restore(self, info: ConnectionInfo, src_path: str, *,
                is_cancelled: Callable[[], bool] | None = None) -> None:
        run_subprocess(self.restore_argv(info, src_path), is_cancelled=is_cancelled)

    def test(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> None:
        # mongotool 无轻量 ping 命令,mongodump 探测过重;暂不支持自动测试
        raise NotImplementedError("MongoDB 暂不支持连接测试,请新建后直接尝试备份")


register_adapter(MongoAdapter())
