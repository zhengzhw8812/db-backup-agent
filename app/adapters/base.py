from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ConnectionInfo:
    """已解密的连接信息(传给适配器执行 dump)。"""
    type: str
    host: str | None = None
    port: int | None = None
    db_name: str | None = None
    username: str | None = None
    password: str | None = None  # 明文(已用 Fernet 解出)


class BackupAdapter(Protocol):
    type: str

    def dump(self, info: ConnectionInfo, dest_path: str) -> None:
        """执行 dump,把原始(未压缩)字节写入 dest_path。失败抛异常。"""
        ...


_REGISTRY: dict[str, BackupAdapter] = {}


def register_adapter(adapter: BackupAdapter) -> None:
    _REGISTRY[adapter.type] = adapter


def get_adapter(db_type: str) -> BackupAdapter:
    try:
        return _REGISTRY[db_type]
    except KeyError:
        raise ValueError(f"不支持的数据库类型: {db_type}")
