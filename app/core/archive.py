from __future__ import annotations
import gzip
import hashlib
import shutil
import zlib
from pathlib import Path


def compress_file(src: Path | str, dest: Path | str) -> None:
    """gzip 压缩 src → dest。"""
    with open(src, "rb") as fin, gzip.open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)


def compress_and_hash(src: Path | str, dest: Path | str) -> str:
    """gzip 压缩 src → dest,并在写入压缩流的同时计算 SHA-256(单次遍历,
    避免对大备份文件先写后读两次 I/O)。返回压缩后文件(.gz)的 sha256 十六进制。

    使用 zlib(wbits=gzip) 逐块产出压缩字节,边写边更新哈希;
    结果与 sha256_of_file(dest) 一致(哈希的就是落盘的字节)。"""
    h = hashlib.sha256()
    compressor = zlib.compressobj(level=9, wbits=16 + zlib.MAX_WBITS)  # 16+ = gzip 输出格式
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        while True:
            chunk = fin.read(65536)
            if not chunk:
                break
            out = compressor.compress(chunk)
            if out:
                fout.write(out)
                h.update(out)
        out = compressor.flush()
        if out:
            fout.write(out)
            h.update(out)
    return h.hexdigest()


def sha256_of_file(path: Path | str) -> str:
    """计算文件内容的 SHA-256(用于完整性校验)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def decompress_file(src: Path | str, dest: Path | str) -> None:
    """gzip 解压 src → dest(还原出原始未压缩 dump,供 restore 喂入适配器)。"""
    with gzip.open(src, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout)
