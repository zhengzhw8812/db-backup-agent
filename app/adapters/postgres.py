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

    def base_argv(self, info: ConnectionInfo, dbname: str | None = None) -> list[str]:
        """psql 基础参数(--no-password/-t/-A + host/port/user/db)。密码走 PGPASSWORD。"""
        argv = ["psql", "--no-password", "-t", "-A"]
        if info.host:
            argv += ["-h", info.host]
        if info.port:
            argv += ["-p", str(info.port)]
        if info.username:
            argv += ["-U", info.username]
        if dbname:
            argv += ["-d", dbname]
        return argv

    def list_databases(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> list[str]:
        """列出该账号真正可备份(pg_dump 可读到数据)的库,两阶段:

        1. 维护库(postgres,失败回退 template1)列出非模板库;
        2. 逐库探测"读数据"能力:超级用户 / pg_read_all_data 角色 / 库 owner /
           任一用户表或视图有 SELECT —— 全无则该库对账号不可备份,剔除。
        (public 角色默认对全部库有 CONNECT,单看 CONNECT 无鉴别力。)
        密码仅走 PGPASSWORD env。"""
        list_sql = ("SELECT datname FROM pg_database "
                    "WHERE datistemplate = false AND datallowconn ORDER BY 1")
        probe_sql = (
            "SELECT 1 WHERE "
            "EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper) "
            "OR pg_has_role(current_user, 'pg_read_all_data', 'member') "
            "OR EXISTS (SELECT 1 FROM pg_tables "
            "   WHERE schemaname NOT IN ('pg_catalog','information_schema','pg_toast') "
            "   AND has_table_privilege(current_user, quote_ident(schemaname)||'.'||quote_ident(tablename), 'SELECT')) "
            "OR EXISTS (SELECT 1 FROM pg_views "
            "   WHERE schemaname NOT IN ('pg_catalog','information_schema') "
            "   AND has_table_privilege(current_user, quote_ident(schemaname)||'.'||quote_ident(viewname), 'SELECT')) "
            "OR (SELECT datdba FROM pg_database WHERE datname = current_database())::regrole::text = current_user "
            "LIMIT 1"
        )
        last_err: Exception | None = None
        for maint in ("postgres", "template1"):
            base = ["psql", "--no-password", "-t", "-A"]
            if info.host:
                base += ["-h", info.host]
            if info.port:
                base += ["-p", str(info.port)]
            if info.username:
                base += ["-U", info.username]
            try:
                out = run_subprocess_capture(base + ["-d", maint, "-c", list_sql],
                                             env=self.env(info), timeout=10, is_cancelled=is_cancelled)
                candidates = [ln.strip() for ln in out.splitlines() if ln.strip()]
            except RuntimeError as e:
                last_err = e
                continue
            allowed: list[str] = []
            for dbname in candidates:
                probe_cmd = base + ["-d", dbname, "-t", "-A", "-c", probe_sql]
                try:
                    probed = run_subprocess_capture(probe_cmd, env=self.env(info),
                                                    timeout=10, is_cancelled=is_cancelled)
                except RuntimeError:
                    continue  # 连不上/无权限的库直接剔除
                if probed.strip() == "1":
                    allowed.append(dbname)
            return allowed
        raise RuntimeError(f"无法连接到维护库 postgres/template1,请检查用户对维护库的 CONNECT 权限: {last_err}")


register_adapter(PostgresAdapter())
