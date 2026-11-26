from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import LoginIn, TokenOut, UserOut
from ..serializers import user_out
from ..services.auth import current_user, issue_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token = issue_token(db, user)
    db.commit()
    return {"token": token, "user": user_out(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)
