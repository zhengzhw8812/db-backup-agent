from __future__ import annotations
import os
import subprocess

from app.adapters.base import ConnectionInfo, register_adapter


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

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        with open(dest_path, "wb") as f:
            subprocess.run(
                self.argv(info),
                env=self.env(info),
                stdout=f,
                stderr=subprocess.PIPE,
                check=True,
            )


register_adapter(PostgresAdapter())
