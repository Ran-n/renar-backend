#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:23.494179
Revised: 2026/11/09 23:36:44.478479

The admin panel's sign-in: username + password + an authenticator-app (TOTP)
code, held as a stateless session cookie.

The cookie is a JWT signed with ``settings.secret_key`` whose audience
(``renar-admin``) keeps an app user's access token from ever passing as an
admin session, and the reverse. It carries ``cred``, a fingerprint of the
current admin username, password and TOTP secret, recomputed on every
request: changing any of them in ``.env`` ends every session at once without
a session table. There is no sliding renewal: 8 hours after sign-in the next
request goes back to the login page.

Scripts that can't type a code (the APK upload) use ``ADMIN_API_TOKEN``
instead, see ``api_token_ok``.
"""

import logging
import secrets
import threading
import time

import blake3
import jwt
import pyotp

from ..config import settings

_log = logging.getLogger(__name__)

COOKIE_NAME = "renar_admin"
AUDIENCE = "renar-admin"
SESSION_SECONDS = 8 * 60 * 60
_ALGORITHM = "HS256"
_TOTP_STEP = 30

# Replay guard: a code whose time step is not newer than the last one used
# is refused. Process-local on purpose (one uvicorn worker); a restart
# forgetting it only re-opens the ±1-step window, at most 90 seconds.
_last_step_lock = threading.Lock()
_last_used_step = -1


def admin_configured() -> bool:
    return bool(settings.admin_username and settings.admin_password and settings.admin_totp_secret)


def _cred_fingerprint() -> str:
    material = "\0".join((settings.admin_username, settings.admin_password, settings.admin_totp_secret))
    return blake3.blake3(material.encode()).hexdigest()[:16]


def _matching_step(code: str, now: float) -> int | None:
    """The time step (current ±1) whose TOTP equals ``code``, else None."""
    totp = pyotp.TOTP(settings.admin_totp_secret)
    current = int(now // _TOTP_STEP)
    for step in (current, current - 1, current + 1):
        if secrets.compare_digest(totp.at(step * _TOTP_STEP), code):
            return step
    return None


def verify_login(username: str, password: str, code: str, now: float | None = None) -> bool:
    """Every part must match; the TOTP step must not have been used before."""
    global _last_used_step
    if not admin_configured():
        return False
    user_ok = secrets.compare_digest(username.encode(), settings.admin_username.encode())
    password_ok = secrets.compare_digest(password.encode(), settings.admin_password.encode())
    code = code.replace(" ", "")
    step = _matching_step(code, time.time() if now is None else now) if code.isdigit() and len(code) == 6 else None
    if not (user_ok and password_ok and step is not None):
        return False
    with _last_step_lock:
        if step <= _last_used_step:
            _log.warning("admin login refused: authenticator code reused")
            return False
        _last_used_step = step
    return True


def reset_replay_guard() -> None:
    """Tests only: forget the last used TOTP step."""
    global _last_used_step
    with _last_step_lock:
        _last_used_step = -1


def issue_session(username: str, now: float | None = None) -> str:
    iat = int(time.time() if now is None else now)
    claims = {"sub": username, "aud": AUDIENCE, "iat": iat, "exp": iat + SESSION_SECONDS, "cred": _cred_fingerprint()}
    return jwt.encode(claims, settings.secret_key, algorithm=_ALGORITHM)


def read_session(token: str | None) -> str | None:
    """The admin username for a valid session cookie, else None."""
    if not token or not admin_configured():
        return None
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM], audience=AUDIENCE)
    except jwt.InvalidTokenError as exc:
        _log.debug("admin session rejected: %s", exc)  # an expired cookie is normal, not an error
        return None
    if not secrets.compare_digest(str(claims.get("cred", "")), _cred_fingerprint()):
        _log.debug("admin session rejected: admin credentials changed since sign-in")
        return None
    if claims.get("sub") != settings.admin_username:
        return None
    return claims["sub"]


def api_token_ok(authorization: str | None) -> bool:
    """True for ``Authorization: Bearer <ADMIN_API_TOKEN>`` when a token is set."""
    if not settings.admin_api_token or not authorization:
        return False
    scheme, _, value = authorization.partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(value.strip(), settings.admin_api_token)
