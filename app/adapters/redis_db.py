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
