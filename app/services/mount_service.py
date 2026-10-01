"""NFS/SMB 目的的容器内挂载管理(配置存 SQLite,凭据 Fernet 解密)。

- 挂载点约定 /mnt/dest-<id>(容器层,重建容器后由启动重挂恢复);
- 幂等:os.path.ismount 为真则跳过;
- SMB 凭据经 MOUNT_ROOT/.creds 下 0600 临时文件传递(credentials= 引用),不进命令行,挂载后即删。"""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.crypto import Crypto
from app.db.models import CloudDestination, SystemLog

from app.config import settings

MOUNT_ROOT = settings.mount_root


def mount_point(dest_id: int) -> Path:
    return MOUNT_ROOT / f"dest-{dest_id}"


def is_mounted(dest_id: int) -> bool:
    return os.path.ismount(mount_point(dest_id))


def _run(argv: list[str]) -> None:
    proc = subprocess.run(argv, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"挂载命令失败: {proc.stderr.decode('utf-8', 'replace').strip()}")


def mount_destination(dest: CloudDestination, crypto: Crypto) -> None:
    """挂载单个 nfs/smb 目的地(幂等)。失败抛 RuntimeError(含 stderr)。"""
    mp = mount_point(dest.id)
    if os.path.ismount(mp):
        return
    cfg = json.loads(dest.mount_config or "{}")
    mp.mkdir(parents=True, exist_ok=True)

    if dest.provider == "nfs":
        version = cfg.get("version", "nfs4")
        if version == "nfs3":
            argv = ["mount", "-t", "nfs", "-o", "vers=3,nolock",
                    f"{cfg['server']}:{cfg['export']}", str(mp)]
        else:
            argv = ["mount", "-t", "nfs4", "-o", "vers=4.1",
                    f"{cfg['server']}:{cfg['export']}", str(mp)]
        _run(argv)
    elif dest.provider == "smb":
        # 凭据走 0600 临时文件,绝不让密码出现在命令行/进程列表
        creds_dir = MOUNT_ROOT / ".creds"
        creds_dir.mkdir(parents=True, exist_ok=True)
        creds = creds_dir / f"dest-{dest.id}.creds"
        lines = [f"username={cfg.get('username') or 'guest'}"]
        password = crypto.decrypt(dest.mount_password_enc) if dest.mount_password_enc else ""
        lines.append(f"password={password}")
        if cfg.get("domain"):
            lines.append(f"domain={cfg['domain']}")
        creds.write_text("\n".join(lines) + "\n")
        os.chmod(creds, 0o600)
        try:
            argv = ["mount", "-t", "cifs", "-o", f"vers=3.0,credentials={creds}",
                    f"//{cfg['server']}/{cfg['share']}", str(mp)]
            _run(argv)
        finally:
            try:
                creds.unlink()
            except FileNotFoundError:
                pass
    else:
        raise ValueError(f"provider {dest.provider} 不支持挂载")


def unmount_destination(dest_id: int) -> None:
    mp = mount_point(dest_id)
    if os.path.ismount(mp):
        subprocess.run(["umount", "-f", str(mp)], capture_output=True, timeout=60)
    try:
        mp.rmdir()
    except OSError:
        pass


def remount_all(db: Session, crypto: Crypto) -> None:
    """启动时重挂全部启用的 nfs/smb 目的地;单目的地失败记 error 后继续。"""
    dests = (
        db.query(CloudDestination)
        .filter(CloudDestination.enabled == True,  # noqa: E712
                CloudDestination.provider.in_(("nfs", "smb")))
        .all()
    )
    for d in dests:
        try:
            mount_destination(d, crypto)
        except Exception as exc:
            db.add(SystemLog(level="error", source="mount",
                             message=f"目的地 {d.name}(#{d.id})启动挂载失败:{exc}"))
            db.commit()
