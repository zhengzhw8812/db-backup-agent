from __future__ import annotations
import hashlib
import zlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.db.models import BackupRecord


def run_verify(db: Session, rec: BackupRecord, backup_dir: Path) -> BackupRecord:
    """验证一份备份文件(单次读 .gz,常量内存):

    - 同一批字节喂 SHA-256 与 gzip 解压器(zlib wbits=31 自动识别 gzip 格式);
    - SHA-256 与 rec.checksum 比对(注意:checksum 是 .gz **压缩字节**的哈希,
      由 archive.compress_and_hash 写入);
    - 解压器到流尾未 eof(截断)、CRC 不符(zlib.error)或尾部有多余数据均判损坏。"""
    if rec.file_path is None:
        raise ValueError("记录无文件路径")
    local = (backup_dir / rec.file_path).resolve()
    base = backup_dir.resolve()
    if local != base and base not in local.parents:
        raise ValueError("备份文件路径非法")

    error = None
    if not local.exists():
        error = "文件不存在"
    else:
        h = hashlib.sha256()
        d = zlib.decompressobj(zlib.MAX_WBITS | 16)
        try:
            with open(local, "rb") as fin:
                while chunk := fin.read(65536):
                    h.update(chunk)
                    d.decompress(chunk)
            if not d.eof:
                error = "gzip 数据损坏:流被截断"
            elif d.unused_data:
                error = "gzip 数据损坏:流尾有多余数据"
            elif h.hexdigest() != (rec.checksum or ""):
                error = "checksum 校验失败"
        except zlib.error as exc:
            error = f"gzip 数据损坏:{exc}"

    if error is None:
        rec.verify_status = "passed"
        rec.verify_error = None
    else:
        rec.verify_status = "failed"
        rec.verify_error = error
    rec.verified_at = utcnow()
    db.commit()
    db.refresh(rec)
    return rec
