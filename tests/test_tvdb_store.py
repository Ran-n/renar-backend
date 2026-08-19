#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000

Unit tests for the tvdb/ package's fetch/shape helpers, independent of the
TV Time import flow that consumes them (see test_tvdb_fallback.py for that).
"""

from renar_backend.database import SessionLocal
from renar_backend.models import Episode, MediaType, Title
from renar_backend.tvdb import tvdb_store
from renar_backend.tvdb.tvdb_store import (
    fetch_series_episodes,
    fetch_series_extended,
    series_names,
    series_summary,
    sync_tvdb_episodes,
)

EXTENDED = {
    "id": 200,
    "name": "No One Could Live Here",
    "aliases": [{"name": "Aqui no hay quien viva"}, "Alt Name"],
    "image": "https://artworks.thetvdb.com/banners/posters/200.jpg",
    "overview": "A building full of neighbors.",
    "status": {"name": "Ended"},
    "averageRuntime": 70,
    "year": "2003",
}

EPISODES_PAGE = {
    "episodes": [
        {"seasonNumber": 1, "number": 1, "name": "Pilot", "aired": "2003-09-22"},
        {"seasonNumber": 1, "number": 2, "name": "Episode Two", "aired": "2003-09-29"},
        {"seasonNumber": 2, "number": 1, "name": "S2E1", "aired": None},
        {"seasonNumber": None, "number": 3, "name": "Bad row, no season"},
    ]
}


def test_fetch_series_extended_delegates_to_tvdb_get(monkeypatch):
    calls = []

    def fake_get(path, params=None):
        calls.append(path)
        return EXTENDED

    monkeypatch.setattr(tvdb_store, "tvdb_get", fake_get)
    result = fetch_series_extended("200")
    assert result == EXTENDED
    assert calls == ["/series/200/extended"]


def test_fetch_series_extended_returns_none_when_tvdb_has_nothing(monkeypatch):
    monkeypatch.setattr(tvdb_store, "tvdb_get", lambda path, params=None: None)
    assert fetch_series_extended("999") is None


def test_series_names_dedupes_and_caps_at_twelve():
    aliases = [{"name": "Primary"}] + [f"Alt{i}" for i in range(1, 16)]  # 15 aliases, one a dupe of the name
    data = {"name": "Primary", "aliases": aliases}
    names = series_names(data)
    assert names[0] == "Primary"
    assert len(names) == 12
    assert names.count("Primary") == 1


def test_series_summary_maps_fields():
    summary = series_summary("200", EXTENDED)
    assert summary == {
        "tvdb_id": 200,
        "name": "No One Could Live Here",
        "poster_url": "https://artworks.thetvdb.com/banners/posters/200.jpg",
        "overview": "A building full of neighbors.",
        "show_status": "Ended",
        "runtime_minutes": 70,
        "year": 2003,
    }


def test_series_summary_handles_missing_fields():
    summary = series_summary("5", {})
    assert summary == {
        "tvdb_id": 5,
        "name": None,
        "poster_url": None,
        "overview": None,
        "show_status": None,
        "runtime_minutes": None,
        "year": None,
    }


def test_fetch_series_episodes_maps_and_skips_bad_rows(monkeypatch):
    monkeypatch.setattr(tvdb_store, "tvdb_get", lambda path, params=None: EPISODES_PAGE)
    episodes = fetch_series_episodes("200")
    assert episodes == [
        {"season": 1, "episode_number": 1, "name": "Pilot", "air_date": "2003-09-22"},
        {"season": 1, "episode_number": 2, "name": "Episode Two", "air_date": "2003-09-29"},
        {"season": 2, "episode_number": 1, "name": "S2E1", "air_date": None},
    ]


def test_fetch_series_episodes_returns_empty_when_tvdb_has_nothing(monkeypatch):
    monkeypatch.setattr(tvdb_store, "tvdb_get", lambda path, params=None: None)
    assert fetch_series_episodes("200") == []


def test_sync_tvdb_episodes_inserts_and_updates():
    db = SessionLocal()
    try:
        title = Title(media_type=MediaType.tv_show, title="No One Could Live Here", tvdb_id=200)
        db.add(title)
        db.flush()

        sync_tvdb_episodes(
            db,
            title,
            [
                {"season": 1, "episode_number": 1, "name": "Pilot", "air_date": "2003-09-22"},
                {"season": 1, "episode_number": 2, "name": "Episode Two", "air_date": None},
            ],
        )
        db.commit()

        rows = db.query(Episode).filter_by(title_id=title.id).order_by(Episode.episode_number).all()
        assert [(r.season, r.episode_number, r.name) for r in rows] == [
            (1, 1, "Pilot"),
            (1, 2, "Episode Two"),
        ]

        # re-sync with an updated name for episode 1 upserts in place, no duplicate row
        sync_tvdb_episodes(db, title, [{"season": 1, "episode_number": 1, "name": "Pilot (renamed)", "air_date": None}])
        db.commit()
        rows = db.query(Episode).filter_by(title_id=title.id).all()
        assert len(rows) == 2
        pilot = next(r for r in rows if r.episode_number == 1)
        assert pilot.name == "Pilot (renamed)"
        assert pilot.air_date is None
    finally:
        db.close()


def test_sync_tvdb_episodes_ignores_unparseable_air_date():
    db = SessionLocal()
    try:
        title = Title(media_type=MediaType.tv_show, title="Whatever", tvdb_id=201)
        db.add(title)
        db.flush()

        sync_tvdb_episodes(db, title, [{"season": 1, "episode_number": 1, "name": "Ep", "air_date": "not-a-date"}])
        db.commit()

        row = db.query(Episode).filter_by(title_id=title.id).one()
        assert row.air_date is None
    finally:
        db.close()
