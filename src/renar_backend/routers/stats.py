#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.713668
Revised: 2026/11/10 09:48:06.601691

Watch-time and library statistics for the current user.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..catalog.titles import WITH_TITLE_GENRES
from ..constants import DEFAULT_EPISODE_RUNTIME, DEFAULT_FILM_RUNTIME
from ..database import get_db
from ..models import AppCounters, EpisodeWatch, LibraryEntry, MediaType, User, WatchStatus
from ..users.auth import get_current_user, require_premium
from ..users.premium import feature_enabled

router = APIRouter(prefix="/stats", tags=["stats"])
_log = logging.getLogger(__name__)


def _runtime_or_default(runtime_minutes: int | None, default: int) -> int:
    """`runtime_minutes or default` looks equivalent but is wrong: an
    explicit 0 (a real, schema-allowed value) is falsy in Python, so `or`
    would silently substitute the default. Only None means "unknown" — mirrors
    the trigger SQL's COALESCE(runtime_minutes, default), which is NULL-only."""
    return default if runtime_minutes is None else runtime_minutes


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
    # only the timestamp is used below — selecting the one column skips ORM
    # hydration of every watch row, which dominated this endpoint's time
    watched_ats: list[datetime | None] = list(
        db.scalars(
            select(EpisodeWatch.watched_at)
            .join(LibraryEntry, EpisodeWatch.media_item_id == LibraryEntry.id)
            .where(LibraryEntry.user_id == user.id)
        )
    )

    film_minutes = 0
    tv_minutes = 0
    films_watched = 0
    episodes_watched = 0
    shows_completed = 0
    shows_watching = 0
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
                film_minutes += _runtime_or_default(item.runtime_minutes, DEFAULT_FILM_RUNTIME)
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
            tv_minutes += eps * _runtime_or_default(item.runtime_minutes, DEFAULT_EPISODE_RUNTIME)

    # ----- time-based stats from per-episode history -----
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    episodes_last_7_days = 0
    episodes_last_30_days = 0
    weekday_counter: Counter[str] = Counter()
    watch_days: set[date] = set()

    for watched_at in watched_ats:
        ts = _as_utc(watched_at)
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
            "minutes": count * _runtime_or_default(item.runtime_minutes, DEFAULT_EPISODE_RUNTIME),
            "poster_url": item.poster_url,
        })

    decile_distribution: Counter[str] = Counter()
    for r in ratings:
        bucket_start = ((r - 1) // 10) * 10 + 1
        bucket_end = min(bucket_start + 9, 100)
        label = f"{bucket_start}-{bucket_end}"
        decile_distribution[label] += 1
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
        "total_items": len(items),
        "favorites": favorites,
        "avg_rating": round(sum(ratings) / len(ratings)) if ratings else None,
        "rating_distribution": dict(sorted(decile_distribution.items())),
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


def _total_watch_minutes_by_user(db: Session, user_id: int | None = None) -> dict[int, int]:
    """Total film + tv watch minutes for every user, keyed by user id — an
    independent, from-scratch computation. Not used by request-time code
    (which reads the trigger-maintained User.total_watch_minutes column
    directly, see RankingMetric below); this exists so tests can verify the
    Postgres triggers added in migration a7c2e9f4b816 actually keep that
    column correct, by comparing against this."""
    totals: dict[int, int] = defaultdict(int)
    query = db.query(LibraryEntry)
    if user_id is not None:
        query = query.filter(LibraryEntry.user_id == user_id)
    for item in query.all():
        if item.media_type == MediaType.film and item.status == WatchStatus.completed:
            totals[item.user_id] += _runtime_or_default(item.runtime_minutes, DEFAULT_FILM_RUNTIME)
        elif item.media_type == MediaType.tv_show:
            eps = item.episodes_watched or 0
            if item.status == WatchStatus.completed and eps == 0 and item.total_episodes:
                eps = item.total_episodes
            totals[item.user_id] += eps * _runtime_or_default(item.runtime_minutes, DEFAULT_EPISODE_RUNTIME)
    return totals


@dataclass(frozen=True)
class RankingMetric:
    """One leaderboard: a display label, the unit its value is in (so the
    frontend knows how to format it), and the indexed User column a Postgres
    trigger keeps current (see migration a7c2e9f4b816 — total_watch_minutes
    is maintained atomically by the database itself, in the same transaction
    as the row that changed it, not by application code remembering to call
    a recompute function after every write. That "remember to call it"
    pattern is exactly the drift risk docs/design-decisions.md's
    stored-aggregate rule exists to rule out — see ALLOWED_AGGREGATES).

    Add an entry here to add a new ranking: it needs its own indexed User
    column plus a migration-level trigger to maintain it — there's no
    Python-level write path to hook, by design."""

    key: str
    label: str
    unit: str  # "minutes" | "count"
    attr: str  # name of the persisted, trigger-maintained column on User


RANKING_METRICS: dict[str, RankingMetric] = {
    m.key: m
    for m in [
        RankingMetric("watch_time", "Total watch time", "minutes", "total_watch_minutes"),
    ]
}


def _compute_ranking(db: Session, user: User, ranking_metric: RankingMetric) -> dict:
    """Where `user` stands on this metric. `ahead` is one conditional-count
    query — no scan of anyone's library, including the viewer's own, since
    the column is already kept current by a database trigger, not computed
    here. `total_users` is a single-row lookup (app_counters), not a
    COUNT(*) FROM users: COUNT(*) has no O(1) shortcut in Postgres — MVCC
    means every row's visibility must be checked regardless of indexing — so
    at real scale that would mean scanning the entire users table on every
    ranking request just to answer the denominator.

    Only email_confirmed users count, on both sides of this fraction — a
    hand-registered throwaway account otherwise pads the "ahead of me" count
    and app_counters.total_users equally (see db_triggers.py's confirmed-only
    counter and TODO.md's ranking-exploit note). The viewing `user`
    doesn't have to be confirmed themselves to see their own (likely poor)
    standing — only who counts as competition is filtered."""
    column = getattr(User, ranking_metric.attr)
    own_value = getattr(user, ranking_metric.attr)
    ahead = (
        db.query(func.count(User.id))
        .filter(
            User.email_confirmed.is_(True),
            or_(
                column > own_value,
                and_(column == own_value, User.created_at < user.created_at),
            ),
        )
        .scalar()
    )
    total_users = db.query(AppCounters.total_users).filter(AppCounters.id == 1).scalar() or 0
    rank = ahead + 1
    return {
        "metric": ranking_metric.key,
        "label": ranking_metric.label,
        "unit": ranking_metric.unit,
        "rank": rank,
        "total_users": total_users,
        "value": own_value,
        "percentile": round(rank / total_users * 100, 1) if total_users else None,
    }


def _all_rankings(db: Session, user: User) -> list[dict]:
    """Every metric's ranking, ordered so the metric the user is best
    positioned on (smallest rank/total_users fraction) comes first."""
    rankings = [_compute_ranking(db, user, m) for m in RANKING_METRICS.values()]
    rankings.sort(key=lambda r: r["rank"] / r["total_users"] if r["total_users"] else 1)
    return rankings


@router.get("/ranking/metrics")
def get_ranking_metrics(db: Session = Depends(get_db), user: User = Depends(require_premium)):
    """Which leaderboards exist, so the frontend can offer a metric picker
    without hardcoding the list."""
    if not feature_enabled("ranking"):
        raise HTTPException(status_code=403, detail="Ranking is currently disabled")
    return [{"key": r["metric"], "label": r["label"], "unit": r["unit"]} for r in _all_rankings(db, user)]


@router.get("/ranking")
def get_ranking(metric: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_premium)):
    """Where a premium user stands against everyone else on the given metric —
    defaults to whichever metric they're best positioned on. Premium-gated at
    the router level — the frontend's locked card mirrors this, it doesn't
    enforce it.

    Bundles the full metrics list into the response too (as "metrics") so a
    single request is enough to render tabs plus the selected standing,
    instead of needing a round trip to /ranking/metrics first."""
    if not feature_enabled("ranking"):
        raise HTTPException(status_code=403, detail="Ranking is currently disabled")
    rankings = _all_rankings(db, user)
    if not rankings:
        raise HTTPException(status_code=404, detail="No ranking metrics configured")
    if metric is None:
        selected = rankings[0]
    else:
        selected = next((r for r in rankings if r["metric"] == metric), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"Unknown ranking metric: {metric}")
    return {
        **selected,
        "metrics": [{"key": r["metric"], "label": r["label"], "unit": r["unit"]} for r in rankings],
    }
