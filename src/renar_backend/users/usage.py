#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/09 09:30:00.000000
Revised: 2026/09/02 10:57:11.499049

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

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..config import settings
from ..database import SessionLocal
from ..models import EndpointStat, RequestDay, User, utcnow
from .auth import user_id_from_token

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

    For authenticated requests the unique constraint (method, path, user_id) is
    fully non-nullable, so a true PostgreSQL INSERT … ON CONFLICT DO UPDATE
    upsert is safe and serialises concurrent inserts without losing any count.

    For anonymous requests (user_id IS NULL) PostgreSQL unique constraints treat
    NULL values as distinct, so ON CONFLICT never fires against a NULL key — we
    fall back to UPDATE-or-INSERT for that minority path.  Anonymous endpoint
    traffic is inherently low-concurrency (rate-limited before it reaches here),
    so the residual race is acceptable and mirrors the previous behaviour.
    """
    with SessionLocal() as db:
        now = utcnow()
        if user_id is not None:
            # Self-delete guard: a DELETE /auth/me removes the user before this
            # post-response hook runs; check once here so both upserts can skip
            # cleanly without each doing their own existence query.
            user_exists = db.get(User, user_id) is not None
            if not user_exists:
                user_id = None  # attribute the trailing request to no one

        if user_id is not None:
            # True atomic upsert: concurrent inserts on the same key are merged
            # by Postgres rather than racing to a UniqueViolation.
            stmt = (
                pg_insert(EndpointStat)
                .values(method=method, path=path, user_id=user_id, count=1, last_at=now)
                .on_conflict_do_update(
                    constraint="uq_endpoint_stat",
                    set_={
                        "count": EndpointStat.count + 1,
                        "last_at": now,
                    },
                )
            )
            db.execute(stmt)
            _record_request_day(db, user_id)
        else:
            updated = (
                db.query(EndpointStat)
                .filter(
                    EndpointStat.method == method,
                    EndpointStat.path == path,
                    EndpointStat.user_id.is_(None),
                )
                .update(
                    {EndpointStat.count: EndpointStat.count + 1, EndpointStat.last_at: now},
                    synchronize_session=False,
                )
            )
            if not updated:
                db.add(EndpointStat(method=method, path=path, user_id=None, count=1, last_at=now))
        db.commit()


def _record_request_day(db: Session, user_id: int) -> None:
    """Bump the (user, today) request counter for the per-day chart.

    Uses a true upsert so concurrent requests from the same user on the same
    calendar day never race to a UniqueViolation on uq_request_day.  The caller
    (_record) has already verified the user still exists, so no extra guard here.
    """
    today = utcnow().date()
    stmt = (
        pg_insert(RequestDay)
        .values(user_id=user_id, day=today, count=1)
        .on_conflict_do_update(
            constraint="uq_request_day",
            set_={"count": RequestDay.count + 1},
        )
    )
    db.execute(stmt)


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
