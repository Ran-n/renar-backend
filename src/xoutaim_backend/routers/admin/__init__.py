#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 14:51:05.196725

Admin router package.

Aggregates all domain-specific sub-routers into a single APIRouter that
main.py registers as ``app.include_router(admin.router)``.

Sub-module layout
-----------------
dashboard   — admin landing page (service tiles, quick links)
users       — user list, detail view, library, and all user-action POSTs
analytics   — site-wide usage stats and per-endpoint caller breakdown
moderation  — comment review/deletion and banned-IP management
settings    — site settings read/write
invites     — invite-code generation and lifecycle management
_html       — shared CSS constants, chart helpers, HTML utilities
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from . import analytics, dashboard, invites, moderation, users
from . import settings as settings_panel
from ._html import _P

router = APIRouter(prefix=_P, tags=["admin"])

# The admin root path — registered here (not in dashboard.py) because FastAPI
# rejects including a sub-router that has both an empty prefix AND an empty
# route path. The trailing-slash variant lives in dashboard.router ("/").
router.add_api_route(
    "",
    dashboard.admin_dashboard,
    methods=["GET"],
    response_class=HTMLResponse,
    include_in_schema=False,
)

router.include_router(dashboard.router)
router.include_router(users.router)
router.include_router(analytics.router)
router.include_router(moderation.router)
router.include_router(settings_panel.router)
router.include_router(invites.router)
