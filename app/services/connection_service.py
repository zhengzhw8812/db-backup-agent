import json
from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session

from app.db.models import DbConnection
from app.core.crypto import Crypto


def _crypto(request: Request) -> Crypto:
    return request.app.state.crypto


def create_connection(db: Session, request: Request, data) -> DbConnection:
    c = DbConnection(
        name=data.name,
        type=data.type,
        host=data.host,
        port=data.port,
        db_name=data.db_name,
        username=data.username,
        password_enc=_crypto(request).encrypt(data.password) if data.password else None,
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


def update_connection(db: Session, request: Request, conn_id: int, data) -> DbConnection:
    c = get_connection(db, conn_id)
    for field in ("name", "type", "host", "port", "db_name", "username"):
        val = getattr(data, field)
        if val is not None:
            setattr(c, field, val)
    if data.password is not None:
        c.password_enc = _crypto(request).encrypt(data.password) if data.password else None
    if data.extra is not None:
        c.extra = json.dumps(data.extra)
    db.commit()
    db.refresh(c)
    return c


def delete_connection(db: Session, conn_id: int) -> None:
    c = get_connection(db, conn_id)
    db.delete(c)
    db.commit()


def decrypt_password(c: DbConnection, request: Request) -> str | None:
    if not c.password_enc:
        return None
    return _crypto(request).decrypt(c.password_enc)
