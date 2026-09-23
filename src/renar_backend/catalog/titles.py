#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 00:00:00.000000
Revised: 2026/09/17 10:04:39.850028

Shared Title resolution: every place that addresses a global title by
(media_type, tmdb_id-or-title text) — library adds, imports, comments,
cross-user ratings — resolves it through here, so there is exactly one
implementation of the identity rules described on the Title model.
"""

import logging

from sqlalchemy import func as db_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Comment,
    Episode,
    EpisodeRatingAggregate,
    Genre,
    LibraryEntry,
    MediaType,
    Title,
    TmdbCache,
    normalize_title_key,
)

_log = logging.getLogger(__name__)

# Reading a library entry's genres walks title_ref -> genre_rows; queries that
# return many entries attach this so it's 3 queries total instead of 1 + 2·N.
# poster_url/backdrop_url also walk custom_poster_image/custom_backdrop_image
# for premium users, so those ride along here too instead of firing 1 query
# per entry that has a custom override set.
WITH_TITLE_GENRES = (
    selectinload(LibraryEntry.title_ref).selectinload(Title.genre_rows),
    selectinload(LibraryEntry.custom_poster_image),
    selectinload(LibraryEntry.custom_backdrop_image),
)


def resolve_genres(db: Session, names: list[str] | None) -> list[Genre]:
    """Map genre names to Genre rows, creating missing ones.

    Names are trimmed and deduplicated; creation is race-safe (parallel
    import workers can hit the same new genre) via a savepoint per insert.
    """
    cleaned = list(dict.fromkeys(n.strip()[:100] for n in (names or []) if n and n.strip()))
    genres: list[Genre] = []
    for name in cleaned:
        genre = db.query(Genre).filter(Genre.name == name).first()
        if genre is None:
            try:
                with db.begin_nested():
                    genre = Genre(name=name)
                    db.add(genre)
            except IntegrityError:
                # another session created it between our SELECT and INSERT
                genre = db.query(Genre).filter(Genre.name == name).first()
        if genre is not None:
            genres.append(genre)
        else:
            _log.error("genre %r could not be created nor found after insert race", name)
    return genres


def find_title(
    db: Session, media_type: MediaType, tmdb_id: int | None, title: str | None, *, tvdb_id: int | None = None
) -> Title | None:
    """Locate the shared Title row by its identity, in priority order:
    tmdb_id, then tvdb_id (TheTVDB v4 fallback for a show TMDB hasn't
    matched — see users/tvtime_import.py), then the normalized title text.
    Returns None when nobody has created that title yet.
    """
    query = db.query(Title).filter(Title.media_type == media_type)
    if tmdb_id is not None:
        return query.filter(Title.tmdb_id == tmdb_id).first()
    if tvdb_id is not None:
        return query.filter(Title.tvdb_id == tvdb_id).first()
    if title:
        return query.filter(Title.tmdb_id.is_(None), Title.title_key == normalize_title_key(title)).first()
    return None


def escape_like(s: str) -> str:
    """Escape SQL LIKE/ILIKE wildcard characters in a user-supplied search
    string so they are matched literally rather than as patterns.

    Escapes ``\\``, ``%``, and ``_`` with a leading backslash; callers must
    pass ``escape="\\"`` to SQLAlchemy's ``like``/``ilike`` so PostgreSQL
    knows to interpret ``\\`` as the escape prefix.  Without this, a search
    for ``100%`` matches every title containing "100" followed by anything,
    and a search for ``_`` matches any single character.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_local_titles(db: Session, media_type: MediaType, query: str, limit: int = 10) -> list[Title]:
    """Fallback for /tmdb/search when TMDB is unreachable: substring match
    against titles Renar already knows about (tmdb_id required — these feed
    the same add/detail flow as live TMDB results, which key off it)."""
    return (
        db.query(Title)
        .filter(
            Title.media_type == media_type,
            Title.tmdb_id.isnot(None),
            Title.title.ilike(f"%{escape_like(query)}%", escape="\\"),
        )
        .order_by(Title.title)
        .limit(limit)
        .all()
    )


def popular_local_titles(db: Session, media_type: MediaType, limit: int = 20) -> list[Title]:
    """Fallback for /tmdb/trending and /tmdb/popular when TMDB is
    unreachable: titles ranked by how many users have added them, since
    there's no TMDB popularity score to fall back on locally."""
    return (
        db.query(Title)
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(Title.media_type == media_type, Title.tmdb_id.isnot(None))
        .group_by(Title.id)
        .order_by(db_func.count(LibraryEntry.id).desc())
        .limit(limit)
        .all()
    )


def backfill_title_tmdb_id(
    db: Session,
    title_row: Title,
    tmdb_id: int,
    *,
    title: str | None = None,
    poster_url: str | None = None,
    runtime_minutes: int | None = None,
    total_episodes: int | None = None,
) -> None:
    """Fill in tmdb_id (and any metadata the row is still missing) on a Title
    that was created without a match — e.g. a TV Time import row that
    resolved to nothing at the time, later re-imported after a transient
    TMDB failure clears up. Without this, a title-text match against that
    row's existing (tmdb_id-less) Title reconciles the entry but never
    upgrades the Title itself, so it stays degraded forever.

    `title`, when given, replaces the row's stored `title` unconditionally
    (unlike the metadata fields below, which only fill gaps) — an unmatched
    row's title is whatever the source gave us (a raw import name, TV
    Time's un-translated text, ...), and the newly resolved `tmdb_id` means
    that's no longer the best text available; the caller's own resolved
    title is.

    Race-safe like resolve_genres/find_or_create_title: a concurrent import
    worker claiming the same tmdb_id for a *different* Title (a genuine
    crosswalk collision, per uq_title_tmdb) is caught and skipped rather than
    raised — the caller's row still reconciles into title_row either way.
    """
    if title_row.tmdb_id is not None:
        return
    try:
        with db.begin_nested():
            title_row.tmdb_id = tmdb_id
            title_row.title_key = None
            if title:
                title_row.title = title
            if poster_url and not title_row.poster_url:
                title_row.poster_url = poster_url
            if runtime_minutes and not title_row.runtime_minutes:
                title_row.runtime_minutes = runtime_minutes
            if total_episodes and not title_row.total_episodes:
                title_row.total_episodes = total_episodes
            db.flush()
    except IntegrityError:
        winner = find_title(db, title_row.media_type, tmdb_id, None)
        if winner is None or winner.id == title_row.id:
            _log.info("tmdb_id=%s already claimed by another title; leaving %r unmatched", tmdb_id, title_row.title)
            return
        try:
            with db.begin_nested():
                merge_titles(db, loser=title_row, winner=winner)
        except IntegrityError:
            _log.warning(
                "tmdb_id=%s already claimed by title_id=%s; merge of duplicate %r also failed, leaving unmatched",
                tmdb_id,
                winner.id,
                title_row.title,
            )


def backfill_title_tvdb_id(
    db: Session,
    title_row: Title,
    tvdb_id: int,
    *,
    title: str | None = None,
    poster_url: str | None = None,
    runtime_minutes: int | None = None,
    total_episodes: int | None = None,
) -> None:
    """TVDB counterpart to backfill_title_tmdb_id: attaches TheTVDB's own
    fallback identity to a Title that has neither tmdb_id nor tvdb_id yet —
    the case where TMDB itself has no match at all for a show TV Time gave
    a TVDB id for (see users/tvtime_import.py's TVDB fallback).

    Never touches a Title that already has *either* identity: an existing
    tmdb_id always wins (this only runs when TMDB found nothing), and an
    existing tvdb_id means some earlier run already attached one. Race-safe
    like backfill_title_tmdb_id, against the same kind of crosswalk
    collision (via uq_title_tvdb instead of uq_title_tmdb).
    """
    if title_row.tmdb_id is not None or title_row.tvdb_id is not None:
        return
    try:
        with db.begin_nested():
            title_row.tvdb_id = tvdb_id
            title_row.title_key = None
            if title:
                title_row.title = title
            if poster_url and not title_row.poster_url:
                title_row.poster_url = poster_url
            if runtime_minutes and not title_row.runtime_minutes:
                title_row.runtime_minutes = runtime_minutes
            if total_episodes and not title_row.total_episodes:
                title_row.total_episodes = total_episodes
            db.flush()
    except IntegrityError:
        winner = find_title(db, title_row.media_type, None, None, tvdb_id=tvdb_id)
        if winner is None or winner.id == title_row.id:
            _log.info("tvdb_id=%s already claimed by another title; leaving %r unmatched", tvdb_id, title_row.title)
            return
        try:
            with db.begin_nested():
                merge_titles(db, loser=title_row, winner=winner)
        except IntegrityError:
            _log.warning(
                "tvdb_id=%s already claimed by title_id=%s; merge of duplicate %r also failed, leaving unmatched",
                tvdb_id,
                winner.id,
                title_row.title,
            )


def merge_titles(db: Session, *, loser: Title, winner: Title) -> None:
    """Fold a duplicate, still-unmatched Title into the Title that already
    holds the identity (tmdb_id/tvdb_id) it was just about to claim.

    Happens when a transient TMDB/TVDB outage let an import create a fresh
    unmatched row for a show that's already tracked under a different Title
    (see backfill_title_tmdb_id/backfill_title_tvdb_id's IntegrityError
    branch) — without this, the two rows stay permanently split and every
    caller resolving `winner` never sees `loser`'s library entries, watches,
    ratings, or comments.

    Every row referencing `loser` by title_id is repointed onto `winner`;
    where that collides with something `winner` already has (same user's
    LibraryEntry, a synced Episode, a cached TmdbCache entry), `winner`'s
    own copy wins — it carries the actually-resolved identity — and the
    loser's counterpart is dropped rather than reconciled field-by-field.
    Per-episode rating aggregates are the one exception: those are real
    summed user ratings, so on collision the two sides are added together
    instead of one being discarded. `loser` is deleted once nothing
    references it anymore. Caller must run this inside a still-open
    transaction/savepoint (it's meant to be called from the `except
    IntegrityError` branch of a failed backfill, itself inside one).
    """
    if loser.id == winner.id:
        return

    winner_users = {uid for (uid,) in db.query(LibraryEntry.user_id).filter(LibraryEntry.title_id == winner.id)}
    for entry in db.query(LibraryEntry).filter(LibraryEntry.title_id == loser.id):
        if entry.user_id in winner_users:
            _log.warning(
                "merge_titles: user_id=%s tracks both title_id=%s and title_id=%s; dropping the duplicate entry",
                entry.user_id,
                loser.id,
                winner.id,
            )
            db.delete(entry)
        else:
            entry.title_id = winner.id
            if entry.rating is not None:
                winner.rating_sum += entry.rating
                winner.rating_count += 1
    db.flush()

    winner_episodes = {
        (season, num)
        for season, num in db.query(Episode.season, Episode.episode_number).filter(Episode.title_id == winner.id)
    }
    for episode in db.query(Episode).filter(Episode.title_id == loser.id):
        if (episode.season, episode.episode_number) in winner_episodes:
            db.delete(episode)
        else:
            episode.title_id = winner.id
    db.flush()

    winner_aggregates = {
        (agg.season, agg.episode): agg
        for agg in db.query(EpisodeRatingAggregate).filter(EpisodeRatingAggregate.title_id == winner.id)
    }
    for agg in db.query(EpisodeRatingAggregate).filter(EpisodeRatingAggregate.title_id == loser.id):
        existing = winner_aggregates.get((agg.season, agg.episode))
        if existing is not None:
            existing.rating_sum += agg.rating_sum
            existing.rating_count += agg.rating_count
            db.delete(agg)
        else:
            agg.title_id = winner.id
    db.flush()

    winner_cache_keys = {
        (cache.kind, cache.season, cache.language)
        for cache in db.query(TmdbCache).filter(TmdbCache.title_id == winner.id)
    }
    for cache in db.query(TmdbCache).filter(TmdbCache.title_id == loser.id):
        if (cache.kind, cache.season, cache.language) in winner_cache_keys:
            db.delete(cache)
        else:
            cache.title_id = winner.id
    db.flush()

    db.query(Comment).filter(Comment.title_id == loser.id).update({"title_id": winner.id})

    # Via the ORM relationship, not a raw Core statement on title_genres:
    # `loser` is about to be db.delete()'d, and the ORM independently manages
    # its own secondary-table rows for that delete — a Core-level DELETE here
    # would race it and blow up with StaleDataError when the ORM's cleanup
    # finds nothing left to remove.
    winner_genre_names = {g.name for g in winner.genre_rows}
    for genre in list(loser.genre_rows):
        if genre.name not in winner_genre_names:
            winner.genre_rows.append(genre)
            winner_genre_names.add(genre.name)
    loser.genre_rows = []

    for field in (
        "poster_url",
        "backdrop_url",
        "runtime_minutes",
        "total_episodes",
        "total_seasons",
        "overview",
        "tagline",
        "imdb_id",
        "wikidata_id",
    ):
        if getattr(winner, field) is None and getattr(loser, field) is not None:
            setattr(winner, field, getattr(loser, field))

    db.flush()
    db.delete(loser)
    db.flush()
    _log.info(
        "merge_titles: merged duplicate title_id=%s (%r) into title_id=%s (%r)",
        loser.id,
        loser.title,
        winner.id,
        winner.title,
    )


def find_or_create_title(
    db: Session,
    media_type: MediaType,
    tmdb_id: int | None,
    title: str,
    *,
    tvdb_id: int | None = None,
    year: int | None = None,
    poster_url: str | None = None,
    runtime_minutes: int | None = None,
    total_episodes: int | None = None,
    genres: list[str] | None = None,
) -> Title:
    """Find the shared Title, creating it (with its genre links) if no one
    has tracked or commented on it yet. Race-safe: a concurrent insert of
    the same identity is resolved by re-querying after the unique-index hit.
    """
    found = find_title(db, media_type, tmdb_id, title, tvdb_id=tvdb_id)
    if found:
        return found
    new_title = Title(
        media_type=media_type,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        title_key=None if (tmdb_id is not None or tvdb_id is not None) else normalize_title_key(title),
        title=title,
        year=year,
        poster_url=poster_url,
        runtime_minutes=runtime_minutes,
        total_episodes=total_episodes,
        genre_rows=resolve_genres(db, genres),
    )
    db.add(new_title)
    try:
        db.flush()
    except IntegrityError:
        # another import/request created the same global Title in the meantime
        db.rollback()
        existing = find_title(db, media_type, tmdb_id, title, tvdb_id=tvdb_id)
        if existing is None:  # rollback also undid unrelated state; caller must retry
            raise
        return existing
    return new_title
