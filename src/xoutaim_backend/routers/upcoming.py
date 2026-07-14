#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.990684
Revised: 2026/07/13 09:26:03.346399

Upcoming releases for tracked titles: next episodes and film premieres.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Episode, LibraryEntry, MediaType, Title, User, WatchStatus
from ..tmdb_store import sync_show_episodes

router = APIRouter(prefix="/upcoming", tags=["upcoming"])
_log = logging.getLogger(__name__)


def _tv_entry(entry: LibraryEntry, title: Title, today: date) -> dict | None:
    when = title.next_episode_air_date
    if when is None or when < today:
        return None
    return {
        "item_id": entry.id,
        "media_type": "tv_show",
        "title": title.title,
        "poster_url": title.poster_url,
        "date": when.isoformat(),
        "days_until": (when - today).days,
        "season": title.next_episode_season,
        "episode": title.next_episode_number,
        "episode_name": title.next_episode_name,
    }


def _film_entry(entry: LibraryEntry, title: Title, today: date) -> dict | None:
    when = title.release_date
    if when is None or when <= today:
        return None
    return {
        "item_id": entry.id,
        "media_type": "film",
        "title": title.title,
        "poster_url": title.poster_url,
        "date": when.isoformat(),
        "days_until": (when - today).days,
        "season": None,
        "episode": None,
        "episode_name": None,
    }


@router.get("")
def get_upcoming(
    status_filter: WatchStatus | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        db.query(LibraryEntry, Title)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(
            LibraryEntry.user_id == user.id,
            Title.tmdb_id.isnot(None),
            or_(
                and_(
                    Title.media_type == MediaType.tv_show,
                    LibraryEntry.status != WatchStatus.dropped,
                ),
                # only unreleased films the user still wants to watch
                and_(
                    Title.media_type == MediaType.film,
                    LibraryEntry.status == WatchStatus.want_to_watch,
                ),
            ),
        )
    )
    if status_filter is not None:
        query = query.filter(LibraryEntry.status == status_filter)
    rows = query.all()
    today = date.today()
    # Next-episode/release-date data is synced onto Title in the background
    # (notifier.run_periodic) and on add/visit (refresh_title_details), so
    # this is a plain DB read — no per-title TMDB round trips on the request path.
    out = []
    for entry, title in rows:
        found = (
            _tv_entry(entry, title, today)
            if title.media_type == MediaType.tv_show
            else _film_entry(entry, title, today)
        )
        if found is not None:
            out.append(found)
    out.sort(key=lambda e: e["date"])
    return out


@router.get("/history")
def get_upcoming_history(
    status_filter: WatchStatus | None = None,
    before: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Past releases: aired TV episodes and released films for tracked
    titles, most recent first. `before` (an ISO date from a previous
    page's oldest entry) pages further into the past."""
    today = date.today()
    cutoff = date.fromisoformat(before) if before else today + timedelta(days=1)

    tv_query = (
        db.query(LibraryEntry, Title)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(
            LibraryEntry.user_id == user.id,
            Title.media_type == MediaType.tv_show,
            Title.tmdb_id.isnot(None),
            LibraryEntry.status != WatchStatus.dropped,
        )
    )
    if status_filter is not None:
        tv_query = tv_query.filter(LibraryEntry.status == status_filter)

    out = []
    for entry, title in tv_query.all():
        # Backfilled lazily here (through the same persistent TMDB cache
        # season_tmdb() uses) so a show's history shows up on the first
        # request rather than waiting for the periodic background job;
        # sync_show_episodes skips seasons already fully captured, so a
        # synced show costs only indexed DB reads.
        sync_show_episodes(db, title)
        episodes = (
            db.query(Episode)
            .filter(
                Episode.title_id == title.id,
                Episode.air_date.isnot(None),
                Episode.air_date < cutoff,
            )
            .order_by(Episode.air_date.desc())
            .limit(limit)
            .all()
        )
        for ep in episodes:
            out.append({
                "item_id": entry.id,
                "media_type": "tv_show",
                "title": title.title,
                "poster_url": title.poster_url,
                "date": ep.air_date.isoformat(),
                "days_until": (ep.air_date - today).days,
                "season": ep.season,
                "episode": ep.episode_number,
                "episode_name": ep.name,
            })

    film_query = (
        db.query(LibraryEntry, Title)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(
            LibraryEntry.user_id == user.id,
            Title.media_type == MediaType.film,
            Title.tmdb_id.isnot(None),
            LibraryEntry.status != WatchStatus.dropped,
            Title.release_date.isnot(None),
            Title.release_date < cutoff,
        )
    )
    if status_filter is not None:
        film_query = film_query.filter(LibraryEntry.status == status_filter)
    for entry, title in film_query.all():
        out.append({
            "item_id": entry.id,
            "media_type": "film",
            "title": title.title,
            "poster_url": title.poster_url,
            "date": title.release_date.isoformat(),
            "days_until": (title.release_date - today).days,
            "season": None,
            "episode": None,
            "episode_name": None,
        })

    out.sort(key=lambda e: e["date"], reverse=True)
    return out[:limit]
