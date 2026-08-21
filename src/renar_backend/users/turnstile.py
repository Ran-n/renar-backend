#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/19 00:00:00.000000
Revised: 2026/08/21 16:27:43.086775

Cloudflare Turnstile verification for /auth/register. See tmdb/tmdb_http.py
for the same pooled-client pattern this mirrors.

Also hosts the widget itself (new_widget_session/widget_html/set_widget_token/
get_widget_token) — the Turnstile JS widget has to load from a real,
Cloudflare-registered hostname (their mobile-implementation docs: a WebView's
`load_html()` with no real origin fails domain validation), and the backend
is the one host both the web build and compiled mobile apps can always
reach, unlike the frontend's own (per-platform, sometimes-nonexistent) web
server. Session state is persisted (models.TurnstileWidgetSession) rather
than an in-process dict, so a session created just before a restart doesn't
404 when its callback/poll lands on the fresh process (in-memory storage
was tried first and hit exactly that during 2026-08-20's Turnstile rollout).
"""

import html
import logging
import secrets
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from ..models import TurnstileWidgetSession, utcnow

_log = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# One pooled client: reusing connections to Cloudflare saves a TLS handshake
# on every registration.
http_client = httpx.Client(timeout=10)

_WIDGET_SESSION_TTL_SECONDS = 10 * 60  # a register screen left open longer than this gets a fresh session


def verify_turnstile(token: str, remote_ip: str | None, *, enabled: bool, secret_key: str) -> bool:
    """True if Cloudflare accepts the token. Also true (no-op) when `enabled`
    is False (the site_settings admin toggle — see models.SiteSettings) or
    when Turnstile isn't configured at all (empty secret_key means the
    deployment hasn't set it up yet, not that every registration should
    start failing). `secret_key` is already resolved by the caller (see
    Settings.turnstile_secret_key_for) — this module doesn't need to know
    about hostnames or dev/prod at all."""
    if not enabled or not secret_key:
        return True
    if not token:
        return False

    data = {"secret": secret_key, "response": token}
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


def _purge_expired_widget_sessions(db: Session) -> None:
    cutoff = utcnow() - timedelta(seconds=_WIDGET_SESSION_TTL_SECONDS)
    db.query(TurnstileWidgetSession).filter(TurnstileWidgetSession.created_at < cutoff).delete()
    db.commit()


def new_widget_session(db: Session) -> str:
    _purge_expired_widget_sessions(db)
    session_id = secrets.token_urlsafe(24)
    db.add(TurnstileWidgetSession(id=session_id))
    db.commit()
    return session_id


def widget_session_exists(db: Session, session_id: str) -> bool:
    return db.get(TurnstileWidgetSession, session_id) is not None


def get_widget_token(db: Session, session_id: str) -> str | None:
    row = db.get(TurnstileWidgetSession, session_id)
    return row.token if row else None


def set_widget_token(db: Session, session_id: str, token: str) -> bool:
    """True if the session existed and was updated; False for an unknown or
    expired session_id, so the caller can 404 instead of silently no-op'ing."""
    row = db.get(TurnstileWidgetSession, session_id)
    if row is None:
        return False
    row.token = token
    db.commit()
    return True


def clear_widget_session(db: Session, session_id: str) -> None:
    db.query(TurnstileWidgetSession).filter(TurnstileWidgetSession.id == session_id).delete()
    db.commit()


_VALID_THEMES = frozenset({"light", "dark", "auto"})


# Gruvbox yellow — the app's default theme seed (branding/themes.py's
# GRUVBOX["yellow"]) and the color its Register button renders in by
# default. This page can't derive a user's actual custom theme (only
# light/dark reaches it), so it borrows the default as a fixed brand accent
# rather than guessing — close enough for a one-off verification page.
_BRAND_ACCENT = "#fabd2f"


def widget_html(site_key: str, session_id: str, theme: str, *, standalone: bool = False) -> str:
    # Cloudflare's own widget renders its checkbox/status text and the
    # required "Cloudflare" wordmark, plus the green tick + "Success!" once
    # verified — this page doesn't build any of that itself.
    # theme is validated against the whitelist and HTML-escaped as defence-in-depth
    # to prevent reflected XSS if the allowed set ever widens.
    safe_theme = html.escape(theme if theme in _VALID_THEMES else "dark")
    safe_site_key = html.escape(site_key)
    # session_id is secrets.token_urlsafe(24) — only URL-safe chars, no escaping needed
    widget_div = f"""<div class="cf-turnstile"
       data-sitekey="{safe_site_key}"
       data-theme="{safe_theme}"
       data-callback="onVerified"></div>"""

    if not standalone:
        # Inline WebView (mobile/web, embedded at 68x300 in the app's own
        # bordered field): stays transparent, no heading/card/branding — it
        # blends into the app's own container instead of fighting it. Note:
        # `display:flex` belongs on body only — putting it on html too (an
        # earlier version of this page did) makes body a flex *item* of html
        # and `align-items:center` then shrinks body to its content width
        # instead of letting it fill the viewport, off-centering everything.
        body = widget_div
        style = """
  html{height:100%;margin:0;}
  body{margin:0;height:100%;background:transparent;overflow:hidden;
    display:flex;align-items:center;justify-content:center;}"""
        return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Renar — Verify you're human</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<style>{style}</style></head>
<body>{body}
  <script>
    function onVerified(token) {{
      fetch("/auth/turnstile-callback/{session_id}?token=" + encodeURIComponent(token), {{method: "POST"}});
    }}
  </script>
</body></html>"""

    # Standalone (desktop's system-browser tab): a real page — full-viewport
    # background, a branded card giving context a bare tab otherwise has
    # none of (which app this is, why a checkbox just appeared), plus a
    # best-effort window.close() on success — browsers only honor that on a
    # tab a script opened itself, so it's a courtesy, not guaranteed;
    # Cloudflare's own "Success!" state stays visible either way, so a
    # browser that blocks it just leaves the user looking at that.
    # English-only: the backend has no i18n system (unlike the frontend's
    # own tr()) and this page is reached directly via the system browser,
    # outside the app's own locale-aware UI.
    dark = safe_theme == "dark"
    page_bg = "#161616" if dark else "#f4f4f5"
    card_bg = "#1f1f23" if dark else "#ffffff"
    card_border = "#2a2a30" if dark else "#e4e4e7"
    text_color = "#e4e4e7" if dark else "#27272a"
    style = f"""
  html{{height:100%;margin:0;}}
  body{{margin:0;min-height:100%;background:{page_bg};box-sizing:border-box;
    display:flex;align-items:center;justify-content:center;padding:24px;
    font-family:system-ui,-apple-system,sans-serif;}}
  .rn-card{{display:flex;flex-direction:column;align-items:center;
    background:{card_bg};border:1px solid {card_border};border-radius:12px;
    padding:28px 32px;}}
  .rn-brand{{font-size:12px;font-weight:700;letter-spacing:2px;
    color:{_BRAND_ACCENT};text-transform:uppercase;margin:0 0 10px;}}
  .rn-heading{{font-size:15px;font-weight:600;color:{text_color};
    text-align:center;margin:0 0 20px;max-width:280px;}}"""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Renar — Verify you're human</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<style>{style}</style></head>
<body>
  <div class="rn-card">
    <div class="rn-brand">Renar</div>
    <div class="rn-heading">Verify you're human to continue registering</div>
    {widget_div}
  </div>
  <script>
    function onVerified(token) {{
      fetch("/auth/turnstile-callback/{session_id}?token=" + encodeURIComponent(token), {{method: "POST"}})
        .then(function () {{ window.close(); }});
    }}
  </script>
</body></html>"""
