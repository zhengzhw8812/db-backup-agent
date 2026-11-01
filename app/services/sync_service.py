from __future__ import annotations

import re
from pathlib import Path
from sqlalchemy.orm import Session

from app.db.models import BackupRecord, SyncTarget, CloudDestination, SystemLog
from app.core.crypto import Crypto
from app.cloud.base import CloudConfig, get_storage

# 自备份云端副本:对象前缀、保留份数、文件名白名单(本地快照命名一致)
SELFBACKUP_PREFIX = "selfbackup/"
CLOUD_KEEP = 30
SELFBACKUP_KEY_RE = re.compile(r"^app-\d{8}-\d{6}\.(db\.gz|sql)$")


def _cloud_config(dest: CloudDestination, crypto: Crypto) -> CloudConfig:
    # nfs/smb:适配器操作挂载点;同步与删除联动共用本构造,必须带上 mount_point
    mount_point = None
    if dest.provider in ("nfs", "smb"):
        from app.services import mount_service

        mount_point = str(mount_service.mount_point(dest.id))
    return CloudConfig(
        endpoint=dest.endpoint,
        access_key=crypto.decrypt(dest.access_key_enc),
        secret_key=crypto.decrypt(dest.secret_enc),
        bucket=dest.bucket,
        region=dest.region,
        secure=dest.secure,
        prefix=dest.prefix,
        mount_point=mount_point,
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


def delete_cloud_copies(db: Session, crypto: Crypto, connection_id: int, key: str) -> tuple[int, int]:
    """删除该连接所有启用云目标上的对象 key(对象名与上传时一致,即备份记录的 file_path)。

    单目标失败:记 SystemLog(warning)后继续其余目标。返回 (成功数, 失败数);
    失败数 > 0 时调用方必须保留本地记录与文件,等待下轮重试。"""
    targets = (
        db.query(SyncTarget)
        .filter(SyncTarget.connection_id == connection_id, SyncTarget.enabled.is_(True))
        .all()
    )
    deleted, failed = 0, 0
    for t in targets:
        dest = db.get(CloudDestination, t.cloud_destination_id)
        if dest is None or not dest.enabled:
            continue  # 目的地缺失/禁用 → 不发起破坏性删除(与 sync 启用语义一致)
        try:
            cfg = _cloud_config(dest, crypto)
            get_storage(dest.provider).delete(cfg, key)
            deleted += 1
        except Exception as exc:
            failed += 1
            db.add(SystemLog(level="warning", source="cloud",
                             message=f"云副本删除失败:{dest.name}:{key}",
                             context=str(exc)))
            db.commit()
    return deleted, failed


def _rotate_cloud_self_backups(storage, cfg: CloudConfig) -> None:
    """云端 selfbackup/ 前缀轮转:仅匹配白名单名,按名排序删最旧,保留 CLOUD_KEEP 份。"""
    names = [k for k in storage.list_prefix(cfg, SELFBACKUP_PREFIX)
             if SELFBACKUP_KEY_RE.match(k[len(SELFBACKUP_PREFIX):])]
    names.sort()
    for old in names[:-CLOUD_KEEP]:
        storage.delete(cfg, old)


def upload_self_backup(db: Session, crypto: Crypto, path: Path) -> dict:
    """把自备份快照上传到所有启用的云目标(对象 key = selfbackup/<文件名>)并做云端轮转。

    自备份不属于任何连接,不走 SyncTarget 规则 —— 目标集就是全部 enabled 的云目的地,
    需排除某目标时在云存储页禁用即可。上传/轮转逐目标独立 try/except,失败记
    SystemLog(warning)不影响其余目标,也不影响自备份本身。返回 {synced, errors}。"""
    synced, errors = [], []
    key = f"{SELFBACKUP_PREFIX}{Path(path).name}"
    dests = db.query(CloudDestination).filter(CloudDestination.enabled.is_(True)).all()
    for dest in dests:
        storage = None
        try:
            cfg = _cloud_config(dest, crypto)
            storage = get_storage(dest.provider)
            uri = storage.upload(cfg, str(path), key)
            synced.append({"destination": dest.name, "uri": uri})
        except Exception as exc:
            errors.append({"destination": dest.name, "error": str(exc)})
            db.add(SystemLog(level="warning", source="cloud",
                             message=f"自备份上云失败:{dest.name}:{Path(path).name}",
                             context=str(exc)))
            db.commit()
            continue
        try:
            _rotate_cloud_self_backups(storage, cfg)
        except Exception as exc:
            db.add(SystemLog(level="warning", source="cloud",
                             message=f"云端自备份轮转失败:{dest.name}",
                             context=str(exc)))
            db.commit()
    return {"synced": synced, "errors": errors}


def delete_self_backup_cloud(db: Session, crypto: Crypto, name: str) -> None:
    """尽力删除各启用云目标上的 selfbackup/<name> 副本;失败仅记日志。"""
    key = f"{SELFBACKUP_PREFIX}{name}"
    for dest in db.query(CloudDestination).filter(CloudDestination.enabled.is_(True)).all():
        try:
            get_storage(dest.provider).delete(_cloud_config(dest, crypto), key)
        except Exception as exc:
            db.add(SystemLog(level="warning", source="cloud",
                             message=f"云自备份副本删除失败:{dest.name}:{name}",
                             context=str(exc)))
            db.commit()
