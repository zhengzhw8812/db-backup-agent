import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_account
from app.schemas.connection import ConnectionProbe, ConnectionCreate, ConnectionUpdate, ConnectionOut
from app.services import connection_service as svc

router = APIRouter()


def _db_names_of(c) -> list[str]:
    """优先 db_names(JSON);为空回退到旧 db_name;再为空返回 []。"""
    if c.db_names:
        try:
            names = json.loads(c.db_names)
            if names:
                return names
        except (TypeError, ValueError):
            pass
    if c.db_name:
        return [c.db_name]
    return []


def _serialize(c) -> ConnectionOut:
    return ConnectionOut(
        id=c.id, name=c.name, type=c.type, host=c.host, port=c.port,
        db_name=c.db_name, db_names=_db_names_of(c),
        username=c.username,
        extra=json.loads(c.extra) if c.extra else None, created_at=c.created_at,
    )


@router.get("", response_model=list[ConnectionOut])
def list_(db: Session = Depends(get_db), _=Depends(get_current_account)):
    return [_serialize(c) for c in svc.list_connections(db)]


@router.post("", response_model=ConnectionOut, status_code=201)
def create(payload: ConnectionCreate, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _serialize(svc.create_connection(db, request.app.state.crypto, payload))


@router.get("/{conn_id}", response_model=ConnectionOut)
def detail(conn_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _serialize(svc.get_connection(db, conn_id))


@router.put("/{conn_id}", response_model=ConnectionOut)
def update(conn_id: int, payload: ConnectionUpdate, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    return _serialize(svc.update_connection(db, request.app.state.crypto, conn_id, payload))


@router.delete("/{conn_id}", status_code=204)
def delete(conn_id: int, db: Session = Depends(get_db), _=Depends(get_current_account)):
    svc.delete_connection(db, conn_id)


@router.post("/{conn_id}/test")
def test(conn_id: int, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    try:
        svc.test_connection(db, request.app.state.crypto, conn_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@router.post("/list-databases")
def list_databases_pre(payload: ConnectionProbe, request: Request, _=Depends(get_current_account)):
    try:
        dbs = svc.list_databases_for_payload(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"databases": dbs}


@router.post("/{conn_id}/databases")
def list_databases_post(conn_id: int, request: Request, db: Session = Depends(get_db), _=Depends(get_current_account)):
    try:
        dbs = svc.list_databases_for_connection(db, request.app.state.crypto, conn_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"databases": dbs}
