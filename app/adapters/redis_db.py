from __future__ import annotations
import os
from typing import Callable

from app.adapters.base import ConnectionInfo, register_adapter, run_subprocess


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

    def dump(self, info: ConnectionInfo, dest_path: str, *,
             is_cancelled: Callable[[], bool] | None = None) -> None:
        run_subprocess(self.dump_argv(info, dest_path), env=self.env(info), is_cancelled=is_cancelled)

    def restore(self, info: ConnectionInfo, src_path: str, *,
                is_cancelled: Callable[[], bool] | None = None) -> None:
        raise NotImplementedError(
            "Redis 恢复需停写并替换 dump.rdb 后重启服务,暂不支持自动还原"
        )

    def test(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> None:
        # redis-cli PING 对鉴权失败的退出码不稳定(部分版本 exit 0),无法可靠判定,暂不支持
        raise NotImplementedError("Redis 暂不支持连接测试,请新建后直接尝试备份")


register_adapter(RedisAdapter())
