#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/23 11:49:59.650423
Revised: 2026/11/23 12:52:18.499855

Episodes TMDB adds to a season after all the ones it listed have aired: the
show's details announce them, and the catalog must fetch the season again
(tmdb_store.sync_show_episodes / sync_announced_seasons) so Home's Watch Next
shows them. Before, a season whose last known episode had aired counted as
finished forever.
"""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException, status

from renar_backend.database import SessionLocal
from renar_backend.models import Episode, EpisodeWatch, LibraryEntry, MediaType, Title, utcnow
from renar_backend.social.notifier import check_new_episodes
from renar_backend.tmdb import tmdb_store
from renar_backend.tmdb.tmdb_store import NO_SEASON


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _make_title(db) -> Title:
    title = Title(title="Test", media_type=MediaType.tv_show, tmdb_id=1, year=2020)
    db.add(title)
    db.commit()
    return title


def _weekly_show(db, announced: dict | None, known=(1, 2)) -> Title:
    """A one-season show whose known episodes have all aired, with `announced`
    as its stored details."""
    title = _make_title(db)
    title.total_seasons = 1
    for number in known:
        db.add(Episode(title_id=title.id, season=1, episode_number=number, air_date=date(2026, 1, number)))
    if announced is not None:
        tmdb_store.upsert_cache(db, title.id, "details", NO_SEASON, announced)
    db.commit()
    return title


def _serve_season(monkeypatch, *numbers) -> list:
    calls = []

    def fetch(path, params=None, cache=True):
        calls.append((path, cache))
        return {"episodes": [{"episode_number": n, "name": f"E{n}", "air_date": f"2026-01-{n:02d}"} for n in numbers]}

    monkeypatch.setattr(tmdb_store, "tmdb_get", fetch)
    return calls


def _numbers(db, title) -> list[int]:
    rows = db.query(Episode).filter_by(title_id=title.id).order_by(Episode.episode_number)
    return [row.episode_number for row in rows]


_SYNCS = pytest.mark.parametrize("sync", [tmdb_store.sync_show_episodes, tmdb_store.sync_announced_seasons])


@_SYNCS
@pytest.mark.parametrize("key", ["last_episode_to_air", "next_episode_to_air"])
def test_announced_episode_reopens_a_season_that_looked_finished(db, monkeypatch, sync, key):
    title = _weekly_show(db, {key: {"season_number": 1, "episode_number": 3}})
    calls = _serve_season(monkeypatch, 1, 2, 3)
    sync(db, title)
    assert calls == [("/tv/1/season/1", False)]
    assert _numbers(db, title) == [1, 2, 3]


@_SYNCS
@pytest.mark.parametrize(
    "announced",
    [
        None,
        {"last_episode_to_air": None, "next_episode_to_air": None},
        {"last_episode_to_air": {"season_number": 1, "episode_number": 2}},
        # details number lower than the season's own (a TMDB renumbering)
        {"last_episode_to_air": {"season_number": 1, "episode_number": 1}},
        {"last_episode_to_air": {"season_number": 0, "episode_number": 9}},
    ],
)
def test_season_with_everything_announced_is_not_refetched(db, monkeypatch, sync, announced):
    title = _weekly_show(db, announced)
    calls = _serve_season(monkeypatch, 1, 2, 3)
    sync(db, title)
    assert calls == []


@_SYNCS
def test_season_page_older_than_the_announcement_is_refetched_once(db, monkeypatch, sync):
    """A season page cached before the announcement is refetched although
    it's "fresh"; one fetched after it, still without the episode, is not."""
    title = _weekly_show(db, None)
    tmdb_store.upsert_cache(db, title.id, "season", 1, {"episodes": []})
    db.commit()
    tmdb_store.upsert_cache(
        db, title.id, "details", NO_SEASON, {"last_episode_to_air": {"season_number": 1, "episode_number": 3}}
    )
    db.commit()
    calls = _serve_season(monkeypatch, 1, 2)
    sync(db, title)
    sync(db, title)
    assert len(calls) == 1


def test_announced_sync_fetches_a_season_never_synced(db, monkeypatch):
    title = _weekly_show(db, {"next_episode_to_air": {"season_number": 2, "episode_number": 1}})
    calls = _serve_season(monkeypatch, 1)
    tmdb_store.sync_announced_seasons(db, title)
    assert [path for path, _ in calls] == ["/tv/1/season/2"]


def test_announced_sync_survives_tmdb_being_down(db, monkeypatch):
    title = _weekly_show(db, {"last_episode_to_air": {"season_number": 1, "episode_number": 3}})

    def down(path, params=None, cache=True):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB down")

    monkeypatch.setattr(tmdb_store, "tmdb_get", down)
    tmdb_store.sync_announced_seasons(db, title)
    assert _numbers(db, title) == [1, 2]


def test_announced_sync_ignores_a_title_without_tmdb_id(db, monkeypatch):
    title = _weekly_show(db, {"last_episode_to_air": {"season_number": 1, "episode_number": 3}})
    title.tmdb_id = None
    db.commit()
    calls = _serve_season(monkeypatch, 1, 2, 3)
    tmdb_store.sync_announced_seasons(db, title)
    assert calls == []


def test_sync_episodes_losing_an_insert_race_keeps_the_rest(db, monkeypatch):
    """Another session inserts episode 1 between the lookup and the insert:
    episode 2 is still saved and the transaction survives."""
    title = _make_title(db)
    real_begin_nested, raced = db.begin_nested, []

    def race_first():
        if not raced:
            raced.append(True)
            with SessionLocal() as other:
                other.add(Episode(title_id=title.id, season=1, episode_number=1, name="Theirs"))
                other.commit()
        return real_begin_nested()

    monkeypatch.setattr(db, "begin_nested", race_first)
    data = {"episodes": [{"episode_number": 1, "name": "Ours"}, {"episode_number": 2, "name": "Second"}]}
    tmdb_store.sync_episodes(db, title, 1, data)
    db.commit()
    assert _numbers(db, title) == [1, 2]


# ---------- from the background check to Home ----------


def _caught_up_show(client, headers, title: str, tmdb_id: int, last_watched) -> None:
    """A one-season show in progress whose two known episodes are watched."""
    body = {"media_type": "tv_show", "status": "watching", "title": title, "tmdb_id": tmdb_id}
    r = client.post("/media", json=body, headers=headers)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        entry = db.get(LibraryEntry, r.json()["id"])
        entry.last_watched_at = last_watched
        entry.title_ref.total_seasons = 1
        for number in (1, 2):
            aired = date.today() - timedelta(days=30 - number)
            db.add(Episode(title_id=entry.title_id, season=1, episode_number=number, air_date=aired))
            db.add(EpisodeWatch(media_item_id=entry.id, season=1, episode=number))
        db.commit()


def _film_in_progress(client, headers, title: str, last_watched) -> None:
    body = {"media_type": "film", "status": "watching", "title": title}
    r = client.post("/media", json=body, headers=headers)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        db.get(LibraryEntry, r.json()["id"]).last_watched_at = last_watched
        db.commit()


def _watch_next(client, headers) -> list[str]:
    r = client.get("/media", params={"status_filter": "watching", "order_by": "last_watched"}, headers=headers)
    assert r.status_code == 200, r.text
    return [item["title"] for item in r.json()]


def test_background_check_puts_a_new_episode_on_home(client, alice, monkeypatch):
    """Nothing but the periodic check runs: the caught-up show comes back to
    Home at #2, its new episode having just aired."""
    _, headers = alice
    now = utcnow()
    _film_in_progress(client, headers, "Last Watched", now)
    _film_in_progress(client, headers, "Older", now - timedelta(days=1))
    _caught_up_show(client, headers, "Weekly", 1, now - timedelta(days=9))
    assert _watch_next(client, headers) == ["Last Watched", "Older"]

    aired = (date.today() - timedelta(days=1)).isoformat()
    announced = {"season_number": 1, "episode_number": 3, "air_date": aired, "name": "New"}

    def season_page(path, params=None, cache=True):
        assert path == "/tv/1/season/1"
        return {"episodes": [announced]}

    monkeypatch.setattr(tmdb_store, "tmdb_get", season_page)
    details = {"name": "Weekly", "status": "Returning Series", "number_of_seasons": 1}
    with SessionLocal() as db:
        check_new_episodes(db, fetch=lambda tmdb_id: details | {"last_episode_to_air": announced})

    assert _watch_next(client, headers) == ["Last Watched", "Weekly", "Older"]
