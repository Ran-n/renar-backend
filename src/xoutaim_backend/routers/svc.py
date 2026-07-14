#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 17:00:30.032438
Revised: 2026/07/12 17:22:33.145708

Machine-to-machine endpoints so the xoutaim-frontend web server's own
anti-abuse guard (xoutaim-frontend/src/xoutaim_frontend/anti_abuse.py) can
share this server's persisted ban state instead of keeping its own: an IP
permabanned or struck on either surface is blocked on both, and a frontend
restart reloads both permabans and active temp bans instead of granting
amnesty. Guarded by INTERNAL_SERVICE_SECRET, not the admin session — there is
no browser involved. Deliberately NOT under /internal/, which is honeypot
bait (see security.HONEYPOT_PREFIXES) that permabans real callers.
"""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import BannedIP
from ..security import load_active_temp_bans, permaban, strike_and_maybe_ban

router = APIRouter(prefix="/svc", tags=["svc"])
_log = logging.getLogger(__name__)


def _require_internal_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    # 404 rather than 401/403: an unconfigured or wrong-secret caller should
    # see no evidence this route exists, matching the honeypot posture below.
    if not settings.internal_service_secret or not hmac.compare_digest(
        x_internal_secret or "", settings.internal_service_secret
    ):
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
