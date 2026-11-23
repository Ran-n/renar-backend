#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/23 08:13:13.022305
Revised: 2026/11/23 10:25:05.880890

Home's "Watch Next" list (`GET /media?status_filter=watching&order_by=last_watched`):
which in-progress entries it shows, in what order, and keeping the
`last_watched_at` it orders by true to the user's real watch history.

Order: #1 is what the user watched last. Then the shows they've started
that have a new episode (an unwatched one that aired after their last
watch of that show), newest air date first. Then everything else by last
watch, newest first, and last the entries never watched (imported as
"watching" but never started: none of their episodes is news). Ties break
on the newest entry, so the order never depends on how the database
happens to return equal rows.

A tv_show caught up on everything aired so far is left out until a new
episode airs. That's checked live against `episodes`/`episode_watches`, not
the stored `status`, which only changes on a write and goes stale as soon as
an episode airs with the user doing nothing.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

from sqlalchemy import Date, and_, cast, exists, func, or_, select, update
from sqlalchemy.orm import Session

from ..models import Episode, EpisodeWatch, LibraryEntry, MediaType, Title, WatchEvent, WatchStatus

# a timestamp older than any real watch, so GREATEST/comparisons never see NULL
_NEVER = datetime(1970, 1, 1, tzinfo=UTC)


def _unwatched_aired_conditions() -> list:
    """Conditions on `Episode`, correlated to the outer `LibraryEntry` row:
    the episode has aired and this entry has no `EpisodeWatch` for it.

    The inner EXISTS sits two query levels below the `LibraryEntry` it must
    match. SQLAlchemy only auto-correlates one level, so without
    `.correlate(LibraryEntry, Episode)` it silently read `media_items` as a
    fresh, uncorrelated table: "has *any* entry watched this season/episode
    number", which matched almost everywhere and hid nearly every show."""
    return [
        Episode.title_id == LibraryEntry.title_id,
        Episode.air_date.isnot(None),
        Episode.air_date <= date.today(),
        ~exists()
        .where(
            EpisodeWatch.media_item_id == LibraryEntry.id,
            EpisodeWatch.season == Episode.season,
            EpisodeWatch.episode == Episode.episode_number,
        )
        .correlate(LibraryEntry, Episode),
    ]


def has_unwatched_aired_episode():
    """EXISTS: this entry has an aired episode it hasn't watched."""
    return exists().where(and_(*_unwatched_aired_conditions()))


def has_known_aired_episode():
    """EXISTS: at least one aired episode is synced for this title. Without
    it, a show with no episode data yet (season list never pulled, brand-new
    addition) would look exactly like a caught-up one and vanish."""
    return exists().where(
        Episode.title_id == LibraryEntry.title_id, Episode.air_date.isnot(None), Episode.air_date <= date.today()
    )


def watch_next_filter():
    """Keep films, shows with no episode data yet, and shows with something
    aired left to watch. Films short-circuit before the correlated EXISTS."""
    return or_(Title.media_type != MediaType.tv_show, ~has_known_aired_episode(), has_unwatched_aired_episode())


def newest_new_episode_aired():
    """Scalar: air date of this entry's newest unwatched episode that aired
    after its last watch, or NULL. NULL for an entry never watched, since
    every episode of a show never started isn't "new"."""
    return (
        select(func.max(Episode.air_date))
        .where(
            *_unwatched_aired_conditions(),
            LibraryEntry.last_watched_at.isnot(None),
            Episode.air_date > cast(LibraryEntry.last_watched_at, Date),
        )
        .correlate(LibraryEntry)
        .scalar_subquery()
    )


def watch_next_order() -> tuple:
    """ORDER BY clauses for the recency part: last watch first, never-watched
    last, newest entry first on ties. rank_watch_next does the rest."""
    return LibraryEntry.last_watched_at.desc().nullslast(), LibraryEntry.id.desc()


def rank_watch_next(rows: Iterable[Sequence]) -> list[LibraryEntry]:
    """Final order from `(entry, newest_new_episode_aired)` rows already in
    watch_next_order: the first stays #1, then rows with a new episode by
    air date (newest first; Python's sort is stable, so equal dates keep
    recency order), then the rest as they came. In Python, not SQL, because
    "the first row is exempt" can't be one ORDER BY key; the list is one
    user's in-progress shows, never large."""
    rows = list(rows)
    if not rows:
        return []
    (head, _), rest = rows[0], rows[1:]
    fresh = sorted((r for r in rest if r[1] is not None), key=lambda r: r[1], reverse=True)
    stale = [r for r in rest if r[1] is None]
    return [head, *(entry for entry, _ in fresh + stale)]


def restamp_last_watched(db: Session, user_id: int) -> int:
    """Set each of the user's in-progress or finished entries'
    `last_watched_at` to its latest real watch (episode or watch event), when
    that is newer than what it has. Imports write watch history with its real
    dates but never touched this column, so every imported show sorted as
    "never watched". Never moves a stamp backwards: a newer stamp from a
    status change made in the app stays. Returns the rows changed; the caller
    commits."""
    latest_episode = (
        select(func.max(EpisodeWatch.watched_at)).where(EpisodeWatch.media_item_id == LibraryEntry.id).scalar_subquery()
    )
    latest_event = (
        select(func.max(WatchEvent.watched_at)).where(WatchEvent.media_item_id == LibraryEntry.id).scalar_subquery()
    )
    latest = func.greatest(latest_episode, latest_event)
    result = db.execute(
        update(LibraryEntry)
        .where(
            LibraryEntry.user_id == user_id,
            LibraryEntry.status.in_((WatchStatus.watching, WatchStatus.completed)),
            latest > func.coalesce(LibraryEntry.last_watched_at, _NEVER),
        )
        .values(last_watched_at=latest)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount
