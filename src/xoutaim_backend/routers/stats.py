#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.713668
Revised: 2026/07/10 08:47:47.421329

Watch-time and library statistics for the current user.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_premium
from ..database import get_db
from ..models import EpisodeWatch, LibraryEntry, MediaType, User, WatchStatus
from ..titles import WITH_TITLE_GENRES

router = APIRouter(prefix="/stats", tags=["stats"])

DEFAULT_FILM_RUNTIME = 110  # minutes, used when runtime is unknown
DEFAULT_EPISODE_RUNTIME = 40


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _streaks(days: list[date]) -> tuple[int, int]:
    """(current, longest) streak of consecutive days with at least one episode."""
    if not days:
        return 0, 0
    longest = run = 1
    for prev, cur in zip(days, days[1:], strict=False):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    today = date.today()
    current = 0
    if (today - days[-1]).days <= 1:  # streak still alive today or as of yesterday
        current = 1
        for prev, cur in zip(reversed(days[:-1]), reversed(days[1:]), strict=False):
            if (cur - prev).days == 1:
                current += 1
            else:
                break
    return current, longest


@router.get("")
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items: list[LibraryEntry] = (
        db.query(LibraryEntry).options(*WITH_TITLE_GENRES).filter(LibraryEntry.user_id == user.id).all()
    )
    items_by_id = {item.id: item for item in items}
    watches: list[EpisodeWatch] = (
        db.query(EpisodeWatch)
        .join(LibraryEntry, EpisodeWatch.media_item_id == LibraryEntry.id)
        .filter(LibraryEntry.user_id == user.id)
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
        genre_counter.update(item.genres)

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
        elif item.media_type == MediaType.book and item.status == WatchStatus.completed:
            books_read += 1
            pages_read += item.page_count or 0

    # ----- time-based stats from per-episode history -----
    now = datetime.now(UTC)
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
    for item_id, count in episodes_per_item.most_common(20):
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
        "activity_by_weekday": dict(weekday_counter),
        "most_watched_shows": most_watched,
        "by_status": dict(by_status),
        "by_type": dict(by_type),
        "top_genres": [{"genre": g, "count": c} for g, c in genre_counter.most_common(20)],
    }


def _total_watch_minutes_by_user(db: Session) -> dict[int, int]:
    """Total film + tv watch minutes for every user, keyed by user id."""
    totals: dict[int, int] = defaultdict(int)
    for item in db.query(LibraryEntry).all():
        if item.media_type == MediaType.film and item.status == WatchStatus.completed:
            totals[item.user_id] += item.runtime_minutes or DEFAULT_FILM_RUNTIME
        elif item.media_type == MediaType.tv_show:
            eps = item.episodes_watched or 0
            if item.status == WatchStatus.completed and eps == 0 and item.total_episodes:
                eps = item.total_episodes
            totals[item.user_id] += eps * (item.runtime_minutes or DEFAULT_EPISODE_RUNTIME)
    return totals


@dataclass(frozen=True)
class RankingMetric:
    """One leaderboard: a display label, the unit its value is in (so the
    frontend knows how to format it), and how to compute per-user totals.
    Add an entry here to add a new ranking — /stats/ranking/metrics and
    /stats/ranking?metric=... both pick it up automatically."""

    key: str
    label: str
    unit: str  # "minutes" | "count"
    compute: Callable[[Session], dict[int, int]]


RANKING_METRICS: dict[str, RankingMetric] = {
    m.key: m
    for m in [
        RankingMetric("watch_time", "Total watch time", "minutes", _total_watch_minutes_by_user),
    ]
}


@router.get("/ranking/metrics")
def get_ranking_metrics(user: User = Depends(require_premium)):
    """Which leaderboards exist, so the frontend can offer a metric picker
    without hardcoding the list."""
    return [{"key": m.key, "label": m.label, "unit": m.unit} for m in RANKING_METRICS.values()]


@router.get("/ranking")
def get_ranking(
    metric: str = "watch_time", db: Session = Depends(get_db), user: User = Depends(require_premium)
):
    """Where a premium user stands against everyone else on the given metric.
    Premium-gated at the router level — the frontend's locked card mirrors
    this, it doesn't enforce it."""
    ranking_metric = RANKING_METRICS.get(metric)
    if ranking_metric is None:
        raise HTTPException(status_code=404, detail=f"Unknown ranking metric: {metric}")
    totals = ranking_metric.compute(db)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    total_users = len(ranked)
    rank = next((i + 1 for i, (uid, _value) in enumerate(ranked) if uid == user.id), total_users + 1)
    return {
        "metric": ranking_metric.key,
        "label": ranking_metric.label,
        "unit": ranking_metric.unit,
        "rank": rank,
        "total_users": total_users,
        "value": totals.get(user.id, 0),
        "percentile": round((total_users - rank + 1) / total_users * 100, 1) if total_users else None,
    }
