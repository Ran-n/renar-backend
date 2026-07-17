#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.719597
Revised: 2026/07/18 00:26:58.708084

Book catalog via Open Library (free, no API key).
"""

import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..media.http_cache import TTLCache
from ..media.image_cache import store_external_image, stored_external_image
from ..models import User
from ..users.auth import get_current_user

router = APIRouter(prefix="/books", tags=["books"])
_log = logging.getLogger(__name__)

OL_BASE = "https://openlibrary.org"
COVER_BASE = "https://covers.openlibrary.org/b/id"

CACHE_TTL_SECONDS = 30 * 60
CACHE_MAX_ENTRIES = 1024  # bound: search responses are small JSON dicts
_cache = TTLCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)

_http = httpx.Client(
    timeout=15,
    follow_redirects=True,  # covers.openlibrary.org 302s to archive.org
    headers={"User-Agent": "Renar/0.1 (personal media tracker)"},
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)


def _ol_get(path: str, params: dict | None = None) -> dict:
    key = (path, tuple(sorted((params or {}).items())))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        resp = _http.get(f"{OL_BASE}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach Open Library") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Open Library error {resp.status_code}")
    data = resp.json()
    _cache.put(key, data)
    return data


def _map_docs(docs: list[dict], limit: int = 20) -> list[dict]:
    out = []
    for d in docs[:limit]:
        title = d.get("title")
        if not title:
            continue
        cover_id = d.get("cover_i") or d.get("cover_id")
        authors = d.get("author_name") or []
        if isinstance(authors, str):
            authors = [authors]
        out.append({
            "title": title,
            "year": d.get("first_publish_year"),
            "author": ", ".join(authors[:3]) or None,
            # served via our own cover proxy: cached, redirect-safe
            "poster_url": f"/books/cover/{cover_id}" if cover_id else None,
            "pages": d.get("number_of_pages_median"),
            "overview": None,
        })
    return out


# Covers are stable per id, so they are cached forever: bytes in the
# content-addressed store, identity in external_images — each cover is
# fetched from Open Library at most once (mirrors the TMDB image proxy).
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}

# Missing covers can appear later, so 404s are only remembered for a day —
# in memory, to avoid re-hitting Open Library on every books-tab render.
MISS_TTL_SECONDS = 24 * 3600
_cover_misses: dict[int, float] = {}


@router.get("/cover/{cover_id}")
def book_cover(cover_id: int, db: Session = Depends(get_db)):
    """Proxy + cache Open Library covers (public: <img>-style fetches)."""
    cached = stored_external_image(db, "openlibrary", str(cover_id))
    if cached is not None:
        return FileResponse(cached, media_type="image/jpeg", headers=_IMMUTABLE)

    now = time.time()
    if _cover_misses.get(cover_id, 0) > now:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cover")

    try:
        resp = _http.get(f"{COVER_BASE}/{cover_id}-M.jpg")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach cover server") from exc
    # OL returns a tiny placeholder for unknown ids — treat as missing
    if resp.status_code != 200 or len(resp.content) < 500:
        if len(_cover_misses) > 10000:
            _cover_misses.clear()
        _cover_misses[cover_id] = now + MISS_TTL_SECONDS
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cover")

    store_external_image(db, "openlibrary", str(cover_id), resp.content)
    return Response(resp.content, media_type="image/jpeg", headers=_IMMUTABLE)


@router.get("/search")
def search_books(
    query: str = Query(min_length=1, max_length=200),
    user: User = Depends(get_current_user),
):
    data = _ol_get(
        "/search.json",
        {
            "q": query,
            "limit": 10,
            "fields": "title,first_publish_year,author_name,cover_i,number_of_pages_median",
        },
    )
    return _map_docs(data.get("docs", []), limit=10)


@router.get("/trending")
def trending_books(user: User = Depends(get_current_user)):
    data = _ol_get("/trending/daily.json", {"limit": 20})
    docs = data.get("works", [])
    for d in docs:  # trending uses slightly different field names
        d.setdefault("author_name", d.get("author_names") or [])
    return _map_docs(docs)
