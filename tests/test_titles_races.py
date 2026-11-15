#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 14:25:25.401369
Revised: 2026/11/13 15:35:12.433223

catalog/titles.py's concurrency fallbacks and local-search helpers.

The race branches (a parallel import worker inserting the same genre/title
between this session's SELECT and INSERT) can't be hit by timing in a
single-threaded test, so each one is staged deterministically: the
competing row is committed from a second session, and this session is made
to miss it on the first lookup, either with a `do_orm_execute` hook that
blanks one SELECT or by stubbing `find_title`. Everything after that
(the real INSERT, the real unique-index IntegrityError, the savepoint
rollback, the re-query) runs against real Postgres.
"""

import logging

import pytest
from _race_helpers import commit_elsewhere, hide_selects, integrity_error
from sqlalchemy.exc import IntegrityError

from renar_backend.catalog import titles
from renar_backend.catalog.titles import (
    backfill_title_tmdb_id,
    backfill_title_tvdb_id,
    find_or_create_title,
    popular_local_titles,
    resolve_genres,
    search_local_titles,
)
from renar_backend.database import SessionLocal
from renar_backend.models import Genre, LibraryEntry, MediaType, Title, User


@pytest.fixture
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# resolve_genres
# ---------------------------------------------------------------------------


def test_resolve_genres_recovers_from_insert_race(db):
    """The SELECT misses a genre another worker just committed: the INSERT
    hits the unique index, the savepoint rolls back, and the re-query hands
    back the other worker's row instead of failing the import."""
    (winner_id,) = commit_elsewhere(Genre(name="Noir"))
    hide_selects(db, Genre, times=1)

    genres = resolve_genres(db, ["Noir"])

    assert [g.id for g in genres] == [winner_id]
    assert db.query(Genre).filter(Genre.name == "Noir").count() == 1


def test_resolve_genres_logs_and_skips_when_race_row_never_appears(db, caplog):
    """Insert collided but the re-query still finds nothing: the genre is
    left off (the title is still created) and the failure is logged, not
    swallowed."""
    commit_elsewhere(Genre(name="Ghost"))
    hide_selects(db, Genre, times=None)

    with caplog.at_level(logging.ERROR, logger=titles.__name__):
        genres = resolve_genres(db, ["Ghost", "Drama"])

    # Drama's SELECT is blanked too, but its INSERT has nothing to collide with
    assert [g.name for g in genres] == ["Drama"]
    assert "could not be created nor found" in caplog.text


def test_resolve_genres_keeps_genres_unaffected_by_the_race(db):
    """Only the raced name is re-resolved; a brand-new name in the same call
    is created normally."""
    commit_elsewhere(Genre(name="Noir"))
    hide_selects(db, Genre, times=1)

    genres = resolve_genres(db, ["Noir", "Western"])

    assert [g.name for g in genres] == ["Noir", "Western"]


# ---------------------------------------------------------------------------
# search_local_titles / popular_local_titles (TMDB-outage fallbacks)
# ---------------------------------------------------------------------------


def test_search_local_titles_matches_substring_case_insensitively(db):
    db.add_all([
        Title(media_type=MediaType.film, tmdb_id=1, title="The Matrix"),
        Title(media_type=MediaType.film, tmdb_id=2, title="Matrix Reloaded"),
        Title(media_type=MediaType.film, tmdb_id=3, title="Heat"),
        Title(media_type=MediaType.tv_show, tmdb_id=4, title="Matrix: The Series"),
        Title(media_type=MediaType.film, tmdb_id=None, title="Matrix fan edit", title_key="matrix fan edit"),
    ])
    db.flush()

    found = search_local_titles(db, MediaType.film, "matrix")

    # films only, tmdb_id required, ordered by title
    assert [t.title for t in found] == ["Matrix Reloaded", "The Matrix"]


def test_search_local_titles_treats_wildcards_literally(db):
    db.add_all([
        Title(media_type=MediaType.film, tmdb_id=1, title="100% Wolf"),
        Title(media_type=MediaType.film, tmdb_id=2, title="1000 Wolves"),
    ])
    db.flush()

    assert [t.title for t in search_local_titles(db, MediaType.film, "100%")] == ["100% Wolf"]
    assert search_local_titles(db, MediaType.film, "_") == []


def test_search_local_titles_honours_limit(db):
    db.add_all([Title(media_type=MediaType.film, tmdb_id=i, title=f"Saw {i}") for i in range(1, 6)])
    db.flush()

    assert len(search_local_titles(db, MediaType.film, "saw", limit=3)) == 3


def test_popular_local_titles_ranks_by_library_count(db):
    users = [User(username=f"u{i}", email=f"u{i}@example.com", password_hash="x") for i in range(3)]
    popular = Title(media_type=MediaType.film, tmdb_id=10, title="Popular")
    niche = Title(media_type=MediaType.film, tmdb_id=11, title="Niche")
    show = Title(media_type=MediaType.tv_show, tmdb_id=12, title="Show")
    unmatched = Title(media_type=MediaType.film, tmdb_id=None, title="Unmatched", title_key="unmatched")
    db.add_all([*users, popular, niche, show, unmatched])
    db.flush()
    for user in users:
        db.add(LibraryEntry(user_id=user.id, title_id=popular.id))
        db.add(LibraryEntry(user_id=user.id, title_id=show.id))
        db.add(LibraryEntry(user_id=user.id, title_id=unmatched.id))
    db.add(LibraryEntry(user_id=users[0].id, title_id=niche.id))
    db.flush()

    assert [t.title for t in popular_local_titles(db, MediaType.film)] == ["Popular", "Niche"]
    assert [t.title for t in popular_local_titles(db, MediaType.film, limit=1)] == ["Popular"]


# ---------------------------------------------------------------------------
# backfill_title_tmdb_id / backfill_title_tvdb_id: metadata gaps + failures
# ---------------------------------------------------------------------------


def _unmatched(db, media_type=MediaType.tv_show, **fields) -> Title:
    row = Title(media_type=media_type, tmdb_id=None, title="Raw Name", title_key="raw name", **fields)
    db.add(row)
    db.flush()
    return row


_BACKFILLS = [
    pytest.param(backfill_title_tmdb_id, "tmdb_id", id="tmdb"),
    pytest.param(backfill_title_tvdb_id, "tvdb_id", id="tvdb"),
]


@pytest.mark.parametrize(("backfill", "identity"), _BACKFILLS)
def test_backfill_fills_missing_metadata(db, backfill, identity):
    row = _unmatched(db)

    backfill(db, row, 501, poster_url="/p.jpg", runtime_minutes=42, total_episodes=10)

    assert getattr(row, identity) == 501
    assert (row.poster_url, row.runtime_minutes, row.total_episodes) == ("/p.jpg", 42, 10)


@pytest.mark.parametrize(("backfill", "identity"), _BACKFILLS)
def test_backfill_never_overwrites_known_metadata(db, backfill, identity):
    row = _unmatched(db, poster_url="/mine.jpg", runtime_minutes=30, total_episodes=8)

    backfill(db, row, 502, poster_url="/theirs.jpg", runtime_minutes=60, total_episodes=20)

    assert getattr(row, identity) == 502
    assert (row.poster_url, row.runtime_minutes, row.total_episodes) == ("/mine.jpg", 30, 8)


@pytest.mark.parametrize(("backfill", "identity"), _BACKFILLS)
def test_backfill_leaves_row_unmatched_when_claimant_cannot_be_found(db, monkeypatch, caplog, backfill, identity):
    """The identity collided, but the claiming row isn't visible to the
    re-query: nothing to merge into, so the row stays unmatched (and the
    savepoint rollback keeps the session usable)."""
    commit_elsewhere(Title(media_type=MediaType.tv_show, title="Claimant", **{identity: 503}))
    row = _unmatched(db)
    monkeypatch.setattr(titles, "find_title", lambda *a, **kw: None)

    with caplog.at_level(logging.INFO, logger=titles.__name__):
        backfill(db, row, 503)

    assert getattr(row, identity) is None
    assert "already claimed by another title" in caplog.text
    assert db.query(Title).filter(Title.id == row.id).one().title == "Raw Name"


@pytest.mark.parametrize(("backfill", "identity"), _BACKFILLS)
def test_backfill_leaves_row_unmatched_when_merge_fails(db, monkeypatch, caplog, backfill, identity):
    """The identity collided with a real claimant, but folding the duplicate
    into it failed too: both rows survive, the failure is logged."""
    (claimant_id,) = commit_elsewhere(Title(media_type=MediaType.tv_show, title="Claimant", **{identity: 504}))
    row = _unmatched(db)

    def _merge_fails(session, *, loser, winner):
        raise integrity_error()

    monkeypatch.setattr(titles, "merge_titles", _merge_fails)

    with caplog.at_level(logging.WARNING, logger=titles.__name__):
        backfill(db, row, 504)

    assert getattr(row, identity) is None
    assert f"already claimed by title_id={claimant_id}" in caplog.text
    assert "merge of duplicate 'Raw Name' also failed" in caplog.text
    assert db.query(Title).count() == 2


# ---------------------------------------------------------------------------
# find_or_create_title: concurrent create of the same identity
# ---------------------------------------------------------------------------


def test_find_or_create_title_returns_the_concurrently_created_row(db, monkeypatch):
    (existing_id,) = commit_elsewhere(Title(media_type=MediaType.film, tmdb_id=600, title="Heat"))
    real_find = titles.find_title
    calls = []

    def _miss_first(*args, **kwargs):
        calls.append(args)
        return None if len(calls) == 1 else real_find(*args, **kwargs)

    monkeypatch.setattr(titles, "find_title", _miss_first)

    found = find_or_create_title(db, MediaType.film, 600, "Heat")

    assert found.id == existing_id
    assert len(calls) == 2
    assert db.query(Title).filter(Title.tmdb_id == 600).count() == 1


def test_find_or_create_title_reraises_when_the_collision_cannot_be_resolved(db, monkeypatch):
    """The insert collided but the re-query finds nothing either; the
    rollback has already undone the caller's other pending work, so the
    caller has to retry and gets the original error."""
    commit_elsewhere(Title(media_type=MediaType.film, tmdb_id=601, title="Alien"))
    monkeypatch.setattr(titles, "find_title", lambda *a, **kw: None)

    with pytest.raises(IntegrityError):
        find_or_create_title(db, MediaType.film, 601, "Alien")


def test_merge_moves_unrated_entry_without_touching_rating_totals(db):
    """An unrated entry on the duplicate moves over, but adds nothing to the
    winner's community rating sum/count."""
    user = User(username="mover", email="mover@example.com", password_hash="x")
    winner = Title(media_type=MediaType.film, tmdb_id=700, title="Winner")
    loser = Title(media_type=MediaType.film, tmdb_id=None, title="Loser", title_key="loser")
    db.add_all([user, winner, loser])
    db.flush()
    entry = LibraryEntry(user_id=user.id, title_id=loser.id, rating=None)
    db.add(entry)
    db.flush()
    before = (winner.rating_sum, winner.rating_count)

    titles.merge_titles(db, loser=loser, winner=winner)

    assert entry.title_id == winner.id
    assert (winner.rating_sum, winner.rating_count) == before
