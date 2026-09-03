#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:18.044778
Revised: 2026/09/03 08:33:31.304026

Proxy against TMDB so the API key never reaches clients.

HTTP transport + short in-memory cache live in tmdb_http.py; tracked
titles additionally get their raw payloads persisted through
tmdb_store.py, so detail pages survive TMDB outages and server restarts.
"""

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, joinedload

from ..catalog.titles import popular_local_titles, search_local_titles
from ..database import SessionLocal, get_db
from ..media.image_cache import store_external_image, stored_external_image
from ..models import LibraryEntry, MediaType, Title, User
from ..schemas import TmdbCreditsOut, TmdbDetailsOut, TmdbEpisodeOut, TmdbImageOut, TmdbResultOut
from ..tmdb.tmdb_http import BACKDROP_BASE, IMAGE_BASE, POSTER_BASE, TMDB_KIND, http_client, tmdb_get
from ..tmdb.tmdb_store import TMDB_LOCALE, cached_tmdb
from ..users.auth import get_current_user

router = APIRouter(prefix="/tmdb", tags=["tmdb"])
_log = logging.getLogger(__name__)

# tmdb_get raises these when TMDB itself is unreachable/misconfigured/erroring
# (as opposed to 404, which means TMDB reached us fine and genuinely has no
# such result) — only these warrant falling back to Renar's own catalog.
_TMDB_DOWN_STATUSES = {
    status.HTTP_502_BAD_GATEWAY,
    status.HTTP_503_SERVICE_UNAVAILABLE,
    status.HTTP_504_GATEWAY_TIMEOUT,
}


def _locale_params(language: str) -> dict | None:
    locale = TMDB_LOCALE.get(language)
    return {"language": locale} if locale else None


def _poster_overrides(db: Session, user: User, media_type: str, tmdb_ids: set[int]) -> dict[int, str]:
    """tmdb_id -> custom poster URL for this premium user's library entries.

    Explore/Search/Trending otherwise build poster_url straight from TMDB's
    own poster_path, so a premium user's custom poster (set from the
    library/detail view, stored on LibraryEntry.custom_poster_image_id and
    never written back to the shared Title row) never showed up there.
    """
    if not user.is_premium or not tmdb_ids:
        return {}
    entries = (
        db.query(LibraryEntry)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(
            LibraryEntry.user_id == user.id,
            Title.media_type == MediaType(media_type),
            Title.tmdb_id.in_(tmdb_ids),
            LibraryEntry.custom_poster_image_id.isnot(None),
        )
        .options(joinedload(LibraryEntry.title_ref), joinedload(LibraryEntry.custom_poster_image))
        .all()
    )
    return {e.title_ref.tmdb_id: e.custom_poster_url for e in entries}


def _map_results(raw: list[dict], limit: int = 20, poster_overrides: dict[int, str] | None = None) -> list[dict]:
    results = []
    for r in raw[:limit]:
        # movies use title/release_date, tv uses name/first_air_date
        title = r.get("title") or r.get("name")
        date = r.get("release_date") or r.get("first_air_date") or ""
        if not title:
            continue
        tmdb_id = r["id"]
        poster_url = f"{POSTER_BASE}{r['poster_path']}" if r.get("poster_path") else None
        if poster_overrides:
            poster_url = poster_overrides.get(tmdb_id, poster_url)
        results.append({
            "tmdb_id": tmdb_id,
            "title": title,
            "year": int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None,
            "poster_url": poster_url,
            "overview": (r.get("overview") or "")[:300],
            "vote_average": round((r.get("vote_average") or 0) * 10),
            "vote_count": r.get("vote_count") or 0,
        })
    return results


def _map_local_titles(titles: list[Title], poster_overrides: dict[int, str] | None = None) -> list[dict]:
    """Shape Title rows into the same result contract _map_results produces,
    for the local-catalog fallback. No TMDB rating data lives on Title, so
    vote_average/vote_count are always empty here."""
    results = []
    for t in titles:
        poster_url = t.poster_url
        if poster_overrides:
            poster_url = poster_overrides.get(t.tmdb_id, poster_url)
        results.append({
            "tmdb_id": t.tmdb_id,
            "title": t.title,
            "year": t.year,
            "poster_url": poster_url,
            "overview": (t.overview or "")[:300],
            "vote_average": None,
            "vote_count": 0,
        })
    return results


@router.get("/search", response_model=list[TmdbResultOut])
def search_tmdb(
    query: str = Query(min_length=1, max_length=200),
    media_type: str = Query(pattern="^(film|tv_show)$"),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        data = tmdb_get(
            f"/search/{TMDB_KIND[media_type]}",
            {"query": query, "include_adult": "false", **(_locale_params(language) or {})},
        )
    except HTTPException as exc:
        if exc.status_code not in _TMDB_DOWN_STATUSES:
            raise
        _log.warning("TMDB search unreachable (%s), falling back to local catalog for %r", exc.detail, query)
        titles = search_local_titles(db, MediaType(media_type), query, limit=10)
        overrides = _poster_overrides(db, user, media_type, {t.tmdb_id for t in titles})
        return _map_local_titles(titles, poster_overrides=overrides)
    results = data.get("results", [])[:10]
    overrides = _poster_overrides(db, user, media_type, {r["id"] for r in results})
    return _map_results(results, limit=10, poster_overrides=overrides)


@router.get("/trending", response_model=list[TmdbResultOut])
def trending_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        data = tmdb_get(f"/trending/{TMDB_KIND[media_type]}/week", _locale_params(language))
    except HTTPException as exc:
        if exc.status_code not in _TMDB_DOWN_STATUSES:
            raise
        _log.warning("TMDB trending unreachable (%s), falling back to local catalog", exc.detail)
        titles = popular_local_titles(db, MediaType(media_type), limit=20)
        overrides = _poster_overrides(db, user, media_type, {t.tmdb_id for t in titles})
        return _map_local_titles(titles, poster_overrides=overrides)
    results = data.get("results", [])[:20]
    overrides = _poster_overrides(db, user, media_type, {r["id"] for r in results})
    return _map_results(results, poster_overrides=overrides)


@router.get("/popular", response_model=list[TmdbResultOut])
def popular_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        data = tmdb_get(f"/{TMDB_KIND[media_type]}/popular", _locale_params(language))
    except HTTPException as exc:
        if exc.status_code not in _TMDB_DOWN_STATUSES:
            raise
        _log.warning("TMDB popular unreachable (%s), falling back to local catalog", exc.detail)
        titles = popular_local_titles(db, MediaType(media_type), limit=20)
        overrides = _poster_overrides(db, user, media_type, {t.tmdb_id for t in titles})
        return _map_local_titles(titles, poster_overrides=overrides)
    results = data.get("results", [])[:20]
    overrides = _poster_overrides(db, user, media_type, {r["id"] for r in results})
    return _map_results(results, poster_overrides=overrides)


def _map_details(media_type: str, tmdb_id: int, data: dict) -> dict:
    date = data.get("release_date") or data.get("first_air_date") or ""
    year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None

    seasons = None
    show_status = None
    last_air_year = None
    if media_type == "film":
        runtime = data.get("runtime") or None
        total_episodes = None
        total_seasons = None
    else:
        run_times = data.get("episode_run_time") or []
        runtime = round(sum(run_times) / len(run_times)) if run_times else None
        if runtime is None:
            last_ep = data.get("last_episode_to_air") or {}
            runtime = last_ep.get("runtime") or None
        total_episodes = data.get("number_of_episodes")
        total_seasons = data.get("number_of_seasons")
        show_status = data.get("status") or None
        last_air = data.get("last_air_date") or ""
        last_air_year = int(last_air[:4]) if len(last_air) >= 4 and last_air[:4].isdigit() else None
        seasons = [
            {
                "season": s["season_number"],
                "name": s.get("name") or f"Season {s['season_number']}",
                "episode_count": s.get("episode_count") or 0,
                "air_date": s.get("air_date") or None,
            }
            for s in data.get("seasons", [])
            if s.get("season_number", 0) > 0  # skip "Specials"
        ]

    return {
        "tmdb_id": tmdb_id,
        "title": (data.get("title") or data.get("name") or "")[:300] or None,
        "original_title": (data.get("original_title") or data.get("original_name") or "")[:300] or None,
        "year": year,
        "runtime_minutes": runtime,
        "total_episodes": total_episodes,
        "total_seasons": total_seasons,
        "genres": [g["name"] for g in data.get("genres", [])],
        "poster_url": f"{POSTER_BASE}{data['poster_path']}" if data.get("poster_path") else None,
        "backdrop_url": f"{BACKDROP_BASE}{data['backdrop_path']}" if data.get("backdrop_path") else None,
        "overview": (data.get("overview") or "")[:1000] or None,
        "tagline": (data.get("tagline") or "")[:500] or None,
        "vote_average": round((data.get("vote_average") or 0) * 10) or None,
        "vote_count": data.get("vote_count") or 0,
        "show_status": show_status,
        "last_air_year": last_air_year,
        "seasons": seasons,
        # movie release date / show first-air date, verbatim TMDB
        # "YYYY-MM-DD" — used to badge a not-yet-released title on the
        # frontend's title page (see docs/backlog.md's "Not-yet-released
        # content" item). Distinct from `year` above, which is just the
        # first 4 digits and can't tell an already-aired title from one
        # premiering later this year.
        "release_date": date or None,
    }


@router.get("/details", response_model=TmdbDetailsOut)
def details_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    tmdb_id: int = Query(ge=1),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    path = f"/{TMDB_KIND[media_type]}/{tmdb_id}"
    data = cached_tmdb(db, MediaType(media_type), tmdb_id, "details", path, language=language)
    return _map_details(media_type, tmdb_id, data)


ALLOWED_IMAGE_SIZES = {"w92", "w154", "w185", "w300", "w342", "w500", "w780", "w1280", "original"}
# w1280 is backdrop/still-only upstream (not a poster bucket) but TMDB 404s on
# an unknown size regardless of image kind, so it's safe to allow globally —
# posters simply never request it. Used by the tap-to-zoom backdrop dialog
# (`open_zoom_dialog` in the frontend), which needs a size bigger than w780.
# TMDB image paths are immutable (a given /size/file never changes), so
# cached copies are kept forever: bytes in the content-addressed store,
# identity in the external_images table (each image fetched at most once).
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_CTYPES = {".png": "image/png", ".webp": "image/webp"}


@router.get("/image/{size}/{filename}")
def image_proxy(size: str, filename: str):
    """Serve TMDB posters/backdrops from our origin.

    Browsers sometimes cannot load image.tmdb.org directly (ISP blocks,
    filtering extensions), and <img> tags cannot send auth headers — so this
    endpoint is public but restricted to TMDB image files only.

    Deliberately does not take `db` via `Depends(get_db)`: that would keep a
    pooled connection checked out for the entire request, including the
    outbound TMDB fetch below (tens to hundreds of ms). A grid view loading
    dozens of never-before-seen posters at once would then be bottlenecked by
    the DB pool size (5 + 10 overflow) rather than actual network/CPU work.
    Each of the two short DB touches below opens and closes its own session.
    """
    if (
        size not in ALLOWED_IMAGE_SIZES
        or "/" in filename
        or "\\" in filename
        or ".." in filename
        or not filename.endswith((".jpg", ".jpeg", ".png", ".webp"))
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    ctype = _CTYPES.get(Path(filename).suffix, "image/jpeg")
    key = f"{size}/{filename}"
    with SessionLocal() as db:
        cached = stored_external_image(db, "tmdb", key)
    if cached is not None:
        return FileResponse(cached, media_type=ctype, headers=_IMMUTABLE)

    try:
        resp = http_client.get(f"{IMAGE_BASE}/{size}/{filename}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB images") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    with SessionLocal() as db:
        store_external_image(db, "tmdb", key, resp.content)
    return Response(resp.content, media_type=ctype, headers=_IMMUTABLE)


@router.get("/posters", response_model=list[TmdbImageOut])
def alternate_posters(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    tmdb_id: int = Query(ge=1),
    user: User = Depends(get_current_user),
):
    """Official alternate posters for a title — the curated source for the
    premium custom-poster picker. `url` (w500) is what gets stored;
    `preview_url` (w185) keeps the picker grid light."""
    data = tmdb_get(f"/{TMDB_KIND[media_type]}/{tmdb_id}/images", {"include_image_language": "en,null"})
    return [
        {
            "preview_url": f"{IMAGE_BASE}/w185{p['file_path']}",
            "url": f"{IMAGE_BASE}/w500{p['file_path']}",
        }
        for p in data.get("posters", [])[:40]
        if p.get("file_path")
    ]


@router.get("/backdrops", response_model=list[TmdbImageOut])
def alternate_backdrops(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    tmdb_id: int = Query(ge=1),
    user: User = Depends(get_current_user),
):
    """Official alternate backdrops for a title — the curated source for the
    premium custom-backdrop picker. `url` (w780) is what gets stored;
    `preview_url` (w300) keeps the picker grid light."""
    data = tmdb_get(f"/{TMDB_KIND[media_type]}/{tmdb_id}/images", {"include_image_language": "en,null"})
    return [
        {
            "preview_url": f"{IMAGE_BASE}/w300{b['file_path']}",
            "url": f"{IMAGE_BASE}/w780{b['file_path']}",
        }
        for b in data.get("backdrops", [])[:40]
        if b.get("file_path")
    ]


@router.get("/episode-stills", response_model=list[TmdbImageOut])
def alternate_episode_stills(
    tmdb_id: int = Query(ge=1),
    season: int = Query(ge=0),
    episode: int = Query(ge=1),
    user: User = Depends(get_current_user),
):
    """Official alternate stills for one episode — the curated source for
    the premium custom-episode-still picker. Same `url`/`preview_url` shape
    as /posters and /backdrops."""
    data = tmdb_get(
        f"/tv/{tmdb_id}/season/{season}/episode/{episode}/images",
        {"include_image_language": "en,null"},
    )
    return [
        {
            "preview_url": f"{IMAGE_BASE}/w300{s['file_path']}",
            "url": f"{IMAGE_BASE}/original{s['file_path']}",
        }
        for s in data.get("stills", [])[:40]
        if s.get("file_path")
    ]


def fetch_poster_bytes(url: str) -> bytes:
    """Download a TMDB image a user picked as their custom poster/backdrop
    (the URL prefix is validated by the CustomPosterSet schema)."""
    try:
        resp = http_client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB images") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poster not found on TMDB")
    return resp.content


@router.get("/credits", response_model=TmdbCreditsOut)
def credits_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    tmdb_id: int = Query(ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kind = TMDB_KIND[media_type]
    mt = MediaType(media_type)
    data = cached_tmdb(db, mt, tmdb_id, "credits", f"/{kind}/{tmdb_id}/credits")
    cast = [
        {
            "name": c["name"],
            "character": c.get("character") or "",
            "profile_url": f"{IMAGE_BASE}/w185{c['profile_path']}" if c.get("profile_path") else None,
        }
        for c in data.get("cast", [])
    ]

    def person(p: dict) -> dict:
        return {
            "name": p["name"],
            "profile_url": f"{IMAGE_BASE}/w185{p['profile_path']}" if p.get("profile_path") else None,
        }

    if media_type == "film":
        directors = [person(c) for c in data.get("crew", []) if c.get("job") == "Director"]
        role = "Directed by"
    else:
        details = cached_tmdb(db, mt, tmdb_id, "details", f"/tv/{tmdb_id}")
        directors = [person(p) for p in details.get("created_by", [])]
        role = "Created by"

    # everyone else behind the camera, grouped by TMDB department so the
    # frontend can segregate the crew list (Writing, Camera, Editing, ...) —
    # director/creator already surfaces separately above, so excluded here
    crew = [
        {**person(c), "character": c.get("job") or "", "department": c.get("department") or ""}
        for c in data.get("crew", [])
        if c.get("job") != "Director"
    ]

    return {"cast": cast, "crew": crew, "directors": directors, "director_role": role}


@router.get("/season", response_model=list[TmdbEpisodeOut])
def season_tmdb(
    tmdb_id: int = Query(ge=1),
    season_number: int = Query(ge=0),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    path = f"/tv/{tmdb_id}/season/{season_number}"
    data = cached_tmdb(db, MediaType.tv_show, tmdb_id, "season", path, season=season_number, language=language)
    return [
        {
            "season": season_number,
            "episode": e["episode_number"],
            "name": e.get("name") or f"Episode {e['episode_number']}",
            "air_date": e.get("air_date"),
            "runtime": e.get("runtime"),
            "overview": e.get("overview") or "",
            "still_url": (f"{IMAGE_BASE}/w300{e['still_path']}" if e.get("still_path") else None),
            "vote_average": round((e.get("vote_average") or 0) * 10) or None,
            "vote_count": e.get("vote_count") or 0,
            "guest_stars": [
                {
                    "name": g["name"],
                    "character": g.get("character") or "",
                    "profile_url": (f"{IMAGE_BASE}/w185{g['profile_path']}" if g.get("profile_path") else None),
                }
                for g in e.get("guest_stars", [])[:12]
            ],
        }
        for e in data.get("episodes", [])
    ]
