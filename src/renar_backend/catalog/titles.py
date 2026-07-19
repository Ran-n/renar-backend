#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 00:00:00.000000
Revised: 2026/07/18 19:33:27.239607

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


def find_title(db: Session, media_type: MediaType, tmdb_id: int | None, title: str | None) -> Title | None:
    """Locate the shared Title row by its identity: tmdb_id when given,
    otherwise the normalized title text. Returns None when nobody has
    created that title yet.
    """
    query = db.query(Title).filter(Title.media_type == media_type)
    if tmdb_id is not None:
        return query.filter(Title.tmdb_id == tmdb_id).first()
    if title:
        return query.filter(Title.tmdb_id.is_(None), Title.title_key == normalize_title_key(title)).first()
    return None


def find_or_create_title(
    db: Session,
    media_type: MediaType,
    tmdb_id: int | None,
    title: str,
    *,
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
    found = find_title(db, media_type, tmdb_id, title)
    if found:
        return found
    new_title = Title(
        media_type=media_type,
        tmdb_id=tmdb_id,
        title_key=None if tmdb_id is not None else normalize_title_key(title),
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
        existing = find_title(db, media_type, tmdb_id, title)
        if existing is None:  # rollback also undid unrelated state; caller must retry
            raise
        return existing
    return new_title
