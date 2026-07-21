#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/19 00:00:00.000000
Revised: 2026/07/21 09:51:08.170297

Cloudflare Turnstile verification for /auth/register. See tmdb/tmdb_http.py
for the same pooled-client pattern this mirrors.

Also hosts the widget itself (new_widget_session/widget_html/set_widget_token/
get_widget_token) — the Turnstile JS widget has to load from a real,
Cloudflare-registered hostname (their mobile-implementation docs: a WebView's
`load_html()` with no real origin fails domain validation), and the backend
is the one host both the web build and compiled mobile apps can always
reach, unlike the frontend's own (per-platform, sometimes-nonexistent) web
server. Session state is an in-process dict — fine for a single worker;
running the backend with multiple uvicorn workers would need this moved to
something shared (Redis, the DB) since a callback and the poll that follows
it aren't guaranteed to land on the same worker.
"""

import html
import logging
import secrets
import time

import httpx

from ..config import settings

_log = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# One pooled client: reusing connections to Cloudflare saves a TLS handshake
# on every registration.
http_client = httpx.Client(timeout=10)

_WIDGET_SESSION_TTL_SECONDS = 10 * 60  # a register screen left open longer than this gets a fresh session
_widget_sessions: dict[str, tuple[str | None, float]] = {}  # session_id -> (token, created_at)


def verify_turnstile(token: str, remote_ip: str | None, *, enabled: bool) -> bool:
    """True if Cloudflare accepts the token. Also true (no-op) when `enabled`
    is False (the site_settings admin toggle — see models.SiteSettings) or
    when Turnstile isn't configured at all (empty TURNSTILE_SECRET_KEY means
    the deployment hasn't set it up yet, not that every registration should
    start failing)."""
    if not enabled or not settings.turnstile_secret_key:
        return True
    if not token:
        return False

    data = {"secret": settings.turnstile_secret_key, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        resp = http_client.post(SITEVERIFY_URL, data=data)
        resp.raise_for_status()
    except httpx.HTTPError:
        _log.warning("could not reach Cloudflare Turnstile siteverify", exc_info=True)
        return False

    result = resp.json()
    if not result.get("success"):
        _log.info("turnstile verification failed: %s", result.get("error-codes"))
    return bool(result.get("success"))


def _purge_expired_widget_sessions() -> None:
    cutoff = time.monotonic() - _WIDGET_SESSION_TTL_SECONDS
    expired = [sid for sid, (_token, created) in _widget_sessions.items() if created < cutoff]
    for sid in expired:
        del _widget_sessions[sid]


def new_widget_session() -> str:
    _purge_expired_widget_sessions()
    session_id = secrets.token_urlsafe(24)
    _widget_sessions[session_id] = (None, time.monotonic())
    return session_id


def widget_session_exists(session_id: str) -> bool:
    return session_id in _widget_sessions


def get_widget_token(session_id: str) -> str | None:
    entry = _widget_sessions.get(session_id)
    return entry[0] if entry else None


def set_widget_token(session_id: str, token: str) -> bool:
    """True if the session existed and was updated; False for an unknown or
    expired session_id, so the caller can 404 instead of silently no-op'ing."""
    entry = _widget_sessions.get(session_id)
    if entry is None:
        return False
    _widget_sessions[session_id] = (token, entry[1])
    return True


def clear_widget_session(session_id: str) -> None:
    _widget_sessions.pop(session_id, None)


_VALID_THEMES = frozenset({"light", "dark", "auto"})


def widget_html(site_key: str, session_id: str, theme: str) -> str:
    # Cloudflare's own widget renders its checkbox/status text and the
    # required "Cloudflare" wordmark — this page is just a transparent frame
    # around it, sized to match the frontend's outlined form fields.
    # theme is validated against the whitelist and HTML-escaped as defence-in-depth
    # to prevent reflected XSS if the allowed set ever widens.
    safe_theme = html.escape(theme if theme in _VALID_THEMES else "dark")
    safe_site_key = html.escape(site_key)
    # session_id is secrets.token_urlsafe(24) — only URL-safe chars, no escaping needed
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<style>
  html,body{{margin:0;padding:0;background:transparent;overflow:hidden;
    display:flex;align-items:center;justify-content:center;height:100%;}}
</style></head>
<body>
  <div class="cf-turnstile"
       data-sitekey="{safe_site_key}"
       data-theme="{safe_theme}"
       data-callback="onVerified"></div>
  <script>
    function onVerified(token) {{
      fetch("/auth/turnstile-callback/{session_id}?token=" + encodeURIComponent(token), {{method: "POST"}});
    }}
  </script>
</body></html>"""
