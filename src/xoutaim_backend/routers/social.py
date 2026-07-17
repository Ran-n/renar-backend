#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.566899
Revised: 2026/07/17 10:25:32.702003

Social graph: user search, profiles, follow/unfollow, activity feed.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..catalog.titles import WITH_TITLE_GENRES
from ..constants import DEFAULT_EPISODE_RUNTIME, DEFAULT_FILM_RUNTIME
from ..database import get_db
from ..models import Follow, LibraryEntry, MediaType, Title, User, WatchStatus
from ..schemas import LibraryEntryOut
from ..users.auth import get_current_user
from ..users.premium import flair

router = APIRouter(tags=["social"])
_log = logging.getLogger(__name__)


def _user_or_404(user_id: int, db: Session) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return target


def _is_following(follower_id: int, followed_id: int, db: Session) -> bool:
    return (
        db.query(Follow).filter(Follow.follower_id == follower_id, Follow.followed_id == followed_id).first()
        is not None
    )


def _watch_minutes_expr():
    """Same film/tv-episode minutes formula as stats.get_stats, as a SQL
    expression rather than a per-row Python loop. media_type/runtime_minutes/
    total_episodes live on the shared Title row, not LibraryEntry, hence the
    Title columns instead of LibraryEntry ones."""
    runtime = func.coalesce(Title.runtime_minutes, DEFAULT_FILM_RUNTIME)
    episode_runtime = func.coalesce(Title.runtime_minutes, DEFAULT_EPISODE_RUNTIME)
    episodes = case(
        (
            (LibraryEntry.status == WatchStatus.completed)
            & (LibraryEntry.episodes_watched == 0)
            & Title.total_episodes.isnot(None),
            Title.total_episodes,
        ),
        else_=LibraryEntry.episodes_watched,
    )
    return case(
        (
            (Title.media_type == MediaType.film) & (LibraryEntry.status == WatchStatus.completed),
            runtime,
        ),
        (Title.media_type == MediaType.tv_show, episodes * episode_runtime),
        else_=0,
    )


def _total_watch_minutes(user_id: int, db: Session) -> int:
    total = (
        db.query(func.coalesce(func.sum(_watch_minutes_expr()), 0))
        .select_from(LibraryEntry)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(LibraryEntry.user_id == user_id)
        .scalar()
    )
    return int(total)


def _public_users_batch(targets: list[User], me: User, db: Session) -> list[dict]:
    """All the per-profile counters for a whole list of users in a fixed
    5 queries, not 5*N: each of followers/following/items/watch-minutes/
    is-following used to be its own scalar subquery *per target user*, so a
    followers/following list with N entries fired 5*N queries."""
    if not targets:
        return []
    target_ids = [t.id for t in targets]

    followers_by_id = dict(
        db.execute(
            select(Follow.followed_id, func.count())
            .where(Follow.followed_id.in_(target_ids))
            .group_by(Follow.followed_id)
        ).all()
    )
    following_by_id = dict(
        db.execute(
            select(Follow.follower_id, func.count())
            .where(Follow.follower_id.in_(target_ids))
            .group_by(Follow.follower_id)
        ).all()
    )
    items_by_id = dict(
        db.execute(
            select(LibraryEntry.user_id, func.count())
            .where(LibraryEntry.user_id.in_(target_ids))
            .group_by(LibraryEntry.user_id)
        ).all()
    )
    watch_minutes_by_id = dict(
        db.execute(
            select(LibraryEntry.user_id, func.coalesce(func.sum(_watch_minutes_expr()), 0))
            .select_from(LibraryEntry)
            .join(Title, LibraryEntry.title_id == Title.id)
            .where(LibraryEntry.user_id.in_(target_ids))
            .group_by(LibraryEntry.user_id)
        ).all()
    )
    following_ids = {
        row[0]
        for row in db.execute(
            select(Follow.followed_id).where(Follow.follower_id == me.id, Follow.followed_id.in_(target_ids))
        ).all()
    }

    return [
        {
            "id": target.id,
            "username": target.username,
            "avatar": target.avatar,
            **flair(target),
            "created_at": target.created_at,
            "followers": followers_by_id.get(target.id, 0),
            "following": following_by_id.get(target.id, 0),
            "items": items_by_id.get(target.id, 0),
            "total_watch_minutes": int(watch_minutes_by_id.get(target.id, 0)),
            "is_following": target.id in following_ids,
            "is_me": target.id == me.id,
        }
        for target in targets
    ]


def _public_user(target: User, me: User, db: Session) -> dict:
    return _public_users_batch([target], me, db)[0]


@router.get("/users/search")
def search_users(
    q: str = Query(min_length=1, max_length=50),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    users = db.query(User).filter(User.username.ilike(f"%{q}%"), User.id != me.id).limit(20).all()
    return _public_users_batch(users, me, db)


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return _public_user(_user_or_404(user_id, db), me, db)


@router.post("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if user_id == me.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot follow yourself")
    _user_or_404(user_id, db)
    if not _is_following(me.id, user_id, db):
        db.add(Follow(follower_id=me.id, followed_id=user_id))
        db.commit()


@router.delete("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    follow = db.query(Follow).filter(Follow.follower_id == me.id, Follow.followed_id == user_id).first()
    if follow:
        db.delete(follow)
        db.commit()


@router.get("/users/{user_id}/following")
def list_following(
    user_id: int,
    limit: int | None = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _user_or_404(user_id, db)
    query = db.query(Follow).filter(Follow.follower_id == user_id).order_by(Follow.created_at.desc(), Follow.id.desc())
    if limit is not None:
        query = query.offset(offset).limit(limit)
    follows = query.all()
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_([f.followed_id for f in follows]))}
    return _public_users_batch([users_by_id[f.followed_id] for f in follows], me, db)


@router.get("/users/{user_id}/followers")
def list_followers(
    user_id: int,
    limit: int | None = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _user_or_404(user_id, db)
    query = db.query(Follow).filter(Follow.followed_id == user_id).order_by(Follow.created_at.desc(), Follow.id.desc())
    if limit is not None:
        query = query.offset(offset).limit(limit)
    follows = query.all()
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_([f.follower_id for f in follows]))}
    return _public_users_batch([users_by_id[f.follower_id] for f in follows], me, db)


@router.get("/users/{user_id}/media", response_model=list[LibraryEntryOut])
def user_media(
    user_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _user_or_404(user_id, db)
    return (
        db.query(LibraryEntry)
        .options(*WITH_TITLE_GENRES)
        .filter(LibraryEntry.user_id == user_id)
        .order_by(LibraryEntry.updated_at.desc())
        .limit(100)
        .all()
    )


@router.get("/feed")
def activity_feed(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    followed_ids = [f.followed_id for f in db.query(Follow).filter(Follow.follower_id == me.id)]
    if not followed_ids:
        return []
    entries = (
        db.query(LibraryEntry, User)
        .join(User, LibraryEntry.user_id == User.id)
        .filter(LibraryEntry.user_id.in_(followed_ids))
        .order_by(LibraryEntry.updated_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "user_id": item.user_id,
            "username": owner.username,
            **flair(owner),
            "item_id": item.id,
            "media_type": item.media_type.value,
            "title": item.title,
            "year": item.year,
            "poster_url": item.poster_url,
            "status": item.status.value,
            "rating": item.rating,
            "tmdb_id": item.tmdb_id,
            "episodes_watched": item.episodes_watched,
            "total_episodes": item.total_episodes,
            "updated_at": item.updated_at,
        }
        for item, owner in entries
    ]
