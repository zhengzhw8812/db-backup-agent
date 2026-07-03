from __future__ import annotations
import gzip
import hashlib
import shutil
from pathlib import Path


def compress_file(src: Path | str, dest: Path | str) -> None:
    """gzip 压缩 src → dest。"""
    with open(src, "rb") as fin, gzip.open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def sha256_of_file(path: Path | str) -> str:
    """计算文件内容的 SHA-256(用于完整性校验)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
