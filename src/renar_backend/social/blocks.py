#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:19:53.243082
Revised: 2026/11/15 02:45:11.916872

User blocks. A block is stored one-way (who blocked whom, because only the
blocker may undo it) but its effect is symmetric: neither side sees the
other's comments, reviews, profile or library, and neither can follow the
other. Every router that hides content asks `blocked_pair_ids`, so the
symmetric rule lives in one place.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Follow, UserBlock

_log = logging.getLogger(__name__)


def blocked_pair_ids(db: Session, me_id: int) -> set[int]:
    """Every user id on the other side of a block with `me_id`, whichever of
    the two made it. One query."""
    rows = db.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            (UserBlock.blocker_id == me_id) | (UserBlock.blocked_id == me_id)
        )
    ).all()
    return {blocked if blocker == me_id else blocker for blocker, blocked in rows}


def block_user(db: Session, blocker_id: int, blocked_id: int) -> bool:
    """`blocker_id` blocks `blocked_id`, and any follow between the two (both
    directions) is deleted in the same transaction. Commits. Returns whether
    a new block was made (False when it already existed)."""
    already = db.query(UserBlock).filter(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id).first()
    if already is not None:
        return False
    db.add(UserBlock(blocker_id=blocker_id, blocked_id=blocked_id))
    db.query(Follow).filter(
        ((Follow.follower_id == blocker_id) & (Follow.followed_id == blocked_id))
        | ((Follow.follower_id == blocked_id) & (Follow.followed_id == blocker_id))
    ).delete(synchronize_session=False)
    try:
        db.commit()
    except IntegrityError:
        # the same user's concurrent request made the block first, and its
        # transaction removed the follows: nothing left to do
        db.rollback()
        _log.info("concurrent block of user %s by user %s: kept the first", blocked_id, blocker_id)
        return False
    _log.info("user %s blocked user %s", blocker_id, blocked_id)
    return True


def unblock_user(db: Session, blocker_id: int, blocked_id: int) -> bool:
    """Undo `blocker_id`'s block of `blocked_id`. Follows the block deleted
    are not restored. Commits. Returns whether a block was removed."""
    block = db.query(UserBlock).filter(UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id).first()
    if block is None:
        return False
    db.delete(block)
    db.commit()
    _log.info("user %s unblocked user %s", blocker_id, blocked_id)
    return True
