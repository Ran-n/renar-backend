#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/13 09:21:11.000000
Revised: 2026/07/16 09:54:32.010518

/upcoming/history: past aired episodes and released films for tracked
titles. Episode data is backfilled lazily (through the same TMDB season
cache season_tmdb() uses) on the first request that needs it.
"""

from datetime import date, timedelta

from renar_backend.tmdb import tmdb_store
from renar_backend.database import SessionLocal
from renar_backend.models import Episode, LibraryEntry


def _add(client, headers, **kwargs) -> dict:
    payload = {"title": "Placeholder", "status": "watching"} | kwargs
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _set_title_for_entry(client, headers, item_id: int, **fields) -> None:
    db = SessionLocal()
    try:
        entry = db.get(LibraryEntry, item_id)
        for k, v in fields.items():
            setattr(entry.title_ref, k, v)
        db.commit()
    finally:
        db.close()


def _season_payload(*episodes: tuple[int, str, str]) -> dict:
    return {"episodes": [{"episode_number": n, "name": name, "air_date": air_date} for n, name, air_date in episodes]}


def test_history_empty(client, alice):
    _, headers = alice
    assert client.get("/upcoming/history", headers=headers).json() == []


def test_history_lists_past_tv_episode(client, alice, monkeypatch):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    aired = date.today() - timedelta(days=3)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)

    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload((1, "Pilot", aired.isoformat())),
    )
    out = client.get("/upcoming/history", headers=headers).json()
    assert len(out) == 1
    assert out[0]["media_type"] == "tv_show"
    assert out[0]["date"] == aired.isoformat()
    assert out[0]["days_until"] == -3
    assert (out[0]["season"], out[0]["episode"], out[0]["episode_name"]) == (1, 1, "Pilot")


def test_history_excludes_dropped_show(client, alice, monkeypatch):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="dropped")
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload((1, "Pilot", "2020-01-01")),
    )
    assert client.get("/upcoming/history", headers=headers).json() == []


def test_history_excludes_future_episode(client, alice, monkeypatch):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    future = (date.today() + timedelta(days=5)).isoformat()
    monkeypatch.setattr(
        tmdb_store, "tmdb_get", lambda path, params=None, cache=True: _season_payload((1, "Next", future))
    )
    assert client.get("/upcoming/history", headers=headers).json() == []


def test_history_lists_past_film_release(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Heat", tmdb_id=100, status="completed")
    released = date.today() - timedelta(days=100)
    _set_title_for_entry(client, headers, film["id"], release_date=released)
    out = client.get("/upcoming/history", headers=headers).json()
    assert len(out) == 1
    assert out[0]["media_type"] == "film"
    assert out[0]["date"] == released.isoformat()
    assert out[0]["days_until"] == -100


def test_history_excludes_future_film(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Dune Part Three", tmdb_id=999, status="want_to_watch")
    _set_title_for_entry(client, headers, film["id"], release_date=date.today() + timedelta(days=30))
    assert client.get("/upcoming/history", headers=headers).json() == []


def test_history_status_filter(client, alice, monkeypatch):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = (date.today() - timedelta(days=3)).isoformat()
    monkeypatch.setattr(
        tmdb_store, "tmdb_get", lambda path, params=None, cache=True: _season_payload((1, "Pilot", aired))
    )
    film = _add(client, headers, media_type="film", title="Heat", tmdb_id=100, status="completed")
    _set_title_for_entry(client, headers, film["id"], release_date=date.today() - timedelta(days=10))

    out = client.get("/upcoming/history", params={"status_filter": "completed"}, headers=headers).json()
    assert len(out) == 1
    assert out[0]["media_type"] == "film"


def test_history_pagination_with_before_cursor(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Heat", tmdb_id=100, status="completed")
    old = date.today() - timedelta(days=200)
    _set_title_for_entry(client, headers, film["id"], release_date=old)

    film2 = _add(client, headers, media_type="film", title="Old Movie", tmdb_id=101, status="completed")
    older = date.today() - timedelta(days=400)
    _set_title_for_entry(client, headers, film2["id"], release_date=older)

    page1 = client.get("/upcoming/history", params={"limit": 1}, headers=headers).json()
    assert len(page1) == 1
    assert page1[0]["date"] == old.isoformat()

    page2 = client.get("/upcoming/history", params={"limit": 1, "before": page1[0]["date"]}, headers=headers).json()
    assert len(page2) == 1
    assert page2[0]["date"] == older.isoformat()


def test_history_second_call_does_not_refetch_fully_aired_season(client, alice, monkeypatch):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = (date.today() - timedelta(days=3)).isoformat()

    calls = {"n": 0}

    def fetch(path, params=None, cache=True):
        calls["n"] += 1
        return _season_payload((1, "Pilot", aired))

    monkeypatch.setattr(tmdb_store, "tmdb_get", fetch)
    client.get("/upcoming/history", headers=headers)
    assert calls["n"] == 1

    def forbidden(path, params=None, cache=True):
        raise AssertionError("a fully-aired season must not be refetched")

    monkeypatch.setattr(tmdb_store, "tmdb_get", forbidden)
    out = client.get("/upcoming/history", headers=headers).json()
    assert len(out) == 1


def test_sync_show_episodes_upserts_episode_rows(client, alice, monkeypatch):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload((1, "Pilot", "2020-01-05"), (2, "Secrets", "2020-01-12")),
    )
    client.get("/upcoming/history", headers=headers)

    db = SessionLocal()
    try:
        rows = db.query(Episode).order_by(Episode.episode_number).all()
        assert [(r.season, r.episode_number, r.name) for r in rows] == [
            (1, 1, "Pilot"),
            (1, 2, "Secrets"),
        ]
    finally:
        db.close()


def test_history_rejects_malformed_before_date(client, alice):
    """A malformed `before` cursor must return 422, not a 500 from fromisoformat."""
    _, headers = alice
    r = client.get("/upcoming/history", params={"before": "not-a-date"}, headers=headers)
    assert r.status_code == 422
