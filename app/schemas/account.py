from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AccountOut(BaseModel):
    id: int
    username: str
