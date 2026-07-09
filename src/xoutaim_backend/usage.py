#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/09 09:30:00.000000
Revised: 2026/07/09 13:01:54.791296

Per-endpoint usage tracking.

UsageTrackingMiddleware records one aggregated counter per (HTTP method, route
template, user) in the endpoint_stats table. It keys on the route *template*
(`/media/{item_id}`, never `/media/42`), so the table is bounded by the number
of endpoints rather than by traffic — an upserted counter, never one row per
request (mirroring how the abuse guard persists strikes).

Only requests the router actually dispatched are counted: `scope["route"]` is
set by Starlette during routing, so anything short-circuited earlier by the
abuse guard (bans, rate-limit 429s) never reaches this and isn't counted. The
admin panel's own pages are excluded so watching the dashboard doesn't inflate
the numbers it shows.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .auth import user_id_from_token
from .config import settings
from .database import SessionLocal
from .models import EndpointStat, RequestDay, User, utcnow

_log = logging.getLogger(__name__)

# Infrastructure / self-referential paths that aren't real product usage.
_UNTRACKED_PATHS = frozenset({"/", "/health", "/robots.txt", "/openapi.json", "/docs", "/redoc", "/favicon.ico"})


def _bearer_user_id(request: Request) -> int | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return user_id_from_token(header[7:])
    return None


def _record(method: str, path: str, user_id: int | None) -> None:
    """Atomically bump the (method, path, user) counter, inserting it if new.

    The increment is a server-side UPDATE (not read-modify-write) so concurrent
    requests can't lose counts; a lost insert race only ever creates a duplicate
    row, which still sums correctly.
    """
    with SessionLocal() as db:
        query = db.query(EndpointStat).filter(EndpointStat.method == method, EndpointStat.path == path)
        if user_id is None:
            query = query.filter(EndpointStat.user_id.is_(None))
        else:
            query = query.filter(EndpointStat.user_id == user_id)
        updated = query.update(
            {EndpointStat.count: EndpointStat.count + 1, EndpointStat.last_at: utcnow()},
            synchronize_session=False,
        )
        if not updated:
            # A self-delete (DELETE /auth/me) removes the user before this
            # post-response hook runs; attribute that trailing request to no
            # one rather than leaving a dangling user_id (a FK violation on
            # Postgres, an orphan row on SQLite).
            if user_id is not None and db.get(User, user_id) is None:
                user_id = None
            db.add(EndpointStat(method=method, path=path, user_id=user_id, count=1, last_at=utcnow()))
        if user_id is not None:
            _record_request_day(db, user_id)
        db.commit()


def _record_request_day(db, user_id: int) -> None:
    """Bump the (user, today) request counter for the per-day chart. Skips the
    insert if the user was just deleted (same trailing-self-delete guard)."""
    today = utcnow().date()
    updated = (
        db.query(RequestDay)
        .filter(RequestDay.user_id == user_id, RequestDay.day == today)
        .update({RequestDay.count: RequestDay.count + 1}, synchronize_session=False)
    )
    if not updated and db.get(User, user_id) is not None:
        db.add(RequestDay(user_id=user_id, day=today, count=1))


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # Analytics must never break a request — surface failures to the log,
        # but always return the response.
        try:
            route = request.scope.get("route")
            template = getattr(route, "path", None)
            admin_prefix = settings.admin_path.rstrip("/") or "/admin"
            if template and template not in _UNTRACKED_PATHS and not template.startswith(admin_prefix):
                _record(request.method, template, _bearer_user_id(request))
        except Exception:
            _log.exception("usage tracking failed for %s %s", request.method, request.url.path)
        return response
