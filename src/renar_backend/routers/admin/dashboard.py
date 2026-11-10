#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/11/09 23:36:39.789889

Admin dashboard: the tile-grid landing page at /admin (or the configured
admin path).
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from ...users.auth import require_admin as _require_admin
from ._html import (
    _BASE_CSS,
    _FAVICON,
    _P,
    _RESPONSIVE_CSS,
    _logout_button,
)
from .app_releases import APP_RELEASES_ICON_PATHS
from .update import SERVER_UPDATE_ICON_PATHS

router = APIRouter()

_DASHBOARD_CSS = """
    .page { max-width: 860px; margin: 0 auto; padding: 2.5rem 2rem; }
    .page-heading {
      font-size: 1.35rem; font-weight: 700; letter-spacing: -.02em;
      color: var(--text); margin-bottom: .35rem;
    }
    .page-sub { font-size: .85rem; color: var(--text-2); margin-bottom: 2rem; }

    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
    .tile {
      display: flex; flex-direction: column; gap: 1rem;
      background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
      padding: 1.5rem 1.25rem; text-decoration: none; color: inherit;
      transition: border-color .15s, background .15s, transform .1s; cursor: pointer;
    }
    .tile:hover { background: var(--surface-hi); border-color: rgba(250,189,47,.4); transform: translateY(-2px); }
    .tile:hover .tile-icon { background: rgba(250,189,47,.18); color: #fbf1c7; }
    .tile-icon {
      width: 52px; height: 52px; background: rgba(250,189,47,.12); border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      color: var(--accent); transition: background .15s, color .15s; flex-shrink: 0;
    }
    .tile-icon svg { width: 26px; height: 26px; }
    .tile-name { font-size: .95rem; font-weight: 600; color: var(--text); letter-spacing: -.01em; }
    .tile-desc { font-size: .78rem; color: var(--text-2); margin-top: .15rem; line-height: 1.4; }
"""

_SERVICES = [
    {
        "name": "User Manager",
        "desc": "Inspect and delete user accounts",
        "href": f"{_P}/users",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
            '<circle cx="9" cy="7" r="4"/>'
            '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
            '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
            "</svg>"
        ),
    },
    {
        "name": "Usage & Analytics",
        "desc": "Requests by endpoint and site-wide activity",
        "href": f"{_P}/usage",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M3 3v18h18"/>'
            '<rect x="7" y="12" width="3" height="6"/>'
            '<rect x="12" y="8" width="3" height="10"/>'
            '<rect x="17" y="4" width="3" height="14"/>'
            "</svg>"
        ),
    },
    {
        "name": "Comment Manager",
        "desc": "Read and delete user comments",
        "href": f"{_P}/comments",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'
            "</svg>"
        ),
    },
    {
        "name": "Banned IPs",
        "desc": "Review and lift permanent honeypot bans",
        "href": f"{_P}/bans",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
            '<line x1="9" y1="9" x2="15" y2="15"/>'
            '<line x1="15" y1="9" x2="9" y2="15"/>'
            "</svg>"
        ),
    },
    {
        "name": "Site Settings",
        "desc": "Registration mode and anti-abuse tuning",
        "href": f"{_P}/settings",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="3"/>'
            '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06'
            "a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09"
            "A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06"
            "A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09"
            "A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06"
            "A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09"
            "a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06"
            "A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09"
            'a1.65 1.65 0 0 0-1.51 1z"/>'
            "</svg>"
        ),
    },
    {
        "name": "Invite Codes",
        "desc": "Generate and manage registration invites",
        "href": f"{_P}/invites",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<rect x="1" y="4" width="22" height="16" rx="2" ry="2"/>'
            '<line x1="1" y1="10" x2="23" y2="10"/>'
            "</svg>"
        ),
    },
    {
        "name": "Periodic Tasks",
        "desc": "Enable, schedule, and monitor background pollers",
        "href": f"{_P}/periodic-tasks",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="10"/>'
            '<polyline points="12 6 12 12 16 14"/>'
            "</svg>"
        ),
    },
    {
        # Same crown shape as frontend assets/badge_premium.svg — the actual
        # badge shown next to a premium user's name — flattened to one fill
        # so it drops into this tile's flat monochrome icon slot.
        "name": "Premium Features",
        "desc": "Toggle each premium perk on or off site-wide",
        "href": f"{_P}/premium",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 -1.25 24 24"'
            ' fill="currentColor">'
            '<circle cx="2.7" cy="6" r="1.7"/><circle cx="12" cy="3.2" r="1.9"/><circle cx="21.3" cy="6" r="1.7"/>'
            '<path d="M2.7 8.1 7.7 11.5 12 5.6 16.3 11.5 21.3 8.1 19.8 16.3 4.2 16.3Z"/>'
            '<rect x="4.2" y="17.5" width="15.6" height="2.7" rx="1.35"/>'
            '<path d="M12 9.4 14.1 12 12 14.6 9.9 12Z" opacity=".5"/>'
            "</svg>"
        ),
    },
    {
        "name": "App Releases",
        "desc": "Android builds served to in-app updates",
        "href": f"{_P}/app-releases",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            f"{APP_RELEASES_ICON_PATHS}</svg>"
        ),
    },
    {
        "name": "Server Update",
        "desc": "Pull the latest version and restart",
        "href": f"{_P}/update",
        "icon": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"'
            ' fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
            f"{SERVER_UPDATE_ICON_PATHS}</svg>"
        ),
    },
]


def _render_dashboard() -> str:
    tiles = ""
    for svc in _SERVICES:
        tiles += (
            f'<a class="tile" href="{svc["href"]}">'
            f'<div class="tile-icon">{svc["icon"]}</div>'
            f'<div class="tile-body">'
            f'<div class="tile-name">{svc["name"]}</div>'
            f'<div class="tile-desc">{svc["desc"]}</div>'
            f"</div></a>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Admin &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_DASHBOARD_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>
  <header class="topbar">
    <div class="logo">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
    </div>
    <div class="brand">
      <span class="brand-name">Admin</span>
      <span class="brand-sub">renar</span>
    </div>
    <div class="topbar-fill"></div>
    <span class="admin-pill">Admin</span>
    {_logout_button()}
  </header>
  <div class="page">
    <h1 class="page-heading">Control Panel</h1>
    <p class="page-sub">Select a service to manage.</p>
    <div class="grid">{tiles}</div>
  </div>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def admin_dashboard(_: str = Depends(_require_admin)):
    return _render_dashboard()
