"""Watch-time and library statistics for the current user."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import EpisodeWatch, MediaItem, MediaType, User, WatchStatus

router = APIRouter(prefix="/stats", tags=["stats"])

DEFAULT_FILM_RUNTIME = 110  # minutes, used when runtime is unknown
DEFAULT_EPISODE_RUNTIME = 40


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _streaks(days: list[date]) -> tuple[int, int]:
    """(current, longest) streak of consecutive days with at least one episode."""
    if not days:
        return 0, 0
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    today = date.today()
    current = 0
    if (today - days[-1]).days <= 1:  # streak still alive today or as of yesterday
        current = 1
        for prev, cur in zip(reversed(days[:-1]), reversed(days[1:])):
            if (cur - prev).days == 1:
                current += 1
            else:
                break
    return current, longest


@router.get("")
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items: list[MediaItem] = (
        db.query(MediaItem).filter(MediaItem.user_id == user.id).all()
    )
    items_by_id = {item.id: item for item in items}
    watches: list[EpisodeWatch] = (
        db.query(EpisodeWatch)
        .join(MediaItem, EpisodeWatch.media_item_id == MediaItem.id)
        .filter(MediaItem.user_id == user.id)
        .all()
    )

    film_minutes = 0
    tv_minutes = 0
    films_watched = 0
    episodes_watched = 0
    shows_completed = 0
    shows_watching = 0
    youtube_watched = 0
    books_read = 0
    pages_read = 0
    favorites = 0
    genre_counter: Counter[str] = Counter()
    ratings: list[int] = []
    episodes_per_item: Counter[int] = Counter()

    for item in items:
        if item.is_favorite:
            favorites += 1
        if item.rating:
            ratings.append(item.rating)
        if item.genres:
            genre_counter.update(g.strip() for g in item.genres.split(",") if g.strip())

        if item.media_type == MediaType.film:
            if item.status == WatchStatus.completed:
                films_watched += 1
                film_minutes += item.runtime_minutes or DEFAULT_FILM_RUNTIME
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
            episodes_per_item[item.id] = eps
            tv_minutes += eps * (item.runtime_minutes or DEFAULT_EPISODE_RUNTIME)
        elif item.media_type == MediaType.youtube:
            if item.status == WatchStatus.completed:
                youtube_watched += 1
        elif item.media_type == MediaType.book:
            if item.status == WatchStatus.completed:
                books_read += 1
                pages_read += item.page_count or 0

    # ----- time-based stats from per-episode history -----
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    episodes_last_7_days = 0
    episodes_last_30_days = 0
    weekday_counter: Counter[str] = Counter()
    watch_days: set[date] = set()

    for w in watches:
        ts = _as_utc(w.watched_at)
        if ts is None:
            continue
        watch_days.add(ts.date())
        weekday_counter[ts.strftime("%A")] += 1
        if ts >= week_ago:
            episodes_last_7_days += 1
        if ts >= month_ago:
            episodes_last_30_days += 1

    current_streak, longest_streak = _streaks(sorted(watch_days))

    most_watched = []
    for item_id, count in episodes_per_item.most_common(5):
        if count == 0:
            continue
        item = items_by_id[item_id]
        most_watched.append({
            "title": item.title,
            "episodes": count,
            "minutes": count * (item.runtime_minutes or DEFAULT_EPISODE_RUNTIME),
            "poster_url": item.poster_url,
        })

    rating_distribution = Counter(ratings)
    by_status = Counter(item.status.value for item in items)
    by_type = Counter(item.media_type.value for item in items)

    return {
        "total_watch_minutes": film_minutes + tv_minutes,
        "film_minutes": film_minutes,
        "tv_minutes": tv_minutes,
        "films_watched": films_watched,
        "episodes_watched": episodes_watched,
        "shows_completed": shows_completed,
        "shows_watching": shows_watching,
        "youtube_watched": youtube_watched,
        "books_read": books_read,
        "pages_read": pages_read,
        "total_items": len(items),
        "favorites": favorites,
        "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "rating_distribution": {str(k): v for k, v in sorted(rating_distribution.items())},
        "episodes_last_7_days": episodes_last_7_days,
        "episodes_last_30_days": episodes_last_30_days,
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
        "most_active_day": weekday_counter.most_common(1)[0][0] if weekday_counter else None,
        "most_watched_shows": most_watched,
        "by_status": dict(by_status),
        "by_type": dict(by_type),
        "top_genres": [
            {"genre": g, "count": c} for g, c in genre_counter.most_common(5)
        ],
    }
