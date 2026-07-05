from sqlalchemy.orm import Session
from app.db.models import Account
from app.core.security import hash_password


def get_account(db: Session) -> Account | None:
    return db.query(Account).first()


def ensure_account(db: Session, username: str, password: str) -> Account:
    acc = get_account(db)
    if acc is not None:
        return acc
    acc = Account(username=username, password_hash=hash_password(password))
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
