#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:22:54.723786
Revised: 2026/07/27 16:39:30.147559

Background checkers: new-episode notifications, film release-date refresh,
episode history backfill, and periodic TMDB metadata resync for every
tracked title (see task_runs.py for the shared enable/interval mechanism).
"""

import asyncio
import logging
import time
from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import task_runs
from ..database import SessionLocal
from ..models import EpisodeWatch, LibraryEntry, MediaType, Notification, Title, WatchStatus, utcnow
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
        # commit per show instead of batching the whole scan into one
        # transaction — otherwise this loop holds tmdb_cache row locks for
        # every title it has touched so far, and can deadlock against the
        # other background loops (film_check, tmdb_metadata_resync, ...)
        # updating the same rows in a different order (see also
        # resync_tmdb_metadata / check_upcoming_films below).
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
        # commit per title, not once for the whole scan — see the comment
        # in check_new_episodes on why a long-held transaction here
        # deadlocks against the other tmdb_cache writers.
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


def resync_tmdb_metadata(db: Session, fetch_show=fetch_show, fetch_film=fetch_film, pace_seconds: float = 0.05) -> int:
    """Refresh poster/backdrop/details for every tracked title, no matter its
    watch status. check_new_episodes/check_upcoming_films both permanently
    stop polling a title once it's dropped/ended/released — so if TMDB later
    swaps a title's official poster, a completed or dropped title would never
    pick it up. This is the only job that revisits those too. Returns the
    number of titles successfully refreshed."""
    titles = (
        db.query(Title)
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(Title.tmdb_id.isnot(None))
        .distinct()
        .all()
    )
    refreshed = 0
    for title in titles:
        fetch = fetch_show if title.media_type == MediaType.tv_show else fetch_film
        try:
            data = fetch(title.tmdb_id)
        except Exception as exc:
            _log.warning("TMDB resync fetch failed for title %s (tmdb %s): %s", title.id, title.tmdb_id, exc)
            continue
        store_details(db, title, data)
        refreshed += 1
        # commit per title, not once for the whole scan — see the comment
        # in check_new_episodes on why a long-held transaction here
        # deadlocks against the other tmdb_cache writers. Committing before
        # the pacing sleep also means the row lock isn't held across it.
        db.commit()
        if pace_seconds:
            time.sleep(pace_seconds)  # spread requests instead of bursting TMDB (no rate limiting in tmdb_http.py)
    return refreshed


def resync_tmdb_metadata_once() -> int:
    db = SessionLocal()
    try:
        return resync_tmdb_metadata(db)
    finally:
        db.close()


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


async def _episode_check_loop() -> None:
    await asyncio.sleep(15)  # let the app finish booting
    while True:
        if not task_runs.is_enabled("episode_check"):
            _log.info("episode check skipped: disabled")
        else:
            started = utcnow()
            try:
                n = await asyncio.to_thread(check_once)
                _log.info("episode check done: %d new notifications", n)
                task_runs.record_run("episode_check", started, "ok", f"{n} new notifications")
            except Exception:
                _log.exception("episode check failed")
                task_runs.record_run("episode_check", started, "error", "check failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("episode_check") * 60)


async def _episode_history_sync_loop() -> None:
    await asyncio.sleep(15)
    while True:
        if not task_runs.is_enabled("episode_history_sync"):
            _log.info("episode history sync skipped: disabled")
        else:
            started = utcnow()
            try:
                k = await asyncio.to_thread(sync_episode_history_once)
                _log.info("episode history sync done: %d shows checked", k)
                task_runs.record_run("episode_history_sync", started, "ok", f"{k} shows checked")
            except Exception:
                _log.exception("episode history sync failed")
                task_runs.record_run("episode_history_sync", started, "error", "sync failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("episode_history_sync") * 60)


async def _film_check_loop() -> None:
    await asyncio.sleep(15)
    while True:
        if not task_runs.is_enabled("film_check"):
            _log.info("film check skipped: disabled")
        else:
            started = utcnow()
            try:
                m = await asyncio.to_thread(check_films_once)
                _log.info("film release check done: %d titles refreshed", m)
                task_runs.record_run("film_check", started, "ok", f"{m} titles refreshed")
            except Exception:
                _log.exception("film release check failed")
                task_runs.record_run("film_check", started, "error", "check failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("film_check") * 60)


def cleanup_unconfirmed_accounts_once() -> int:
    from ..users.email_confirmation import cleanup_unconfirmed_accounts  # local import: avoids a cycle at module load

    db = SessionLocal()
    try:
        return cleanup_unconfirmed_accounts(db)
    finally:
        db.close()


async def _email_confirmation_cleanup_loop() -> None:
    await asyncio.sleep(15)
    while True:
        if not task_runs.is_enabled("email_confirmation_cleanup"):
            _log.info("email confirmation cleanup skipped: disabled")
        else:
            started = utcnow()
            try:
                n = await asyncio.to_thread(cleanup_unconfirmed_accounts_once)
                _log.info("email confirmation cleanup done: %d accounts removed", n)
                task_runs.record_run("email_confirmation_cleanup", started, "ok", f"{n} accounts removed")
            except Exception:
                _log.exception("email confirmation cleanup failed")
                task_runs.record_run("email_confirmation_cleanup", started, "error", "cleanup failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("email_confirmation_cleanup") * 60)


def purge_expired_exports_once() -> int:
    from ..users.export import purge_expired_exports  # local import: avoids a cycle at module load

    db = SessionLocal()
    try:
        return purge_expired_exports(db)
    finally:
        db.close()


async def _export_cleanup_loop() -> None:
    await asyncio.sleep(15)
    while True:
        if not task_runs.is_enabled("export_cleanup"):
            _log.info("export cleanup skipped: disabled")
        else:
            started = utcnow()
            try:
                n = await asyncio.to_thread(purge_expired_exports_once)
                _log.info("export cleanup done: %d exports purged", n)
                task_runs.record_run("export_cleanup", started, "ok", f"{n} exports purged")
            except Exception:
                _log.exception("export cleanup failed")
                task_runs.record_run("export_cleanup", started, "error", "cleanup failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("export_cleanup") * 60)


async def _tmdb_metadata_resync_loop() -> None:
    await asyncio.sleep(15)
    while True:
        if not task_runs.is_enabled("tmdb_metadata_resync"):
            _log.info("TMDB metadata resync skipped: disabled")
        else:
            started = utcnow()
            try:
                n = await asyncio.to_thread(resync_tmdb_metadata_once)
                _log.info("TMDB metadata resync done: %d titles refreshed", n)
                task_runs.record_run("tmdb_metadata_resync", started, "ok", f"{n} titles refreshed")
            except Exception:
                _log.exception("TMDB metadata resync failed")
                task_runs.record_run("tmdb_metadata_resync", started, "error", "resync failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("tmdb_metadata_resync") * 60)


def start_periodic_tasks() -> list[asyncio.Task]:
    """Launch the six independent per-task loops; each is paused/rescheduled
    without affecting the others (see task_runs.py / admin Periodic Tasks page)."""
    return [
        asyncio.create_task(_episode_check_loop()),
        asyncio.create_task(_episode_history_sync_loop()),
        asyncio.create_task(_film_check_loop()),
        asyncio.create_task(_tmdb_metadata_resync_loop()),
        asyncio.create_task(_email_confirmation_cleanup_loop()),
        asyncio.create_task(_export_cleanup_loop()),
    ]
