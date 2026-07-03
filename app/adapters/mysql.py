from __future__ import annotations
import os
import subprocess
import tempfile

from app.adapters.base import ConnectionInfo, register_adapter


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

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        defaults_file = self._write_defaults(info)
        try:
            argv = self.argv(info, defaults_file)
            with open(dest_path, "wb") as f:
                subprocess.run(argv, stdout=f, stderr=subprocess.PIPE, check=True)
        finally:
            try:
                os.unlink(defaults_file)
            except OSError:
                pass


register_adapter(MysqlAdapter())
