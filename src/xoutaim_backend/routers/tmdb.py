#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:18.044778
Revised: 2026/07/16 09:54:31.367093

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
from sqlalchemy.orm import Session

from ..database import get_db
from ..media.image_cache import store_external_image, stored_external_image
from ..models import MediaType, User
from ..tmdb.tmdb_http import BACKDROP_BASE, IMAGE_BASE, POSTER_BASE, TMDB_KIND, http_client, tmdb_get
from ..tmdb.tmdb_store import TMDB_LOCALE, cached_tmdb
from ..users.auth import get_current_user

router = APIRouter(prefix="/tmdb", tags=["tmdb"])
_log = logging.getLogger(__name__)


def _locale_params(language: str) -> dict | None:
    locale = TMDB_LOCALE.get(language)
    return {"language": locale} if locale else None


def _map_results(raw: list[dict], limit: int = 20) -> list[dict]:
    results = []
    for r in raw[:limit]:
        # movies use title/release_date, tv uses name/first_air_date
        title = r.get("title") or r.get("name")
        date = r.get("release_date") or r.get("first_air_date") or ""
        if not title:
            continue
        results.append({
            "tmdb_id": r["id"],
            "title": title,
            "year": int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None,
            "poster_url": f"{POSTER_BASE}{r['poster_path']}" if r.get("poster_path") else None,
            "overview": (r.get("overview") or "")[:300],
            "vote_average": round(r.get("vote_average") or 0, 1),
        })
    return results


@router.get("/search")
def search_tmdb(
    query: str = Query(min_length=1, max_length=200),
    media_type: str = Query(pattern="^(film|tv_show)$"),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    user: User = Depends(get_current_user),
):
    data = tmdb_get(
        f"/search/{TMDB_KIND[media_type]}",
        {"query": query, "include_adult": "false", **(_locale_params(language) or {})},
    )
    return _map_results(data.get("results", []), limit=10)


@router.get("/trending")
def trending_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    user: User = Depends(get_current_user),
):
    data = tmdb_get(f"/trending/{TMDB_KIND[media_type]}/week", _locale_params(language))
    return _map_results(data.get("results", []))


@router.get("/popular")
def popular_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    language: str = Query(default="en", pattern="^(en|gl|pt|es|eo)$"),
    user: User = Depends(get_current_user),
):
    data = tmdb_get(f"/{TMDB_KIND[media_type]}/popular", _locale_params(language))
    return _map_results(data.get("results", []))


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
        "vote_average": round(data.get("vote_average") or 0, 1) or None,
        "show_status": show_status,
        "last_air_year": last_air_year,
        "seasons": seasons,
    }


@router.get("/details")
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


ALLOWED_IMAGE_SIZES = {"w92", "w154", "w185", "w300", "w342", "w500", "w780", "original"}
# TMDB image paths are immutable (a given /size/file never changes), so
# cached copies are kept forever: bytes in the content-addressed store,
# identity in the external_images table (each image fetched at most once).
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_CTYPES = {".png": "image/png", ".webp": "image/webp"}


@router.get("/image/{size}/{filename}")
def image_proxy(size: str, filename: str, db: Session = Depends(get_db)):
    """Serve TMDB posters/backdrops from our origin.

    Browsers sometimes cannot load image.tmdb.org directly (ISP blocks,
    filtering extensions), and <img> tags cannot send auth headers — so this
    endpoint is public but restricted to TMDB image files only.
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
    cached = stored_external_image(db, "tmdb", f"{size}/{filename}")
    if cached is not None:
        return FileResponse(cached, media_type=ctype, headers=_IMMUTABLE)

    try:
        resp = http_client.get(f"{IMAGE_BASE}/{size}/{filename}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB images") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    store_external_image(db, "tmdb", f"{size}/{filename}", resp.content)
    return Response(resp.content, media_type=ctype, headers=_IMMUTABLE)


@router.get("/posters")
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


@router.get("/backdrops")
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


@router.get("/episode-stills")
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
            "url": f"{IMAGE_BASE}/w780{s['file_path']}",
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


@router.get("/credits")
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
        for c in data.get("cast", [])[:12]
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
    return {"cast": cast, "directors": directors[:4], "director_role": role}


@router.get("/season")
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
            "still_url": (f"{IMAGE_BASE}/w342{e['still_path']}" if e.get("still_path") else None),
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
