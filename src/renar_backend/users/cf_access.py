#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 11:52:55.150739
Revised: 2026/11/15 11:56:21.200181

Cloudflare Access check for the admin path.

When ``CF_ACCESS_TEAM_DOMAIN`` and ``CF_ACCESS_AUD`` are both set, every
request under ``ADMIN_PATH`` must carry the signed JWT Cloudflare Access
adds to requests it lets through (``Cf-Access-Jwt-Assertion``). Accepting
only Cloudflare's IP ranges does not prove a request passed *this* zone's
Access policy: anyone can point their own proxied Cloudflare record at the
server and arrive from a Cloudflare IP. The signature, audience and issuer
do prove it.

A request without a valid token gets the 404 an unknown path gets, before
any admin code runs, and no abuse strike (a stale browser tab must not get
the operator banned). If the signing keys can't be fetched the answer is a
503: never fail open. Both settings empty (dev) means no check at all.

See docs/design-decisions.md, "Prod admin panel behind Cloudflare Access".
"""

import logging
from functools import lru_cache

import anyio
import jwt
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from .security import client_ip

_log = logging.getLogger(__name__)

HEADER = "Cf-Access-Jwt-Assertion"
_ALGORITHMS = ["RS256"]
_CLOCK_SKEW_SECONDS = 60
_KEYS_LIFESPAN_SECONDS = 3600
_KEYS_TIMEOUT_SECONDS = 10

# PyJWT's own exception for each refusal, most specific first, and the
# reason logged for it.
_REASONS: tuple[tuple[type[jwt.InvalidTokenError], str], ...] = (
    (jwt.ExpiredSignatureError, "expired"),
    (jwt.InvalidAudienceError, "wrong aud"),
    (jwt.InvalidIssuerError, "wrong iss"),
    (jwt.InvalidSignatureError, "bad signature"),
    (jwt.MissingRequiredClaimError, "missing claim"),
)


class AccessDenied(Exception):
    """The request did not come through this zone's Access policy."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AccessUnavailable(Exception):
    """The signing keys could not be fetched, so nothing can be verified."""


def enabled() -> bool:
    return bool(settings.cf_access_team_domain and settings.cf_access_aud)


def _issuer() -> str:
    return f"https://{settings.cf_access_team_domain}"


@lru_cache(maxsize=4)
def _keys_client(certs_url: str) -> jwt.PyJWKClient:
    """One cached JWKS client per certs URL (the URL only changes in tests)."""
    return jwt.PyJWKClient(certs_url, lifespan=_KEYS_LIFESPAN_SECONDS, timeout=_KEYS_TIMEOUT_SECONDS)


def _signing_key(token: str):
    try:
        return _keys_client(f"{_issuer()}/cdn-cgi/access/certs").get_signing_key_from_jwt(token).key
    except jwt.exceptions.PyJWKClientConnectionError as exc:
        raise AccessUnavailable(str(exc)) from exc
    except jwt.PyJWKClientError as exc:
        # The keys were fetched, but none is the one this token names.
        raise AccessDenied("bad signature") from exc
    except jwt.InvalidTokenError as exc:
        raise AccessDenied("malformed") from exc


def _reason(exc: jwt.InvalidTokenError) -> str:
    return next((reason for kind, reason in _REASONS if isinstance(exc, kind)), "invalid token")


def verify_access_jwt(token: str | None) -> None:
    """Return when ``token`` is a valid Access JWT for this application.

    Raises ``AccessDenied(reason)`` otherwise, or ``AccessUnavailable`` when
    the signing keys can't be fetched. Blocking (may fetch the keys).
    """
    if not token:
        raise AccessDenied("missing")
    key = _signing_key(token)
    try:
        jwt.decode(
            token,
            key,
            algorithms=_ALGORITHMS,
            audience=settings.cf_access_aud,
            issuer=_issuer(),
            leeway=_CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.InvalidTokenError as exc:
        raise AccessDenied(_reason(exc)) from exc


def is_admin_path(path: str) -> bool:
    admin_path = settings.admin_path.rstrip("/") or "/admin"
    return path == admin_path or path.startswith(f"{admin_path}/")


class CloudflareAccessMiddleware(BaseHTTPMiddleware):
    """One gate for the whole admin path, so no admin route can be missed."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if not enabled() or not is_admin_path(request.url.path):
            return await call_next(request)
        try:
            await anyio.to_thread.run_sync(verify_access_jwt, request.headers.get(HEADER))
        except AccessDenied as exc:
            _log.warning("admin path refused for %s: Cloudflare Access token %s", client_ip(request), exc.reason)
            # Indistinguishable from a path that doesn't exist.
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        except AccessUnavailable:
            _log.error(
                "admin path refused for %s: Cloudflare Access keys unavailable", client_ip(request), exc_info=True
            )
            return JSONResponse({"detail": "Admin access check unavailable"}, status_code=503)
        return await call_next(request)
