import json
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import config
from app.db.models import DbConnection
from app.core.crypto import Crypto
from app.adapters.base import ConnectionInfo, get_adapter


def _validate_sqlite_path(db_name: str | None) -> None:
    """SQLite 备份的 db 文件路径必须落在 data_dir 内,杜绝任意文件读/写
    (防止 db_name=/etc/shadow 读取或 restore 覆盖任意文件)。"""
    if not db_name:
        return
    root = config.settings.data_dir.resolve()
    target = (root / db_name).resolve() if not Path(db_name).is_absolute() else Path(db_name).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SQLite 文件路径必须位于数据目录(data_dir)内",
        )


def create_connection(db: Session, crypto: Crypto, data) -> DbConnection:
    if data.type == "sqlite":
        _validate_sqlite_path(data.db_name)
    c = DbConnection(
        name=data.name,
        type=data.type,
        host=data.host,
        port=data.port,
        db_name=data.db_name,
        db_names=json.dumps(data.db_names) if data.db_names else None,
        username=data.username,
        password_enc=crypto.encrypt(data.password) if data.password else None,
        extra=json.dumps(data.extra) if data.extra is not None else None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def get_connection(db: Session, conn_id: int) -> DbConnection:
    c = db.get(DbConnection, conn_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="连接不存在")
    return c


def list_connections(db: Session) -> list[DbConnection]:
    return db.query(DbConnection).order_by(DbConnection.id).all()


def update_connection(db: Session, crypto: Crypto, conn_id: int, data) -> DbConnection:
    c = get_connection(db, conn_id)
    effective_type = data.type or c.type
    if effective_type == "sqlite" and data.db_name is not None:
        _validate_sqlite_path(data.db_name)
    for field in ("name", "type", "host", "port", "db_name", "username"):
        val = getattr(data, field)
        if val is not None:
            setattr(c, field, val)
    # 仅非空才更新密码;空串视为"不修改",避免前端表单重提交时把密码清空
    if data.password:
        c.password_enc = crypto.encrypt(data.password)
    if data.db_names is not None:
        c.db_names = json.dumps(data.db_names) if data.db_names else None
    if data.extra is not None:
        c.extra = json.dumps(data.extra)
    db.commit()
    db.refresh(c)
    return c


def delete_connection(db: Session, conn_id: int) -> None:
    c = get_connection(db, conn_id)
    db.delete(c)
    db.commit()


def decrypt_password(c: DbConnection, crypto: Crypto) -> str | None:
    if not c.password_enc:
        return None
    return crypto.decrypt(c.password_enc)


def test_connection(db: Session, crypto: Crypto, conn_id: int) -> None:
    """探测连接/认证是否可用。失败抛异常(由路由层转 400)。"""
    c = get_connection(db, conn_id)
    info = ConnectionInfo(
        type=c.type, host=c.host, port=c.port, db_name=c.db_name,
        username=c.username, password=decrypt_password(c, crypto),
    )
    get_adapter(c.type).test(info)
