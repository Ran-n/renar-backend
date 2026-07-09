#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.286403
Revised: 2026/07/07 13:25:15.286403
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import EpisodeWatch, LibraryEntry, MediaType, Title, User, WatchEvent, WatchStatus, normalize_title_key
from ..schemas import (
    EpisodeBulk,
    EpisodeSet,
    LibraryEntryCreate,
    LibraryEntryOut,
    LibraryEntryUpdate,
    RewatchCreate,
)

router = APIRouter(prefix="/media", tags=["media"])


def _get_owned_item(item_id: int, user: User, db: Session) -> LibraryEntry:
    item = db.get(LibraryEntry, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return item


def _find_or_create_title(data: LibraryEntryCreate, db: Session) -> Title:
    if data.tmdb_id is not None:
        found = (
            db.query(Title)
            .filter(Title.media_type == data.media_type, Title.tmdb_id == data.tmdb_id)
            .first()
        )
    else:
        found = (
            db.query(Title)
            .filter(
                Title.media_type == data.media_type,
                Title.tmdb_id.is_(None),
                Title.title_key == normalize_title_key(data.title),
            )
            .first()
        )
    if found:
        return found
    new_title = Title(
        media_type=data.media_type,
        tmdb_id=data.tmdb_id,
        title_key=None if data.tmdb_id is not None else normalize_title_key(data.title),
        title=data.title,
        year=data.year,
        poster_url=data.poster_url,
        runtime_minutes=data.runtime_minutes,
        total_episodes=data.total_episodes,
        genres=data.genres,
        author=data.author,
        page_count=data.page_count,
    )
    db.add(new_title)
    db.flush()
    return new_title


@router.get("", response_model=list[LibraryEntryOut])
def list_media(
    media_type: MediaType | None = None,
    status_filter: WatchStatus | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(LibraryEntry).join(Title).filter(LibraryEntry.user_id == user.id)
    if media_type is not None:
        query = query.filter(Title.media_type == media_type)
    if status_filter is not None:
        query = query.filter(LibraryEntry.status == status_filter)
    if search:
        query = query.filter(Title.title.ilike(f"%{search}%"))
    return query.order_by(LibraryEntry.updated_at.desc()).all()


@router.post("", response_model=LibraryEntryOut, status_code=status.HTTP_201_CREATED)
def create_media(
    data: LibraryEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    title = _find_or_create_title(data, db)
    duplicate = (
        db
        .query(LibraryEntry)
        .filter(LibraryEntry.user_id == user.id, LibraryEntry.title_id == title.id)
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already saved this title",
        )
    item = LibraryEntry(
        user_id=user.id,
        title_id=title.id,
        url=data.url,
        status=data.status,
        rating=data.rating,
        notes=data.notes,
        current_season=data.current_season,
        current_episode=data.current_episode,
        episodes_watched=data.episodes_watched,
        is_favorite=data.is_favorite,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/ratings")
def title_ratings(
    media_type: MediaType,
    tmdb_id: int | None = None,
    title: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )
    title_query = db.query(Title.id).filter(Title.media_type == media_type)
    title_query = (
        title_query.filter(Title.tmdb_id == tmdb_id)
        if tmdb_id is not None
        else title_query.filter(Title.tmdb_id.is_(None), Title.title_key == normalize_title_key(title))
    )
    title_ids = [t for (t,) in title_query.all()]
    ratings = [
        r
        for (r,) in db
        .query(LibraryEntry.rating)
        .filter(LibraryEntry.title_id.in_(title_ids), LibraryEntry.rating.isnot(None))
        .all()
    ]
    average = round(sum(ratings) / len(ratings), 1) if ratings else None
    return {"average": average, "count": len(ratings)}


@router.get("/{item_id}", response_model=LibraryEntryOut)
def get_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_owned_item(item_id, user, db)


@router.patch("/{item_id}", response_model=LibraryEntryOut)
def update_media(
    item_id: int,
    data: LibraryEntryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    db.delete(item)
    db.commit()


# ---------- per-episode tracking ----------


def _sync_progress(item: LibraryEntry, db: Session) -> None:
    """Recompute counters/status from the episode_watches rows."""
    watches = db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item.id).all()
    item.episodes_watched = len(watches)
    if watches:
        last = max(watches, key=lambda w: (w.season, w.episode))
        item.current_season, item.current_episode = last.season, last.episode
    if item.total_episodes and item.episodes_watched >= item.total_episodes:
        item.status = WatchStatus.completed
    elif item.episodes_watched > 0 and item.status == WatchStatus.want_to_watch:
        item.status = WatchStatus.watching
    db.commit()


def _ratings_summary(item: LibraryEntry, db: Session) -> dict:
    ep_ratings = [
        w.rating
        for w in db
        .query(EpisodeWatch)
        .filter(EpisodeWatch.media_item_id == item.id, EpisodeWatch.rating.isnot(None))
        .all()
    ]
    episode_avg = round(sum(ep_ratings) / len(ep_ratings), 1) if ep_ratings else None
    all_episodes_rated = bool(item.total_episodes) and len(ep_ratings) >= item.total_episodes
    combined = round((item.rating + episode_avg) / 2, 1) if item.rating and episode_avg and all_episodes_rated else None
    rewatch_count = (
        db.query(WatchEvent).filter(WatchEvent.media_item_id == item.id, WatchEvent.season.is_(None)).count()
    )
    return {
        "overall_rating": item.rating,
        "episode_avg": episode_avg,
        "combined_score": combined,
        "rated_episodes": len(ep_ratings),
        "rewatch_count": rewatch_count,
    }


@router.get("/{item_id}/episodes")
def list_episodes(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    watches = (
        db
        .query(EpisodeWatch)
        .filter(EpisodeWatch.media_item_id == item.id)
        .order_by(EpisodeWatch.season, EpisodeWatch.episode)
        .all()
    )
    rewatch_counts = {
        (s, e): c
        for s, e, c in db
        .query(WatchEvent.season, WatchEvent.episode, func.count(WatchEvent.id))
        .filter(WatchEvent.media_item_id == item.id, WatchEvent.season.isnot(None))
        .group_by(WatchEvent.season, WatchEvent.episode)
        .all()
    }
    return {
        "watched": [
            {
                "season": w.season,
                "episode": w.episode,
                "rating": w.rating,
                "rewatch_count": rewatch_counts.get((w.season, w.episode), 0),
            }
            for w in watches
        ],
        **_ratings_summary(item, db),
    }


@router.post("/{item_id}/rewatch")
def rewatch(
    item_id: int,
    data: RewatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    if (data.season is None) != (data.episode is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="season and episode must be given together",
        )
    if data.season is not None:
        watch = (
            db
            .query(EpisodeWatch)
            .filter(
                EpisodeWatch.media_item_id == item.id,
                EpisodeWatch.season == data.season,
                EpisodeWatch.episode == data.episode,
            )
            .first()
        )
        if watch is None:
            db.add(EpisodeWatch(media_item_id=item.id, season=data.season, episode=data.episode))
    db.add(WatchEvent(media_item_id=item.id, season=data.season, episode=data.episode))
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)


@router.put("/{item_id}/episodes/{season}/{episode}")
def set_episode(
    item_id: int,
    season: int,
    episode: int,
    data: EpisodeSet,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    watch = (
        db
        .query(EpisodeWatch)
        .filter(
            EpisodeWatch.media_item_id == item.id,
            EpisodeWatch.season == season,
            EpisodeWatch.episode == episode,
        )
        .first()
    )
    if data.watched:
        if watch is None:
            watch = EpisodeWatch(media_item_id=item.id, season=season, episode=episode)
            db.add(watch)
        watch.rating = data.rating
    elif watch is not None:
        db.delete(watch)
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)


@router.post("/{item_id}/episodes/bulk")
def bulk_episodes(
    item_id: int,
    data: EpisodeBulk,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    existing = {
        w.episode: w
        for w in db.query(EpisodeWatch).filter(
            EpisodeWatch.media_item_id == item.id, EpisodeWatch.season == data.season
        )
    }
    for ep in data.episodes:
        if data.watched and ep not in existing:
            db.add(EpisodeWatch(media_item_id=item.id, season=data.season, episode=ep))
        elif not data.watched and ep in existing:
            db.delete(existing[ep])
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)
