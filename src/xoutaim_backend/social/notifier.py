#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:22:54.723786
Revised: 2026/07/17 18:08:57.738916

Background checker: creates notifications when tracked shows air new episodes.
"""

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import site_settings
from ..config import settings
from ..database import SessionLocal
from ..models import EpisodeWatch, LibraryEntry, MediaType, Notification, Title, WatchStatus
from ..tmdb.tmdb_http import tmdb_get
from ..tmdb.tmdb_store import ENDED_STATUSES, store_details, sync_show_episodes

_log = logging.getLogger(__name__)

RECENT_DAYS = 7  # notify about episodes that aired in the last week


def fetch_show(tmdb_id: int) -> dict:
    return tmdb_get(f"/tv/{tmdb_id}")


def fetch_film(tmdb_id: int) -> dict:
    return tmdb_get(f"/movie/{tmdb_id}")


def check_new_episodes(db: Session, fetch=fetch_show) -> int:
    """Scan all tracked TV shows once; returns number of notifications created."""
    items = (
        db.query(LibraryEntry)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(
            Title.media_type == MediaType.tv_show,
            Title.tmdb_id.isnot(None),
            LibraryEntry.status != WatchStatus.dropped,
            # finished shows air nothing — stop polling them (a detail-page
            # visit still refreshes show_status, so revivals recover)
            or_(Title.show_status.is_(None), Title.show_status.notin_(ENDED_STATUSES)),
        )
        .all()
    )
    by_tmdb: dict[int, list[LibraryEntry]] = {}
    for item in items:
        by_tmdb.setdefault(item.tmdb_id, []).append(item)

    created = 0
    today = date.today()
    for tmdb_id, group in by_tmdb.items():
        try:
            data = fetch(tmdb_id)
        except Exception as exc:
            _log.warning("TMDB fetch failed for show %s: %s", tmdb_id, exc)
            continue
        # the payload is already in hand — persist it (tmdb_cache + typed
        # Title columns: show_status, next_episode_air_date, ...) for free
        store_details(db, group[0].title_ref, data)
        last = data.get("last_episode_to_air") or {}
        air_str = last.get("air_date")
        season = last.get("season_number")
        episode = last.get("episode_number")
        if not air_str or season is None or episode is None:
            continue
        try:
            air = date.fromisoformat(air_str)
        except ValueError:
            _log.warning("malformed air_date %r for show %s", air_str, tmdb_id)
            continue
        if air > today or air < today - timedelta(days=RECENT_DAYS):
            continue

        show_name = data.get("name") or group[0].title
        ep_name = last.get("name") or f"Episode {episode}"
        for item in group:
            already_watched = (
                db.query(EpisodeWatch).filter_by(media_item_id=item.id, season=season, episode=episode).first()
            )
            if already_watched:
                continue
            # a show the user finished has a new, unwatched episode now —
            # resurface it under "watching" so it reappears on Home instead
            # of staying parked under "completed" forever.
            if item.status == WatchStatus.completed:
                item.status = WatchStatus.watching
            already_notified = (
                db.query(Notification)
                .filter_by(
                    user_id=item.user_id,
                    media_item_id=item.id,
                    season=season,
                    episode=episode,
                    kind="new_episode",
                )
                .first()
            )
            if already_notified:
                continue
            db.add(
                Notification(
                    user_id=item.user_id,
                    media_item_id=item.id,
                    kind="new_episode",
                    title=f"New episode: {show_name}",
                    body=f"S{season:02d}E{episode:02d} · {ep_name} · aired {air_str}",
                    season=season,
                    episode=episode,
                )
            )
            created += 1
    db.commit()
    return created


def check_upcoming_films(db: Session, fetch=fetch_film) -> int:
    """Refresh Title.release_date for tracked want-to-watch films whose
    release hasn't happened yet, so /upcoming can read it without hitting
    TMDB on the request path. Returns number of titles refreshed."""
    titles = (
        db.query(Title)
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(
            Title.media_type == MediaType.film,
            Title.tmdb_id.isnot(None),
            LibraryEntry.status == WatchStatus.want_to_watch,
            # already-released films have nothing left to change, and
            # /upcoming ignores them anyway once release_date is in the past
            or_(Title.release_date.is_(None), Title.release_date >= date.today()),
        )
        .distinct()
        .all()
    )
    refreshed = 0
    for title in titles:
        try:
            data = fetch(title.tmdb_id)
        except Exception as exc:
            _log.warning("TMDB fetch failed for film %s: %s", title.tmdb_id, exc)
            continue
        store_details(db, title, data)
        refreshed += 1
    db.commit()
    return refreshed


def sync_episode_history(db: Session) -> int:
    """Backfill the episodes table for every tracked, non-dropped show, so
    /upcoming/history is a plain DB read — no per-title TMDB round trips on
    the request path. Titles with a fully-captured history cost only a few
    indexed reads (see sync_show_episodes)."""
    titles = (
        db.query(Title)
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(
            Title.media_type == MediaType.tv_show,
            Title.tmdb_id.isnot(None),
            LibraryEntry.status != WatchStatus.dropped,
        )
        .distinct()
        .all()
    )
    for title in titles:
        try:
            sync_show_episodes(db, title)
        except Exception:
            _log.exception("episode history sync failed for title %s", title.id)
    return len(titles)


def sync_episode_history_once() -> int:
    db = SessionLocal()
    try:
        return sync_episode_history(db)
    finally:
        db.close()


def check_once() -> int:
    db = SessionLocal()
    try:
        return check_new_episodes(db)
    finally:
        db.close()


def check_films_once() -> int:
    db = SessionLocal()
    try:
        return check_upcoming_films(db)
    finally:
        db.close()


async def run_periodic() -> None:
    await asyncio.sleep(15)  # let the app finish booting
    while True:
        ss = site_settings.current()
        if not ss.episode_check_enabled:
            _log.info("episode check skipped: disabled in site settings")
        else:
            try:
                n = await asyncio.to_thread(check_once)
                _log.info("episode check done: %d new notifications", n)
            except Exception:
                _log.exception("episode check failed")
            try:
                k = await asyncio.to_thread(sync_episode_history_once)
                _log.info("episode history sync done: %d shows checked", k)
            except Exception:
                _log.exception("episode history sync failed")
        if not ss.film_check_enabled:
            _log.info("film check skipped: disabled in site settings")
        else:
            try:
                m = await asyncio.to_thread(check_films_once)
                _log.info("film release check done: %d titles refreshed", m)
            except Exception:
                _log.exception("film release check failed")
        await asyncio.sleep(settings.episode_check_minutes * 60)
