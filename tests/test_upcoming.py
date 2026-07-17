#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 18:10:00.000000
Revised: 2026/07/12 18:10:00.000000

/upcoming reads next-episode/release-date data straight off Title (synced
by the background pollers) instead of hitting TMDB on the request path;
these tests seed that data directly. Also covers the film-release poller.
"""

from datetime import date, timedelta

from renar_backend.database import SessionLocal
from renar_backend.social.notifier import check_upcoming_films


def _add(client, headers, **kwargs) -> dict:
    payload = {"title": "Placeholder", "status": "watching"} | kwargs
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _set_title_for_entry(client, headers, item_id: int, **fields) -> None:
    from renar_backend.models import LibraryEntry

    db = SessionLocal()
    try:
        entry = db.get(LibraryEntry, item_id)
        for k, v in fields.items():
            setattr(entry.title_ref, k, v)
        db.commit()
    finally:
        db.close()


def test_upcoming_empty(client, alice):
    _, headers = alice
    assert client.get("/upcoming", headers=headers).json() == []


def test_upcoming_lists_tv_show_with_future_episode(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    when = date.today() + timedelta(days=5)
    _set_title_for_entry(
        client,
        headers,
        show["id"],
        next_episode_air_date=when,
        next_episode_season=2,
        next_episode_number=3,
        next_episode_name="Ghosts",
    )
    out = client.get("/upcoming", headers=headers).json()
    assert len(out) == 1
    assert out[0]["media_type"] == "tv_show"
    assert out[0]["date"] == when.isoformat()
    assert (out[0]["season"], out[0]["episode"], out[0]["episode_name"]) == (2, 3, "Ghosts")


def test_upcoming_excludes_tv_show_with_no_or_past_episode(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    # no next_episode_air_date set at all
    assert client.get("/upcoming", headers=headers).json() == []
    _set_title_for_entry(client, headers, show["id"], next_episode_air_date=date.today() - timedelta(days=1))
    assert client.get("/upcoming", headers=headers).json() == []


def test_upcoming_excludes_dropped_tv_show(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="dropped")
    _set_title_for_entry(client, headers, show["id"], next_episode_air_date=date.today() + timedelta(days=5))
    assert client.get("/upcoming", headers=headers).json() == []


def test_upcoming_lists_want_to_watch_film_with_future_release(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Dune Part Three", tmdb_id=999, status="want_to_watch")
    when = date.today() + timedelta(days=30)
    _set_title_for_entry(client, headers, film["id"], release_date=when)
    out = client.get("/upcoming", headers=headers).json()
    assert len(out) == 1
    assert out[0]["media_type"] == "film"
    assert out[0]["date"] == when.isoformat()


def test_upcoming_excludes_already_released_or_non_want_to_watch_film(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Old Movie", tmdb_id=998, status="want_to_watch")
    _set_title_for_entry(client, headers, film["id"], release_date=date.today() - timedelta(days=1))
    assert client.get("/upcoming", headers=headers).json() == []

    watched = _add(client, headers, media_type="film", title="Watched Movie", tmdb_id=997, status="completed")
    _set_title_for_entry(client, headers, watched["id"], release_date=date.today() + timedelta(days=10))
    assert client.get("/upcoming", headers=headers).json() == []


def test_upcoming_status_filter(client, alice):
    _, headers = alice
    watching = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523, status="watching")
    _set_title_for_entry(client, headers, watching["id"], next_episode_air_date=date.today() + timedelta(days=1))
    want = _add(client, headers, media_type="film", title="Dune Part Three", tmdb_id=999, status="want_to_watch")
    _set_title_for_entry(client, headers, want["id"], release_date=date.today() + timedelta(days=1))

    out = client.get("/upcoming", params={"status_filter": "watching"}, headers=headers).json()
    assert len(out) == 1
    assert out[0]["media_type"] == "tv_show"


# ---------- film release-date poller ----------


def _fake_fetch(release_date: str):
    def fetch(tmdb_id: int) -> dict:
        return {"release_date": release_date}

    return fetch


def test_film_checker_refreshes_release_date(client, alice):
    _, headers = alice
    _add(client, headers, media_type="film", title="Dune Part Three", tmdb_id=999, status="want_to_watch")
    new_date = (date.today() + timedelta(days=60)).isoformat()

    db = SessionLocal()
    try:
        assert check_upcoming_films(db, fetch=_fake_fetch(new_date)) == 1
    finally:
        db.close()

    out = client.get("/upcoming", headers=headers).json()
    assert len(out) == 1
    assert out[0]["date"] == new_date


def test_film_checker_skips_already_released_film(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Old Movie", tmdb_id=998, status="want_to_watch")
    _set_title_for_entry(client, headers, film["id"], release_date=date.today() - timedelta(days=1))

    def fail_if_called(tmdb_id: int) -> dict:
        raise AssertionError("should not poll an already-released film")

    db = SessionLocal()
    try:
        assert check_upcoming_films(db, fetch=fail_if_called) == 0
    finally:
        db.close()


def test_film_checker_survives_fetch_failure(client, alice):
    _, headers = alice
    _add(client, headers, media_type="film", title="Dune Part Three", tmdb_id=999, status="want_to_watch")

    def broken_fetch(tmdb_id: int) -> dict:
        raise RuntimeError("TMDB down")

    db = SessionLocal()
    try:
        assert check_upcoming_films(db, fetch=broken_fetch) == 0
    finally:
        db.close()
