#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:22:54.723786
Revised: 2026/08/19 19:11:30.683774

Background checkers: new-episode notifications, film release-date refresh,
episode history backfill, and periodic TMDB metadata resync for every
tracked title (see task_runs.py for the shared enable/interval mechanism).
"""

import asyncio
import logging
import time
from datetime import date, timedelta

from sqlalchemy import inspect, or_
from sqlalchemy.orm import Session

from .. import task_runs
from ..catalog.titles import backfill_title_tmdb_id, find_title
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


def retry_unmatched_titles(
    db: Session,
    search_tv=None,
    search_movie=None,
    find_by_tvdb=None,
    fetch_show=fetch_show,
    fetch_film=fetch_film,
    pace_seconds: float = 0.05,
) -> int:
    """Re-attempt a TMDB match for every shared Title still unmatched
    (`tmdb_id` is None) — an unmatched Title otherwise only heals via the
    retry/backoff already inside `tmdb_get` (fixes a blip within one
    import), a later re-import happening to resolve it (see
    `catalog/titles.py`'s `backfill_title_tmdb_id` and
    `users/tvtime_import.py`'s raw-name-keyed reconciliation), or the show
    having a TheTVDB fallback identity already (`title_row.tvdb_id` — see
    `users/tvtime_import.py`'s TVDB fallback) — none of that helps a title
    that keeps failing on all of the above with nobody ever re-importing. A
    Title is shared across every user tracking it, so one successful match
    here fixes every affected library entry at once, not just one
    account's.

    When a title already carries a `tvdb_id`, `find_by_tvdb` (TMDB's own
    `/find` crosswalk by TVDB id) is tried before the plain name search —
    far more reliable, and already the identity TV Time gave us. `search_tv`
    /`search_movie`/`find_by_tvdb` default to the same matchers the TV Time
    importer uses (lazy-imported to avoid a load-time cycle); overridable
    for tests. A movie that now resolves as a TV show is left alone — a
    genuine media_type change isn't something this can safely rewrite in
    place, so it's left for the manual "Link to catalog" relink instead.
    """
    if search_tv is None or search_movie is None or find_by_tvdb is None:
        from ..users.tvtime_import import _find_tv_by_tvdb, _search_movie, _search_tv  # avoids a load-time cycle

        search_tv = search_tv or _search_tv
        search_movie = search_movie or _search_movie
        find_by_tvdb = find_by_tvdb or _find_tv_by_tvdb

    titles = db.query(Title).filter(Title.tmdb_id.is_(None)).all()
    fixed = 0
    for title_row in titles:
        try:
            if title_row.media_type == MediaType.tv_show:
                found = find_by_tvdb(str(title_row.tvdb_id)) if title_row.tvdb_id else None
                found = found or search_tv(title_row.title)
            else:
                found, is_tv = search_movie(title_row.title, str(title_row.year) if title_row.year else None)
                if is_tv:
                    continue
        except Exception as exc:
            _log.warning("TMDB retry search failed for title %s (%r): %s", title_row.id, title_row.title, exc)
            continue
        if found is None:
            continue

        tmdb_id = found["id"]
        media_type = title_row.media_type
        name_field = "name" if media_type == MediaType.tv_show else "title"
        resolved_title = found.get(name_field) or title_row.title
        backfill_title_tmdb_id(db, title_row, tmdb_id, title=resolved_title)
        # tmdb_id was already claimed by another Title: merge_titles (inside
        # backfill_title_tmdb_id) folds title_row into that Title and deletes
        # title_row, so the row now carrying tmdb_id is that other Title, not
        # title_row itself — re-resolve before checking/using it below.
        resolved = title_row if not inspect(title_row).deleted else find_title(db, media_type, tmdb_id, None)
        if resolved is None or resolved.tmdb_id != tmdb_id:
            db.rollback()  # lost a race to another writer claiming this tmdb_id first
            continue
        db.commit()

        try:
            fetch = fetch_show if media_type == MediaType.tv_show else fetch_film
            data = fetch(tmdb_id)
            store_details(db, resolved, data)
            db.commit()
        except Exception as exc:
            # identity (tmdb_id, title) is already saved above; only the
            # richer metadata (genres, overview, ...) is missing this round
            _log.warning("TMDB details fetch failed after relinking title %s (tmdb %s): %s", resolved.id, tmdb_id, exc)
        fixed += 1
        if pace_seconds:
            time.sleep(pace_seconds)  # spread requests instead of bursting TMDB
    return fixed


def retry_unmatched_titles_once() -> int:
    db = SessionLocal()
    try:
        return retry_unmatched_titles(db)
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


async def _unmatched_title_retry_loop() -> None:
    await asyncio.sleep(15)
    while True:
        if not task_runs.is_enabled("unmatched_title_retry"):
            _log.info("unmatched title retry skipped: disabled")
        else:
            started = utcnow()
            try:
                n = await asyncio.to_thread(retry_unmatched_titles_once)
                _log.info("unmatched title retry done: %d titles fixed", n)
                task_runs.record_run("unmatched_title_retry", started, "ok", f"{n} titles fixed")
            except Exception:
                _log.exception("unmatched title retry failed")
                task_runs.record_run("unmatched_title_retry", started, "error", "retry failed, see server logs")
        await asyncio.sleep(task_runs.get_interval_minutes("unmatched_title_retry") * 60)


def start_periodic_tasks() -> list[asyncio.Task]:
    """Launch the seven independent per-task loops; each is paused/rescheduled
    without affecting the others (see task_runs.py / admin Periodic Tasks page)."""
    return [
        asyncio.create_task(_episode_check_loop()),
        asyncio.create_task(_episode_history_sync_loop()),
        asyncio.create_task(_film_check_loop()),
        asyncio.create_task(_tmdb_metadata_resync_loop()),
        asyncio.create_task(_unmatched_title_retry_loop()),
        asyncio.create_task(_email_confirmation_cleanup_loop()),
        asyncio.create_task(_export_cleanup_loop()),
    ]
