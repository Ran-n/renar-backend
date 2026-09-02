#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:36:40.138297
Revised: 2026/09/02 10:57:10.961341

Reviews: longer, considered write-ups on a title, distinct from the casual
Comments thread — restricted to a hand-picked whitelist of reviewers (see
models.py's Review/ReviewWhitelist docstrings). Reads are open to any
authenticated user; only whitelisted users may write.
"""

import logging
from collections.abc import Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..catalog.titles import find_or_create_title, find_title
from ..database import get_db
from ..models import MediaType, Review, ReviewWhitelist, User
from ..schemas import ReviewCreate, ReviewUpdate
from ..users.auth import get_current_user
from ..users.premium import flair

router = APIRouter(prefix="/media", tags=["reviews"])
_log = logging.getLogger(__name__)


def is_whitelisted_reviewer(user_id: int, db: Session) -> bool:
    return db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user_id).first() is not None


def reviewer_ids(db: Session, user_ids: Iterable[int]) -> set[int]:
    """Batched whitelist-membership check for a set of users — one query
    regardless of list size, for callers rendering many authors at once
    (comment threads, review lists, profile batches) so the reviewer badge
    doesn't cost a query per author (see comments.py/social.py callers)."""
    ids = set(user_ids)
    if not ids:
        return set()
    rows = db.query(ReviewWhitelist.user_id).filter(ReviewWhitelist.user_id.in_(ids)).all()
    return {r[0] for r in rows}


def _require_target(tmdb_id: int | None, title: str | None) -> None:
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )


def _review_out(review: Review, me: User, is_reviewer: bool) -> dict:
    return {
        "id": review.id,
        "title_id": review.title_id,
        "user_id": review.user_id,
        "username": review.author.username,
        "avatar": review.author.avatar,
        **flair(review.author, is_reviewer=is_reviewer),
        "text": review.text,
        "rating": review.rating,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
        "mine": review.user_id == me.id,
    }


def _resolve_target(db: Session, media_type: MediaType, tmdb_id: int | None, title: str | None):
    _require_target(tmdb_id, title)
    if tmdb_id is not None and not title:
        target = find_title(db, media_type, tmdb_id, None)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Provide title for a tmdb_id not seen before",
            )
        return target
    return find_or_create_title(db, media_type, tmdb_id, title)


@router.get("/reviews")
def list_reviews(
    media_type: MediaType,
    tmdb_id: int | None = None,
    title: str | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_target(tmdb_id, title)
    target = find_title(db, media_type, tmdb_id, title)
    if target is None:  # nobody has tracked or reviewed this title yet
        return []
    reviews = (
        db.query(Review)
        .options(selectinload(Review.author))
        .filter(Review.title_id == target.id)
        .order_by(Review.created_at.desc())
        .all()
    )
    rev_ids = reviewer_ids(db, {r.user_id for r in reviews})
    return [_review_out(r, me, r.user_id in rev_ids) for r in reviews]


@router.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(
    data: ReviewCreate,
    media_type: MediaType,
    tmdb_id: int | None = None,
    title: str | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if not is_whitelisted_reviewer(me.id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not on the reviewer whitelist")
    target = _resolve_target(db, media_type, tmdb_id, title)
    existing = db.query(Review).filter(Review.user_id == me.id, Review.title_id == target.id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already reviewed this title — edit your existing review instead",
        )
    review = Review(user_id=me.id, title_id=target.id, text=data.text.strip(), rating=data.rating)
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Two simultaneous submissions from the same reviewer raced past the
        # SELECT check above — surface the same 409 as the pre-commit path.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already reviewed this title — edit your existing review instead",
        ) from None
    db.refresh(review)
    # already checked above — no second query needed for this single-user case
    return _review_out(review, me, True)


@router.patch("/reviews/{review_id}")
def update_review(
    review_id: int,
    data: ReviewUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    review = db.get(Review, review_id)
    if review is None or review.user_id != me.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    review.text = data.text.strip()
    review.rating = data.rating
    db.commit()
    db.refresh(review)
    # re-checked (not assumed True): the whitelist could have been revoked
    # since this review was first written
    return _review_out(review, me, is_whitelisted_reviewer(me.id, db))


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    review = db.get(Review, review_id)
    if review is None or review.user_id != me.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(review)
    db.commit()
