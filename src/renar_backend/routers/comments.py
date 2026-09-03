#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.875365
Revised: 2026/09/02 16:41:42.055667

Comments on titles (global across users), with likes, nested replies and
user reports.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog.titles import find_or_create_title, find_title
from ..database import get_db
from ..events import publish as publish_event
from ..models import Comment, CommentLike, CommentReport, EpisodeWatch, LibraryEntry, MediaType, User
from ..schemas import CommentCreate, CommentOut, CommentReportCreate
from ..social.comment_threads import ancestor_depth, load_thread, resolve_root_scope
from ..users.auth import get_current_user
from ..users.premium import flair
from .reviews import reviewer_ids

router = APIRouter(prefix="/comments", tags=["comments"])
_log = logging.getLogger(__name__)


MAX_REPLY_DEPTH = 8  # a reply can target any ancestor reply, so nesting is
# otherwise unbounded — cap it so a deep (or adversarially built) thread can't
# blow up _comment_out into unbounded recursion / query fan-out


def _build_watch_info(
    db: Session, user_ids: set[int], title_id: int, season: int | None, episode: int | None
) -> dict[int, tuple[bool, int | None]]:
    """`{user_id: (seen, rating)}` for every commenter in a thread, off each
    commenter's own library entry for this title — every comment in a
    `list_comments`/`create_comment` call shares the same (season, episode)
    scope (replies inherit their root's, and root comments are only ever
    fetched filtered to one season/episode pair), so this is computed once
    per request rather than per comment. `rating` is the commenter's own
    1-100 grade (EpisodeWatch.rating for an episode-scoped thread,
    LibraryEntry.rating for a title-level one) — never another user's rating
    merged in, and never TMDB's. A commenter with no library entry for this
    title at all is simply absent, so callers default to (False, None)."""
    entries = db.query(LibraryEntry).filter(LibraryEntry.user_id.in_(user_ids), LibraryEntry.title_id == title_id).all()
    if not entries:
        return {}
    if episode is not None:
        entry_by_id = {e.id: e for e in entries}
        watches = (
            db.query(EpisodeWatch)
            .filter(
                EpisodeWatch.media_item_id.in_(entry_by_id.keys()),
                EpisodeWatch.season == season,
                EpisodeWatch.episode == episode,
            )
            .all()
        )
        watch_by_entry_id = {w.media_item_id: w for w in watches}
        return {
            e.user_id: (
                e.id in watch_by_entry_id,
                watch_by_entry_id[e.id].rating if e.id in watch_by_entry_id else None,
            )
            for e in entries
        }
    return {e.user_id: (e.last_watched_at is not None, e.rating) for e in entries}


def _comment_out(
    c: Comment,
    me: User,
    children_by_parent: dict[int | None, list[Comment]],
    watch_info: dict[int, tuple[bool, int | None]] | None = None,
    reviewer_id_set: set[int] | None = None,
    depth: int = 0,
) -> dict:
    replies = children_by_parent.get(c.id, [])
    seen, author_rating = (watch_info or {}).get(c.user_id, (False, None))
    return {
        "id": c.id,
        "user_id": c.user_id,
        "parent_id": c.parent_id,
        "username": c.author.username,
        "avatar": c.author.avatar,
        **flair(c.author, is_reviewer=c.user_id in (reviewer_id_set or ())),
        "text": c.text,
        "created_at": c.created_at,
        "likes": sum(1 for like in c.likes if like.value > 0),
        "dislikes": sum(1 for like in c.likes if like.value < 0),
        "liked_by_me": any(like.user_id == me.id and like.value > 0 for like in c.likes),
        "disliked_by_me": any(like.user_id == me.id and like.value < 0 for like in c.likes),
        "mine": c.user_id == me.id,
        "reported_by_me": any(r.user_id == me.id for r in c.reports),
        "seen_by_author": seen,
        "author_rating": author_rating,
        "replies": [_comment_out(r, me, children_by_parent, watch_info, reviewer_id_set, depth + 1) for r in replies]
        if depth < MAX_REPLY_DEPTH
        else [],
    }


def _require_target(tmdb_id: int | None, title: str | None) -> None:
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )


@router.get("", response_model=list[CommentOut])
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
    root_ids = [
        cid
        for (cid,) in db.query(Comment.id)
        .filter(
            Comment.title_id == target.id,
            Comment.season == season,
            Comment.episode == episode,
            Comment.parent_id.is_(None),  # replies come nested under their parent
        )
        .order_by(Comment.created_at.desc())
        .limit(100)
        .all()
    ]
    if not root_ids:
        return []
    by_id, children_by_parent = load_thread(db, root_ids)
    all_comments = list(by_id.values())
    watch_info = _build_watch_info(db, {c.user_id for c in all_comments}, target.id, season, episode)
    rev_ids = reviewer_ids(db, {c.user_id for c in all_comments})
    return [_comment_out(by_id[cid], me, children_by_parent, watch_info, rev_ids) for cid in root_ids]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CommentOut)
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
    publish_event(me.id, "comment_changed")
    # `data.season`/`data.episode` are the thread's real scope even for a
    # reply (the Comment row itself stores None there — see above — but the
    # request payload is validated against the parent's own root scope just
    # above, so it's already the right pair to look up watch/rating info by).
    watch_info = _build_watch_info(db, {comment.user_id}, target.id, data.season, data.episode)
    rev_ids = reviewer_ids(db, {comment.user_id})
    return _comment_out(comment, me, {}, watch_info, rev_ids)


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
    publish_event(me.id, "comment_changed")


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
            publish_event(me.id, "comment_changed")
    else:
        db.add(CommentLike(comment_id=comment_id, user_id=me.id, value=value))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # concurrent reaction from the same user — treat as no-op
            return
        publish_event(me.id, "comment_changed")


def _clear_reaction(db: Session, comment_id: int, me: User, value: int) -> None:
    """Remove the caller's reaction, but only if it currently matches `value`
    — e.g. DELETE .../like must not retract an existing dislike."""
    reaction = db.query(CommentLike).filter(CommentLike.comment_id == comment_id, CommentLike.user_id == me.id).first()
    if reaction and reaction.value == value:
        db.delete(reaction)
        db.commit()
        publish_event(me.id, "comment_changed")


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
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # concurrent report from same user — no-op
            return
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
