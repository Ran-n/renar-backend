#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 00:00:00.000000
Revised: 2026/07/10 08:47:48.374007

Shared Title resolution and normalized genres: one Genre row per name,
linked to titles through title_genres, round-tripped as list[str].
"""

from xoutaim_backend.database import SessionLocal
from xoutaim_backend.models import Genre, Title


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
