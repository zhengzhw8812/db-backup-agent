from __future__ import annotations

from pathlib import Path
from sqlalchemy.orm import Session

from app.db.models import BackupRecord, SyncTarget, CloudDestination
from app.core.crypto import Crypto
from app.cloud.base import CloudConfig, get_storage


def _cloud_config(dest: CloudDestination, crypto: Crypto) -> CloudConfig:
    return CloudConfig(
        endpoint=dest.endpoint,
        access_key=crypto.decrypt(dest.access_key_enc),
        secret_key=crypto.decrypt(dest.secret_enc),
        bucket=dest.bucket,
        region=dest.region,
        secure=dest.secure,
        prefix=dest.prefix,
    )


def run_sync(db: Session, crypto: Crypto, backup_record: BackupRecord, backup_dir: Path) -> dict:
    """把一份备份文件上传到其连接所有启用的云目标。返回 {synced, errors}。

    每个目标独立 try/except —— 一个目标失败不影响其余。文件路径做穿越校验。"""
    if not backup_record.file_path:
        raise FileNotFoundError("备份记录无文件路径")
    local_path = (backup_dir / backup_record.file_path).resolve()
    base = backup_dir.resolve()
    if local_path != base and base not in local_path.parents:
        raise ValueError("备份文件路径非法")
    if not local_path.exists():
        raise FileNotFoundError("备份文件不存在")

    key = backup_record.file_path
    targets = (
        db.query(SyncTarget)
        .filter(SyncTarget.connection_id == backup_record.connection_id, SyncTarget.enabled.is_(True))
        .all()
    )
    synced, errors = [], []
    for t in targets:
        dest = db.get(CloudDestination, t.cloud_destination_id)
        if dest is None or not dest.enabled:
            continue
        try:
            cfg = _cloud_config(dest, crypto)
            uri = get_storage(dest.provider).upload(cfg, str(local_path), key)
            synced.append({"target_id": t.id, "destination": dest.name, "uri": uri})
        except Exception as exc:
            errors.append({"target_id": t.id, "destination": dest.name, "error": str(exc)})
    return {"synced": synced, "errors": errors}
