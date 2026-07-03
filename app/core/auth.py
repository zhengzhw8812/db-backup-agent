from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session

from app.db.models import Account
from app.services.account_service import get_account
from app.core.security import verify_password

SESSION_KEY = "account_id"


def login(request: Request, db: Session, username: str, password: str) -> Account:
    acc = get_account(db)
    if acc is None or acc.username != username or not verify_password(password, acc.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    request.session[SESSION_KEY] = acc.id
    return acc


def logout(request: Request) -> None:
    request.session.clear()


def current_account_id(request: Request) -> int:
    acc_id = request.session.get(SESSION_KEY)
    if acc_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    return acc_id
