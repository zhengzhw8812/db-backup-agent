from __future__ import annotations
import os
from pathlib import Path


def safe_remove(path: Path | str) -> None:
    """删除文件,忽略不存在/无权限等 OSError(清理中间文件用)。"""
    try:
        os.remove(path)
    except OSError:
        pass
