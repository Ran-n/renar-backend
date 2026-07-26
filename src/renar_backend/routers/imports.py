#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.146587
Revised: 2026/07/21 09:51:03.798227

Import a TV Time GDPR export zip: shows, episode history, movies, favorites.

The zip contains gdpr-data/*.csv. Relevant files:
  user_tv_show_data.csv        one row per show: name, TVDB id, favorite flag
  followed_tv_show.csv         active/archived flags per show
  user_show_special_status.csv 'for_later' watchlist entries
  tv_show_rate.csv             show ratings
  tracking-prod-records-v2.csv per-episode watch events (season/episode/date)
  tracking-prod-records.csv    movie follow/towatch/watch events
  show_comment.csv             this user's own show-level comments
  episode_comment.csv          this user's own episode-level comments
  comments-prod-comments.csv   this user's own movie comments (type=comment/reply rows only)
  rewatched_episode.csv        per-episode rewatch counts ("cpt")

Shows are matched to TMDB via TVDB id (/find), movies via name+year search.
If the TVDB-id lookup misses (TMDB has no crosswalk entry for that id — common
even for well-known shows) and a TVDB_API_KEY is configured, we ask TheTVDB
for the show's name/aliases and retry a TMDB title search with each; if that
still comes up empty (or no TVDB_API_KEY is set), we fall back to a plain
TMDB title search on the name TV Time gave us.
Runs in a background thread; progress is polled via GET /import/tvtime/status.
"""

import csv
import difflib
import io
import logging
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog.titles import backfill_title_tmdb_id, find_or_create_title, find_title
from ..config import settings
from ..database import SessionLocal
from ..models import (
    Comment,
    EpisodeWatch,
    ImportJob,
    LibraryEntry,
    MediaType,
    Title,
    User,
    WatchEvent,
    WatchStatus,
    normalize_title_key,
)
from ..tmdb.tmdb_http import POSTER_BASE, tmdb_get
from ..users.auth import get_current_user

router = APIRouter(prefix="/import", tags=["import"])
_log = logging.getLogger(__name__)

# Matching a show/movie against TMDB is the slow part of an import (network
# round trips), so each row's match + insert runs as one worker task. Postgres
# handles the concurrent writes fine; the DB's unique constraints are the
# authority on dedupe races (see _upsert_library_entry).
MATCH_WORKERS = 8

# Each upload is read fully into memory (up to 200 MB, see import_tvtime) and
# then processed on its own thread — with no cap, N users importing at once
# could each hold ~200 MB simultaneously. This bounds concurrent imports
# process-wide; anyone past the cap gets a 429 and can retry shortly instead
# of piling onto memory.
MAX_CONCURRENT_IMPORTS = 3
_import_slots = threading.Semaphore(MAX_CONCURRENT_IMPORTS)

_progress: dict[int, dict] = {}


def _set(user_id: int, **kw):
    _progress.setdefault(user_id, {}).update(kw)


def _mark_job(user_id: int, *, finished: bool, error: str | None = None, summary: dict | None = None) -> None:
    """Upsert the durable ImportJob row so a status poll after a server
    restart (which wipes _progress) can tell "job was interrupted" apart
    from "never ran". Called only at job start and at completion/failure —
    see ImportJob's docstring in models.py.
    """
    db = SessionLocal()
    try:
        job = db.get(ImportJob, user_id)
        if job is None:
            job = ImportJob(user_id=user_id)
            db.add(job)
        job.finished = finished
        job.error = error
        job.summary = summary
        db.commit()
    except Exception:
        db.rollback()
        _log.warning("Failed to persist import job state for user_id=%s", user_id, exc_info=True)
    finally:
        db.close()


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


# TV Time disambiguates same-named shows by appending a trailing year, either
# bare ("Shogun 1980") or parenthesized ("Shogun (1980)") — TMDB's /search/tv
# matches on title text, so a literal year suffix in the query routinely
# returns zero results even though the show exists under its plain title.
_TRAILING_YEAR_RE = re.compile(r"^(?P<base>.+\S)\s*\(?(?P<year>19\d{2}|20\d{2})\)?$")


def _split_trailing_year(name: str) -> tuple[str, str | None]:
    m = _TRAILING_YEAR_RE.match(name.strip())
    if not m:
        return name, None
    return m.group("base").strip(), m.group("year")


# CJK scripts have no real word-boundary spaces of their own — a stray space
# introduced by the export (observed on Japanese titles, e.g. TV Time's
# "ドラゴンボール超スーパー ヒーロー" vs TMDB's "ドラゴンボール超 スーパーヒーロー")
# is enough to turn an otherwise-correct query into zero results, since TMDB's
# search tokenizes on whitespace. Only applied when CJK characters are
# present — stripping spaces from a Latin title would just break it further.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")


def _cjk_space_stripped(name: str) -> str | None:
    if " " in name and _CJK_RE.search(name):
        return name.replace(" ", "")
    return None


# Last-resort fallback for near-miss export data — a typo or a wrong-script
# letter substitution (e.g. TV Time exporting "طعم كيلاس" for what TMDB
# stores as "طعم گيلاس", or "O Corpo Oberto" for "O Corpo Aberto") — that
# TMDB's own search won't surface at all under the exact string, since it
# does no fuzzy matching server-side. Dropping the last word broadens the
# query enough to surface a candidate pool; a high similarity threshold on
# the result is what keeps this from silently attaching the wrong title to
# someone's library — a bad guess here is worse than leaving it unmatched.
_FUZZY_THRESHOLD = 0.8
_FUZZY_MAX_TRIMS = 2


def _fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.strip().casefold(), b.strip().casefold()).ratio()


def _fuzzy_search(name: str, kind: str) -> dict | None:
    query = name
    candidates: dict[int, dict] = {}
    for _ in range(_FUZZY_MAX_TRIMS):
        query, _, last_word = query.rpartition(" ")
        if not query or not last_word or len(query) < 3:
            break
        try:
            data = tmdb_get(f"/search/{kind}", {"query": query, "include_adult": "false"})
        except Exception:
            _log.warning("TMDB fuzzy %s search failed for %r", kind, query, exc_info=True)
            continue
        for r in data.get("results") or []:
            candidates[r["id"]] = r

    if not candidates:
        return None

    title_field = "title" if kind == "movie" else "name"
    orig_field = "original_title" if kind == "movie" else "original_name"
    best, best_score = None, 0.0
    for r in candidates.values():
        score = max(_fuzzy_ratio(name, r.get(title_field) or ""), _fuzzy_ratio(name, r.get(orig_field) or ""))
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= _FUZZY_THRESHOLD else None


def _search_tv(name: str) -> dict | None:
    base_name, year = _split_trailing_year(name)
    try:
        params = {"query": base_name, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        data = tmdb_get("/search/tv", params)
        results = data.get("results") or []
        if not results and year:  # retry without the year constraint
            data = tmdb_get("/search/tv", {"query": base_name, "include_adult": "false"})
            results = data.get("results") or []
        if not results and base_name != name:  # last resort: the verbatim query
            data = tmdb_get("/search/tv", {"query": name, "include_adult": "false"})
            results = data.get("results") or []
        stripped = _cjk_space_stripped(name)
        if not results and stripped:
            data = tmdb_get("/search/tv", {"query": stripped, "include_adult": "false"})
            results = data.get("results") or []
        if results:
            return results[0]
        return _fuzzy_search(name, "tv")
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
    found = _find_tv_by_tvdb(tvdb_id) or _find_tv_via_tvdb_fallback(tvdb_id) or _search_tv(name)
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


def _search_movie(name: str, year: str | None) -> tuple[dict | None, bool]:
    """Returns (result, is_tv). TV Time sometimes logs an item as a movie
    whose TMDB entry is actually a TV show (observed with short-form/
    streaming-original series, e.g. "Die Hart 2: Die Harter") — a plain
    movie search finds nothing for those, so once the movie-side retries are
    exhausted we also try `_search_tv`, which already tries harder
    (year-splitting, CJK-space retry) than duplicating that logic here.
    """
    try:
        params = {"query": name, "include_adult": "false"}
        if year:
            params["primary_release_year"] = year
        data = tmdb_get("/search/movie", params)
        results = data.get("results") or []
        if not results and year:  # retry without the year constraint
            data = tmdb_get("/search/movie", {"query": name, "include_adult": "false"})
            results = data.get("results") or []
        stripped = _cjk_space_stripped(name)
        if not results and stripped:
            data = tmdb_get("/search/movie", {"query": stripped, "include_adult": "false"})
            results = data.get("results") or []
        if results:
            return results[0], False
    except Exception:
        _log.warning("TMDB movie search failed for %r", name, exc_info=True)
        return None, False
    tv_found = _search_tv(name)  # already tries its own fuzzy fallback internally
    if tv_found:
        return tv_found, True
    fuzzy_found = _fuzzy_search(name, "movie")
    return (fuzzy_found, False) if fuzzy_found else (None, False)


# TV Time has no season/episode concept for one-off specials and OVAs, so it
# logs them as a standalone item instead of folding them into the parent
# show's episode history — title search then fails outright, since neither a
# show nor a movie by that exact name exists on TMDB; it only exists as one
# specific episode of a show. TV Time uses more than one naming convention
# for this, so several splits are tried, broadest/most reliable first:
#   "進撃の巨人 - Wall Sina, Goodbye 前編"        (Attack on Titan S0E17)
#   "Thus Spoke Kishibe Rohan 2: Mutsu-kabe Hill" (a franchise-entry ordinal
#                                                   on the show side, S1E2)
# A wrong split just fails to resolve a show, or resolves one whose episode
# list doesn't contain the episode part, and falls through safely either way
# — see _match_episode_in_pool's containment check and similarity floor.
def _show_episode_splits(name: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if " - " in name:
        show_part, _, episode_part = name.partition(" - ")
        candidates.append((show_part.strip(), episode_part.strip()))
    if ": " in name:
        show_part, _, episode_part = name.rpartition(": ")
        show_part, episode_part = show_part.strip(), episode_part.strip()
        if show_part and episode_part:
            candidates.append((show_part, episode_part))
            trimmed = re.sub(r"\s+\d{1,2}$", "", show_part)
            if trimmed != show_part:
                candidates.append((trimmed, episode_part))
    return [(s, e) for s, e in candidates if s and e]


def _show_episode_pool(tmdb_id: int) -> list[dict]:
    """Every episode of a show, season 0 (specials) included, as {season,
    episode, name} — the only way to check whether a name is one specific
    episode, since TMDB has no "search episodes by name" endpoint.
    """
    episodes: list[dict] = []
    try:
        show = tmdb_get(f"/tv/{tmdb_id}")
    except Exception:
        _log.warning("TMDB show fetch failed for tmdb_id=%s", tmdb_id, exc_info=True)
        return episodes
    for s in show.get("seasons") or []:
        season_number = s.get("season_number")
        if season_number is None:
            continue
        try:
            season = tmdb_get(f"/tv/{tmdb_id}/season/{season_number}")
        except Exception:
            _log.warning("TMDB season fetch failed for tmdb_id=%s season=%s", tmdb_id, season_number, exc_info=True)
            continue
        for ep in season.get("episodes") or []:
            episodes.append({
                "season": season_number,
                "episode": ep.get("episode_number"),
                "name": ep.get("name") or "",
            })
    return episodes


_EPISODE_DECORATION_RE = re.compile(r"[(（][^)）]*[)）]|[前後]編\s*$")
_EPISODE_THRESHOLD = 0.75


def _episode_core(name: str) -> str:
    """Strip parenthetical part-numbers ("(1)") and the Japanese part-marker
    suffixes ("前編"/"後編", "part 1"/"part 2") that differ between how TV
    Time names a special and how TMDB's episode list does — leaving just the
    part likely to appear, verbatim, inside the other string.
    """
    return _EPISODE_DECORATION_RE.sub("", name).strip().casefold()


def _episode_similarity(episode_part: str, candidate_name: str) -> float:
    """A resolved show's own episode named "Lost Girls: Wall Sina, Goodbye
    (1)" is a superset of the export's plainer "Wall Sina, Goodbye 前編", not
    a near-identical string — so containment of one's decoration-stripped
    core in the other is a stronger, and here safer, signal than raw
    character-sequence similarity: a wrong pick only misfiles one episode of
    a show already anchored by an earlier exact match, not a whole extra
    title.
    """
    a, b = episode_part.strip().casefold(), candidate_name.strip().casefold()
    if not a or not b:
        return 0.0
    core_a, core_b = _episode_core(a), _episode_core(b)
    if (core_a and core_a in b) or (core_b and core_b in a):
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


def _match_episode_in_pool(episode_part: str, pool: list[dict]) -> dict | None:
    best, best_score = None, 0.0
    for ep in pool:
        score = _episode_similarity(episode_part, ep["name"])
        if score > best_score:
            best, best_score = ep, score
    return best if best is not None and best_score >= _EPISODE_THRESHOLD and best["episode"] is not None else None


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
) -> tuple[int | None, bool, bool, bool, bool]:
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

    Returns (item_id, is_new, changed, error, duplicate_in_run). `error` is
    only True when the row failed for an infra reason (DB hiccup, unexpected
    exception) — the caller counts that separately from a normal dedupe
    skip. `duplicate_in_run` is True only for the race loser above: the
    identity wasn't in `existing_map` (so nothing pre-existed for this user
    before the import started), it just lost a same-run race to a sibling
    row for the same title — the caller must not count that as "already in
    your library", since on a brand-new account nothing could be.
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
                    return None, False, False, False, False
                if tmdb_id is not None and winner_title is not None:
                    backfill_title_tmdb_id(
                        db,
                        winner_title,
                        tmdb_id,
                        poster_url=title_meta.get("poster_url"),
                        runtime_minutes=title_meta.get("runtime_minutes"),
                        total_episodes=title_meta.get("total_episodes"),
                    )
                changed = reconcile(winner, entry_fields)
                db.commit()
                return winner.id, False, changed, False, True
            db.refresh(entry)
            return entry.id, True, False, False, False
        entry = db.get(LibraryEntry, item_id)
        if entry is None:
            return None, False, False, False, False
        if tmdb_id is not None:
            title_row = db.get(Title, entry.title_id)
            if title_row is not None:
                backfill_title_tmdb_id(
                    db,
                    title_row,
                    tmdb_id,
                    poster_url=title_meta.get("poster_url"),
                    runtime_minutes=title_meta.get("runtime_minutes"),
                    total_episodes=title_meta.get("total_episodes"),
                )
        changed = reconcile(entry, entry_fields)
        db.commit()
        return item_id, False, changed, False, False
    except Exception:
        db.rollback()
        _log.warning("Upsert failed for %r (user_id=%s)", title, user_id, exc_info=True)
        return None, is_new, False, True, False
    finally:
        db.close()


def _process_show(
    user_id: int,
    row: dict,
    followed: dict,
    for_later: set,
    rates: dict,
    existing_map: dict,
) -> tuple[str, int | None, str | None, bool, bool, bool, bool] | None:
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
    item_id, is_new, changed, error, duplicate_in_run = _upsert_library_entry(
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
    return tvdb_id, item_id, unmatched, is_new, changed, error, duplicate_in_run


def _process_movie(
    user_id: int,
    name: str,
    m: dict,
    existing_map: dict,
) -> tuple[int | None, str | None, bool, bool, bool, bool]:
    """Match one movie against TMDB and insert it. Runs in a worker thread."""
    found, is_tv = _search_movie(name, m["year"])
    tmdb_id = found["id"] if found else None
    # A TV fallback match uses "name"/"first_air_date" instead of the movie
    # fields; recorded as a tv_show entry so its library card/poster/genres
    # come from the right TMDB endpoint, not a nonexistent movie one.
    final_title = ((found or {}).get("title" if not is_tv else "name") or name).strip()
    unmatched = name if not found else None
    release = (found or {}).get("release_date" if not is_tv else "first_air_date") or ""
    title_meta = {
        "year": int(release[:4]) if release[:4].isdigit() else (int(m["year"]) if m["year"] else None),
        "runtime_minutes": m["runtime"],
        "poster_url": f"{POSTER_BASE}{found['poster_path']}" if found and found.get("poster_path") else None,
    }
    entry_fields = {
        "status": WatchStatus.completed if m["watched"] else WatchStatus.want_to_watch,
    }
    media_type = MediaType.tv_show if is_tv else MediaType.film
    key_kind = "tv_show" if is_tv else "film"
    title_key = (key_kind, normalize_title_key(final_title))
    tmdb_key = (key_kind, tmdb_id) if tmdb_id else None
    item_id, is_new, changed, error, duplicate_in_run = _upsert_library_entry(
        user_id,
        media_type,
        tmdb_id,
        final_title,
        title_meta,
        entry_fields,
        title_key,
        tmdb_key,
        existing_map,
        _reconcile_movie_entry,
    )
    return item_id, unmatched, is_new, changed, error, duplicate_in_run


def _run_import(user_id: int, zip_bytes: bytes):
    db: Session = SessionLocal()
    summary = {
        "shows": 0,
        "updated": 0,
        "episodes": 0,
        "movies": 0,
        "comments": 0,
        "comments_skipped": 0,
        "rewatches": 0,
        "rewatches_skipped": 0,
        "skipped": 0,
        "errors": 0,
        "unmatched": [],
    }
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
        show_results: list[tuple[str, int, bool, bool, bool]] = []
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
                tvdb_id, item_id, unmatched, is_new, changed, error, duplicate_in_run = result
                if item_id is not None:
                    items_by_tvdb[tvdb_id] = item_id
                    show_results.append((tvdb_id, item_id, is_new, changed, duplicate_in_run))
                elif error:
                    summary["errors"] += 1
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

        for _tvdb_id, item_id, is_new, changed, duplicate_in_run in show_results:
            if is_new:
                summary["shows"] += 1
            elif duplicate_in_run:
                # This row lost a same-run race to a sibling that resolved to
                # the same identity — that sibling already put this item_id
                # in exactly one bucket above (new, or updated via touching
                # episodes). Counting it again here — even as "updated",
                # since the same touched_items membership would otherwise
                # qualify it — would double-count one imported title as two.
                continue
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

        # name (normalized) -> item id, for every movie touched this run
        # (matched fresh or reconciled) — lets movie comments below attach
        # without re-resolving each title a second time.
        items_by_movie: dict[str, int] = {}

        _set(user_id, stage="Matching movies", done=0, total=len(movies))
        done = 0
        with ThreadPoolExecutor(max_workers=MATCH_WORKERS) as pool:
            fut_to_name: dict = {}
            for name, m in movies.items():
                # A movie already tracked under this exact name that TV Time
                # doesn't report as watched has nothing to reconcile (only
                # "watched" ever changes an existing entry) — skip the TMDB
                # search entirely rather than re-matching every re-run.
                existing_id = existing_map.get(("film", normalize_title_key(name)))
                if not m["watched"] and existing_id is not None:
                    items_by_movie[normalize_title_key(name)] = existing_id
                    done += 1
                    summary["skipped"] += 1
                    _set(user_id, done=done)
                    continue
                fut_to_name[pool.submit(_process_movie, user_id, name, m, existing_map)] = name
            for fut in as_completed(fut_to_name):
                done += 1
                _set(user_id, done=done)
                item_id, unmatched, is_new, changed, error, duplicate_in_run = fut.result()
                if item_id is not None:
                    items_by_movie[normalize_title_key(fut_to_name[fut])] = item_id
                    if is_new:
                        summary["movies"] += 1
                    elif duplicate_in_run:
                        pass  # already counted once by the sibling that won the insert race
                    elif changed:
                        summary["updated"] += 1
                    else:
                        summary["skipped"] += 1
                elif error:
                    summary["errors"] += 1
                else:
                    summary["skipped"] += 1
                if unmatched:
                    summary["unmatched"].append(unmatched)

        # ---------- one-off special/OVA fallback ----------
        # Anything still unmatched gets one more look: if it splits into a
        # show name and an episode name (see _show_episode_splits), the show
        # resolves, and that show actually has an episode with that name
        # (specials included), it's really a watch on that show, not a
        # missing title. Several candidate splits are tried per name since
        # TV Time doesn't use one consistent naming convention for these.
        still_unmatched: list[str] = []
        season_cache: dict[int, list[dict]] = {}
        touched_by_fallback: set[int] = set()
        for name in summary["unmatched"]:
            show_found = None
            episode = None
            show_part = None
            for candidate_show, candidate_episode in _show_episode_splits(name):
                found = _search_tv(candidate_show)
                if not found:
                    continue
                tmdb_id = found["id"]
                pool = season_cache.get(tmdb_id)
                if pool is None:
                    pool = _show_episode_pool(tmdb_id)
                    season_cache[tmdb_id] = pool
                matched = _match_episode_in_pool(candidate_episode, pool)
                if matched is not None:
                    show_found, episode, show_part = found, matched, candidate_show
                    break
            if episode is None:
                still_unmatched.append(name)
                continue

            tmdb_id = show_found["id"]
            show_title = show_found.get("name") or show_part
            title_row = find_title(db, MediaType.tv_show, tmdb_id, show_title)
            entry = (
                db.query(LibraryEntry).filter_by(user_id=user_id, title_id=title_row.id).first()
                if title_row is not None
                else None
            )
            if entry is None:
                # not tracked as a show in this import at all — add it so the
                # episode has somewhere to attach, same as any other new show
                db_title = find_or_create_title(db, MediaType.tv_show, tmdb_id, show_title)
                entry = LibraryEntry(user_id=user_id, title_id=db_title.id, status=WatchStatus.watching)
                db.add(entry)
                db.flush()

            key = (entry.id, episode["season"], episode["episode"])
            if key not in seen:
                seen.add(key)
                db.add(
                    EpisodeWatch(
                        media_item_id=entry.id,
                        season=episode["season"],
                        episode=episode["episode"],
                        watched_at=datetime.now(UTC),
                    )
                )
                summary["episodes"] += 1
                touched_by_fallback.add(entry.id)
        summary["unmatched"] = still_unmatched
        db.commit()

        # same counters/auto-status sync as the main show loop above, scoped
        # to just the handful of entries this fallback touched
        for item_id in touched_by_fallback:
            watches = db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item_id).all()
            item = db.get(LibraryEntry, item_id)
            item.episodes_watched = len(watches)
            last = max(watches, key=lambda w: (w.season, w.episode))
            item.current_season, item.current_episode = last.season, last.episode
            if (
                item.total_episodes
                and item.episodes_watched >= item.total_episodes
                and item.status not in (WatchStatus.dropped, WatchStatus.paused)
            ):
                item.status = WatchStatus.completed
        db.commit()

        # ---------- comments ----------
        # The export's user_id column is constant across every row (verified
        # empirically against a real export) — this is only ever the
        # exporting user's own comments, never other users', so importing
        # them needs no per-row author check. Only attached to shows that
        # got matched above (items_by_tvdb): a comment left on a show the
        # user isn't tracking in this run would otherwise force a fresh TMDB
        # match (and possibly a new library entry) just to file a comment,
        # which isn't what "import my watch history" should do.
        #
        # show_comment.csv carries tv_show_id directly; episode_comment.csv
        # doesn't, only tv_show_name, so it's matched via the same show
        # rows' name -> tvdb_id mapping instead.
        #
        # Reply threads (parent_comment_id): a reply is only ever
        # reconstructible when its parent is ALSO one of this user's own
        # comments — i.e. present somewhere else in this same export — since
        # the export contains nothing about other TV Time users' comments.
        # `tvtime_id_to_comment_id` tracks TV Time's own `id` column ->
        # the resulting Renar Comment.id for every comment resolved so far
        # (root or reply, newly-created or found via dedupe), so a reply can
        # look up its parent even across an arbitrarily deep self-reply
        # chain, in any row order, via the retry loop below. A reply whose
        # parent never resolves — because it's a reply to another TV Time
        # user, the actual common case — is dropped rather than imported as
        # a fake root comment: filing it as ordinary commentary on the
        # show/episode would misrepresent what it actually is.
        #
        # Comment has no external TV Time id column, so re-running the
        # import resolves existing rows the same way as new ones: a dedupe
        # hit still yields that comment's id into tvtime_id_to_comment_id,
        # so replies onto a comment from a *previous* import run resolve
        # correctly too, not just replies within a single run.
        #
        # Movie comments live in a separate, newer export table
        # (comments-prod-comments.csv) that also carries likes/reports mixed
        # in via its own `type` column — only `comment`/`reply` rows are real
        # commentary, so those are the only ones read here. It has no
        # per-movie id either, only movie_name, matched the same way as
        # episode comments: via items_by_movie, the name -> item id map built
        # while matching movies above.
        show_comment_rows = _read_csv(zf, "show_comment.csv")
        episode_comment_rows = _read_csv(zf, "episode_comment.csv")
        movie_comment_rows = [
            r for r in _read_csv(zf, "comments-prod-comments.csv") if r.get("type") in ("comment", "reply")
        ]
        name_to_tvdb = {r["tv_show_name"]: r["tv_show_id"] for r in show_rows if r.get("tv_show_name")}

        def _resolve_show_comment(row: dict) -> tuple[int | None, None, None, str]:
            item_id = items_by_tvdb.get(row.get("tv_show_id") or "")
            return item_id, None, None, (row.get("comment") or "").strip()

        def _resolve_episode_comment(row: dict) -> tuple[int | None, int | None, int | None, str]:
            tvdb_id = name_to_tvdb.get(row.get("tv_show_name") or "")
            item_id = items_by_tvdb.get(tvdb_id or "")
            text = (row.get("comment") or "").strip()
            s_no, ep_no = row.get("episode_season_number"), row.get("episode_number")
            try:
                season, episode = (int(s_no), int(ep_no)) if item_id and s_no and ep_no else (None, None)
            except ValueError:
                season = episode = None
            if item_id and (season is None or episode is None):
                item_id = None  # matched show, but episode numbers didn't parse — treat as unmatched
            return item_id, season, episode, text

        def _resolve_movie_comment(row: dict) -> tuple[int | None, None, None, str]:
            item_id = items_by_movie.get(normalize_title_key(row.get("movie_name") or ""))
            return item_id, None, None, (row.get("text") or "").strip()

        jobs = [
            (row.get("id") or "", row.get("parent_comment_id") or "", *_resolve_show_comment(row), row)
            for row in show_comment_rows
        ]
        jobs += [
            (row.get("id") or "", row.get("parent_comment_id") or "", *_resolve_episode_comment(row), row)
            for row in episode_comment_rows
        ]
        jobs += [
            (row.get("uuid") or "", row.get("parent_uuid") or "", *_resolve_movie_comment(row), row)
            for row in movie_comment_rows
        ]

        _set(user_id, stage="Importing comments", done=0, total=len(jobs))
        title_comment_cache: dict[int, dict[tuple, int]] = {}
        reply_comment_cache: dict[int, dict[str, int]] = {}
        tvtime_id_to_comment_id: dict[str, int] = {}

        def _existing_root(title_id: int, season: int | None, episode: int | None, text: str) -> int | None:
            if title_id not in title_comment_cache:
                rows = (
                    db.query(Comment.id, Comment.season, Comment.episode, Comment.text)
                    .filter(Comment.user_id == user_id, Comment.title_id == title_id)
                    .all()
                )
                title_comment_cache[title_id] = {(s, e, t): cid for cid, s, e, t in rows}
            return title_comment_cache[title_id].get((season, episode, text))

        def _existing_reply(parent_id: int, text: str) -> int | None:
            if parent_id not in reply_comment_cache:
                rows = (
                    db.query(Comment.id, Comment.text)
                    .filter(Comment.user_id == user_id, Comment.parent_id == parent_id)
                    .all()
                )
                reply_comment_cache[parent_id] = {t: cid for cid, t in rows}
            return reply_comment_cache[parent_id].get(text)

        def _create_root(
            item_id: int | None, season: int | None, episode: int | None, text: str, created_at: datetime
        ) -> tuple[int | None, bool]:
            if not item_id or not text:
                return None, False
            item = db.get(LibraryEntry, item_id)
            if item is None:
                return None, False
            existing = _existing_root(item.title_id, season, episode, text)
            if existing is not None:
                return existing, False
            comment = Comment(
                user_id=user_id,
                title_id=item.title_id,
                season=season,
                episode=episode,
                text=text,
                created_at=created_at,
            )
            db.add(comment)
            db.flush()
            title_comment_cache.setdefault(item.title_id, {})[(season, episode, text)] = comment.id
            return comment.id, True

        def _create_reply(parent_comment_id: int, text: str, created_at: datetime) -> tuple[int | None, bool]:
            if not text:
                return None, False
            existing = _existing_reply(parent_comment_id, text)
            if existing is not None:
                return existing, False
            comment = Comment(
                user_id=user_id,
                title_id=None,
                parent_id=parent_comment_id,
                season=None,
                episode=None,
                text=text,
                created_at=created_at,
            )
            db.add(comment)
            db.flush()
            reply_comment_cache.setdefault(parent_comment_id, {})[text] = comment.id
            return comment.id, True

        done = 0
        pending: list[tuple[str, str, str, datetime]] = []
        for tvtime_id, parent_tvtime_id, item_id, season, episode, text, row in jobs:
            done += 1
            if done % 100 == 0:
                _set(user_id, done=done)
            created_at = _parse_dt(row.get("created_at")) or datetime.now(UTC)
            if parent_tvtime_id:
                pending.append((tvtime_id, parent_tvtime_id, text, created_at))
                continue
            comment_id, is_new = _create_root(item_id, season, episode, text, created_at)
            if comment_id is None:
                summary["comments_skipped"] += 1
                continue
            if tvtime_id:
                tvtime_id_to_comment_id[tvtime_id] = comment_id
            if is_new:
                summary["comments"] += 1

        # Retry pending replies until a full pass makes no progress, so a
        # multi-level self-reply chain resolves regardless of row order.
        progress = True
        while pending and progress:
            progress = False
            still_pending = []
            for tvtime_id, parent_tvtime_id, text, created_at in pending:
                parent_comment_id = tvtime_id_to_comment_id.get(parent_tvtime_id)
                if parent_comment_id is None:
                    still_pending.append((tvtime_id, parent_tvtime_id, text, created_at))
                    continue
                comment_id, is_new = _create_reply(parent_comment_id, text, created_at)
                if comment_id is None:
                    summary["comments_skipped"] += 1
                    continue
                if tvtime_id:
                    tvtime_id_to_comment_id[tvtime_id] = comment_id
                if is_new:
                    summary["comments"] += 1
                progress = True
            pending = still_pending
        # Whatever's left replies to a comment that isn't this user's own —
        # can't be attached anywhere without misrepresenting it, so it's
        # dropped rather than filed as a fake root comment.
        summary["comments_skipped"] += len(pending)

        db.commit()

        # ---------- rewatches ----------
        # rewatched_episode.csv has no tv_show_id, only tv_show_name (same as
        # episode_comment.csv), matched the same way via name_to_tvdb. `cpt`
        # is TV Time's own rewatch count for that episode; WatchEvent.
        # rewatch_count (routers/media.py) is a plain COUNT of WatchEvent
        # rows, so importing means topping each episode's row count up to
        # `cpt`, never overwriting it — a rewatch already logged manually (or
        # via the app's own POST /rewatch) is left alone, and re-running the
        # import only ever inserts the shortfall, never doubles up. A
        # rewatched episode implies at least one watch, so a missing
        # EpisodeWatch row is created too, same as the app's own endpoint
        # does. TV Time gives one timestamp per row, not one per rewatch, so
        # every synthesized WatchEvent for a `cpt` > 1 row shares it.
        rewatch_rows = _read_csv(zf, "rewatched_episode.csv")

        def _resolve_rewatch(row: dict) -> tuple[int | None, int | None, int | None, int]:
            tvdb_id = name_to_tvdb.get(row.get("tv_show_name") or "")
            item_id = items_by_tvdb.get(tvdb_id or "")
            try:
                season, episode, cpt = (
                    int(row.get("episode_season_number")),
                    int(row.get("episode_number")),
                    int(row.get("cpt")),
                )
            except (TypeError, ValueError):
                return None, None, None, 0
            if cpt < 1:
                return None, None, None, 0
            return item_id, season, episode, cpt

        _set(user_id, stage="Importing rewatches", done=0, total=len(rewatch_rows))
        done = 0
        for row in rewatch_rows:
            done += 1
            if done % 100 == 0:
                _set(user_id, done=done)
            item_id, season, episode, cpt = _resolve_rewatch(row)
            if not item_id or db.get(LibraryEntry, item_id) is None:
                summary["rewatches_skipped"] += 1
                continue
            watched_at = _parse_dt(row.get("updated_at")) or _parse_dt(row.get("created_at")) or datetime.now(UTC)
            if db.query(EpisodeWatch).filter_by(media_item_id=item_id, season=season, episode=episode).first() is None:
                db.add(EpisodeWatch(media_item_id=item_id, season=season, episode=episode, watched_at=watched_at))
            existing_events = (
                db.query(WatchEvent)
                .filter(WatchEvent.media_item_id == item_id, WatchEvent.season == season, WatchEvent.episode == episode)
                .count()
            )
            to_add = cpt - existing_events
            if to_add > 0:
                for _ in range(to_add):
                    db.add(WatchEvent(media_item_id=item_id, season=season, episode=episode, watched_at=watched_at))
                summary["rewatches"] += to_add
        db.commit()

        summary["unmatched"] = summary["unmatched"][:20]
        _set(user_id, stage="Done", finished=True, summary=summary, error=None)
        _mark_job(user_id, finished=True, error=None, summary=summary)
        _log.info(
            "TV Time import finished for user_id=%s: %s shows, %s episodes, %s movies, %s comments, %s rewatches, "
            "%s updated, %s skipped, %s errors, %s unmatched",
            user_id,
            summary["shows"],
            summary["episodes"],
            summary["movies"],
            summary["comments"],
            summary["rewatches"],
            summary["updated"],
            summary["skipped"],
            summary["errors"],
            len(summary["unmatched"]),
        )
    except Exception:
        db.rollback()
        _log.exception("TV Time import failed for user_id=%s", user_id)
        # The real exception (which can include file paths, driver internals,
        # or DB error text) goes to the server log above only — callers only
        # ever see a generic message via GET /import/tvtime/status.
        generic_error = "Import failed due to an internal error. Please try again or contact support."
        _set(user_id, stage="Failed", finished=True, error=generic_error, summary=summary)
        _mark_job(user_id, finished=True, error=generic_error, summary=summary)
    finally:
        db.close()
        _import_slots.release()


@router.post("/tvtime", status_code=status.HTTP_202_ACCEPTED)
async def import_tvtime(
    file: UploadFile,
    user: User = Depends(get_current_user),
):
    running = _progress.get(user.id)
    if running and not running.get("finished", True):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An import is already running")
    # Acquired before reading the body — that's the expensive part (up to
    # 200 MB held in memory) this slot exists to bound. Released in
    # _run_import's finally.
    if not _import_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many imports running right now. Please try again shortly.",
        )
    try:
        data = await file.read()
        if len(data) > 200 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File too large")
        try:
            zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="That is not a zip file"
            ) from exc
    except Exception:
        _import_slots.release()
        raise
    _progress[user.id] = {"stage": "Starting", "done": 0, "total": 0, "finished": False, "error": None, "summary": None}
    _mark_job(user.id, finished=False, error=None, summary=None)
    threading.Thread(target=_run_import, args=(user.id, data), daemon=True).start()
    return {"status": "started"}


@router.get("/tvtime/status")
def import_status(user: User = Depends(get_current_user)):
    live = _progress.get(user.id)
    if live is not None:
        return live

    # Nothing in memory for this user — either no import ever ran on this
    # process, or one did and the process (and its in-memory _progress dict)
    # was lost mid-import, e.g. a server restart. ImportJob (written at job
    # start and at completion/failure) tells the two apart: a row stuck at
    # finished=False means the job never got to report back.
    db = SessionLocal()
    try:
        job = db.get(ImportJob, user.id)
    finally:
        db.close()
    if job is None:
        return {"stage": "Never run", "finished": True, "error": None, "summary": None, "done": 0, "total": 0}
    if not job.finished:
        return {
            "stage": "Failed",
            "finished": True,
            "error": "Import was interrupted by a server restart. Please re-run it.",
            "summary": None,
            "done": 0,
            "total": 0,
        }
    return {
        "stage": "Failed" if job.error else "Done",
        "finished": True,
        "error": job.error,
        "summary": job.summary,
        "done": 0,
        "total": 0,
    }
