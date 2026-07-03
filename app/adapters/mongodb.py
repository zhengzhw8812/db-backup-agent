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
