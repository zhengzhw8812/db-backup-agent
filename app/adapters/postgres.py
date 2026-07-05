from __future__ import annotations
import os
from typing import Callable

from app.adapters.base import ConnectionInfo, register_adapter, run_subprocess, run_subprocess_capture


class PostgresAdapter:
    type = "pg"

    def argv(self, info: ConnectionInfo) -> list[str]:
        cmd = ["pg_dump", "--no-password"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-p", str(info.port)]
        if info.username:
            cmd += ["-U", info.username]
        if info.db_name:
            cmd += [info.db_name]
        return cmd

    def env(self, info: ConnectionInfo) -> dict:
        e = os.environ.copy()
        if info.password:
            e["PGPASSWORD"] = info.password
        return e

    def dump(self, info: ConnectionInfo, dest_path: str, *,
             is_cancelled: Callable[[], bool] | None = None) -> None:
        with open(dest_path, "wb") as f:
            run_subprocess(self.argv(info), env=self.env(info), stdout=f, is_cancelled=is_cancelled)

    def restore_argv(self, info: ConnectionInfo, src_path: str) -> list[str]:
        cmd = ["psql", "--no-password", "-v", "ON_ERROR_STOP=1"]  # 遇 SQL 错误立即非零退出,避免半恢复被误判成功
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-p", str(info.port)]
        if info.username:
            cmd += ["-U", info.username]
        if info.db_name:
            cmd += ["-d", info.db_name]
        cmd += ["-f", src_path]
        return cmd

    def restore(self, info: ConnectionInfo, src_path: str, *,
                is_cancelled: Callable[[], bool] | None = None) -> None:
        run_subprocess(self.restore_argv(info, src_path), env=self.env(info), is_cancelled=is_cancelled)

    def test(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> None:
        """连接/认证探测:psql -c 'select 1'(短超时,失败抛异常)。"""
        cmd = ["psql", "--no-password"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-p", str(info.port)]
        if info.username:
            cmd += ["-U", info.username]
        if info.db_name:
            cmd += ["-d", info.db_name]
        cmd += ["-c", "select 1"]
        run_subprocess(cmd, env=self.env(info), timeout=10, is_cancelled=is_cancelled)

    def list_databases(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> list[str]:
        """列出该用户可连接的非模板库:连维护库 postgres(失败回退 template1)→
        SELECT datname FROM pg_database WHERE datistemplate=false AND datallowconn。
        密码仅走 PGPASSWORD env。"""
        sql = "SELECT datname FROM pg_database WHERE datistemplate = false AND datallowconn ORDER BY 1"
        last_err: Exception | None = None
        for maint in ("postgres", "template1"):
            cmd = ["psql", "--no-password", "-t", "-A"]  # -t 去表头, -A 不对齐
            if info.host:
                cmd += ["-h", info.host]
            if info.port:
                cmd += ["-p", str(info.port)]
            if info.username:
                cmd += ["-U", info.username]
            cmd += ["-d", maint, "-c", sql]
            try:
                out = run_subprocess_capture(cmd, env=self.env(info), timeout=10, is_cancelled=is_cancelled)
                return [ln.strip() for ln in out.splitlines() if ln.strip()]
            except RuntimeError as e:
                last_err = e
                continue
        raise RuntimeError(f"无法连接到维护库 postgres/template1,请检查用户对维护库的 CONNECT 权限: {last_err}")


register_adapter(PostgresAdapter())
