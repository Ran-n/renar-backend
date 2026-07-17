#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.282446
Revised: 2026/07/18 00:26:58.614713
"""

import asyncio
import logging
import tomllib
from contextlib import asynccontextmanager, suppress
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ._devserver import exit_when_orphaned
from .config import settings
from .routers import (
    admin,
    auth,
    books,
    comments,
    images,
    imports,
    media,
    notifications,
    premium,
    social,
    stats,
    svc,
    tmdb,
    upcoming,
    youtube,
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
app.include_router(media.router)
app.include_router(tmdb.router)
app.include_router(stats.router)
app.include_router(social.router)
app.include_router(comments.router)
app.include_router(notifications.router)
app.include_router(images.router)
app.include_router(upcoming.router)
app.include_router(books.router)
app.include_router(youtube.router)
app.include_router(imports.router)
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
