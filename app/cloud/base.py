from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CloudConfig:
    """已解密的云存储配置(传给适配器执行上传/删除)。"""
    endpoint: str          # host:port(无 scheme)
    access_key: str
    secret_key: str
    bucket: str
    region: str | None = None
    secure: bool = True
    prefix: str = ""


class StorageAdapter(Protocol):
    provider: str

    def upload(self, cfg: CloudConfig, local_path: str, key: str) -> str:
        """上传 local_path 到云,key 为对象名。返回 remote_uri。失败抛异常。"""
        ...

    def delete(self, cfg: CloudConfig, key: str) -> None:
        """删除对象。失败抛异常。"""
        ...

    def test(self, cfg: CloudConfig) -> None:
        """连接/凭据/桶存在性校验。失败抛异常。"""
        ...


_REGISTRY: dict[str, StorageAdapter] = {}


def register_storage(adapter: StorageAdapter) -> None:
    _REGISTRY[adapter.provider] = adapter


def get_storage(provider: str) -> StorageAdapter:
    try:
        return _REGISTRY[provider]
    except KeyError:
        raise ValueError(f"不支持的云存储: {provider}")
