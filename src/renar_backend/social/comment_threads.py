#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 20:00:00.000000
Revised: 2026/07/17 19:40:36.456228

Thread-root resolution for comments. Only a root comment (parent_id is
NULL) stores title_id/season/episode; a reply's scope is the thread it
belongs to, not an independent fact about the reply itself, so it is
derived by walking parent_id up to the root instead of being copied onto
every row (see docs/design-decisions.md, "Comment replies").
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, selectinload

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


def load_thread(db: Session, root_ids: list[int]) -> tuple[dict[int, Comment], dict[int | None, list[Comment]]]:
    """Every comment in the threads rooted at `root_ids` — the roots plus
    every nested reply, arbitrarily deep — fetched in one recursive query
    with author/likes/reports eager-loaded.

    routers.comments._comment_out used to walk Comment.replies/.author/
    .likes/.reports directly, which are all lazy relationships: rendering a
    page of 100 root comments with replies fired on the order of 100s-1000s
    of queries. Returns (comments_by_id, children_by_parent_id) so the
    caller can rebuild the reply tree in Python without touching those
    relationships at all.
    """
    if not root_ids:
        return {}, {}
    base = select(Comment.id).where(Comment.id.in_(root_ids)).cte(name="thread_ids", recursive=True)
    child = aliased(Comment)
    ids_cte = base.union_all(select(child.id).where(child.parent_id == base.c.id))
    all_ids = db.execute(select(ids_cte.c.id)).scalars().all()
    comments = (
        db.query(Comment)
        .options(selectinload(Comment.author), selectinload(Comment.likes), selectinload(Comment.reports))
        .filter(Comment.id.in_(all_ids))
        .order_by(Comment.created_at)
        .all()
    )
    by_id = {c.id: c for c in comments}
    children_by_parent: dict[int | None, list[Comment]] = defaultdict(list)
    for c in comments:
        children_by_parent[c.parent_id].append(c)
    return by_id, children_by_parent
