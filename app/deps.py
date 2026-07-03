from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Account
from app.core.auth import current_account_id


def get_current_account(request: Request, db: Session = Depends(get_db)) -> Account:
    acc_id = current_account_id(request)
    acc = db.get(Account, acc_id)
    if acc is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")
    return acc
