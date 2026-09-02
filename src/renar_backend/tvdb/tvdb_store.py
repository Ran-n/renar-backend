#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/09/02 10:57:11.136899

Fetch + shape TheTVDB v4 data for the import fallback path: a series'
extended record (name/aliases/poster/overview/status) and its full episode
list. Deliberately thin — TVDB here is a stopgap for a show TMDB hasn't
matched yet, not a general catalog source (tmdb_store.py is that); once
TMDB resolves, its data always wins (see catalog/titles.py's
backfill_title_tmdb_id, which never touches a Title once tmdb_id is set).
"""

import logging
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Episode, Title
from .tvdb_http import tvdb_get

_log = logging.getLogger(__name__)


def fetch_series_extended(tvdb_id: str) -> dict | None:
    """Raw SeriesExtendedRecord for one TVDB series id, or None if TVDB has
    nothing (not configured, not found, or unreachable)."""
    return tvdb_get(f"/series/{tvdb_id}/extended")


# Each name tried costs one TMDB search call (up to 3 attempts apiece,
# under tmdb_get's retry/backoff), so this is a real cost cap, not an
# arbitrary one — a show with an unusually long regional-name list
# shouldn't be able to turn one unmatched row into dozens of HTTP calls
# during an 8-worker import batch. 12 comfortably covers the common case
# (most shows carry a handful of aliases) while still bounding the tail.
_MAX_NAME_CANDIDATES = 12


def series_names(data: dict) -> list[str]:
    """Primary name + aliases from an extended record — candidate titles
    for retrying a TMDB search (the pre-existing use of TVDB, before it
    also became a fallback identity in its own right)."""
    names = [data["name"]] if data.get("name") else []
    for alias in data.get("aliases") or []:
        name = alias.get("name") if isinstance(alias, dict) else alias
        if name and name not in names:
            names.append(name)
    return names[:_MAX_NAME_CANDIDATES]


def series_summary(tvdb_id: str, data: dict) -> dict:
    """Map an extended record to the shape find_or_create_title/
    backfill_title_tvdb_id expect — one tier down from tmdb.py's
    _map_details (TVDB's base fields carry no genre list)."""
    year = data.get("year")
    return {
        "tvdb_id": int(tvdb_id),
        "name": (data.get("name") or "").strip() or None,
        "poster_url": data.get("image") or None,
        "overview": (data.get("overview") or "").strip()[:2000] or None,
        "show_status": ((data.get("status") or {}).get("name") or "").strip()[:30] or None,
        "runtime_minutes": data.get("averageRuntime") or None,
        "year": int(year) if year and str(year).isdigit() else None,
    }


def fetch_series_episodes(tvdb_id: str) -> list[dict]:
    """Every episode TVDB has for one series, in its default season order.

    Only the first page is fetched — TVDB paginates this endpoint (a few
    hundred rows per page), and fetching every page for a handful of
    unmatched shows per import isn't worth the extra round trips. A show
    large enough to need page 2 still gets its early seasons tracked
    instead of none, and picks up the rest once TMDB resolves.
    """
    data = tvdb_get(f"/series/{tvdb_id}/episodes/default", params={"page": 0})
    if not data:
        return []
    episodes = []
    for e in data.get("episodes") or []:
        season = e.get("seasonNumber")
        number = e.get("number")
        if season is None or number is None:
            continue
        episodes.append({
            "season": season,
            "episode_number": number,
            "name": (e.get("name") or "").strip()[:300] or None,
            "air_date": e.get("aired") or None,
        })
    return episodes


def sync_tvdb_episodes(db: Session, title: Title, episodes: list[dict]) -> None:
    """Upsert Episode rows from fetch_series_episodes' output, keyed the
    same (title_id, season, episode_number) way tmdb_store.sync_episodes
    is — so these rows are transparently overwritten in place once TMDB
    resolves and sync_show_episodes takes over syncing this title."""
    for e in episodes:
        air_date = None
        if e.get("air_date"):
            try:
                air_date = date.fromisoformat(e["air_date"])
            except ValueError:
                air_date = None
        row = (
            db.query(Episode)
            .filter_by(title_id=title.id, season=e["season"], episode_number=e["episode_number"])
            .first()
        )
        if row is not None:
            row.name = e["name"]
            row.air_date = air_date
        else:
            try:
                with db.begin_nested():
                    db.add(
                        Episode(
                            title_id=title.id,
                            season=e["season"],
                            episode_number=e["episode_number"],
                            name=e["name"],
                            air_date=air_date,
                        )
                    )
            except IntegrityError:
                # concurrent sync request inserted the same episode — skip
                _log.debug(
                    "episode (%s, s%se%s) already inserted by a concurrent sync",
                    title.id,
                    e["season"],
                    e["episode_number"],
                )
