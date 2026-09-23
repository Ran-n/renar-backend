#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 00:00:00.000000
Revised: 2026/09/02 10:58:23.244780

Shared Title resolution and normalized genres: one Genre row per name,
linked to titles through title_genres, round-tripped as list[str].
"""

import pytest

from renar_backend.catalog.titles import (
    backfill_title_tmdb_id,
    backfill_title_tvdb_id,
    escape_like,
    find_title,
    merge_titles,
)
from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeRatingAggregate, Genre, MediaType, Title

pytestmark = pytest.mark.regression


# ---------------------------------------------------------------------------
# escape_like — pure-function unit tests (no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # ordinary text passes through unchanged
        ("hello", "hello"),
        # percent wildcard is escaped
        ("100%", "100\\%"),
        # underscore wildcard is escaped
        ("_type", "\\_type"),
        # backslash (the escape char itself) is doubled first
        ("a\\b", "a\\\\b"),
        # all three metacharacters in one string
        ("100% _done\\ok", "100\\% \\_done\\\\ok"),
        # empty string
        ("", ""),
        # leading/trailing wildcards
        ("%abc%", "\\%abc\\%"),
    ],
)
def test_escape_like_pure(raw, expected):
    assert escape_like(raw) == expected


def _create(client, headers, **overrides) -> dict:
    payload = {"media_type": "film", "title": "Heat"}
    payload.update(overrides)
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_genres_round_trip_as_list(client, alice):
    _, headers = alice
    item = _create(client, headers, genres=["Crime", "Drama"])
    assert item["genres"] == ["Crime", "Drama"]
    listed = client.get("/media", headers=headers).json()
    assert listed[0]["genres"] == ["Crime", "Drama"]


def test_genre_names_are_trimmed_and_deduplicated(client, alice):
    _, headers = alice
    item = _create(client, headers, genres=["  Drama ", "Drama", "", "Crime"])
    assert sorted(item["genres"]) == ["Crime", "Drama"]


def test_same_genre_is_one_shared_row(client, alice):
    _, headers = alice
    _create(client, headers, title="Heat", genres=["Crime", "Drama"])
    _create(client, headers, title="Se7en", genres=["Crime", "Thriller"])

    db = SessionLocal()
    try:
        assert db.query(Genre).filter(Genre.name == "Crime").count() == 1
        assert {g.name for g in db.query(Genre).all()} == {"Crime", "Drama", "Thriller"}
    finally:
        db.close()


def test_no_genres_is_empty_list(client, alice):
    _, headers = alice
    item = _create(client, headers)
    assert item["genres"] == []


def test_shared_title_reuses_genre_links(client, alice, bob):
    """Two users adding the same title share one Title row and its genres."""
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers, tmdb_id=949, genres=["Crime"])
    item = _create(client, bob_headers, tmdb_id=949)  # no genres sent: Title already exists
    assert item["genres"] == ["Crime"]

    db = SessionLocal()
    try:
        assert db.query(Title).count() == 1
    finally:
        db.close()


def test_stats_top_genres_from_normalized_rows(client, alice):
    _, headers = alice
    _create(client, headers, title="Heat", genres=["Crime", "Drama"])
    _create(client, headers, title="Se7en", genres=["Crime"])
    s = client.get("/stats", headers=headers).json()
    assert s["top_genres"][0] == {"genre": "Crime", "count": 2}


# ---------------------------------------------------------------------------
# find_title
# ---------------------------------------------------------------------------


def test_find_title_returns_none_when_no_criteria_match(client):
    """find_title(db, mt, None, None) — all identity fields None — returns None."""
    db = SessionLocal()
    try:
        result = find_title(db, MediaType.film, None, None)
        assert result is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# backfill_title_tmdb_id
# ---------------------------------------------------------------------------


def _make_unmatched(db, *, media_type=MediaType.film, title="Raw Name") -> Title:
    t = Title(media_type=media_type, tmdb_id=None, title=title, title_key="raw-name")
    db.add(t)
    db.flush()
    return t


def test_backfill_title_tmdb_id_skips_already_matched(client):
    """If the row already has a tmdb_id, backfill is a no-op (early return)."""
    db = SessionLocal()
    try:
        t = Title(media_type=MediaType.film, tmdb_id=949, title="Heat", title_key=None)
        db.add(t)
        db.flush()
        original_id = t.tmdb_id

        backfill_title_tmdb_id(db, t, 1234)

        assert t.tmdb_id == original_id  # unchanged
    finally:
        db.rollback()
        db.close()


def test_backfill_title_tmdb_id_updates_title_text_when_provided(client):
    """When the optional `title` kwarg is given, the stored title is replaced."""
    db = SessionLocal()
    try:
        t = _make_unmatched(db)
        backfill_title_tmdb_id(db, t, 100, title="Resolved Title")
        assert t.title == "Resolved Title"
        assert t.tmdb_id == 100
    finally:
        db.rollback()
        db.close()


def test_backfill_title_tmdb_id_handles_collision_with_existing_winner(client):
    """If another Title already owns the target tmdb_id, the two are merged."""
    db = SessionLocal()
    try:
        winner = Title(media_type=MediaType.film, tmdb_id=777, title="Winner", title_key=None)
        loser = _make_unmatched(db)
        db.add(winner)
        db.flush()

        backfill_title_tmdb_id(db, loser, 777)
        db.flush()

        # loser merged into winner — only winner survives
        assert db.query(Title).filter(Title.tmdb_id == 777).count() == 1
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# backfill_title_tvdb_id
# ---------------------------------------------------------------------------


def test_backfill_title_tvdb_id_attaches_tvdb_identity(client):
    """Basic happy path: sets tvdb_id, clears title_key."""
    db = SessionLocal()
    try:
        t = _make_unmatched(db)
        backfill_title_tvdb_id(db, t, tvdb_id=9999)
        assert t.tvdb_id == 9999
        assert t.title_key is None
    finally:
        db.rollback()
        db.close()


def test_backfill_title_tvdb_id_skips_when_tmdb_id_already_set(client):
    db = SessionLocal()
    try:
        t = Title(media_type=MediaType.film, tmdb_id=111, title="Already Matched", title_key=None)
        db.add(t)
        db.flush()
        backfill_title_tvdb_id(db, t, tvdb_id=222)
        assert t.tvdb_id is None  # no change; tmdb_id guard fired
    finally:
        db.rollback()
        db.close()


def test_backfill_title_tvdb_id_skips_when_tvdb_id_already_set(client):
    db = SessionLocal()
    try:
        t = _make_unmatched(db)
        t.tvdb_id = 333
        db.flush()
        backfill_title_tvdb_id(db, t, tvdb_id=444)
        assert t.tvdb_id == 333  # unchanged
    finally:
        db.rollback()
        db.close()


def test_backfill_title_tvdb_id_updates_title_when_provided(client):
    db = SessionLocal()
    try:
        t = _make_unmatched(db)
        backfill_title_tvdb_id(db, t, tvdb_id=555, title="TVDB Title")
        assert t.title == "TVDB Title"
    finally:
        db.rollback()
        db.close()


def test_backfill_title_tvdb_id_handles_collision_with_existing_winner(client):
    """IntegrityError on tvdb_id collision triggers a merge."""
    db = SessionLocal()
    try:
        winner = Title(media_type=MediaType.tv_show, tvdb_id=8888, title="TVDB Winner", title_key=None)
        loser = _make_unmatched(db, media_type=MediaType.tv_show)
        db.add(winner)
        db.flush()

        backfill_title_tvdb_id(db, loser, tvdb_id=8888)
        db.flush()

        assert db.query(Title).filter(Title.tvdb_id == 8888).count() == 1
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# merge_titles — same-id no-op
# ---------------------------------------------------------------------------


def test_merge_titles_noop_when_loser_equals_winner(client):
    """merge_titles(loser=t, winner=t) must return immediately without DB writes."""
    db = SessionLocal()
    try:
        t = Title(media_type=MediaType.film, tmdb_id=42, title="Same", title_key=None)
        db.add(t)
        db.flush()
        # Should not raise and should not touch the DB
        merge_titles(db, loser=t, winner=t)
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# merge_titles — non-colliding episode rating aggregate moves to winner
# ---------------------------------------------------------------------------


def test_merge_moves_non_colliding_aggregate_to_winner(client):
    """An EpisodeRatingAggregate on the loser that has no counterpart on the
    winner must be moved (not deleted)."""
    db = SessionLocal()
    try:
        winner = Title(media_type=MediaType.film, tmdb_id=11, title="Winner", title_key=None)
        loser = Title(media_type=MediaType.film, tmdb_id=None, title="Loser", title_key="loser")
        db.add_all([winner, loser])
        db.flush()

        agg = EpisodeRatingAggregate(title_id=loser.id, season=1, episode=1, rating_sum=50, rating_count=1)
        db.add(agg)
        db.flush()
        agg_id = agg.id

        merge_titles(db, loser=loser, winner=winner)
        db.flush()

        moved = db.get(EpisodeRatingAggregate, agg_id)
        assert moved.title_id == winner.id
        assert moved.rating_sum == 50
    finally:
        db.rollback()
        db.close()
