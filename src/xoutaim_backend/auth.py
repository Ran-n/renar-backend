#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.008319
Revised: 2026/07/09 10:06:23.177271
"""

import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User, utcnow

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
_basic = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(_basic)) -> str:
    if not settings.admin_username or not settings.admin_password:
        raise HTTPException(status_code=503, detail="ADMIN_USERNAME or ADMIN_PASSWORD not configured")
    user_ok = secrets.compare_digest(credentials.username.encode(), settings.admin_username.encode())
    pw_ok = secrets.compare_digest(credentials.password.encode(), settings.admin_password.encode())
    if not user_ok or not pw_ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="Admin"'},
        )
    return credentials.username


# bcrypt only reads the first 72 bytes of a password; since 5.x it raises
# instead of truncating silently. Schemas cap passwords at 72 bytes, so
# hash_password never sees longer input — but verify_password can (e.g. an
# absurdly long login attempt) and must answer False, not crash with a 500.
BCRYPT_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def user_id_from_token(token: str) -> int | None:
    """Decode a bearer token to its user id without a DB hit, or None if the
    token is missing/invalid/expired. Used by usage tracking to attribute a
    request to a user cheaply, off the request's hot path."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error from None

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been banned")
    _touch_activity(user, db)
    return user


def _touch_activity(user: User, db: Session) -> None:
    """Usage bookkeeping: one authenticated request = one activity tick.

    Server-side increment (not read-modify-write) so concurrent requests
    from the same user can't lose counts.
    """
    db.query(User).filter(User.id == user.id).update(
        {User.last_active_at: utcnow(), User.request_count: User.request_count + 1},
        synchronize_session=False,
    )
    db.commit()
