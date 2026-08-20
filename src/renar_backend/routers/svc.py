#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 17:00:30.032438
Revised: 2026/08/20 10:39:54.344580

Machine-to-machine endpoints so the renar-frontend web server's own
anti-abuse guard (renar-frontend/src/renar_frontend/anti_abuse.py) can
share this server's persisted ban state instead of keeping its own: an IP
permabanned or struck on either surface is blocked on both, and a frontend
restart reloads both permabans and active temp bans instead of granting
amnesty. Guarded by INTERNAL_SERVICE_SECRET, not the admin session — there is
no browser involved. Deliberately NOT under /internal/, which is honeypot
bait (see security.HONEYPOT_PREFIXES) that permabans real callers.

GET /bans is also the frontend's steady-state path: past startup, it
re-pulls this on a long interval (default 60 minutes — permabans never
expire, so lag doesn't cost anything) instead of asking about individual
IPs, keeping this frontend-initiated and the backend still unaware the
frontend exists.
"""

import hmac
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import site_settings
from ..config import settings
from ..database import get_db
from ..models import BannedIP
from ..users.security import client_ip, load_active_temp_bans, permaban, strike_and_maybe_ban

router = APIRouter(prefix="/svc", tags=["svc"])
_log = logging.getLogger(__name__)

# A wrong-secret caller here is either a stale internal deployment (annoying
# but harmless) or someone guessing the secret (not harmless) — the 404
# posture below hides which, and unlike a real unknown-path probe this route
# always resolves, so AbuseGuardMiddleware's own probe-scanner ban never
# sees it. Track failures ourselves so repeated guessing still escalates
# through the same strike/ban path a probing scanner would hit. Exempt IPs
# (127.0.0.1/::1 by default — see site_settings) skip this entirely: the
# frontend itself calls from localhost, and a misconfigured/stale local
# deployment retrying with a wrong secret must never end up banning the
# machine it's running on.
_MINUTE = 60.0
_FAIL_LIMIT_PER_MINUTE = 5
_auth_failures: dict[str, deque[float]] = defaultdict(deque)


def _require_internal_secret(request: Request, x_internal_secret: str | None = Header(default=None)) -> None:
    # 404 rather than 401/403: an unconfigured or wrong-secret caller should
    # see no evidence this route exists, matching the honeypot posture below.
    match = hmac.compare_digest(x_internal_secret or "", settings.internal_service_secret)
    if not settings.internal_service_secret or not match:
        _log.warning(
            "svc auth rejected: header_present=%s header_len=%s configured_len=%s match=%s",
            x_internal_secret is not None,
            len(x_internal_secret or ""),
            len(settings.internal_service_secret),
            match,
        )
        ip = client_ip(request)
        if ip in site_settings.current().exempt_ips:
            raise HTTPException(status_code=404)
        now = time.time()
        failures = _auth_failures[ip]
        while failures and failures[0] < now - _MINUTE:
            failures.popleft()
        failures.append(now)
        if len(failures) > _FAIL_LIMIT_PER_MINUTE:
            count, until = strike_and_maybe_ban(ip, f"repeated invalid /svc auth: >{_FAIL_LIMIT_PER_MINUTE}/min")
            if until is None:
                permaban(ip, f"{count} repeated invalid /svc auth offenses")
        raise HTTPException(status_code=404)


class BanRequest(BaseModel):
    ip: str
    reason: str


class StrikeRequest(BaseModel):
    ip: str
    reason: str


@router.get("/bans", dependencies=[Depends(_require_internal_secret)])
def list_banned_ips(db: Session = Depends(get_db)):
    return {
        "ips": [ip for (ip,) in db.query(BannedIP.ip).all()],
        "temp_bans": load_active_temp_bans(),
    }


@router.post("/bans", dependencies=[Depends(_require_internal_secret)])
def add_banned_ip(body: BanRequest):
    permaban(body.ip, body.reason)
    return {"status": "ok"}


@router.post("/strikes", dependencies=[Depends(_require_internal_secret)])
def add_strike(body: StrikeRequest):
    """For non-honeypot bans (floods) — goes through the same persisted,
    escalating strike/temp-ban logic used for this server's own offenders,
    rather than a flat one-off ban, so a repeat scanner hitting only the
    frontend still escalates toward a permaban over time."""
    count, until = strike_and_maybe_ban(body.ip, body.reason)
    if until is None:
        permaban(body.ip, f"{count} repeated offenses: {body.reason}")
        return {"permanent": True, "banned_until": None}
    return {"permanent": False, "banned_until": until}
