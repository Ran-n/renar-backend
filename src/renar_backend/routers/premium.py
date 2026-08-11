#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:25:42.427427
Revised: 2026/08/05 21:48:03.825541

Premium account features: the color palette, the profile style (avatar ring
+ username colors) and the verified-badge request flow.

Everything that *writes* premium state is gated by require_premium — the
frontend's locked controls are cosmetic, this is the enforcement.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..events import publish as publish_event
from ..models import User
from ..schemas import PremiumStyleUpdate, UserOut
from ..users.auth import get_current_user, require_premium
from ..users.premium import PALETTE, feature_enabled

router = APIRouter(prefix="/premium", tags=["premium"])
_log = logging.getLogger(__name__)


@router.get("/palette")
def palette(user: User = Depends(get_current_user)):
    """Server-defined color options — the single source the pickers render."""
    return {"colors": list(PALETTE)}


@router.patch("/style", response_model=UserOut)
def update_style(
    data: PremiumStyleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_premium),
):
    if not feature_enabled("style"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Profile style is currently disabled")
    changes = data.model_dump(exclude_unset=True)  # explicit null clears a color
    status_color_changes = changes.pop("status_colors", None)
    countdown_color_changes = changes.pop("countdown_colors", None)
    for field, value in changes.items():
        setattr(user, field, value)
    if status_color_changes is not None:
        # per-key patch: null clears that one status, others keep their value
        merged = dict(user.status_colors or {})
        for watch_status, color in status_color_changes.items():
            if color is None:
                merged.pop(watch_status, None)
            else:
                merged[watch_status] = color
        user.status_colors = merged or None
        changes["status_colors"] = status_color_changes
    if countdown_color_changes is not None:
        # per-key patch: null clears that one tier, others keep their value
        merged = dict(user.countdown_colors or {})
        for tier, color in countdown_color_changes.items():
            if color is None:
                merged.pop(tier, None)
            else:
                merged[tier] = color
        user.countdown_colors = merged or None
        changes["countdown_colors"] = countdown_color_changes
    db.commit()
    db.refresh(user)
    _log.info("user id=%s updated premium style %s", user.id, changes)
    if changes:
        publish_event(user.id, "settings_changed")
    return user


@router.post("/verification-request", response_model=UserOut)
def request_verification(
    db: Session = Depends(get_db),
    user: User = Depends(require_premium),
):
    if not feature_enabled("verification"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verification requests are currently disabled"
        )
    if user.verified:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already verified")
    user.verification_requested = True
    db.commit()
    db.refresh(user)
    _log.info("user id=%s username=%s requested verification", user.id, user.username)
    return user


@router.delete("/verification-request", response_model=UserOut)
def withdraw_verification_request(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # withdrawing must work even after premium lapses — no gate
    user.verification_requested = False
    db.commit()
    db.refresh(user)
    _log.info("user id=%s username=%s withdrew verification request", user.id, user.username)
    return user
