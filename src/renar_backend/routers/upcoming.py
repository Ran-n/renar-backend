#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.990684
Revised: 2026/09/30 09:38:45.119542

Upcoming releases for tracked titles: next episodes and film premieres.
"""

import logging
import time
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, aliased

from ..catalog.titles import WITH_TITLE_GENRES
from ..database import SessionLocal, get_db
from ..models import Episode, LibraryEntry, MediaType, Title, User, WatchStatus
from ..schemas import UpcomingItemOut
from ..tmdb.tmdb_store import sync_show_episodes
from ..users.auth import get_current_user

router = APIRouter(prefix="/upcoming", tags=["upcoming"])
_log = logging.getLogger(__name__)

# Cap on how much live TMDB-syncing time /upcoming/history does inline. The
# common case (already-synced shows, or nothing new) costs nothing but
# indexed DB reads regardless of this budget — this only bounds the rare
# case of several newly-tracked/never-synced shows landing in the same
# request, so one bad batch can't turn into a multi-minute response. Titles
# that don't get their turn before the budget runs out are still caught up,
# just via a background task instead of this response.
_HISTORY_SYNC_BUDGET_S = 3.0


def _tv_entry(entry: LibraryEntry, title: Title, today: date) -> dict | None:
    when = title.next_episode_air_date
    if when is None or when < today:
        return None
    return {
        "item_id": entry.id,
        "media_type": "tv_show",
        "title": title.title,
        "tmdb_id": title.tmdb_id,
        "poster_url": entry.poster_url,
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
        "tmdb_id": title.tmdb_id,
        "poster_url": entry.poster_url,
        "date": when.isoformat(),
        "days_until": (when - today).days,
        "season": None,
        "episode": None,
        "episode_name": None,
    }


@router.get("", response_model=list[UpcomingItemOut])
def get_upcoming(
    status_filter: WatchStatus | None = None,
    media_type: MediaType | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        db.query(LibraryEntry, Title)
        .join(Title, LibraryEntry.title_id == Title.id)
        .options(*WITH_TITLE_GENRES)
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
    if media_type is not None:
        query = query.filter(Title.media_type == media_type)
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


def _sync_episodes_background(title_id: int) -> None:
    """Runs after the response is sent (see get_upcoming_history's
    background_tasks.add_task below) — its own DB session, since the
    request-scoped one is already closed by the time this fires."""
    with SessionLocal() as db:
        title = db.get(Title, title_id)
        if title is None:
            return
        try:
            sync_show_episodes(db, title)
        except Exception:
            _log.exception("background episode sync failed for title %s", title_id)


@router.get("/history", response_model=list[UpcomingItemOut])
def get_upcoming_history(
    background_tasks: BackgroundTasks,
    status_filter: WatchStatus | None = None,
    media_type: MediaType | None = None,
    before: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Past releases: aired TV episodes and released films for tracked
    titles, most recent first. `before` (an ISO date from a previous
    page's oldest entry) pages further into the past."""
    today = date.today()
    if before is not None:
        try:
            cutoff = date.fromisoformat(before)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date: {before!r}") from exc
    else:
        # today's own releases belong to /upcoming (which counts an episode
        # airing today, though not a film released today, as "upcoming" —
        # see _tv_entry/_film_entry above); cutting off at today rather than
        # tomorrow keeps them from also showing up here as "history"
        cutoff = today

    out = []

    if media_type is None or media_type == MediaType.tv_show:
        tv_query = (
            db.query(LibraryEntry, Title)
            .join(Title, LibraryEntry.title_id == Title.id)
            .options(*WITH_TITLE_GENRES)
            .filter(
                LibraryEntry.user_id == user.id,
                Title.media_type == MediaType.tv_show,
                Title.tmdb_id.isnot(None),
                LibraryEntry.status != WatchStatus.dropped,
            )
        )
        if status_filter is not None:
            tv_query = tv_query.filter(LibraryEntry.status == status_filter)

        tv_rows = tv_query.all()
        entry_by_title_id = {title.id: (entry, title) for entry, title in tv_rows}
        # Backfilled lazily here (through the same persistent TMDB cache
        # season_tmdb() uses) so a show's history shows up on the first
        # request rather than waiting for the periodic background job — but
        # bounded by _HISTORY_SYNC_BUDGET_S: this endpoint's latency used to
        # scale with TMDB's, for every season of every tracked show, on
        # every call, and a handful of slow/retrying titles could (and did)
        # block the whole response for a minute or more. Once the budget's
        # spent, remaining titles are caught up via background_tasks instead
        # of this response; sync_show_episodes itself skips seasons already
        # fully captured, so a synced show still costs only cheap DB reads.
        sync_deadline = time.monotonic() + _HISTORY_SYNC_BUDGET_S
        for _, title in tv_rows:
            if time.monotonic() >= sync_deadline:
                background_tasks.add_task(_sync_episodes_background, title.id)
                continue
            sync_show_episodes(db, title, deadline=sync_deadline)

        if entry_by_title_id:
            # One query for every tracked show instead of a per-title
            # round trip: a window function caps each title's contribution
            # at `limit` rows (matching the old per-title .limit(limit)),
            # since the global top-`limit` by date can never draw more than
            # `limit` rows from a single title anyway.
            rank = func.row_number().over(partition_by=Episode.title_id, order_by=Episode.air_date.desc()).label("rank")
            ranked = (
                db.query(Episode, rank)
                .filter(
                    Episode.title_id.in_(entry_by_title_id.keys()),
                    Episode.air_date.isnot(None),
                    Episode.air_date < cutoff,
                )
                .subquery()
            )
            RankedEpisode = aliased(Episode, ranked)
            episodes = db.query(RankedEpisode).filter(ranked.c.rank <= limit).all()
            for ep in episodes:
                entry, title = entry_by_title_id[ep.title_id]
                out.append({
                    "item_id": entry.id,
                    "media_type": "tv_show",
                    "title": title.title,
                    "tmdb_id": title.tmdb_id,
                    "poster_url": entry.poster_url,
                    "date": ep.air_date.isoformat(),
                    "days_until": (ep.air_date - today).days,
                    "season": ep.season,
                    "episode": ep.episode_number,
                    "episode_name": ep.name,
                })

    if media_type is None or media_type == MediaType.film:
        film_query = (
            db.query(LibraryEntry, Title)
            .join(Title, LibraryEntry.title_id == Title.id)
            .options(*WITH_TITLE_GENRES)
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
                "tmdb_id": title.tmdb_id,
                "poster_url": entry.poster_url,
                "date": title.release_date.isoformat(),
                "days_until": (title.release_date - today).days,
                "season": None,
                "episode": None,
                "episode_name": None,
            })

    out.sort(key=lambda e: e["date"], reverse=True)
    return out[:limit]
