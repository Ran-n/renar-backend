#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:18.246595
Revised: 2026/09/07 16:47:38.833210

TMDB write-through cache: persistence for tracked titles, freshness
window, offline fallback, typed Title columns, notifier integration and
the image proxy's content-addressed storage.
"""

import base64
import io
from datetime import date, timedelta

import pytest
from fastapi import HTTPException, status
from PIL import Image as PILImage

from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.media.storage import image_path
from renar_backend.models import ExternalImage, Image, Notification, Title, TmdbCache, User, utcnow
from renar_backend.routers import tmdb as tmdb_router
from renar_backend.social.notifier import check_new_episodes
from renar_backend.tmdb import tmdb_store

RAW_TV = {
    "name": "The Show",
    "first_air_date": "2020-01-05",
    "last_air_date": "2023-05-01",
    "overview": "A show about tests.",
    "tagline": "Trust nothing.",
    "status": "Returning Series",
    "episode_run_time": [40],
    "number_of_episodes": 16,
    "number_of_seasons": 2,
    "genres": [{"name": "Drama"}],
    "poster_path": "/p.jpg",
    "next_episode_to_air": {"air_date": "2030-01-01"},
    "created_by": [{"name": "Cora Creator"}],
    "seasons": [
        {"season_number": 1, "name": "Season 1", "episode_count": 8},
        {"season_number": 2, "name": "Season 2", "episode_count": 8},
    ],
}

RAW_SEASON = {
    "episodes": [
        {"episode_number": 1, "name": "Pilot", "air_date": "2020-01-05", "runtime": 40, "overview": "It begins."},
        {"episode_number": 2, "name": "Second", "air_date": "2020-01-12", "runtime": 40, "overview": ""},
    ]
}

RAW_CREDITS = {
    "cast": [{"name": "Ana Actor", "character": "Lead", "profile_path": "/a.jpg"}],
    "crew": [{"name": "Dan Director", "job": "Director"}],
}


def _tmdb_down(path, params=None, cache=True):
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB")


def _tmdb_must_not_be_called(path, params=None, cache=True):
    raise AssertionError(f"unexpected TMDB fetch: {path}")


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def add_show(client, headers, monkeypatch, tmdb_id: int = 100) -> dict:
    """Track a TV show; the add itself syncs details from (patched) TMDB."""
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_TV)
    r = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "The Show", "tmdb_id": tmdb_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_details_persisted_for_tracked_title(client, alice, monkeypatch, db):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    r = client.get("/tmdb/details", params={"media_type": "tv_show", "tmdb_id": 100}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["show_status"] == "Returning Series"
    assert body["last_air_year"] == 2023
    assert body["tagline"] == "Trust nothing."

    row = db.query(TmdbCache).filter_by(kind="details").one()
    assert row.payload["name"] == "The Show"


def test_details_fresh_copy_served_without_fetch(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch)  # persisted the payload at add time

    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_must_not_be_called)
    r = client.get("/tmdb/details", params={"media_type": "tv_show", "tmdb_id": 100}, headers=headers)
    assert r.status_code == 200
    assert r.json()["overview"] == "A show about tests."


def test_details_stale_fallback_when_tmdb_down(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    monkeypatch.setattr(settings, "tmdb_db_cache_hours", 0)  # force refresh attempt
    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)
    r = client.get("/tmdb/details", params={"media_type": "tv_show", "tmdb_id": 100}, headers=headers)
    assert r.status_code == 200
    assert r.json()["show_status"] == "Returning Series"


def test_untracked_title_not_persisted_and_502_when_down(client, alice, monkeypatch, db):
    _, headers = alice
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_TV)
    r = client.get("/tmdb/details", params={"media_type": "tv_show", "tmdb_id": 999}, headers=headers)
    assert r.status_code == 200
    assert db.query(TmdbCache).count() == 0

    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)
    r = client.get("/tmdb/details", params={"media_type": "tv_show", "tmdb_id": 999}, headers=headers)
    assert r.status_code == 502


def test_add_syncs_typed_title_columns(client, alice, monkeypatch, db):
    _, headers = alice
    item = add_show(client, headers, monkeypatch)

    title = db.query(Title).one()
    assert title.overview == "A show about tests."
    assert title.tagline == "Trust nothing."
    assert title.show_status == "Returning Series"
    assert title.next_episode_air_date == date(2030, 1, 1)
    assert title.total_seasons == 2
    assert title.total_episodes == 16
    assert title.genres == ["Drama"]

    # the library list exposes them (offline-capable clients read these)
    assert item["show_status"] == "Returning Series"
    assert item["overview"] == "A show about tests."
    assert item["total_seasons"] == 2


def test_season_stale_fallback(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_SEASON)
    r = client.get("/tmdb/season", params={"tmdb_id": 100, "season_number": 1}, headers=headers)
    assert r.status_code == 200
    assert r.json()[0]["name"] == "Pilot"

    monkeypatch.setattr(settings, "tmdb_db_cache_hours", 0)
    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)
    r = client.get("/tmdb/season", params={"tmdb_id": 100, "season_number": 1}, headers=headers)
    assert r.status_code == 200
    assert [e["episode"] for e in r.json()] == [1, 2]


def test_credits_stale_fallback(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: RAW_CREDITS if path.endswith("/credits") else RAW_TV,
    )
    r = client.get("/tmdb/credits", params={"media_type": "tv_show", "tmdb_id": 100}, headers=headers)
    assert r.status_code == 200
    assert r.json()["cast"][0]["name"] == "Ana Actor"

    monkeypatch.setattr(settings, "tmdb_db_cache_hours", 0)
    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)
    r = client.get("/tmdb/credits", params={"media_type": "tv_show", "tmdb_id": 100}, headers=headers)
    assert r.status_code == 200
    assert r.json()["directors"] == [{"name": "Cora Creator", "profile_url": None}]


def test_notifier_persists_status_and_skips_ended_shows(client, alice, monkeypatch, db):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    aired = (date.today() - timedelta(days=1)).isoformat()
    ended = {
        **RAW_TV,
        "status": "Ended",
        "next_episode_to_air": None,
        "last_episode_to_air": {"air_date": aired, "season_number": 2, "episode_number": 8, "name": "Finale"},
    }
    created = check_new_episodes(db, fetch=lambda tmdb_id: ended)
    assert created == 1  # the finale notification still goes out
    assert db.query(Notification).count() == 1
    title = db.query(Title).one()
    assert title.show_status == "Ended"
    assert title.next_episode_air_date is None

    def _fetch_forbidden(tmdb_id):
        raise AssertionError("ended shows must not be polled")

    assert check_new_episodes(db, fetch=_fetch_forbidden) == 0


def test_image_proxy_stores_in_image_store(client, monkeypatch, db):
    from renar_backend.tmdb import tmdb_http

    payload = b"x" * 600  # anything past the placeholder threshold

    class FakeResponse:
        status_code = 200
        content = payload

    monkeypatch.setattr(tmdb_http.image_http_client, "get", lambda url, **kw: FakeResponse())
    r = client.get("/tmdb/image/w342/poster.jpg")
    assert r.status_code == 200
    assert r.content == payload

    mapping = db.query(ExternalImage).filter_by(source="tmdb", key="w342/poster.jpg").one()
    image = db.get(Image, mapping.image_id)
    assert image_path(image.hash).is_file()

    # second hit comes from the store, never from TMDB
    def _forbidden(url, **kw):
        raise AssertionError("image must be served from the store")

    monkeypatch.setattr(tmdb_http.image_http_client, "get", _forbidden)
    r = client.get("/tmdb/image/w342/poster.jpg")
    assert r.status_code == 200
    assert r.content == payload


def _set_premium(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()


def _png_b64() -> str:
    img = PILImage.new("RGB", (20, 30), (200, 30, 30))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_trending_shows_premium_users_custom_poster(client, alice, monkeypatch):
    """A premium user's custom poster (set on their LibraryEntry) must win
    over the shared TMDB poster in Explore/Trending — not just on the
    library/detail views — since the shared Title row is never updated."""
    user, headers = alice
    item = add_show(client, headers, monkeypatch, tmdb_id=100)
    _set_premium(user["id"])
    r = client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    assert r.status_code == 200
    custom_poster_url = r.json()["custom_poster_url"]
    assert custom_poster_url

    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {"results": [{"id": 100, "name": "The Show", "poster_path": "/stale.jpg"}]},
    )
    r = client.get("/tmdb/trending", params={"media_type": "tv_show", "language": "en"}, headers=headers)
    assert r.status_code == 200
    result = next(x for x in r.json() if x["tmdb_id"] == 100)
    assert result["poster_url"] == custom_poster_url


def test_search_falls_back_to_local_catalog_when_tmdb_down(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch, tmdb_id=100)

    def _search_down(path, params=None):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB")

    monkeypatch.setattr(tmdb_router, "tmdb_get", _search_down)
    r = client.get("/tmdb/search", params={"media_type": "tv_show", "query": "show"}, headers=headers)
    assert r.status_code == 200
    result = next(x for x in r.json() if x["tmdb_id"] == 100)
    assert result["title"] == "The Show"
    assert result["vote_average"] is None


def test_search_404_does_not_fall_back(client, alice, monkeypatch):
    """A genuine "nothing found" from TMDB is not TMDB being down — it must
    surface as an empty/error result, not silently swap in local titles."""
    _, headers = alice

    def _search_404(path, params=None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found on TMDB")

    monkeypatch.setattr(tmdb_router, "tmdb_get", _search_404)
    r = client.get("/tmdb/search", params={"media_type": "tv_show", "query": "show"}, headers=headers)
    assert r.status_code == 404


def test_popular_falls_back_to_local_catalog_ranked_by_library_adds(client, alice, bob, make_user, monkeypatch):
    _, alice_headers = alice
    _, bob_headers = bob
    _, carol_headers = make_user("carol")
    add_show(client, alice_headers, monkeypatch, tmdb_id=100)  # 1 add
    add_show(client, bob_headers, monkeypatch, tmdb_id=200)  # 2 adds
    add_show(client, carol_headers, monkeypatch, tmdb_id=200)

    def _popular_down(path, params=None):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB")

    monkeypatch.setattr(tmdb_router, "tmdb_get", _popular_down)
    r = client.get("/tmdb/popular", params={"media_type": "tv_show"}, headers=alice_headers)
    assert r.status_code == 200
    ids = [x["tmdb_id"] for x in r.json()]
    assert ids[0] == 200  # more library adds ranks first


def test_trending_ignores_custom_poster_without_premium(client, alice, monkeypatch, db):
    """A lapsed/non-premium user must see the shared TMDB poster, matching
    LibraryEntry.poster_url's own premium gate."""
    user, headers = alice
    item = add_show(client, headers, monkeypatch, tmdb_id=101)
    _set_premium(user["id"])
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    db.get(User, user["id"]).premium_until = utcnow() - timedelta(days=1)
    db.commit()

    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {"results": [{"id": 101, "name": "The Show", "poster_path": "/fresh.jpg"}]},
    )
    r = client.get("/tmdb/trending", params={"media_type": "tv_show", "language": "en"}, headers=headers)
    assert r.status_code == 200
    result = next(x for x in r.json() if x["tmdb_id"] == 101)
    assert result["poster_url"] == "https://image.tmdb.org/t/p/w500/fresh.jpg"
