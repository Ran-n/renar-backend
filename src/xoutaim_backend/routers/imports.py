#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.146587
Revised: 2026/07/10 18:19:20.072333

Import a TV Time GDPR export zip: shows, episode history, movies, favorites.

The zip contains gdpr-data/*.csv. Relevant files:
  user_tv_show_data.csv        one row per show: name, TVDB id, favorite flag
  followed_tv_show.csv         active/archived flags per show
  user_show_special_status.csv 'for_later' watchlist entries
  tv_show_rate.csv             show ratings
  tracking-prod-records-v2.csv per-episode watch events (season/episode/date)
  tracking-prod-records.csv    movie follow/towatch/watch events

Shows are matched to TMDB via TVDB id (/find), movies via name+year search.
If the TVDB-id lookup misses (TMDB has no crosswalk entry for that id — common
even for well-known shows), and a TVDB_API_KEY is configured, we ask TheTVDB
for the show's name/aliases and retry a TMDB title search with each.
Runs in a background thread; progress is polled via GET /import/tvtime/status.
"""

import csv
import io
import logging
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import settings
from ..database import SessionLocal
from ..models import EpisodeWatch, LibraryEntry, MediaType, Title, User, WatchStatus, normalize_title_key
from ..titles import find_or_create_title, find_title
from ..tmdb_http import POSTER_BASE, tmdb_get

router = APIRouter(prefix="/import", tags=["import"])
_log = logging.getLogger(__name__)

# Matching a show/movie against TMDB is the slow part of an import (network
# round trips), so each row's match + insert runs as one worker task. Postgres
# handles the concurrent writes fine; the DB's unique constraints are the
# authority on dedupe races (see _upsert_library_entry).
MATCH_WORKERS = 8

_progress: dict[int, dict] = {}


def _set(user_id: int, **kw):
    _progress.setdefault(user_id, {}).update(kw)


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    for entry in zf.namelist():
        if entry.endswith(name):
            with zf.open(entry) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
                return list(csv.DictReader(text))
    return []


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _find_tv_by_tvdb(tvdb_id: str) -> dict | None:
    try:
        data = tmdb_get(f"/find/{tvdb_id}", {"external_source": "tvdb_id"})
        results = data.get("tv_results") or []
        return results[0] if results else None
    except Exception:
        _log.warning("TMDB /find lookup failed for tvdb_id=%s", tvdb_id, exc_info=True)
        return None


def _search_tv(name: str) -> dict | None:
    try:
        data = tmdb_get("/search/tv", {"query": name, "include_adult": "false"})
        results = data.get("results") or []
        return results[0] if results else None
    except Exception:
        _log.warning("TMDB tv search failed for %r", name, exc_info=True)
        return None


TVDB_BASE = "https://api4.thetvdb.com/v4"
_tvdb_http = httpx.Client(timeout=15)
_tvdb_token: str | None = None
_tvdb_token_expiry: float = 0.0


def _tvdb_login() -> str | None:
    """Log in to TheTVDB v4 API; tokens are valid ~1 month so we cache ours."""
    global _tvdb_token, _tvdb_token_expiry
    if not settings.tvdb_api_key:
        return None
    if _tvdb_token and _tvdb_token_expiry > time.time():
        return _tvdb_token
    try:
        resp = _tvdb_http.post(f"{TVDB_BASE}/login", json={"apikey": settings.tvdb_api_key})
        resp.raise_for_status()
        _tvdb_token = resp.json()["data"]["token"]
        _tvdb_token_expiry = time.time() + 20 * 24 * 3600
        return _tvdb_token
    except Exception:
        _log.warning("TheTVDB login failed", exc_info=True)
        return None


def _tvdb_series_names(tvdb_id: str) -> list[str]:
    """Candidate titles (primary name + aliases) for a TVDB series id."""
    token = _tvdb_login()
    if not token:
        return []
    try:
        resp = _tvdb_http.get(f"{TVDB_BASE}/series/{tvdb_id}", headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            return []
        data = resp.json().get("data") or {}
    except Exception:
        _log.warning("TheTVDB series lookup failed for tvdb_id=%s", tvdb_id, exc_info=True)
        return []
    names = [data["name"]] if data.get("name") else []
    for alias in data.get("aliases") or []:
        name = alias.get("name") if isinstance(alias, dict) else alias
        if name and name not in names:
            names.append(name)
    return names[:5]


def _find_tv_via_tvdb_fallback(tvdb_id: str) -> dict | None:
    for candidate in _tvdb_series_names(tvdb_id):
        found = _search_tv(candidate)
        if found:
            return found
    return None


def _match_show(tvdb_id: str, name: str) -> tuple[dict | None, dict]:
    """Resolve one show to TMDB and fetch its details. Network-only, no DB access."""
    if not name:
        return None, {}
    found = _find_tv_by_tvdb(tvdb_id) or _find_tv_via_tvdb_fallback(tvdb_id)
    details: dict = {}
    if found:
        tmdb_id = found["id"]
        try:
            raw = tmdb_get(f"/tv/{tmdb_id}")
            run_times = raw.get("episode_run_time") or []
            details = {
                "runtime_minutes": round(sum(run_times) / len(run_times))
                if run_times
                else (raw.get("last_episode_to_air") or {}).get("runtime"),
                "total_episodes": raw.get("number_of_episodes"),
                "genres": [g["name"] for g in raw.get("genres", [])],
                "poster_url": f"{POSTER_BASE}{raw['poster_path']}" if raw.get("poster_path") else None,
            }
        except Exception:
            _log.warning("TMDB details fetch failed for tmdb_id=%s", tmdb_id, exc_info=True)
            details = {}
    return found, details


def _search_movie(name: str, year: str | None) -> dict | None:
    try:
        params = {"query": name, "include_adult": "false"}
        if year:
            params["primary_release_year"] = year
        data = tmdb_get("/search/movie", params)
        results = data.get("results") or []
        if not results and year:  # retry without the year constraint
            data = tmdb_get("/search/movie", {"query": name, "include_adult": "false"})
            results = data.get("results") or []
        return results[0] if results else None
    except Exception:
        _log.warning("TMDB movie search failed for %r", name, exc_info=True)
        return None


def _reconcile_show_entry(entry: LibraryEntry, incoming: dict) -> bool:
    """Merge import data into a show the user already tracks. Returns whether
    anything actually changed.

    Status is intentionally left untouched here: TV Time's followed/archived
    flags are a weak guess next to whatever the user already set, and could
    wrongly downgrade e.g. a manually-set "watching" to "want_to_watch". The
    one legitimate status upgrade — all episodes now watched -> completed —
    is derived from actual episode counts after history is merged, below.
    """
    changed = False
    if incoming.get("is_favorite") and not entry.is_favorite:
        entry.is_favorite = True
        changed = True
    if entry.rating is None and incoming.get("rating") is not None:
        entry.rating = incoming["rating"]
        changed = True
    return changed


def _reconcile_movie_entry(entry: LibraryEntry, incoming: dict) -> bool:
    """Merge import data into a movie the user already tracks. Returns
    whether anything actually changed.

    "watched" from TV Time is a fact, not a guess, so it's allowed to
    upgrade status forward — but never downgrade an already-completed entry.
    """
    if incoming.get("status") == WatchStatus.completed and entry.status != WatchStatus.completed:
        entry.status = WatchStatus.completed
        return True
    return False


def _upsert_library_entry(
    user_id: int,
    media_type: MediaType,
    tmdb_id: int | None,
    title: str,
    title_meta: dict,
    entry_fields: dict,
    title_key: tuple,
    tmdb_key: tuple | None,
    existing_map: dict,
    reconcile,
) -> tuple[int | None, bool, bool]:
    """Insert or reconcile one LibraryEntry, on its own session.

    `existing_map` holds the identities the user already tracked *before*
    this import started, mapped to their entry id — those get merged via
    `reconcile` instead of skipped, so e.g. a newly-watched season on a show
    already in the library still gets its episode history imported. It's
    read-only after being built, so no locking is needed to consult it.

    Two rows *within this run* can still resolve to the same brand-new
    title; rather than reserve identities up front (and drop the loser),
    both are allowed to race the insert and the DB's unique constraint
    (uq_user_title) picks the winner — the loser catches the IntegrityError,
    looks up what the winner just created, and reconciles into that instead
    of losing its data.

    Returns (item_id, is_new, changed).
    """
    item_id = existing_map.get(tmdb_key) if tmdb_key else None
    if item_id is None:
        item_id = existing_map.get(title_key)
    is_new = item_id is None

    db = SessionLocal()
    try:
        if is_new:
            db_title = find_or_create_title(db, media_type, tmdb_id, title, **title_meta)
            entry = LibraryEntry(user_id=user_id, title_id=db_title.id, **entry_fields)
            db.add(entry)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                winner_title = find_title(db, media_type, tmdb_id, title)
                winner = (
                    db.query(LibraryEntry).filter_by(user_id=user_id, title_id=winner_title.id).first()
                    if winner_title
                    else None
                )
                if winner is None:
                    return None, False, False
                changed = reconcile(winner, entry_fields)
                db.commit()
                return winner.id, False, changed
            db.refresh(entry)
            return entry.id, True, False
        entry = db.get(LibraryEntry, item_id)
        if entry is None:
            return None, False, False
        changed = reconcile(entry, entry_fields)
        db.commit()
        return item_id, False, changed
    except Exception:
        db.rollback()
        _log.warning("Upsert failed for %r (user_id=%s)", title, user_id, exc_info=True)
        return None, is_new, False
    finally:
        db.close()


def _process_show(
    user_id: int,
    row: dict,
    followed: dict,
    for_later: set,
    rates: dict,
    existing_map: dict,
) -> tuple[str, int | None, str | None, bool, bool] | None:
    """Match one show row against TMDB and insert it. Runs in a worker thread."""
    tvdb_id = row.get("tv_show_id") or ""
    name = (row.get("tv_show_name") or "").strip()
    if not name:
        return None

    f = followed.get(tvdb_id, {})
    if tvdb_id in for_later:
        st = WatchStatus.want_to_watch
    elif f.get("archived") == "1":
        st = WatchStatus.dropped
    else:
        st = WatchStatus.watching

    found, details = _match_show(tvdb_id, name)
    tmdb_id = found["id"] if found else None
    final_title = (found["name"] if found else name).strip()
    unmatched = name if not found else None

    rating = None
    rate_row = rates.get(tvdb_id)
    if rate_row and (rate_row.get("rating") or "").isdigit():
        raw_rating = int(rate_row["rating"])
        rating = min(10, raw_rating * 2 if raw_rating <= 5 else raw_rating)

    title_meta = {
        "poster_url": details.get("poster_url"),
        "runtime_minutes": details.get("runtime_minutes"),
        "total_episodes": details.get("total_episodes"),
        "genres": details.get("genres"),
        "year": None,
    }
    entry_fields = {
        "status": st,
        "is_favorite": row.get("is_favorited") == "1",
        "rating": rating,
    }
    # dedupe on BOTH the resolved tmdb id and the final canonical title —
    # different TVDB entries can resolve to the same TMDB show
    title_key = ("tv_show", normalize_title_key(final_title))
    tmdb_key = ("tv_show", tmdb_id) if tmdb_id else None
    item_id, is_new, changed = _upsert_library_entry(
        user_id,
        MediaType.tv_show,
        tmdb_id,
        final_title,
        title_meta,
        entry_fields,
        title_key,
        tmdb_key,
        existing_map,
        _reconcile_show_entry,
    )
    return tvdb_id, item_id, unmatched, is_new, changed


def _process_movie(
    user_id: int,
    name: str,
    m: dict,
    existing_map: dict,
) -> tuple[int | None, str | None, bool, bool]:
    """Match one movie against TMDB and insert it. Runs in a worker thread."""
    found = _search_movie(name, m["year"])
    tmdb_id = found["id"] if found else None
    final_title = ((found or {}).get("title") or name).strip()
    unmatched = name if not found else None
    release = (found or {}).get("release_date") or ""
    title_meta = {
        "year": int(release[:4]) if release[:4].isdigit() else (int(m["year"]) if m["year"] else None),
        "runtime_minutes": m["runtime"],
        "poster_url": f"{POSTER_BASE}{found['poster_path']}" if found and found.get("poster_path") else None,
    }
    entry_fields = {
        "status": WatchStatus.completed if m["watched"] else WatchStatus.want_to_watch,
    }
    title_key = ("film", normalize_title_key(final_title))
    tmdb_key = ("film", tmdb_id) if tmdb_id else None
    item_id, is_new, changed = _upsert_library_entry(
        user_id,
        MediaType.film,
        tmdb_id,
        final_title,
        title_meta,
        entry_fields,
        title_key,
        tmdb_key,
        existing_map,
        _reconcile_movie_entry,
    )
    return item_id, unmatched, is_new, changed


def _run_import(user_id: int, zip_bytes: bytes):
    db: Session = SessionLocal()
    summary = {"shows": 0, "updated": 0, "episodes": 0, "movies": 0, "skipped": 0, "unmatched": []}
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

        show_rows = _read_csv(zf, "user_tv_show_data.csv")
        followed = {r["tv_show_id"]: r for r in _read_csv(zf, "followed_tv_show.csv")}
        for_later = {
            r["tv_show_id"] for r in _read_csv(zf, "user_show_special_status.csv") if r.get("status") == "for_later"
        }
        rates = {r["tv_show_id"]: r for r in _read_csv(zf, "tv_show_rate.csv")}
        episode_events = _read_csv(zf, "tracking-prod-records-v2.csv")
        movie_events = _read_csv(zf, "tracking-prod-records.csv")

        user_rows = (
            db.query(LibraryEntry.id, Title)
            .join(Title, LibraryEntry.title_id == Title.id)
            .filter(LibraryEntry.user_id == user_id)
            .all()
        )
        # Identity (media_type, tmdb_id-or-title_key) -> the user's existing
        # entry id, for titles already tracked before this import started.
        # _upsert_library_entry merges into these instead of skipping them,
        # so e.g. a new season on an already-tracked show still gets imported.
        existing_map: dict = {}
        for entry_id, t in user_rows:
            if t.tmdb_id:
                existing_map[(t.media_type.value, t.tmdb_id)] = entry_id
            existing_map[(t.media_type.value, t.title_key or normalize_title_key(t.title))] = entry_id

        # ---------- shows ----------
        # Each row is matched against TMDB and inserted/reconciled (own session)
        # inside one worker call, so both the network round trip and the write
        # happen in parallel. Bucketing into shows/updated/skipped is deferred
        # until after episode history is merged below, since a show reconciled
        # here with no favorite/rating change can still gain a new season's
        # worth of episodes in the next step.
        _set(user_id, stage="Matching shows", done=0, total=len(show_rows))
        items_by_tvdb: dict[str, int] = {}
        show_results: list[tuple[str, int, bool, bool]] = []
        done = 0
        with ThreadPoolExecutor(max_workers=MATCH_WORKERS) as pool:
            futures = [
                pool.submit(_process_show, user_id, row, followed, for_later, rates, existing_map) for row in show_rows
            ]
            for fut in as_completed(futures):
                done += 1
                _set(user_id, done=done)
                result = fut.result()
                if result is None:
                    continue
                tvdb_id, item_id, unmatched, is_new, changed = result
                if item_id is not None:
                    items_by_tvdb[tvdb_id] = item_id
                    show_results.append((tvdb_id, item_id, is_new, changed))
                else:
                    summary["skipped"] += 1
                if unmatched:
                    summary["unmatched"].append(unmatched)

        # ---------- per-episode history ----------
        # Seed with episodes already on record (whether from a manual mark or
        # a prior import) so merging into an existing show's history doesn't
        # try to re-insert them and trip the uq_item_episode constraint.
        _set(user_id, stage="Importing episode history", done=0, total=len(episode_events))
        seen: set[tuple] = set(
            db.query(EpisodeWatch.media_item_id, EpisodeWatch.season, EpisodeWatch.episode)
            .filter(EpisodeWatch.media_item_id.in_(items_by_tvdb.values()))
            .all()
        )
        touched_items: set[int] = set()
        for n, ev in enumerate(episode_events, 1):
            if n % 500 == 0:
                _set(user_id, done=n)
                db.commit()
            item_id = items_by_tvdb.get(ev.get("s_id") or "")
            s_no, ep_no = ev.get("s_no"), ev.get("ep_no")
            if not item_id or not s_no or not ep_no:
                continue
            try:
                season, episode = int(s_no), int(ep_no)
            except ValueError:
                continue
            key = (item_id, season, episode)
            if key in seen:
                continue
            seen.add(key)
            db.add(
                EpisodeWatch(
                    media_item_id=item_id,
                    season=season,
                    episode=episode,
                    watched_at=_parse_dt(ev.get("created_at")) or datetime.now(UTC),
                )
            )
            touched_items.add(item_id)
            summary["episodes"] += 1
        db.commit()

        for _tvdb_id, item_id, is_new, changed in show_results:
            if is_new:
                summary["shows"] += 1
            elif changed or item_id in touched_items:
                summary["updated"] += 1
            else:
                summary["skipped"] += 1

        # sync counters + auto-status per show
        for item_id in items_by_tvdb.values():
            watches = db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item_id).all()
            if not watches:
                continue
            item = db.get(LibraryEntry, item_id)
            item.episodes_watched = len(watches)
            last = max(watches, key=lambda w: (w.season, w.episode))
            item.current_season, item.current_episode = last.season, last.episode
            # "dropped"/"paused" are deliberate calls the user made; reaching
            # 100% watched shouldn't silently override them.
            if (
                item.total_episodes
                and item.episodes_watched >= item.total_episodes
                and item.status not in (WatchStatus.dropped, WatchStatus.paused)
            ):
                item.status = WatchStatus.completed
        db.commit()

        # ---------- movies ----------
        movies: dict[str, dict] = {}
        for ev in movie_events:
            name = (ev.get("movie_name") or "").strip()
            if not name:
                continue
            m = movies.setdefault(name, {"watched": False, "runtime": None, "year": None, "watched_at": None})
            if ev.get("type") in ("watch", "rewatch"):
                m["watched"] = True
                m["watched_at"] = m["watched_at"] or _parse_dt(ev.get("created_at"))
            runtime = ev.get("runtime")
            if runtime and runtime.isdigit() and int(runtime) > 0:
                m["runtime"] = round(int(runtime) / 60)  # seconds -> minutes
            release = ev.get("release_date") or ""
            if len(release) >= 4 and release[:4].isdigit():
                m["year"] = release[:4]

        _set(user_id, stage="Matching movies", done=0, total=len(movies))
        done = 0
        with ThreadPoolExecutor(max_workers=MATCH_WORKERS) as pool:
            futures = []
            for name, m in movies.items():
                # A movie already tracked under this exact name that TV Time
                # doesn't report as watched has nothing to reconcile (only
                # "watched" ever changes an existing entry) — skip the TMDB
                # search entirely rather than re-matching every re-run.
                if not m["watched"] and ("film", normalize_title_key(name)) in existing_map:
                    done += 1
                    summary["skipped"] += 1
                    _set(user_id, done=done)
                    continue
                futures.append(pool.submit(_process_movie, user_id, name, m, existing_map))
            for fut in as_completed(futures):
                done += 1
                _set(user_id, done=done)
                item_id, unmatched, is_new, changed = fut.result()
                if item_id is not None:
                    if is_new:
                        summary["movies"] += 1
                    elif changed:
                        summary["updated"] += 1
                    else:
                        summary["skipped"] += 1
                else:
                    summary["skipped"] += 1
                if unmatched:
                    summary["unmatched"].append(unmatched)

        summary["unmatched"] = summary["unmatched"][:20]
        _set(user_id, stage="Done", finished=True, summary=summary, error=None)
        _log.info(
            "TV Time import finished for user_id=%s: %s shows, %s episodes, %s movies, %s updated, %s skipped, "
            "%s unmatched",
            user_id,
            summary["shows"],
            summary["episodes"],
            summary["movies"],
            summary["updated"],
            summary["skipped"],
            len(summary["unmatched"]),
        )
    except Exception as exc:
        db.rollback()
        _log.exception("TV Time import failed for user_id=%s", user_id)
        _set(user_id, stage="Failed", finished=True, error=str(exc), summary=summary)
    finally:
        db.close()


@router.post("/tvtime", status_code=status.HTTP_202_ACCEPTED)
async def import_tvtime(
    file: UploadFile,
    user: User = Depends(get_current_user),
):
    running = _progress.get(user.id)
    if running and not running.get("finished", True):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An import is already running")
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File too large")
    try:
        zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="That is not a zip file") from exc
    _progress[user.id] = {"stage": "Starting", "done": 0, "total": 0, "finished": False, "error": None, "summary": None}
    threading.Thread(target=_run_import, args=(user.id, data), daemon=True).start()
    return {"status": "started"}


@router.get("/tvtime/status")
def import_status(user: User = Depends(get_current_user)):
    return _progress.get(user.id) or {
        "stage": "Never run",
        "finished": True,
        "error": None,
        "summary": None,
        "done": 0,
        "total": 0,
    }
