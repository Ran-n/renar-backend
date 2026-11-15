#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.875365
Revised: 2026/11/15 02:45:09.088076

Comments on titles (global across users), with likes, nested replies and
user reports.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..catalog.titles import find_or_create_title, find_title
from ..database import get_db
from ..events import publish as publish_event
from ..models import Comment, CommentLike, CommentReport, EpisodeWatch, LibraryEntry, MediaType, User
from ..schemas import CommentCreate, CommentOut, ReportCreate
from ..social.blocks import blocked_pair_ids
from ..social.comment_threads import ancestor_depth, load_thread, resolve_root_scope
from ..social.reactions import DISLIKE, LIKE, clear_reaction, reaction_counts, set_reaction
from ..social.reports import add_report, remove_report
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
        **reaction_counts(c.likes, me.id),
        "mine": c.user_id == me.id,
        "reported_by_me": any(r.user_id == me.id for r in c.reports),
        "seen_by_author": seen,
        "author_rating": author_rating,
        "replies": [_comment_out(r, me, children_by_parent, watch_info, reviewer_id_set, depth + 1) for r in replies]
        if depth < MAX_REPLY_DEPTH
        else [],
    }


def _without_authors(
    children_by_parent: dict[int | None, list[Comment]], author_ids: set[int]
) -> dict[int | None, list[Comment]]:
    """The reply lists minus every reply written by one of `author_ids`.
    The tree is rendered by walking these lists down from the roots, so a
    dropped reply takes its whole subtree with it: a reply makes no sense
    without the comment it answers."""
    return {
        parent_id: [c for c in children if c.user_id not in author_ids]
        for parent_id, children in children_by_parent.items()
    }


_ROOT_ORDER = {
    "desc": (Comment.created_at.desc(), Comment.id.desc()),
    "asc": (Comment.created_at.asc(), Comment.id.asc()),
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
    sort: Literal["asc", "desc"] = Query(default="desc"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Top-level comments of one thread, replies nested under their parent.

    `sort` orders the top-level comments by posting time: "desc" (default)
    is newest first, "asc" is oldest first (chronological). Replies always
    read oldest first under their parent, whatever `sort` says: a
    conversation only makes sense in the order it was written.
    """
    _require_target(tmdb_id, title)
    target = find_title(db, media_type, tmdb_id, title)
    if target is None:  # nobody has tracked or commented on this title yet
        return []
    blocked = blocked_pair_ids(db, me.id)
    roots = db.query(Comment.id).filter(
        Comment.title_id == target.id,
        Comment.season == season,
        Comment.episode == episode,
        Comment.parent_id.is_(None),  # replies come nested under their parent
    )
    if blocked:  # filtered in SQL so the page limit counts visible comments only
        roots = roots.filter(Comment.user_id.notin_(blocked))
    root_ids = [
        cid
        for (cid,) in roots
        # id breaks ties between comments stamped in the same instant, so the
        # two directions are exact mirrors of each other
        .order_by(*_ROOT_ORDER[sort])
        .limit(100)
        .all()
    ]
    if not root_ids:
        return []
    by_id, children_by_parent = load_thread(db, root_ids)
    if blocked:
        children_by_parent = _without_authors(children_by_parent, blocked)
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
        # A blocked pair can't reply to each other; same answer as a comment
        # that doesn't exist, so a block can't be detected by probing.
        if parent is None or parent.user_id in blocked_pair_ids(db, me.id):
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
    """Set the caller's reaction (see social/reactions.py) on a comment that
    must exist, and tell the caller's other sessions when it changed."""
    if db.get(Comment, comment_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if set_reaction(db, CommentLike, CommentLike.comment_id, comment_id, me.id, value):
        publish_event(me.id, "comment_changed")


def _clear_reaction(db: Session, comment_id: int, me: User, value: int) -> None:
    if clear_reaction(db, CommentLike, CommentLike.comment_id, comment_id, me.id, value):
        publish_event(me.id, "comment_changed")


@router.post("/{comment_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def like_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _set_reaction(db, comment_id, me, LIKE)


@router.delete("/{comment_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _clear_reaction(db, comment_id, me, LIKE)


@router.post("/{comment_id}/dislike", status_code=status.HTTP_204_NO_CONTENT)
def dislike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _set_reaction(db, comment_id, me, DISLIKE)


@router.delete("/{comment_id}/dislike", status_code=status.HTTP_204_NO_CONTENT)
def undislike_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _clear_reaction(db, comment_id, me, DISLIKE)


@router.post("/{comment_id}/report", status_code=status.HTTP_204_NO_CONTENT)
def report_comment(
    comment_id: int,
    data: ReportCreate | None = None,
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
    add_report(
        db,
        CommentReport,
        CommentReport.comment_id,
        comment_id,
        CommentReport.user_id,
        me.id,
        data.reason if data else "",
    )


@router.delete("/{comment_id}/report", status_code=status.HTTP_204_NO_CONTENT)
def unreport_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    remove_report(db, CommentReport, CommentReport.comment_id, comment_id, CommentReport.user_id, me.id)
