from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import Role
from ..models import ApiToken, User

_PBKDF_ROUNDS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF_ROUNDS).hex()
    return f"pbkdf2_sha256${_PBKDF_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
        return secrets.compare_digest(check, digest)
    except (ValueError, AttributeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(ApiToken(user_id=user.id, token_hash=_token_hash(token)))
    return token


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Bearer 令牌")
    token = authorization.removeprefix("Bearer ").strip()
    api_token = db.scalar(select(ApiToken).where(ApiToken.token_hash == _token_hash(token)))
    if api_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已失效")
    user = db.get(User, api_token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def require_roles(*roles: Role):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"当前角色 {user.role.value} 无权执行该操作，需要 {'/'.join(r.value for r in roles)}",
            )
        return user

    return checker
