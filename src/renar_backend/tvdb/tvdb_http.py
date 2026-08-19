#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000

HTTP layer for TheTVDB v4 API: auth + pooled client, mirroring tmdb_http.py.
No in-memory cache here (unlike tmdb_http.py) — this is only ever hit once
per show per import/retry attempt, nowhere near TMDB's read volume from
Explore/Search/season browsing.
"""

import logging
import time

import httpx

from ..config import settings

_log = logging.getLogger(__name__)

TVDB_BASE = "https://api4.thetvdb.com/v4"

http_client = httpx.Client(timeout=15)

_token: str | None = None
_token_expiry: float = 0.0


def _login(*, force: bool = False) -> str | None:
    """Log in to TheTVDB v4 API; tokens are valid ~1 month so we cache ours.
    Returns None (never raises) when tvdb_api_key isn't configured or the
    login call itself fails — TVDB is optional and every caller here treats
    "no token" the same as "TVDB has nothing to offer right now"."""
    global _token, _token_expiry
    if not settings.tvdb_api_key:
        return None
    if not force and _token and _token_expiry > time.time():
        return _token
    try:
        resp = http_client.post(f"{TVDB_BASE}/login", json={"apikey": settings.tvdb_api_key})
        resp.raise_for_status()
        _token = resp.json()["data"]["token"]
        _token_expiry = time.time() + 20 * 24 * 3600
        return _token
    except Exception:
        _log.warning("TheTVDB login failed", exc_info=True)
        return None


def tvdb_get(path: str, params: dict | None = None) -> dict | None:
    """GET a TheTVDB v4 path, returning its `data` payload, or None if TVDB
    isn't configured, login fails, or the request itself fails/404s.

    Deliberately best-effort, unlike tmdb_get: every caller here treats a
    miss as "fall through to the next thing" (TMDB stays the primary
    catalog), never as an error worth retrying or surfacing to a user.
    """
    token = _login()
    if not token:
        return None
    try:
        resp = http_client.get(f"{TVDB_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 401:
            token = _login(force=True)
            if not token:
                return None
            resp = http_client.get(f"{TVDB_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            return None
        return resp.json().get("data")
    except Exception:
        _log.warning("TheTVDB request failed for %s", path, exc_info=True)
        return None
