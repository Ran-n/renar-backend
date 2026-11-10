#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.008319
Revised: 2026/11/09 23:36:40.975282
"""

import logging
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User, utcnow
from . import admin_session

_log = logging.getLogger(__name__)

ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AdminLoginRequired(Exception):
    """Raised by require_admin when there is no valid admin session; main.py
    answers a GET with a redirect to the login page and anything else with a
    401 page (a redirect would silently drop the submitted form)."""

    def __init__(self, method: str, path_with_query: str):
        super().__init__(f"admin login required for {method} {path_with_query}")
        self.method = method
        self.path_with_query = path_with_query


def _not_configured() -> HTTPException:
    return HTTPException(
        status_code=503, detail="Admin panel not configured (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_TOTP_SECRET)"
    )


def _path_with_query(request: Request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def require_admin(request: Request) -> str:
    """The signed-in admin's username, from the session cookie (see admin_session)."""
    if not admin_session.admin_configured():
        raise _not_configured()
    username = admin_session.read_session(request.cookies.get(admin_session.COOKIE_NAME))
    if username is None:
        raise AdminLoginRequired(request.method, _path_with_query(request))
    return username


def require_admin_or_api_token(request: Request) -> str:
    """require_admin, or ``Authorization: Bearer <ADMIN_API_TOKEN>`` for the
    routes a script calls (it can't type an authenticator code). Returns the
    admin username, or ``"api-token"`` for the token, for audit logging."""
    if admin_session.api_token_ok(request.headers.get("authorization")):
        return "api-token"
    if request.headers.get("authorization"):
        _log.warning("admin API token rejected for %s %s", request.method, request.url.path)
        raise HTTPException(status_code=401, detail="Invalid admin API token")
    return require_admin(request)


# bcrypt only reads the first 72 bytes of a password; since 5.x it raises
# instead of truncating silently. schemas.BCRYPT_MAX_PASSWORD_BYTES caps
# inputs at registration/change time, so hash_password never sees longer
# input — but verify_password can (e.g. an absurdly long login attempt)
# and must answer False, not crash with a 500.
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    # "iat" is a registered JWT claim PyJWT floors to whole seconds — too
    # coarse to tell apart a token minted just before vs. just after a
    # password change that happens within the same second. "iat_ts" carries
    # the same instant as a plain float, full microsecond precision intact,
    # for get_current_user's revocation check.
    payload = {"sub": str(user_id), "exp": expire, "iat": now, "iat_ts": now.timestamp()}
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
        issued_at = payload.get("iat_ts")
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error from None

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if user.password_changed_at is not None and (
        issued_at is None or datetime.fromtimestamp(issued_at, UTC) < user.password_changed_at
    ):
        raise credentials_error
    if user.banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been banned")
    _touch_activity(user, db)
    return user


def require_premium(user: User = Depends(get_current_user)) -> User:
    """Gate for premium-only endpoints — the server-side check the UI locks
    mirror. 403 (not 402) so clients treat it like any other permission.

    Only checks the subscription itself; the admin's per-feature kill
    switches (SiteSettings.premium_*_enabled) are checked separately by each
    endpoint/field via users/premium.py::feature_enabled, since they disable
    one perk at a time rather than premium as a whole.
    """
    if not user.is_premium:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Premium subscription required")
    return user


# Every current reader of last_active_at (admin analytics' active_today/
# active_7d, the admin user-detail page, the GDPR export) only needs
# day-level accuracy, so a write on every single authenticated request is
# far more precision than anything consumes — and it's a DB write+commit on
# the single busiest dependency in the app. Skipping the write when the
# existing value is already fresh enough cuts that cost by ~two orders of
# magnitude for an active user without changing anything any reader sees.
_ACTIVITY_TOUCH_INTERVAL = timedelta(minutes=15)


def _touch_activity(user: User, db: Session) -> None:
    """Record the moment of this authenticated request, throttled to at most
    once per `_ACTIVITY_TOUCH_INTERVAL` per user. Request *counts* are not
    kept here — they are derived from endpoint_stats / request_days, which
    UsageTrackingMiddleware maintains.
    """
    now = utcnow()
    if user.last_active_at is not None and now - user.last_active_at < _ACTIVITY_TOUCH_INTERVAL:
        return
    db.query(User).filter(User.id == user.id).update(
        {User.last_active_at: now},
        synchronize_session=False,
    )
    db.commit()
