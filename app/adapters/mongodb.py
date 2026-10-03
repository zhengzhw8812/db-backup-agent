from __future__ import annotations
from pathlib import Path
from typing import Callable

import json

from app.adapters.base import ConnectionInfo, register_adapter, run_subprocess


def _parse_list_output(raw: str) -> list[str]:
    """解析 mongosh listDatabases 的 JSON 输出(容忍首尾 shell 提示行)。"""
    text = raw.strip()
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"mongosh 输出无法解析: {text[:120]}")
    doc = json.JSONDecoder().raw_decode(text[start:])
    return [d["name"] for d in doc[0].get("databases", []) if d.get("name")]



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


    def list_databases(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> list[str]:
        """列出该账号有权限的库:authorizedDatabases=true 由服务端按角色过滤。
        需要镜像内安装 mongosh(与 mongodump 同族)。"""
        cmd = ["mongosh", "--quiet"]
        if info.host:
            cmd += ["--host", info.host]
        if info.port:
            cmd += ["--port", str(info.port)]
        if info.username:
            cmd += ["-u", info.username, "-p", info.password or ""]
        cmd += ["--eval",
                "JSON.stringify(db.adminCommand({listDatabases: 1, authorizedDatabases: true}))"]
        out = run_subprocess_capture(cmd, timeout=15, is_cancelled=is_cancelled)
        return _parse_list_output(out)


    def dump_set(self, info: ConnectionInfo, db_names: list[str], dest_path: str):
        """多库备份集:mongodump --archive --gzip --nsList(原生多库单归档)。"""
        argv = ["mongodump", f"--archive={dest_path}", "--gzip",
                f"--nsList={','.join(db_names)}"]
        if info.host:
            argv += ["--host", info.host]
        if info.port:
            argv += ["--port", str(info.port)]
        if info.username:
            argv += ["-u", info.username, "-p", info.password or ""]
        run_subprocess(argv, timeout=None)
        return Path(dest_path)


register_adapter(MongoAdapter())
