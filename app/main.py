import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import notifier
from .config import settings
from .routers import (
    auth, comments, images, media, notifications, social, stats, tmdb,
)

# Schema is managed by Alembic — run `alembic upgrade head` before starting.


@asynccontextmanager
async def lifespan(app: FastAPI):
    checker = asyncio.create_task(notifier.run_periodic())
    yield
    checker.cancel()


app = FastAPI(title="Xoutaim API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(media.router)
app.include_router(tmdb.router)
app.include_router(stats.router)
app.include_router(social.router)
app.include_router(comments.router)
app.include_router(notifications.router)
app.include_router(images.router)


@app.get("/health")
def health():
    return {"status": "ok"}
