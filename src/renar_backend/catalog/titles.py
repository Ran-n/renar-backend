#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 00:00:00.000000
Revised: 2026/08/18 14:35:48.776130

Shared Title resolution: every place that addresses a global title by
(media_type, tmdb_id-or-title text) — library adds, imports, comments,
cross-user ratings — resolves it through here, so there is exactly one
implementation of the identity rules described on the Title model.
"""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import Genre, LibraryEntry, MediaType, Title, normalize_title_key

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
        _log.info("tmdb_id=%s already claimed by another title; leaving %r unmatched", tmdb_id, title_row.title)


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
        _log.info("tvdb_id=%s already claimed by another title; leaving %r unmatched", tvdb_id, title_row.title)


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
