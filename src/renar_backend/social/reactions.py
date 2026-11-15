#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:43.813271
Revised: 2026/11/14 00:22:43.813271

Like/dislike reactions, shared by every reactable thing (comments, reviews).

A reaction table has one row per (target, user) with `value` +1 (like) or
-1 (dislike): reacting the other way flips that row instead of adding a
second one, so a user can never both like and dislike the same target.
"""

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

LIKE = 1
DISLIKE = -1


def set_reaction(db: Session, model: type, target_column: Any, target_id: int, user_id: int, value: int) -> bool:
    """Upsert `user_id`'s reaction on `target_id` to `value`. Commits.

    `model` is the reaction table's class and `target_column` its FK column
    to the thing reacted to (e.g. `CommentLike`, `CommentLike.comment_id`).
    Returns whether anything changed, so the caller knows whether to
    announce it. The caller checks the target exists first.
    """
    existing = db.query(model).filter(target_column == target_id, model.user_id == user_id).first()
    if existing is not None:
        if existing.value == value:
            return False
        existing.value = value
        db.commit()
        return True
    db.add(model(**{target_column.key: target_id, "user_id": user_id, "value": value}))
    try:
        db.commit()
    except IntegrityError:
        # the same user's concurrent request inserted the row first: the
        # reaction exists, which is what this call wanted
        db.rollback()
        _log.info("concurrent %s reaction by user %s on %s: kept the first", model.__tablename__, user_id, target_id)
        return False
    return True


def clear_reaction(db: Session, model: type, target_column: Any, target_id: int, user_id: int, value: int) -> bool:
    """Remove `user_id`'s reaction on `target_id`, but only if it currently
    is `value`: un-liking must not retract an existing dislike. Commits.
    Returns whether a row was removed."""
    reaction = db.query(model).filter(target_column == target_id, model.user_id == user_id).first()
    if reaction is None or reaction.value != value:
        return False
    db.delete(reaction)
    db.commit()
    return True


def reaction_counts(reactions: list, user_id: int) -> dict:
    """The four reaction fields every reactable API object carries."""
    return {
        "likes": sum(1 for r in reactions if r.value > 0),
        "dislikes": sum(1 for r in reactions if r.value < 0),
        "liked_by_me": any(r.user_id == user_id and r.value > 0 for r in reactions),
        "disliked_by_me": any(r.user_id == user_id and r.value < 0 for r in reactions),
    }
