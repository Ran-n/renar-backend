from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, comments, media, social, stats, tmdb

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Xoutaim API", version="0.1.0")

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


@app.get("/health")
def health():
    return {"status": "ok"}
