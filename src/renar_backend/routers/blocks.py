#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:19:54.799133
Revised: 2026/11/15 02:45:10.297945

Blocking other users: block, unblock, and the caller's own block list.
What a block hides is decided in social/blocks.py and applied by the
routers that serve the content (social, comments, reviews).

main.py includes this router BEFORE routers/social.py: `GET /users/blocked`
has to be matched ahead of `GET /users/{user_id}`, or "blocked" is read as
a user id and answered with a 422.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserBlock
from ..schemas import PublicUserOut
from ..social.blocks import block_user, unblock_user
from ..users.auth import get_current_user
from .social import public_users_batch

router = APIRouter(tags=["social"])
_log = logging.getLogger(__name__)


@router.get("/users/blocked", response_model=list[PublicUserOut])
def list_blocked_users(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """The users the caller blocked, newest block first."""
    users = (
        db.query(User)
        .join(UserBlock, UserBlock.blocked_id == User.id)
        .filter(UserBlock.blocker_id == me.id)
        .order_by(UserBlock.created_at.desc(), UserBlock.id.desc())
        .all()
    )
    return public_users_batch(users, me, db)


@router.post("/users/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
def block(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if user_id == me.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't block yourself")
    # Plain existence check, not the block-aware one: someone who was blocked
    # must still be able to block back.
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    block_user(db, me.id, user_id)


@router.delete("/users/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
def unblock(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    unblock_user(db, me.id, user_id)
