#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.990684
Revised: 2026/07/07 13:25:15.990684

Upcoming releases for tracked titles: next episodes and film premieres.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from typing import Optional

from ..auth import get_current_user
from ..database import get_db
from ..models import LibraryEntry, MediaType, Title, User, WatchStatus
from .tmdb import _tmdb_get

router = APIRouter(prefix="/upcoming", tags=["upcoming"])
_log = logging.getLogger(__name__)

# Large libraries mean hundreds of TMDB lookups per feed build; doing them
# sequentially takes minutes and times out the client. 16 parallel workers
# stay well under TMDB's ~50 req/s ceiling while cutting a cold build to
# a few seconds (warm builds are served from the 30-min TMDB cache).
_MAX_WORKERS = 16


def _tv_entry(item: dict, today: date) -> dict | None:
    data = _tmdb_get(f"/tv/{item['tmdb_id']}")
    nxt = data.get("next_episode_to_air") or {}
    air_str = nxt.get("air_date")
    if not air_str:
        return None
    when = date.fromisoformat(air_str)
    if when < today:
        return None
    return {
        "item_id": item["id"],
        "media_type": "tv_show",
        "title": item["title"],
        "poster_url": item["poster_url"],
        "date": air_str,
        "days_until": (when - today).days,
        "season": nxt.get("season_number"),
        "episode": nxt.get("episode_number"),
        "episode_name": nxt.get("name"),
    }


def _film_entry(item: dict, today: date) -> dict | None:
    data = _tmdb_get(f"/movie/{item['tmdb_id']}")
    rel_str = data.get("release_date")
    if not rel_str:
        return None
    when = date.fromisoformat(rel_str)
    if when <= today:
        return None
    return {
        "item_id": item["id"],
        "media_type": "film",
        "title": item["title"],
        "poster_url": item["poster_url"],
        "date": rel_str,
        "days_until": (when - today).days,
        "season": None,
        "episode": None,
        "episode_name": None,
    }


def _entry(item: dict, today: date) -> dict | None:
    try:
        if item["media_type"] == MediaType.tv_show:
            return _tv_entry(item, today)
        return _film_entry(item, today)
    except Exception:
        # one unreachable title must not break the whole feed
        _log.warning("upcoming lookup failed for %r (tmdb_id=%s)", item["title"], item["tmdb_id"], exc_info=True)
        return None


@router.get("")
def get_upcoming(
    status_filter: Optional[WatchStatus] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        db
        .query(LibraryEntry, Title)
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
    # plain dicts: worker threads must not touch ORM objects tied to the session
    items = [
        {
            "id": entry.id,
            "media_type": title.media_type,
            "title": title.title,
            "poster_url": title.poster_url,
            "tmdb_id": title.tmdb_id,
        }
        for entry, title in rows
    ]
    today = date.today()
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        results = pool.map(lambda it: _entry(it, today), items)
    out = [entry for entry in results if entry is not None]
    out.sort(key=lambda e: e["date"])
    return out
