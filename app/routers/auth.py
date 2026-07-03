from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_account
from app.core.auth import login, logout
from app.schemas.account import LoginRequest, AccountOut

router = APIRouter()


@router.post("/login", response_model=AccountOut)
def do_login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    acc = login(request, db, payload.username, payload.password)
    return acc


@router.post("/logout")
def do_logout(request: Request):
    logout(request)
    return {"ok": True}


@router.get("/me", response_model=AccountOut)
def me(acc=Depends(get_current_account)):
    return acc
