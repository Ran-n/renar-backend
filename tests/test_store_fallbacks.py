#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:10.215537
Revised: 2026/11/13 15:35:10.215537

Degraded paths of the cached settings/task-state readers and the TMDB/TVDB
stores: a failed settings or task-state load (fall back, keep the last good
value, retry next call), concurrent cache/episode inserts, a title deleted
mid-loop, and the post-response episode sync failing or finding nothing.
"""

import logging

import pytest
from _race_helpers import commit_elsewhere, hide_selects

from renar_backend import site_settings, task_runs
from renar_backend.database import SessionLocal
from renar_backend.models import Episode, MediaType, Title, TmdbCache
from renar_backend.routers import upcoming
from renar_backend.tmdb import tmdb_store
from renar_backend.tvdb.tvdb_store import sync_tvdb_episodes


@pytest.fixture
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _title(**fields) -> Title:
    fields.setdefault("media_type", MediaType.tv_show)
    fields.setdefault("title", "Dark")
    (title_id,) = commit_elsewhere(Title(**fields))
    return title_id


def _broken_session(*args, **kwargs):
    raise RuntimeError("database unreachable")


# ---------------------------------------------------------------------------
# site_settings.current()
# ---------------------------------------------------------------------------


def test_site_settings_fall_back_to_config_defaults_when_never_loaded(client, monkeypatch, caplog):
    monkeypatch.setattr(site_settings, "_cached", None)
    monkeypatch.setattr(site_settings, "_cache_ts", 0.0)
    monkeypatch.setattr(site_settings, "SessionLocal", _broken_session)

    with caplog.at_level(logging.ERROR, logger=site_settings.__name__):
        settings_row = site_settings.current()

    assert settings_row.premium_ranking_enabled is True
    assert "could not load site_settings" in caplog.text
    assert site_settings._cache_ts == 0.0  # not advanced: next call retries


def test_site_settings_keep_the_last_good_row_when_a_reload_fails(client, monkeypatch):
    good = site_settings.current()
    monkeypatch.setattr(site_settings, "_cache_ts", 0.0)  # expired
    monkeypatch.setattr(site_settings, "SessionLocal", _broken_session)

    assert site_settings.current() is good


# ---------------------------------------------------------------------------
# task_runs state
# ---------------------------------------------------------------------------


def test_task_state_keeps_the_last_good_state_when_a_reload_fails(client, monkeypatch, caplog):
    key = task_runs.TASKS[0].key
    task_runs.set_enabled(key, False)
    assert task_runs.is_enabled(key) is False
    monkeypatch.setattr(task_runs, "_state_cache_ts", 0.0)  # expired
    monkeypatch.setattr(task_runs, "SessionLocal", _broken_session)

    with caplog.at_level(logging.ERROR, logger=task_runs.__name__):
        assert task_runs.is_enabled(key) is False

    assert "could not load periodic task state" in caplog.text


# ---------------------------------------------------------------------------
# tmdb_store
# ---------------------------------------------------------------------------


def test_upsert_cache_refreshes_a_row_inserted_concurrently(db):
    title_id = _title(tmdb_id=1)
    commit_elsewhere(TmdbCache(title_id=title_id, kind="tv", season=-1, language="en", payload={"v": 1}))
    hide_selects(db, TmdbCache, times=1)

    tmdb_store.upsert_cache(db, title_id, "tv", -1, {"v": 2})
    db.flush()

    row = db.query(TmdbCache).filter_by(title_id=title_id).one()
    assert row.payload == {"v": 2}


def test_upsert_cache_logs_when_the_row_is_neither_insertable_nor_findable(db, caplog):
    title_id = _title(tmdb_id=2)
    commit_elsewhere(TmdbCache(title_id=title_id, kind="tv", season=-1, language="en", payload={"v": 1}))
    hide_selects(db, TmdbCache, times=None)

    with caplog.at_level(logging.ERROR, logger=tmdb_store.__name__):
        tmdb_store.upsert_cache(db, title_id, "tv", -1, {"v": 2})

    assert "neither insertable nor findable" in caplog.text


def test_warm_title_translations_skips_a_title_deleted_mid_loop(client, monkeypatch):
    title_id = _title(tmdb_id=3)
    from renar_backend import database

    real = database.SessionLocal
    opened = []

    def _session():
        session = real()
        opened.append(session)
        if len(opened) == 2:  # the per-title session: the row is gone by now
            hide_selects(session, Title, times=None)
        return session

    monkeypatch.setattr(database, "SessionLocal", _session)
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda *a, **kw: pytest.fail("must not fetch a vanished title"))

    tmdb_store.warm_title_translations([title_id], "es")

    assert len(opened) == 2


# ---------------------------------------------------------------------------
# tvdb_store.sync_tvdb_episodes
# ---------------------------------------------------------------------------


def test_sync_tvdb_episodes_skips_an_episode_inserted_concurrently(db):
    title_id = _title(tvdb_id=77)
    commit_elsewhere(Episode(title_id=title_id, season=1, episode_number=1, name="Pilot"))
    hide_selects(db, Episode, times=1)
    title = db.get(Title, title_id)

    sync_tvdb_episodes(
        db,
        title,
        [
            {"season": 1, "episode_number": 1, "name": "Pilot (TVDB)", "air_date": "2017-12-01"},
            {"season": 1, "episode_number": 2, "name": "Lies", "air_date": None},
        ],
    )
    db.flush()

    rows = db.query(Episode).filter_by(title_id=title_id).order_by(Episode.episode_number).all()
    assert [(r.episode_number, r.name) for r in rows] == [(1, "Pilot"), (2, "Lies")]


# ---------------------------------------------------------------------------
# upcoming._sync_episodes_background
# ---------------------------------------------------------------------------


def test_background_episode_sync_ignores_a_deleted_title(client, monkeypatch):
    monkeypatch.setattr(upcoming, "sync_show_episodes", lambda db, title: pytest.fail("nothing to sync"))

    upcoming._sync_episodes_background(2147483647)


def test_background_episode_sync_logs_a_failure_instead_of_raising(client, monkeypatch, caplog):
    title_id = _title(tmdb_id=4)

    def _boom(db, title):
        raise RuntimeError("TMDB down")

    monkeypatch.setattr(upcoming, "sync_show_episodes", _boom)

    with caplog.at_level(logging.ERROR, logger=upcoming.__name__):
        upcoming._sync_episodes_background(title_id)

    assert f"background episode sync failed for title {title_id}" in caplog.text
