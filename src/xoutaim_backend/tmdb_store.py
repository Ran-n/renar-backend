#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:17.543016
Revised: 2026/07/14 22:48:35.335411

Write-through persistence for TMDB data (see TmdbCache in models.py).

Flow for every cached endpoint: serve the stored payload while it is
fresh; otherwise fetch from TMDB, persist the raw response (only for
titles that exist in our titles table — explore browsing is never
persisted), and fall back to the stale stored copy when TMDB is
unreachable. Detail payloads also sync the typed columns on Title
(overview, show_status, next_episode_air_date, ...) that the notifier,
upcoming feed and clients read directly.
"""

import logging
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import Episode, MediaType, Title, TmdbCache, utcnow
from .titles import find_title, resolve_genres
from .tmdb_http import BACKDROP_BASE, POSTER_BASE, TMDB_KIND, tmdb_get

_log = logging.getLogger(__name__)

# TMDB `status` values for shows that will not air new episodes; the
# notifier stops polling these (a detail-page visit still refreshes them,
# so a revived show recovers on its own).
ENDED_STATUSES = ("Ended", "Canceled")

NO_SEASON = -1  # TmdbCache.season for the non-season kinds (details/credits)

# app language code -> TMDB locale; unmapped codes (e.g. "eo", which TMDB
# doesn't support) fall back to no `language` param, i.e. TMDB's own default
TMDB_LOCALE = {"gl": "gl-ES", "pt": "pt-PT", "es": "es-ES"}


def _is_fresh(fetched_at: datetime) -> bool:
    return utcnow() - fetched_at < timedelta(hours=settings.tmdb_db_cache_hours)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _log.warning("malformed TMDB date %r", value)
        return None


def _parse_year(value: str | None) -> int | None:
    parsed = _parse_date(value)
    return parsed.year if parsed else None


def upsert_cache(db: Session, title_id: int, kind: str, season: int, payload: dict, language: str = "en") -> None:
    """Insert or refresh one cache row; race-safe via a savepoint (two
    requests can fetch the same uncached title concurrently)."""
    row = db.query(TmdbCache).filter_by(title_id=title_id, kind=kind, season=season, language=language).first()
    if row is not None:
        row.payload = payload
        row.fetched_at = utcnow()
        return
    try:
        with db.begin_nested():
            db.add(TmdbCache(title_id=title_id, kind=kind, season=season, language=language, payload=payload))
    except IntegrityError:
        # another request inserted the same key in the meantime — refresh it
        row = db.query(TmdbCache).filter_by(title_id=title_id, kind=kind, season=season, language=language).first()
        if row is None:
            _log.error(
                "tmdb_cache row (%s, %s, %s, %s) neither insertable nor findable", title_id, kind, season, language
            )
            return
        row.payload = payload
        row.fetched_at = utcnow()


def localized_titles(db: Session, title_ids: list[int], language: str) -> dict[int, str]:
    """Best-effort per-title display name in `language`, read from whatever
    TMDB detail payloads are already cached for it — never a live TMDB call,
    so this stays cheap enough to run on every list_media request. Titles
    with no cached translation for that language are simply absent from the
    returned dict; callers fall back to Title.title."""
    if not title_ids or language == "en":
        return {}
    rows = (
        db.query(TmdbCache.title_id, TmdbCache.payload)
        .filter(TmdbCache.title_id.in_(title_ids), TmdbCache.kind == "details", TmdbCache.language == language)
        .all()
    )
    out: dict[int, str] = {}
    for title_id, payload in rows:
        name = payload.get("title") or payload.get("name")
        if name:
            out[title_id] = name
    return out


def warm_title_translations(title_ids: list[int], language: str) -> None:
    """Fire-and-forget: fetch+cache `language` detail payloads for titles that
    don't have one yet, so the *next* list_media call can localize them.
    Runs in a FastAPI BackgroundTasks callback (own DB session, after the
    response is already sent) — never blocks the request that triggered it.
    """
    from .database import SessionLocal  # local import: avoids a cycle at module load

    with SessionLocal() as db:
        titles = db.query(Title).filter(Title.id.in_(title_ids), Title.tmdb_id.isnot(None)).all()
        for title in titles:
            if title.media_type.value not in TMDB_KIND:
                continue
            path = f"/{TMDB_KIND[title.media_type.value]}/{title.tmdb_id}"
            try:
                cached_tmdb(db, title.media_type, title.tmdb_id, "details", path, language=language)
            except HTTPException as exc:
                _log.warning("translation warm-up skipped for title %s (%s): %s", title.id, language, exc.detail)


def sync_title_details(db: Session, title: Title, data: dict) -> None:
    """Copy the app-relevant typed facts from a raw TMDB details payload
    onto the shared Title row (single write path for these columns)."""
    title.overview = (data.get("overview") or "").strip()[:2000] or None
    title.tagline = (data.get("tagline") or "").strip()[:500] or None
    original = (data.get("original_title") or data.get("original_name") or "").strip()[:300]
    if original:
        title.original_title = original
    if data.get("poster_path"):
        title.poster_url = f"{POSTER_BASE}{data['poster_path']}"
    if data.get("backdrop_path"):
        title.backdrop_url = f"{BACKDROP_BASE}{data['backdrop_path']}"
    genres = [g["name"] for g in data.get("genres", []) if g.get("name")]
    if genres:
        title.genre_rows = resolve_genres(db, genres)

    if title.media_type == MediaType.film:
        release_date = data.get("release_date")
        title.year = _parse_year(release_date) or title.year
        title.runtime_minutes = data.get("runtime") or title.runtime_minutes
        title.release_date = _parse_date(release_date)
        return

    title.year = _parse_year(data.get("first_air_date")) or title.year
    run_times = data.get("episode_run_time") or []
    if run_times:
        title.runtime_minutes = round(sum(run_times) / len(run_times))
    elif (data.get("last_episode_to_air") or {}).get("runtime"):
        title.runtime_minutes = data["last_episode_to_air"]["runtime"]
    title.total_episodes = data.get("number_of_episodes") or title.total_episodes
    title.total_seasons = data.get("number_of_seasons") or title.total_seasons
    title.show_status = (data.get("status") or "").strip()[:30] or None
    # Cached here so /upcoming can read a tracked show's next-episode info
    # straight off the Title row instead of hitting TMDB per title per request.
    nxt = data.get("next_episode_to_air") or {}
    title.next_episode_air_date = _parse_date(nxt.get("air_date"))
    title.next_episode_season = nxt.get("season_number")
    title.next_episode_number = nxt.get("episode_number")
    title.next_episode_name = (nxt.get("name") or "").strip()[:300] or None


def store_details(db: Session, title: Title, data: dict) -> None:
    """Persist a raw details payload: cache row + typed Title columns."""
    upsert_cache(db, title.id, "details", NO_SEASON, data)
    sync_title_details(db, title, data)


def cached_tmdb(
    db: Session,
    media_type: MediaType,
    tmdb_id: int,
    kind: str,
    path: str,
    season: int = NO_SEASON,
    language: str = "en",
) -> dict:
    """Fetch a raw TMDB payload through the persistent cache.

    Fresh stored copy -> served without contacting TMDB. Stale or missing
    -> fetched (and persisted when the title is tracked). TMDB down ->
    stale copy if one exists, else the fetch error propagates.

    `language` is a separate cache dimension: only the "en" copy syncs the
    typed Title/Episode columns (see sync_title_details/sync_episodes) —
    those stay the single English source of truth other features read.
    """
    title = find_title(db, media_type, tmdb_id, None)
    row = None
    if title is not None:
        row = db.query(TmdbCache).filter_by(title_id=title.id, kind=kind, season=season, language=language).first()
        if row is not None and _is_fresh(row.fetched_at):
            return row.payload

    locale = TMDB_LOCALE.get(language)
    params = {"language": locale} if locale else None
    try:
        data = tmdb_get(path, params)
    except HTTPException as exc:
        if row is not None:
            _log.warning("TMDB unavailable (%s), serving stored copy of %s: %s", exc.detail, path, exc.status_code)
            return row.payload
        raise

    if title is not None:
        upsert_cache(db, title.id, kind, season, data, language=language)
        if kind == "details" and language == "en":
            sync_title_details(db, title, data)
        db.commit()
    return data


def sync_episodes(db: Session, title: Title, season_number: int, data: dict) -> None:
    """Upsert Episode rows from a raw TMDB season payload (single write
    path for the episodes table, mirroring sync_title_details)."""
    for e in data.get("episodes", []):
        episode_number = e.get("episode_number")
        if episode_number is None:
            continue
        name = (e.get("name") or "").strip()[:300] or None
        air_date = _parse_date(e.get("air_date"))
        row = (
            db.query(Episode).filter_by(title_id=title.id, season=season_number, episode_number=episode_number).first()
        )
        if row is not None:
            row.name = name
            row.air_date = air_date
        else:
            db.add(
                Episode(
                    title_id=title.id,
                    season=season_number,
                    episode_number=episode_number,
                    name=name,
                    air_date=air_date,
                )
            )


def sync_show_episodes(db: Session, title: Title) -> None:
    """Backfill/refresh the episodes table for one tracked show, one season
    at a time, through the same persistent TMDB cache season_tmdb() uses.

    A season already fully captured (its last known episode aired in the
    past) is skipped without contacting TMDB — only seasons that are new,
    unannounced, or still airing get fetched, so a show whose history is
    already synced costs nothing but a few indexed DB reads per request.
    """
    if title.tmdb_id is None or not title.total_seasons:
        return
    today = date.today()
    for season_number in range(1, title.total_seasons + 1):
        latest = (
            db.query(Episode)
            .filter_by(title_id=title.id, season=season_number)
            .order_by(Episode.episode_number.desc())
            .first()
        )
        if latest is not None and latest.air_date is not None and latest.air_date < today:
            continue
        try:
            data = cached_tmdb(
                db,
                title.media_type,
                title.tmdb_id,
                "season",
                f"/tv/{title.tmdb_id}/season/{season_number}",
                season=season_number,
            )
        except HTTPException as exc:
            _log.warning("episode sync skipped for title %s season %s: %s", title.id, season_number, exc.detail)
            continue
        sync_episodes(db, title, season_number, data)
    db.commit()


def refresh_title_details(db: Session, title: Title) -> None:
    """Best-effort details sync for a just-added library title: the client
    was on the detail page moments ago, so this is usually served from the
    in-memory TMDB cache. Failure only delays population, never the add."""
    if title.tmdb_id is None or title.media_type.value not in TMDB_KIND:
        return
    try:
        data = tmdb_get(f"/{TMDB_KIND[title.media_type.value]}/{title.tmdb_id}")
    except HTTPException as exc:
        _log.warning("details sync skipped for title %s (tmdb %s): %s", title.id, title.tmdb_id, exc.detail)
        return
    store_details(db, title, data)
