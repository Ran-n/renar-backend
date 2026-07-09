#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.282446
Revised: 2026/07/09 10:06:23.826801
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import notifier
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
    social,
    stats,
    tmdb,
    upcoming,
    youtube,
)
from .security import AbuseGuardMiddleware, OriginCheckMiddleware, SecurityHeadersMiddleware
from .usage import UsageTrackingMiddleware

# Schema is managed by Alembic — run `alembic upgrade head` before starting.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key.startswith("dev-only-"):
        _log.warning(
            "SECRET_KEY is the built-in dev default — tokens are forgeable. "
            "Set SECRET_KEY in .env before exposing this server."
        )
    checker = asyncio.create_task(notifier.run_periodic())
    yield
    checker.cancel()
    with suppress(asyncio.CancelledError):
        await checker


# openapi_url=None also kills /docs and /redoc — scanners use the schema to
# map every endpoint, so it stays off unless ENABLE_DOCS=true in .env.
app = FastAPI(
    title="Xoutaim API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)

if settings.abuse_guard_enabled:
    app.add_middleware(AbuseGuardMiddleware)
# Outermost of the app middlewares so it only records requests the router
# actually dispatched (it reads scope["route"], unset for short-circuited ones).
app.add_middleware(UsageTrackingMiddleware)
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
app.include_router(admin.router)


@app.get("/")
def home():
    # Lets a browser (e.g. a phone checking the server address) confirm
    # the API is reachable instead of getting a bare 404.
    return {"status": "ok", "message": "Connection to Xoutaim OK", "version": app.version}


@app.get("/health")
def health():
    return {"status": "ok"}
