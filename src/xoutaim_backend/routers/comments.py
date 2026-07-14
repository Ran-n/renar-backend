#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.875365
Revised: 2026/07/11 15:37:11.638816

Comments on titles (global across users), with likes, nested replies and
user reports.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..comment_threads import ancestor_depth, resolve_root_scope
from ..database import get_db
from ..models import Comment, CommentLike, CommentReport, MediaType, User
from ..premium import flair
from ..schemas import CommentCreate, CommentReportCreate
from ..titles import find_or_create_title, find_title

router = APIRouter(prefix="/comments", tags=["comments"])
_log = logging.getLogger(__name__)


MAX_REPLY_DEPTH = 8  # a reply can target any ancestor reply, so nesting is
# otherwise unbounded — cap it so a deep (or adversarially built) thread can't
# blow up _comment_out into unbounded recursion / query fan-out


def _comment_out(c: Comment, me: User, depth: int = 0) -> dict:
    return {
        "id": c.id,
        "user_id": c.user_id,
        "parent_id": c.parent_id,
        "username": c.author.username,
        "avatar": c.author.avatar,
        **flair(c.author),
        "text": c.text,
        "created_at": c.created_at,
        "likes": sum(1 for like in c.likes if like.value > 0),
        "dislikes": sum(1 for like in c.likes if like.value < 0),
        "liked_by_me": any(like.user_id == me.id and like.value > 0 for like in c.likes),
        "disliked_by_me": any(like.user_id == me.id and like.value < 0 for like in c.likes),
        "mine": c.user_id == me.id,
        "reported_by_me": any(r.user_id == me.id for r in c.reports),
        "replies": [_comment_out(r, me, depth + 1) for r in c.replies] if depth < MAX_REPLY_DEPTH else [],
    }


def _require_target(tmdb_id: int | None, title: str | None) -> None:
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )


@router.get("")
def list_comments(
    media_type: MediaType,
    tmdb_id: int | None = Query(default=None, ge=1),
    title: str | None = Query(default=None, max_length=300),
    season: int | None = Query(default=None, ge=0),
    episode: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_target(tmdb_id, title)
    target = find_title(db, media_type, tmdb_id, title)
    if target is None:  # nobody has tracked or commented on this title yet
        return []
    comments = (
        db.query(Comment)
        .filter(
            Comment.title_id == target.id,
            Comment.season == season,
            Comment.episode == episode,
            Comment.parent_id.is_(None),  # replies come nested under their parent
        )
        .order_by(Comment.created_at.desc())
        .limit(100)
        .all()
    )
    return [_comment_out(c, me) for c in comments]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_comment(
    data: CommentCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _require_target(data.tmdb_id, data.title)
    if data.tmdb_id is not None and not data.title:
        # a Title row may not exist yet, and one cannot be created nameless
        target = find_title(db, data.media_type, data.tmdb_id, None)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Provide title for a tmdb_id not seen before",
            )
    else:
        target = find_or_create_title(db, data.media_type, data.tmdb_id, data.title)
    if data.parent_id is not None:
        parent = db.get(Comment, data.parent_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found")
        root_title_id, root_season, root_episode = resolve_root_scope(db, parent)
        if root_title_id != target.id or root_season != data.season or root_episode != data.episode:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Parent comment is not in this thread",
            )
        if ancestor_depth(db, parent) + 1 >= MAX_REPLY_DEPTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Reply nesting limit reached",
            )
    comment = Comment(
        user_id=me.id,
        # Only root comments (parent_id is None) store scope directly; a
        # reply's scope is derived from its thread root (comment_threads.py)
        # instead of being copied onto every row.
        title_id=target.id if data.parent_id is None else None,
        parent_id=data.parent_id,
        season=data.season if data.parent_id is None else None,
        episode=data.episode if data.parent_id is None else None,
        text=data.text.strip(),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return _comment_out(comment, me)


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    comment = db.get(Comment, comment_id)
    if comment is None or comment.user_id != me.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    db.delete(comment)
    db.commit()


def _set_reaction(db: Session, comment_id: int, me: User, value: int) -> None:
    """Upsert the caller's reaction to `value` (+1 like, -1 dislike). A user
    has at most one reaction per comment, so reacting the other way flips the
    existing row instead of adding a second one.
    """
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    existing = db.query(CommentLike).filter(CommentLike.comment_id == comment_id, CommentLike.user_id == me.id).first()
    if existing:
        if existing.value != value:
            existing.value = value
            db.commit()
    else:
        db.add(CommentLike(comment_id=comment_id, user_id=me.id, value=value))
        db.commit()


def _clear_reaction(db: Session, comment_id: int, me: User, value: int) -> None:
    """Remove the caller's reaction, but only if it currently matches `value`
    — e.g. DELETE .../like must not retract an existing dislike."""
    reaction = db.query(CommentLike).filter(CommentLike.comment_id == comment_id, CommentLike.user_id == me.id).first()
    if reaction and reaction.value == value:
        db.delete(reaction)
        db.commit()


@router.post("/{comment_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _set_reaction(db, comment_id, me, 1)


@router.delete("/{comment_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _clear_reaction(db, comment_id, me, 1)


@router.post("/{comment_id}/dislike", status_code=status.HTTP_204_NO_CONTENT)
def dislike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _set_reaction(db, comment_id, me, -1)


@router.delete("/{comment_id}/dislike", status_code=status.HTTP_204_NO_CONTENT)
def undislike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _clear_reaction(db, comment_id, me, -1)


@router.post("/{comment_id}/report", status_code=status.HTTP_204_NO_CONTENT)
def report_comment(
    comment_id: int,
    data: CommentReportCreate | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if comment.user_id == me.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot report your own comment",
        )
    already = (
        db.query(CommentReport).filter(CommentReport.comment_id == comment_id, CommentReport.user_id == me.id).first()
    )
    if not already:  # repeat reports by the same user are no-ops
        db.add(CommentReport(comment_id=comment_id, user_id=me.id, reason=(data.reason.strip() if data else "")))
        db.commit()
        _log.info("comment %s reported by user %s", comment_id, me.id)


@router.delete("/{comment_id}/report", status_code=status.HTTP_204_NO_CONTENT)
def unreport_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    report = (
        db.query(CommentReport).filter(CommentReport.comment_id == comment_id, CommentReport.user_id == me.id).first()
    )
    if report:
        db.delete(report)
        db.commit()
        _log.info("comment %s report retracted by user %s", comment_id, me.id)
