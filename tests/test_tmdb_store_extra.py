#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/09/01
Revised: 2026/09/02 10:58:45.523221

tmdb_store.py coverage gaps: _parse_date ValueError, localized_titles,
warm_title_translations, sync_title_details edge paths (original_title,
imdb_id, wikidata_id, backdrop_url, last_episode runtime, tvdb_id
IntegrityError), cached_tmdb locale branch, sync_episodes update path, and
sync_show_episodes error handling.
"""

from datetime import date

import pytest
from fastapi import HTTPException, status

from renar_backend.database import SessionLocal
from renar_backend.models import Episode, MediaType, Title, TmdbCache
from renar_backend.tmdb import tmdb_store
from renar_backend.tmdb.tmdb_http import BACKDROP_BASE
from renar_backend.tmdb.tmdb_store import NO_SEASON, _parse_date, localized_titles

RAW_TV = {
    "name": "The Show",
    "first_air_date": "2020-01-05",
    "overview": "A show about tests.",
    "tagline": "Trust nothing.",
    "status": "Returning Series",
    "episode_run_time": [40],
    "number_of_episodes": 16,
    "number_of_seasons": 2,
    "genres": [{"name": "Drama"}],
    "poster_path": "/p.jpg",
    "next_episode_to_air": {"air_date": "2030-01-01"},
}


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def add_show(client, headers, monkeypatch, tmdb_id: int = 100) -> dict:
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_TV)
    r = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "The Show", "tmdb_id": tmdb_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _make_title(db, media_type: MediaType = MediaType.tv_show, tmdb_id: int = 1) -> Title:
    t = Title(title="Test", media_type=media_type, tmdb_id=tmdb_id, year=2020)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


def test_parse_date_valid_iso():
    assert _parse_date("2021-06-15") == date(2021, 6, 15)


def test_parse_date_none_returns_none():
    assert _parse_date(None) is None


def test_parse_date_empty_string_returns_none():
    assert _parse_date("") is None


def test_parse_date_malformed_string_returns_none():
    """ValueError path: non-ISO string must log a warning and return None."""
    assert _parse_date("not-a-date") is None


def test_parse_date_out_of_range_returns_none():
    assert _parse_date("2021-99-99") is None


# ---------------------------------------------------------------------------
# localized_titles
# ---------------------------------------------------------------------------


def test_localized_titles_returns_empty_for_english(db):
    assert localized_titles(db, [1, 2], "en") == {}


def test_localized_titles_returns_empty_for_no_ids(db):
    assert localized_titles(db, [], "gl") == {}


def test_localized_titles_reads_name_from_cached_payload(client, alice, monkeypatch, db):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    title = db.query(Title).one()
    row = TmdbCache(
        title_id=title.id,
        kind="details",
        season=NO_SEASON,
        language="es",
        payload={"name": "El Programa"},
    )
    db.add(row)
    db.commit()

    result = localized_titles(db, [title.id], "es")
    assert result == {title.id: "El Programa"}


def test_localized_titles_reads_title_field_from_film_payload(client, alice, monkeypatch, db):
    """Film payloads use the 'title' key instead of 'name'."""
    _, headers = alice
    # Add as a film via the raw DB path (faster than full API call for this edge case).
    title_obj = Title(title="The Film", media_type=MediaType.film, tmdb_id=50)
    db.add(title_obj)
    db.commit()
    db.refresh(title_obj)

    row = TmdbCache(
        title_id=title_obj.id,
        kind="details",
        season=NO_SEASON,
        language="gl",
        payload={"title": "A Película"},
    )
    db.add(row)
    db.commit()

    result = localized_titles(db, [title_obj.id], "gl")
    assert result == {title_obj.id: "A Película"}


def test_localized_titles_ignores_payload_without_name_or_title(client, alice, monkeypatch, db):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    title = db.query(Title).one()
    row = TmdbCache(
        title_id=title.id,
        kind="details",
        season=NO_SEASON,
        language="pt",
        payload={"overview": "No name field here"},
    )
    db.add(row)
    db.commit()

    result = localized_titles(db, [title.id], "pt")
    assert result == {}


# ---------------------------------------------------------------------------
# warm_title_translations
# ---------------------------------------------------------------------------


def test_warm_title_translations_creates_locale_cache_row(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch)

    db_check = SessionLocal()
    try:
        title_id = db_check.query(Title).one().id
    finally:
        db_check.close()

    spanish_payload = {**RAW_TV, "name": "El Programa"}
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: spanish_payload)

    tmdb_store.warm_title_translations([title_id], "es")

    db_check = SessionLocal()
    try:
        row = db_check.query(TmdbCache).filter_by(title_id=title_id, kind="details", language="es").first()
        assert row is not None
        assert row.payload.get("name") == "El Programa"
    finally:
        db_check.close()


def test_warm_title_translations_skips_on_http_exception(client, alice, monkeypatch):
    """HTTPException during warm-up must be swallowed with a warning, not raised."""
    _, headers = alice
    add_show(client, headers, monkeypatch)

    db_check = SessionLocal()
    try:
        title_id = db_check.query(Title).one().id
    finally:
        db_check.close()

    def _tmdb_down(path, params=None, cache=True):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB down")

    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)
    # Must not raise.
    tmdb_store.warm_title_translations([title_id], "es")


def test_warm_title_translations_ignores_title_without_tmdb_id(client, alice, monkeypatch, db):
    """Titles with no tmdb_id must be silently skipped."""
    _, headers = alice
    # Register a title without tmdb_id.
    r = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "No TMDB"},
        headers=headers,
    )
    assert r.status_code == 201
    title_id = db.query(Title).one().id

    called = []
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda *a, **kw: called.append(a) or RAW_TV)
    tmdb_store.warm_title_translations([title_id], "es")
    assert not called


# ---------------------------------------------------------------------------
# sync_title_details edge paths
# ---------------------------------------------------------------------------


def test_sync_title_details_sets_original_title(db):
    title = _make_title(db)
    tmdb_store.sync_title_details(db, title, {"original_name": "Оригинал"})
    assert title.original_title == "Оригинал"


def test_sync_title_details_original_title_from_film_key(db):
    title = _make_title(db, media_type=MediaType.film)
    tmdb_store.sync_title_details(db, title, {"original_title": "Original Title"})
    assert title.original_title == "Original Title"


def test_sync_title_details_sets_imdb_id_from_top_level(db):
    title = _make_title(db)
    tmdb_store.sync_title_details(db, title, {"imdb_id": "tt1234567"})
    assert title.imdb_id == "tt1234567"


def test_sync_title_details_sets_imdb_id_from_external_ids(db):
    title = _make_title(db)
    tmdb_store.sync_title_details(db, title, {"external_ids": {"imdb_id": "tt9876543"}})
    assert title.imdb_id == "tt9876543"


def test_sync_title_details_sets_wikidata_id(db):
    title = _make_title(db)
    tmdb_store.sync_title_details(db, title, {"external_ids": {"wikidata_id": "Q123456"}})
    assert title.wikidata_id == "Q123456"


def test_sync_title_details_sets_backdrop_url(db):
    title = _make_title(db)
    tmdb_store.sync_title_details(db, title, {"backdrop_path": "/back.jpg"})
    assert title.backdrop_url == f"{BACKDROP_BASE}/back.jpg"


def test_sync_title_details_tv_runtime_from_last_episode_to_air(db):
    """When episode_run_time is empty, runtime falls back to last_episode_to_air."""
    title = _make_title(db)
    data = {
        "episode_run_time": [],
        "last_episode_to_air": {"runtime": 47},
    }
    tmdb_store.sync_title_details(db, title, data)
    assert title.runtime_minutes == 47


def test_sync_title_details_tvdb_id_collision_keeps_existing(db):
    """An IntegrityError from a conflicting tvdb_id must be caught; the
    existing tvdb_id must remain unchanged on the colliding title."""
    # Title A owns tvdb_id=42.
    title_a = Title(title="A", media_type=MediaType.tv_show, tmdb_id=10, tvdb_id=42)
    db.add(title_a)
    db.commit()

    # Title B has no tvdb_id yet.
    title_b = Title(title="B", media_type=MediaType.tv_show, tmdb_id=20)
    db.add(title_b)
    db.commit()
    db.refresh(title_b)

    # Syncing external_ids.tvdb_id=42 onto Title B must hit the IntegrityError
    # catch block and leave title_b.tvdb_id as None.
    data = {"external_ids": {"tvdb_id": 42}}
    tmdb_store.sync_title_details(db, title_b, data)
    db.refresh(title_b)
    assert title_b.tvdb_id is None


# ---------------------------------------------------------------------------
# cached_tmdb locale param (line 238)
# ---------------------------------------------------------------------------


def test_cached_tmdb_adds_locale_param_for_non_english_language(client, alice, monkeypatch):
    """Language codes in TMDB_LOCALE must appear as a 'language' query param."""
    _, headers = alice
    add_show(client, headers, monkeypatch)  # stores "en" details cache

    captured: dict = {}

    def fake_tmdb_get(path, params=None, cache=True):
        captured.update(params or {})
        return {**RAW_TV, "name": "El Programa"}

    monkeypatch.setattr(tmdb_store, "tmdb_get", fake_tmdb_get)
    # "es" details not cached → cached_tmdb will call tmdb_get with locale param.
    r = client.get(
        "/tmdb/details",
        params={"media_type": "tv_show", "tmdb_id": 100, "language": "es"},
        headers=headers,
    )
    assert r.status_code == 200
    assert captured.get("language") == "es-ES"


def test_cached_tmdb_no_locale_for_unmapped_language(client, alice, monkeypatch):
    """Language codes not in TMDB_LOCALE must not add a 'language' param."""
    _, headers = alice
    add_show(client, headers, monkeypatch)

    captured: dict = {}

    def fake_tmdb_get(path, params=None, cache=True):
        captured.update(params or {})
        return RAW_TV

    monkeypatch.setattr(tmdb_store, "tmdb_get", fake_tmdb_get)
    r = client.get(
        "/tmdb/details",
        params={"media_type": "tv_show", "tmdb_id": 100, "language": "eo"},
        headers=headers,
    )
    assert r.status_code == 200
    assert "language" not in captured


# ---------------------------------------------------------------------------
# cached_tmdb: refresh stale details for tracked title (line 252)
# ---------------------------------------------------------------------------


def test_cached_tmdb_refreshes_stale_details_and_syncs_title(client, alice, monkeypatch, db):
    """A stale details cache row must be refreshed when TMDB is reachable, and
    sync_title_details must be called with the new payload (line 252 True branch).

    Sets fetched_at to the distant past so _is_fresh returns False regardless
    of the tmdb_db_cache_hours setting — avoids coupling to site_settings timing.
    """
    import datetime as _dt

    _, headers = alice
    add_show(client, headers, monkeypatch)

    title = db.query(Title).one()

    # Mark the cache row as definitely stale.
    row = db.query(TmdbCache).filter_by(title_id=title.id, kind="details").one()
    row.fetched_at = _dt.datetime(2000, 1, 1, tzinfo=_dt.UTC)
    db.commit()

    updated_payload = {**RAW_TV, "overview": "Updated overview from refresh"}
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: updated_payload)

    # Call cached_tmdb directly to avoid HTTP-layer site_settings caching issues.
    result = tmdb_store.cached_tmdb(db, title.media_type, title.tmdb_id, "details", f"/tv/{title.tmdb_id}")
    assert result["overview"] == "Updated overview from refresh"

    # sync_title_details must have been called (line 252 True branch).
    db.refresh(title)
    assert title.overview == "Updated overview from refresh"


# ---------------------------------------------------------------------------
# sync_episodes
# ---------------------------------------------------------------------------


def test_sync_episodes_inserts_new_rows(db):
    title = _make_title(db)
    data = {
        "episodes": [
            {"episode_number": 1, "name": "Pilot", "air_date": "2020-01-05"},
            {"episode_number": 2, "name": "Second", "air_date": "2020-01-12"},
        ]
    }
    tmdb_store.sync_episodes(db, title, 1, data)
    db.commit()
    assert db.query(Episode).filter_by(title_id=title.id, season=1).count() == 2


def test_sync_episodes_updates_existing_row(db):
    """Second call with different data must update the existing Episode row."""
    title = _make_title(db)
    data_v1 = {"episodes": [{"episode_number": 1, "name": "Pilot", "air_date": "2020-01-05"}]}
    tmdb_store.sync_episodes(db, title, 1, data_v1)
    db.commit()

    data_v2 = {"episodes": [{"episode_number": 1, "name": "Pilot (Recut)", "air_date": "2020-01-06"}]}
    tmdb_store.sync_episodes(db, title, 1, data_v2)
    db.commit()

    row = db.query(Episode).filter_by(title_id=title.id, season=1, episode_number=1).one()
    assert row.name == "Pilot (Recut)"
    assert row.air_date == date(2020, 1, 6)
    # Only one row must exist (update, not duplicate insert).
    assert db.query(Episode).filter_by(title_id=title.id, season=1).count() == 1


def test_sync_episodes_skips_episode_without_episode_number(db):
    """Episodes missing episode_number must be silently skipped (continue branch)."""
    title = _make_title(db)
    data = {"episodes": [{"name": "No number", "air_date": "2020-01-05"}]}
    tmdb_store.sync_episodes(db, title, 1, data)
    db.commit()
    assert db.query(Episode).count() == 0


# ---------------------------------------------------------------------------
# sync_show_episodes error handling (lines 314-316)
# ---------------------------------------------------------------------------


def test_sync_show_episodes_skips_failed_season_fetch(client, alice, monkeypatch, db):
    """HTTPException from cached_tmdb must be caught per season; the rest of
    the loop must continue and the function must not raise."""
    _, headers = alice
    add_show(client, headers, monkeypatch)  # total_seasons=2 from RAW_TV

    title = db.query(Title).one()

    def _tmdb_down(path, params=None, cache=True):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB down")

    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)
    # Must not raise; both season fetches fail gracefully.
    tmdb_store.sync_show_episodes(db, title)
    assert db.query(Episode).count() == 0


def test_sync_show_episodes_skips_show_with_no_total_seasons(db):
    title = _make_title(db)
    title.total_seasons = None
    db.commit()
    # Must return immediately without touching TMDB.
    tmdb_store.sync_show_episodes(db, title)
    assert db.query(Episode).count() == 0


def test_sync_show_episodes_skips_already_aired_season(db, monkeypatch):
    """A season whose last known episode has already aired must be skipped
    without a TMDB fetch (line 304 continue branch)."""
    from datetime import date, timedelta

    title = _make_title(db)
    title.total_seasons = 1
    title.tmdb_id = 1
    db.commit()

    # Pre-insert an episode for season 1 with a past air_date.
    past_date = date.today() - timedelta(days=10)
    db.add(Episode(title_id=title.id, season=1, episode_number=1, air_date=past_date))
    db.commit()

    called = []
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda *a, **kw: called.append(a) or {})
    tmdb_store.sync_show_episodes(db, title)
    # Season 1 fully aired → must be skipped; no TMDB call expected.
    assert not called


def test_sync_show_episodes_fetches_and_syncs_unairedseason(db, monkeypatch):
    """A season with no episodes yet must be fetched via cached_tmdb and its
    episodes inserted (line 317: sync_episodes called after successful fetch)."""
    title = _make_title(db)
    title.total_seasons = 1
    title.tmdb_id = 1
    db.commit()

    season_payload = {
        "episodes": [
            {"episode_number": 1, "name": "Pilot", "air_date": "2030-01-01"},
        ]
    }
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: season_payload)
    tmdb_store.sync_show_episodes(db, title)

    ep = db.query(Episode).filter_by(title_id=title.id, season=1, episode_number=1).first()
    assert ep is not None
    assert ep.name == "Pilot"


# ---------------------------------------------------------------------------
# cached_tmdb stale fallback: TMDB down, stale row exists (lines 245-246)
# ---------------------------------------------------------------------------


def test_cached_tmdb_stale_fallback_when_tmdb_down(client, alice, monkeypatch, db):
    """When TMDB is down and a stale cache row exists, cached_tmdb must return
    the stale payload (lines 245-246) rather than raising."""
    import datetime as _dt

    _, headers = alice
    add_show(client, headers, monkeypatch)

    title = db.query(Title).one()

    # Mark the cache row as definitely stale.
    row = db.query(TmdbCache).filter_by(title_id=title.id, kind="details").one()
    row.fetched_at = _dt.datetime(2000, 1, 1, tzinfo=_dt.UTC)
    db.commit()

    def _tmdb_down(path, params=None, cache=True):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB down")

    monkeypatch.setattr(tmdb_store, "tmdb_get", _tmdb_down)

    # Must return the stale payload rather than raising.
    result = tmdb_store.cached_tmdb(db, title.media_type, title.tmdb_id, "details", f"/tv/{title.tmdb_id}")
    assert result.get("name") == "The Show"  # stale payload from RAW_TV
