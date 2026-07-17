#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 20:00:00.000000
Revised: 2026/07/17 00:00:00.000000

Thread-root resolution for comments. Only a root comment (parent_id is
NULL) stores title_id/season/episode; a reply's scope is the thread it
belongs to, not an independent fact about the reply itself, so it is
derived by walking parent_id up to the root instead of being copied onto
every row (see docs/design-decisions.md, "Comment replies").
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from ..models import Comment


def ancestor_depth(db: Session, comment: Comment) -> int:
    """Number of ancestors above `comment` (0 for a root comment). Used to cap
    reply nesting at creation time, matching the read-side cap in
    routers.comments._comment_out."""
    if comment.parent_id is None:
        return 0
    base = (
        select(Comment.id, Comment.parent_id)
        .where(Comment.id == comment.parent_id)
        .cte(name="comment_depth", recursive=True)
    )
    parent = aliased(Comment)
    ancestry = base.union_all(select(parent.id, parent.parent_id).where(parent.id == base.c.parent_id))
    return db.execute(select(func.count()).select_from(ancestry)).scalar_one()


def resolve_root_scope(db: Session, comment: Comment) -> tuple[int, int | None, int | None]:
    """(title_id, season, episode) of the thread `comment` belongs to."""
    if comment.title_id is not None:
        return comment.title_id, comment.season, comment.episode

    base = (
        select(Comment.id, Comment.parent_id, Comment.title_id, Comment.season, Comment.episode)
        .where(Comment.id == comment.parent_id)
        .cte(name="comment_ancestry", recursive=True)
    )
    parent = aliased(Comment)
    ancestry = base.union_all(
        select(parent.id, parent.parent_id, parent.title_id, parent.season, parent.episode).where(
            parent.id == base.c.parent_id
        )
    )
    row = db.execute(
        select(ancestry.c.title_id, ancestry.c.season, ancestry.c.episode).where(ancestry.c.title_id.isnot(None))
    ).first()
    if row is None:
        raise RuntimeError(f"comment {comment.id} has no root with a title_id — broken thread")
    return row.title_id, row.season, row.episode
