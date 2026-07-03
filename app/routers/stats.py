"""Watch-time and library statistics for the current user."""
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import MediaItem, MediaType, User, WatchStatus

router = APIRouter(prefix="/stats", tags=["stats"])

DEFAULT_FILM_RUNTIME = 110  # minutes, used when TMDB runtime is unknown
DEFAULT_EPISODE_RUNTIME = 40


@router.get("")
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items: list[MediaItem] = (
        db.query(MediaItem).filter(MediaItem.user_id == user.id).all()
    )

    total_minutes = 0
    films_watched = 0
    episodes_watched = 0
    shows_completed = 0
    shows_watching = 0
    youtube_watched = 0
    genre_counter: Counter[str] = Counter()
    ratings: list[int] = []

    for item in items:
        if item.rating:
            ratings.append(item.rating)
        if item.genres:
            genre_counter.update(g.strip() for g in item.genres.split(",") if g.strip())

        if item.media_type == MediaType.film:
            if item.status == WatchStatus.completed:
                films_watched += 1
                total_minutes += item.runtime_minutes or DEFAULT_FILM_RUNTIME
        elif item.media_type == MediaType.tv_show:
            if item.status == WatchStatus.completed:
                shows_completed += 1
            elif item.status == WatchStatus.watching:
                shows_watching += 1
            eps = item.episodes_watched or 0
            # a completed show with no per-episode tracking counts in full
            if item.status == WatchStatus.completed and eps == 0 and item.total_episodes:
                eps = item.total_episodes
            episodes_watched += eps
            total_minutes += eps * (item.runtime_minutes or DEFAULT_EPISODE_RUNTIME)
        elif item.media_type == MediaType.youtube:
            if item.status == WatchStatus.completed:
                youtube_watched += 1

    by_status = Counter(item.status.value for item in items)
    by_type = Counter(item.media_type.value for item in items)

    return {
        "total_watch_minutes": total_minutes,
        "films_watched": films_watched,
        "episodes_watched": episodes_watched,
        "shows_completed": shows_completed,
        "shows_watching": shows_watching,
        "youtube_watched": youtube_watched,
        "total_items": len(items),
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "by_status": dict(by_status),
        "by_type": dict(by_type),
        "top_genres": [
            {"genre": g, "count": c} for g, c in genre_counter.most_common(5)
        ],
    }
