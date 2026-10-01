"""NFS/SMB 目的地存储适配器:文件落到已挂载的共享目录。

挂载本身由 app/services/mount_service.py 负责(容器内 mount);
本适配器只操作挂载点内的文件,与 S3 适配器同构(test/upload/delete),
因此 SyncTarget、备份后同步、保留清理云联动零改动复用。"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

from app.cloud.base import CloudConfig, register_storage


class ShareStorageAdapter:
    """provider=nfs/smb 共用的落盘适配器。cfg.mount_point 指向已挂载目录。"""

    def __init__(self, provider: str):
        self.provider = provider

    def _base(self, cfg: CloudConfig) -> Path:
        if not cfg.mount_point or not os.path.ismount(cfg.mount_point):
            raise RuntimeError(f"挂载点不可用:{cfg.mount_point or '(未设置)'}(目的地未挂载或已失效)")
        base = Path(cfg.mount_point)
        if cfg.prefix:
            base = base / cfg.prefix
        return base

    def test(self, cfg: CloudConfig) -> None:
        base = self._base(cfg)
        probe = base / ".probe"
        probe.write_bytes(b"probe")
        ok = probe.read_bytes() == b"probe"
        probe.unlink()
        if not ok:
            raise RuntimeError("挂载点读写探针失败")

    def upload(self, cfg: CloudConfig, local_path: str, key: str) -> str:
        dest = self._base(cfg) / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        return f"share://{cfg.prefix}/{key}" if cfg.prefix else f"share://{key}"

    def delete(self, cfg: CloudConfig, key: str) -> None:
        target = self._base(cfg) / key
        try:
            target.unlink()
        except FileNotFoundError:
            pass  # 已不存在视为删除成功(幂等)


register_storage(ShareStorageAdapter("nfs"))
register_storage(ShareStorageAdapter("smb"))
