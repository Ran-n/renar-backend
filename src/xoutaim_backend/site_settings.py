#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/16 13:30:00.000000
Revised: 2026/07/17 19:32:52.285872

Runtime-tunable site settings backed by the `site_settings` singleton row.

The public surface is two callables:

- `get_site_settings(db)` — direct DB read; use this in request handlers that
  already hold a session (e.g. the register endpoint).  Creates the row with
  config-seeded defaults on the first call if it doesn't exist yet.

- `current()` — short-TTL in-process cache; use this in hot paths such as
  AbuseGuardMiddleware that run on every request and cannot take a DB hit each
  time.  Opens its own SessionLocal() the same way security.py does for strikes.

- `invalidate()` — zero the cache TTL so the next current() call re-reads from
  the database; called by the admin POST handler after committing a change.
"""

import logging
import time

from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import SiteSettings

_log = logging.getLogger(__name__)

_CACHE_TTL = 5.0
_cached: SiteSettings | None = None
_cache_ts: float = 0.0


def _make_defaults() -> SiteSettings:
    """Transient SiteSettings seeded from config.py — used both as the initial
    DB row and as the emergency fallback when the table isn't reachable."""
    return SiteSettings(
        id=1,
        invite_only=False,
        registration_open=settings.registration_open,
        auth_rate_limit_per_minute=settings.auth_rate_limit_per_minute,
        register_per_hour_per_ip=settings.register_per_hour_per_ip,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        flood_ban_per_minute=settings.flood_ban_per_minute,
        login_backoff_threshold=settings.login_backoff_threshold,
        login_backoff_account_threshold=settings.login_backoff_account_threshold,
        login_backoff_minutes=settings.login_backoff_minutes,
        probe_ban_threshold=settings.probe_ban_threshold,
        probe_window_minutes=settings.probe_window_minutes,
        ban_minutes=settings.ban_minutes,
        strike_ban_threshold=settings.strike_ban_threshold,
        trust_proxy_headers=settings.trust_proxy_headers,
        exempt_ips=settings.exempt_ips,
    )


def get_site_settings(db: Session) -> SiteSettings:
    """Read the singleton SiteSettings row, creating it with config defaults
    if it doesn't exist yet (upsert-on-read bootstrap)."""
    row = db.get(SiteSettings, 1)
    if row is None:
        row = _make_defaults()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def current() -> SiteSettings:
    """Return site settings, refreshing from DB at most once every 5 seconds.

    Falls back to config.py defaults when the site_settings table doesn't
    exist yet (fresh checkout, migration not run) — same defensive pattern as
    security.py's _load_permabans.
    """
    global _cached, _cache_ts
    now = time.time()
    if _cached is not None and now - _cache_ts < _CACHE_TTL:
        return _cached
    try:
        with SessionLocal() as db:
            row = get_site_settings(db)
            db.expunge(row)
            _cached = row
            _cache_ts = now
    except Exception:
        _log.exception("could not load site_settings; using config defaults")
        if _cached is None:
            _cached = _make_defaults()
        # don't advance _cache_ts on error so we retry on the next call
    return _cached


def invalidate() -> None:
    """Force the next current() call to re-read from the database.

    Called by the admin settings POST handler immediately after committing a
    change, so the new values take effect without waiting out the TTL.
    """
    global _cache_ts
    _cache_ts = 0.0
