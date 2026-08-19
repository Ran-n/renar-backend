#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000

retry_unmatched_titles is the periodic counterpart to tmdb_get's retry/
backoff and the raw-name-keyed import reconciliation: it's what heals a
title that's still unmatched after both of those, without requiring the
user to ever re-import or manually relink (see docs/backlog.md).
"""

from renar_backend.database import SessionLocal
from renar_backend.models import Title
from renar_backend.social.notifier import retry_unmatched_titles


def _add_unmatched(client, headers, **kwargs) -> dict:
    payload = {"media_type": "film", "title": "Raw Import Name"} | kwargs
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_retry_fixes_unmatched_film(client, alice):
    _, headers = alice
    item = _add_unmatched(client, headers, media_type="film", title="Il Buono, il Brutto, il Cattivo")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(
            db,
            search_movie=lambda name, year: ({"id": 429, "title": "The Good, the Bad and the Ugly"}, False),
            fetch_film=lambda tmdb_id: {"poster_path": "/p.jpg", "genres": [{"name": "Western"}]},
            pace_seconds=0,
        )
        assert n == 1
    finally:
        db.close()

    out = client.get(f"/media/{item['id']}", headers=headers).json()
    assert out["tmdb_id"] == 429
    assert out["title"] == "The Good, the Bad and the Ugly"
    assert out["poster_url"].endswith("/p.jpg")


def test_retry_fixes_unmatched_show(client, alice):
    _, headers = alice
    item = _add_unmatched(client, headers, media_type="tv_show", title="Aqui no hay quien viva")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(
            db,
            search_tv=lambda name: {"id": 501, "name": "No One Could Live Here"},
            fetch_show=lambda tmdb_id: {"number_of_episodes": 200},
            pace_seconds=0,
        )
        assert n == 1
    finally:
        db.close()

    out = client.get(f"/media/{item['id']}", headers=headers).json()
    assert out["tmdb_id"] == 501
    assert out["title"] == "No One Could Live Here"


def test_retry_leaves_entry_alone_when_still_no_match(client, alice):
    _, headers = alice
    item = _add_unmatched(client, headers, media_type="film", title="Something Truly Obscure")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(db, search_movie=lambda name, year: (None, False), pace_seconds=0)
        assert n == 0
    finally:
        db.close()

    out = client.get(f"/media/{item['id']}", headers=headers).json()
    assert out["tmdb_id"] is None
    assert out["title"] == "Something Truly Obscure"


def test_retry_skips_movie_that_now_resolves_as_a_show(client, alice):
    """A media_type change isn't safe to rewrite automatically — left for
    manual relink instead of silently reclassifying the entry."""
    _, headers = alice
    item = _add_unmatched(client, headers, media_type="film", title="Ambiguous Title")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(
            db, search_movie=lambda name, year: ({"id": 999, "name": "Ambiguous Title Show"}, True), pace_seconds=0
        )
        assert n == 0
    finally:
        db.close()

    out = client.get(f"/media/{item['id']}", headers=headers).json()
    assert out["tmdb_id"] is None


def test_retry_survives_search_failure(client, alice):
    _, headers = alice
    _add_unmatched(client, headers, media_type="film", title="Whatever")

    def broken_search(name, year):
        raise RuntimeError("TMDB down")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(db, search_movie=broken_search, pace_seconds=0)
        assert n == 0
    finally:
        db.close()


def test_retry_ignores_already_matched_titles(client, alice):
    _, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat", "tmdb_id": 949}, headers=headers)

    def fail_if_called(name, year):
        raise AssertionError("should not search an already-matched title")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(db, search_movie=fail_if_called, pace_seconds=0)
        assert n == 0
    finally:
        db.close()


def test_retry_survives_details_fetch_failure_but_keeps_the_match(client, alice):
    """Identity (tmdb_id, title) is the important part — losing the richer
    details fetch afterward shouldn't roll that back."""
    _, headers = alice
    item = _add_unmatched(client, headers, media_type="film", title="Raw Name")

    def broken_fetch(tmdb_id):
        raise RuntimeError("TMDB down")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(
            db,
            search_movie=lambda name, year: ({"id": 111, "title": "Resolved Name"}, False),
            fetch_film=broken_fetch,
            pace_seconds=0,
        )
        assert n == 1
    finally:
        db.close()

    out = client.get(f"/media/{item['id']}", headers=headers).json()
    assert out["tmdb_id"] == 111
    assert out["title"] == "Resolved Name"


def test_retry_does_not_clobber_a_concurrently_claimed_tmdb_id(client, alice, bob):
    """Mirrors backfill_title_tmdb_id's own race-safety test: if the tmdb_id
    this row would resolve to is already owned by a *different* Title
    (e.g. a live import just won that race), the unmatched row is left
    alone rather than raising."""
    _, alice_headers = alice
    _, bob_headers = bob
    client.post("/media", json={"media_type": "film", "title": "Other Title", "tmdb_id": 777}, headers=bob_headers)
    item = _add_unmatched(client, alice_headers, media_type="film", title="Raw Name")

    db = SessionLocal()
    try:
        n = retry_unmatched_titles(
            db, search_movie=lambda name, year: ({"id": 777, "title": "Resolved Name"}, False), pace_seconds=0
        )
        assert n == 0
    finally:
        db.close()

    out = client.get(f"/media/{item['id']}", headers=alice_headers).json()
    assert out["tmdb_id"] is None
    db = SessionLocal()
    try:
        assert db.query(Title).filter(Title.tmdb_id == 777).count() == 1
    finally:
        db.close()
