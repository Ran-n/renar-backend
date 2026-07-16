#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:17.357680
Revised: 2026/07/16 09:54:31.683423

HTTP layer for TMDB: pooled client, auth, and the short-lived in-memory
cache. Lives below the router so the notifier and tmdb_store can call TMDB
without importing router modules (no import cycles).

Read-only TMDB responses are cached in memory (30 min TTL) to keep the
Explore feeds and season lists fast and to stay well inside rate limits.
Longer-lived persistence for tracked titles is tmdb_store's job.
"""

import logging

import httpx
from fastapi import HTTPException, status

from .config import settings
from .http_cache import TTLCache

_log = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_BASE = f"{IMAGE_BASE}/w500"
BACKDROP_BASE = f"{IMAGE_BASE}/w780"

# our media_type -> TMDB path segment
TMDB_KIND = {"film": "movie", "tv_show": "tv"}

CACHE_TTL_SECONDS = 30 * 60
CACHE_MAX_ENTRIES = 2048  # ~a few MB worst case; entries are small JSON dicts
_cache = TTLCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)

# one pooled client: reusing connections to TMDB saves a TLS handshake per call
http_client = httpx.Client(
    timeout=15,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)


def tmdb_get(path: str, params: dict | None = None, cache: bool = True) -> dict:
    if not settings.tmdb_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TMDB is not configured — set TMDB_API_KEY in the backend .env",
        )
    params = dict(params or {})

    cache_key = (path, tuple(sorted(params.items())))
    if cache:
        hit = _cache.get(cache_key)
        if hit is not None:
            return hit

    headers = {}
    # v4 read access tokens are JWTs sent as Bearer; v3 keys go in the query string
    if settings.tmdb_api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.tmdb_api_key}"
    else:
        params["api_key"] = settings.tmdb_api_key

    try:
        resp = http_client.get(f"{TMDB_BASE}{path}", params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB") from exc
    if resp.status_code == 401:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB rejected the API key")
    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found on TMDB")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TMDB error {resp.status_code}",
        )

    data = resp.json()
    if cache:
        _cache.put(cache_key, data)
    return data
