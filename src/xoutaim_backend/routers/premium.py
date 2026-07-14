#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:25:42.427427
Revised: 2026/07/10 18:25:42.427427

Premium account features: the color palette, the profile style (avatar ring
+ username colors) and the verified-badge request flow.

Everything that *writes* premium state is gated by require_premium — the
frontend's locked controls are cosmetic, this is the enforcement.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_premium
from ..database import get_db
from ..models import User
from ..premium import PALETTE
from ..schemas import PremiumStyleUpdate, UserOut

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
    changes = data.model_dump(exclude_unset=True)  # explicit null clears a color
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    _log.info("user id=%s updated premium style %s", user.id, changes)
    return user


@router.post("/verification-request", response_model=UserOut)
def request_verification(
    db: Session = Depends(get_db),
    user: User = Depends(require_premium),
):
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
