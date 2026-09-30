#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.282446
Revised: 2026/09/30 09:38:44.861660
"""

import asyncio
import logging
import tomllib
from contextlib import asynccontextmanager, suppress
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, DBAPIError

from ._devserver import exit_when_orphaned
from .config import settings
from .database import engine
from .routers import (
    admin,
    auth,
    comments,
    events,
    export,
    images,
    imports,
    lists,
    media,
    notifications,
    premium,
    reviews,
    social,
    stats,
    svc,
    tmdb,
    upcoming,
)
from .social import notifier
from .users.security import AbuseGuardMiddleware, OriginCheckMiddleware, SecurityHeadersMiddleware
from .users.usage import UsageTrackingMiddleware

# Schema is managed by Alembic — run `alembic upgrade head` before starting.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
_log = logging.getLogger(__name__)


def backend_version() -> str:
    """Installed package version; falls back to pyproject.toml for source checkouts."""
    try:
        return _pkg_version("renar-backend")
    except PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject.open("rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (OSError, KeyError):
        _log.warning("backend version unknown: no dist metadata or pyproject.toml")
        return "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # As a reload worker, die with the reloader instead of becoming a
    # zombie that squats the port with stale code (see _devserver).
    exit_when_orphaned()
    # Every plain `def` route (most of the API) runs on this shared pool.
    # anyio's default of 40 was measured saturating during an ordinary grid
    # load: opening a poster-heavy view alone can fire 90+ concurrent
    # /tmdb/image requests, each holding a thread for its outbound TMDB/CDN
    # round trip — enough on its own to queue out other endpoints (e.g.
    # /upcoming) behind it for the length of that burst. The image proxy now
    # has its own isolated limiter (see routers/tmdb.py's _image_limiter), so
    # this pool mainly serves everything else; still raised from the default
    # for headroom under concurrent users.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 80
    if settings.secret_key.startswith("dev-only-"):
        _log.warning(
            "SECRET_KEY is the built-in dev default — tokens are forgeable. "
            "Set SECRET_KEY in .env before exposing this server."
        )
    checkers = notifier.start_periodic_tasks()
    yield
    for checker in checkers:
        checker.cancel()
    for checker in checkers:
        with suppress(asyncio.CancelledError):
            await checker


# openapi_url=None also kills /docs and /redoc — scanners use the schema to
# map every endpoint, so it stays off unless ENABLE_DOCS=true in .env.
app = FastAPI(
    title="Renar API",
    version=backend_version(),
    lifespan=lifespan,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

# UsageTrackingMiddleware added (and therefore wrapped) before AbuseGuard,
# so AbuseGuard sits outside it: a banned/flooded request is rejected
# before ever reaching UsageTracking, instead of reaching it and being
# filtered out there via scope["route"] (still unset for short-circuited
# requests, so a route that slips past AbuseGuard some other way is still
# never mis-recorded).
app.add_middleware(UsageTrackingMiddleware)
if settings.abuse_guard_enabled:
    app.add_middleware(AbuseGuardMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(OriginCheckMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
# reviews.router uses literal /media/reviews paths and must be registered
# before media.router's /media/{item_id} — Starlette matches route order, so
# the wildcard path param would otherwise swallow "reviews" as an item_id.
app.include_router(reviews.router)
app.include_router(media.router)
app.include_router(tmdb.router)
app.include_router(stats.router)
app.include_router(social.router)
app.include_router(comments.router)
app.include_router(lists.router)
app.include_router(notifications.router)
app.include_router(events.router)
app.include_router(images.router)
app.include_router(upcoming.router)
app.include_router(imports.router)
app.include_router(export.router)
app.include_router(premium.router)
app.include_router(admin.router)
app.include_router(svc.router)


@app.get("/")
def home():
    # Lets a browser (e.g. a phone checking the server address) confirm
    # the API is reachable instead of getting a bare 404.
    return {"status": "ok", "message": "Connection to Renar OK", "version": app.version}


@app.get("/health")
def health():
    return {"status": "ok"}


# psycopg3 auto-prepares statements reused ~5+ times per connection. DDL that
# alters/recreates a table (an Alembic migration, run out-of-process via
# `alembic upgrade head`) invalidates plans already cached on this app's own
# pooled connections from before the migration ran — the next query on one of
# those connections raises "cached plan must not change result type" (see
# docs/backlog.md). Rather than requiring a manual app restart after every
# migration, disposing the pool here self-heals it: only this one in-flight
# request (which was going to fail either way) gets a 503, and every request
# after it gets a fresh connection with no stale plan.
_STALE_PLAN_MARKER = "cached plan must not change result type"


@app.exception_handler(DBAPIError)
async def _handle_stale_prepared_plan(request: Request, exc: DBAPIError) -> JSONResponse:
    if _STALE_PLAN_MARKER not in str(exc.orig):
        raise exc
    _log.warning("stale prepared plan detected (likely post-migration) — disposing connection pool")
    engine.dispose()
    return JSONResponse(status_code=503, content={"detail": "Temporary server error, please retry"})


@app.exception_handler(DataError)
async def _handle_unstorable_value(request: Request, exc: DataError) -> JSONResponse:
    """Translate "this value doesn't fit the column it targets" into a 422.

    psycopg raises `DataError` (SQLAlchemy wraps it as `sqlalchemy.exc.DataError`)
    for a whole family of caller-supplied values Postgres refuses outright:
    an integer beyond `INTEGER`'s ±2**31 range (`NumericValueOutOfRange`), a
    string longer than a `String(n)` column (`StringDataRightTruncation`), a
    NUL byte anywhere in a text value. Every one of those is the *client's*
    data being wrong for the field, i.e. exactly what 422 means — but with no
    handler they escaped as unhandled 500s.

    Why one handler instead of per-field validators: the 2026-09-03 fuzz pass
    fixed this shape field-by-field (`SafeStr`, `PG_INT32_MAX`) for request
    *bodies*, where a Pydantic model gives you one obvious place to put the
    bound. The same crash reaches the DB through path params, query params
    and `Form(...)` fields too — `GET /media/{item_id}` with `item_id=2**40`,
    `GET /admin/comments?user_id=2**40`, every `int = Form(...)` on
    `POST /admin/settings` — across ~60 parameters on a dozen routers, with
    every future route free to reintroduce it. Postgres is the authority on
    what fits its own columns, so the check belongs at the one layer that
    always sees the answer. Per-field bounds stay where they already are:
    they give better messages, and they stop the round trip earlier.

    Not a silent swallow: the original driver error is logged at WARNING with
    the method and path, so a `DataError` caused by a *server-side* value
    (rather than a caller's) is still visible in the logs rather than being
    quietly relabelled a client error.
    """
    _log.warning("value rejected by the database as unstorable: %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=422,
        content={"detail": "A value in the request is out of range or otherwise unstorable for its field"},
    )


class _ShutdownCancellationSilencer:
    """Swallows the CancelledError that tears through an open connection
    (e.g. the SSE stream in routers/events.py) when the process is Ctrl+C'd.

    asyncio.CancelledError (and anyio.WouldBlock, raised as its proximate
    cause here) are BaseException subclasses, so they skip every
    `except Exception` in the FastAPI/Starlette stack — including
    ServerErrorMiddleware — and land straight in uvicorn's run_asgi, which
    logs them as "Exception in ASGI application" with a multi-frame
    traceback. The interrupt itself is expected and harmless; only the
    traceback is noise, so it's downgraded to one clean log line here,
    at the one layer outside the FastAPI middleware stack uvicorn calls
    directly.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except (asyncio.CancelledError, anyio.WouldBlock):
            if scope["type"] != "http":
                raise
            _log.info("connection torn down by shutdown: %s %s", scope.get("method"), scope.get("path"))


# What uvicorn actually serves. Kept separate from `app` so tests
# (TestClient(app), dependency_overrides, ...) keep using the plain
# FastAPI instance untouched.
asgi_app = _ShutdownCancellationSilencer(app)
