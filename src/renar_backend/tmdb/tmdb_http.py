#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:17.357680
Revised: 2026/08/18 13:15:02.789152

HTTP layer for TMDB: pooled client, auth, and the short-lived in-memory
cache. Lives below the router so the notifier and tmdb_store can call TMDB
without importing router modules (no import cycles).

Read-only TMDB responses are cached in memory (6h TTL) to keep the Explore
feeds and season lists fast and to stay well inside rate limits. Trending/
popular/search results don't meaningfully change within a day on TMDB's
side, so a short TTL only bought staleness protection nobody needed while
forcing a live round trip on every first request after an idle spell.
Longer-lived persistence for tracked titles is tmdb_store's job.
"""

import logging
import time

import httpx
from fastapi import HTTPException, status

from ..config import settings
from ..media.http_cache import TTLCache

_log = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_BASE = f"{IMAGE_BASE}/w500"
BACKDROP_BASE = f"{IMAGE_BASE}/w780"

# our media_type -> TMDB path segment
TMDB_KIND = {"film": "movie", "tv_show": "tv"}

CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_MAX_ENTRIES = 2048  # ~a few MB worst case; entries are small JSON dicts
_cache = TTLCache(ttl_seconds=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES)

# one pooled client: reusing connections to TMDB saves a TLS handshake per call
http_client = httpx.Client(
    timeout=15,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)

# A transient TMDB failure (rate limit, blip) used to raise straight away —
# during an import's 8-worker burst that permanently degraded the row (see
# docs/backlog.md's "Transient TMDB failures permanently degrade an entry"):
# no tmdb_id, poster, or episode counts, ever, unless a later re-import
# happened to retry with matching title text. Retrying here instead means
# an import worker only gives up after genuinely exhausting attempts.
# Bounded to keep worst-case added latency reasonable for the same function
# also serving live user requests (Explore search, title details): 3
# attempts, capped backoff, capped Retry-After — a live request stalls at
# most a few seconds longer than before, not indefinitely.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5
_RETRY_AFTER_CAP_SECONDS = 8.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _retry_delay(attempt: int, retry_after_header: str | None) -> float:
    """Seconds to wait before the next attempt (1-indexed `attempt` is the
    one that just failed). Honors TMDB's own Retry-After on a 429 when it
    gives one, capped so a single misbehaving response can't stall a live
    request for as long as TMDB asks; otherwise exponential backoff."""
    if retry_after_header is not None:
        try:
            return min(float(retry_after_header), _RETRY_AFTER_CAP_SECONDS)
        except ValueError:
            pass
    return _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


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

    last_network_error: httpx.HTTPError | None = None
    resp: httpx.Response | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = http_client.get(f"{TMDB_BASE}{path}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            last_network_error = exc
            resp = None
        else:
            last_network_error = None
            if resp.status_code not in _RETRYABLE_STATUS:
                break
        if attempt < _MAX_ATTEMPTS:
            delay = _retry_delay(attempt, resp.headers.get("Retry-After") if resp is not None else None)
            _log.warning(
                "TMDB %s (attempt %d/%d) for %s, retrying in %.1fs",
                resp.status_code if resp is not None else "network error",
                attempt,
                _MAX_ATTEMPTS,
                path,
                delay,
            )
            time.sleep(delay)

    if resp is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB"
        ) from last_network_error
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
