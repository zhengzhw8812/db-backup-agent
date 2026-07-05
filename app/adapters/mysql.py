from __future__ import annotations
import os
import tempfile
from typing import Callable

from app.adapters.base import ConnectionInfo, register_adapter, run_subprocess


class MysqlAdapter:
    type = "mysql"

    def argv(self, info: ConnectionInfo, defaults_file: str) -> list[str]:
        cmd = ["mysqldump", f"--defaults-extra-file={defaults_file}"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-P", str(info.port)]
        if info.db_name:
            cmd += [info.db_name]
        else:
            cmd += ["--all-databases"]
        return cmd

    def _write_defaults(self, info: ConnectionInfo) -> str:
        fd, path = tempfile.mkstemp(prefix="my.", suffix=".cnf")
        lines = ["[client]"]
        if info.username:
            lines.append(f"user = {info.username}")
        if info.password:
            lines.append(f"password = {info.password}")
        if info.port:
            lines.append(f"port = {info.port}")
        if info.host:
            lines.append(f"host = {info.host}")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(path, 0o600)
        return path

    def dump(self, info: ConnectionInfo, dest_path: str, *,
             is_cancelled: Callable[[], bool] | None = None) -> None:
        defaults_file = self._write_defaults(info)
        try:
            with open(dest_path, "wb") as f:
                run_subprocess(self.argv(info, defaults_file), stdout=f, is_cancelled=is_cancelled)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass

    def restore_argv(self, info: ConnectionInfo, defaults_file: str) -> list[str]:
        cmd = ["mysql", f"--defaults-extra-file={defaults_file}"]
        if info.host:
            cmd += ["-h", info.host]
        if info.port:
            cmd += ["-P", str(info.port)]
        if info.db_name:
            cmd += [info.db_name]
        return cmd

    def restore(self, info: ConnectionInfo, src_path: str, *,
                is_cancelled: Callable[[], bool] | None = None) -> None:
        defaults_file = self._write_defaults(info)
        try:
            with open(src_path, "rb") as f:
                run_subprocess(self.restore_argv(info, defaults_file), stdin=f, is_cancelled=is_cancelled)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass

    def test(self, info: ConnectionInfo, *, is_cancelled: Callable[[], bool] | None = None) -> None:
        """连接/认证探测:mysql -e 'select 1'(走 defaults-extra-file,密码不上 argv)。"""
        defaults_file = self._write_defaults(info)
        try:
            cmd = ["mysql", f"--defaults-extra-file={defaults_file}"]
            if info.host:
                cmd += ["-h", info.host]
            if info.port:
                cmd += ["-P", str(info.port)]
            if info.db_name:
                cmd += [info.db_name]
            cmd += ["-e", "select 1"]
            run_subprocess(cmd, timeout=10, is_cancelled=is_cancelled)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass


register_adapter(MysqlAdapter())
