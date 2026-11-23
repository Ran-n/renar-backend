#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:44.159221
Revised: 2026/11/23 11:50:00.225904

Per-season ratings: a season can be rated once every aired episode of it is
watched; the grade is one editable fact per (library entry, season), shown
in the episode list, announced by `season_completed` on the episode write
that finishes a season, and carried by export and import.
"""

import io
import json
import time
from datetime import date, timedelta

import py7zr
import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st

from renar_backend.catalog.progress import completed_seasons, season_is_complete
from renar_backend.database import SessionLocal
from renar_backend.models import Episode, LibraryEntry, SeasonRating
from renar_backend.tmdb import tmdb_store

pytestmark = pytest.mark.regression

PAST = date.today() - timedelta(days=30)
FUTURE = date.today() + timedelta(days=30)


def _show(client, headers, **overrides) -> dict:
    payload = {"media_type": "tv_show", "title": "Dark", "tmdb_id": 70523} | overrides
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _catalog(item_id: int, *episodes: tuple[int, int, date | None]) -> None:
    """Seed the Episode catalog of the show behind `item_id` with
    (season, number, air_date) rows."""
    db = SessionLocal()
    try:
        title_id = db.get(LibraryEntry, item_id).title_id
        for season, number, air_date in episodes:
            db.add(Episode(title_id=title_id, season=season, episode_number=number, air_date=air_date))
        db.commit()
    finally:
        db.close()


def _watch(client, headers, item_id: int, season: int, episode: int, watched: bool = True, **body) -> dict:
    r = client.put(f"/media/{item_id}/episodes/{season}/{episode}", json={"watched": watched, **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _rate(client, headers, item_id: int, season: int, rating: int):
    return client.put(f"/media/{item_id}/seasons/{season}/rating", json={"rating": rating}, headers=headers)


def _episodes(client, headers, item_id: int) -> dict:
    r = client.get(f"/media/{item_id}/episodes", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def show(client, alice):
    """A show with a two-episode aired season 1 and a season 2 whose second
    episode has not aired; returns (item, headers)."""
    _, headers = alice
    item = _show(client, headers)
    _catalog(item["id"], (1, 1, PAST), (1, 2, PAST), (2, 1, PAST), (2, 2, FUTURE))
    return item, headers


# ---------- completeness ----------


def test_season_completed_flag_only_on_the_write_that_finishes_it(client, show):
    """`season_completed` is true exactly once: on the episode write that
    takes the season from unfinished to finished."""
    item, headers = show
    assert _watch(client, headers, item["id"], 1, 1)["season_completed"] is False
    assert _watch(client, headers, item["id"], 1, 2)["season_completed"] is True
    # re-marking (e.g. to rate the episode) an already complete season: no cue
    assert _watch(client, headers, item["id"], 1, 2, rating=80)["season_completed"] is False
    # unwatching never completes anything
    assert _watch(client, headers, item["id"], 1, 2, watched=False)["season_completed"] is False
    assert _watch(client, headers, item["id"], 1, 2)["season_completed"] is True


def test_bulk_mark_reports_season_completed(client, show):
    item, headers = show
    r = client.post(
        f"/media/{item['id']}/episodes/bulk", json={"season": 1, "episodes": [1], "watched": True}, headers=headers
    )
    assert r.json()["season_completed"] is False
    r = client.post(
        f"/media/{item['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2], "watched": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["season_completed"] is True
    r = client.post(
        f"/media/{item['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2], "watched": False}, headers=headers
    )
    assert r.json()["season_completed"] is False


def test_unaired_episode_does_not_hold_a_season_back(client, show):
    """Season 2 has one aired and one future episode: caught up counts as
    complete, and it is listed as rateable."""
    item, headers = show
    assert _watch(client, headers, item["id"], 2, 1)["season_completed"] is True
    assert _episodes(client, headers, item["id"])["completed_seasons"] == [2]


def test_season_unknown_to_the_catalog_is_never_complete(client, alice):
    """No catalog rows means no way to know the season is finished."""
    _, headers = alice
    item = _show(client, headers, tmdb_id=None, title="Home video")
    assert _watch(client, headers, item["id"], 1, 1)["season_completed"] is False
    assert _episodes(client, headers, item["id"])["completed_seasons"] == []
    assert _rate(client, headers, item["id"], 1, 80).status_code == 409


def test_undated_episodes_alone_do_not_make_a_season(client, alice):
    _, headers = alice
    item = _show(client, headers)
    _catalog(item["id"], (1, 1, None))
    _watch(client, headers, item["id"], 1, 1)
    assert _episodes(client, headers, item["id"])["completed_seasons"] == []


def test_completed_seasons_lists_every_finished_season_in_order(client, show):
    item, headers = show
    for season, episode in ((2, 1), (1, 1), (1, 2)):
        _watch(client, headers, item["id"], season, episode)
    assert _episodes(client, headers, item["id"])["completed_seasons"] == [1, 2]
    db = SessionLocal()
    try:
        entry = db.get(LibraryEntry, item["id"])
        assert completed_seasons(db, entry) == [1, 2]
        assert season_is_complete(db, entry, 1) is True
        assert season_is_complete(db, entry, 3) is False
    finally:
        db.close()


@pytest.mark.property
@given(
    aired=st.sets(st.integers(min_value=1, max_value=8), max_size=8),
    watched=st.sets(st.integers(min_value=1, max_value=8), max_size=8),
)
def test_complete_iff_every_aired_episode_is_watched(aired, watched):
    """The rule itself, on the sets: complete exactly when at least one
    episode aired and none of the aired ones is unwatched."""
    from renar_backend.models import EpisodeWatch, MediaType, Title, User

    db = SessionLocal()
    try:
        title = Title(media_type=MediaType.tv_show, title="Prop")
        user = User(username=f"p{time.monotonic_ns()}", email=f"p{time.monotonic_ns()}@example.com", password_hash="x")
        db.add_all([title, user])
        db.flush()
        entry = LibraryEntry(user_id=user.id, title_id=title.id)
        db.add(entry)
        db.flush()
        db.add_all(Episode(title_id=title.id, season=1, episode_number=n, air_date=PAST) for n in aired)
        db.add_all(EpisodeWatch(media_item_id=entry.id, season=1, episode=n) for n in watched)
        db.flush()
        assert season_is_complete(db, entry, 1) is (bool(aired) and aired <= watched)
    finally:
        db.rollback()
        db.close()


# ---------- rating ----------


def test_rate_a_completed_season_and_read_it_back(client, show):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2, rating=30)  # the finale's grade must not leak in
    assert _episodes(client, headers, item["id"])["season_ratings"] == []
    r = _rate(client, headers, item["id"], 1, 88)
    assert r.status_code == 200, r.text
    assert r.json() == {"season": 1, "rating": 88}
    assert _episodes(client, headers, item["id"])["season_ratings"] == [{"season": 1, "rating": 88}]


def test_rerating_updates_the_one_row(client, show):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    _rate(client, headers, item["id"], 1, 88)
    assert _rate(client, headers, item["id"], 1, 60).json() == {"season": 1, "rating": 60}
    db = SessionLocal()
    try:
        assert db.query(SeasonRating).count() == 1
    finally:
        db.close()


def test_rating_an_unfinished_season_is_refused(client, show):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    r = _rate(client, headers, item["id"], 1, 88)
    assert r.status_code == 409
    assert "every aired episode" in r.json()["detail"]
    assert _episodes(client, headers, item["id"])["season_ratings"] == []


@pytest.mark.parametrize("rating", [0, 101, -5, "high", None])
def test_out_of_range_rating_rejected(client, show, rating):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    assert _rate(client, headers, item["id"], 1, rating).status_code == 422


def test_rating_bounds_accepted(client, show):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    assert _rate(client, headers, item["id"], 1, 1).status_code == 200
    assert _rate(client, headers, item["id"], 1, 100).status_code == 200


def test_season_ratings_are_per_season(client, show):
    item, headers = show
    for season, episode in ((1, 1), (1, 2), (2, 1)):
        _watch(client, headers, item["id"], season, episode)
    _rate(client, headers, item["id"], 2, 70)
    _rate(client, headers, item["id"], 1, 90)
    assert _episodes(client, headers, item["id"])["season_ratings"] == [
        {"season": 1, "rating": 90},
        {"season": 2, "rating": 70},
    ]


def test_film_has_no_seasons(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    assert _rate(client, headers, film["id"], 1, 80).status_code == 422


def test_other_users_show_not_found(client, show, bob):
    item, _ = show
    _, b = bob
    assert _rate(client, b, item["id"], 1, 80).status_code == 404
    assert client.delete(f"/media/{item['id']}/seasons/1/rating", headers=b).status_code == 404


def test_season_rating_needs_auth(client, show):
    item, _ = show
    assert client.put(f"/media/{item['id']}/seasons/1/rating", json={"rating": 80}).status_code == 401
    assert client.delete(f"/media/{item['id']}/seasons/1/rating").status_code == 401


def test_negative_season_rejected(client, show):
    item, headers = show
    assert _rate(client, headers, item["id"], -1, 80).status_code == 422


def test_clear_rating(client, show):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    _rate(client, headers, item["id"], 1, 88)
    assert client.delete(f"/media/{item['id']}/seasons/1/rating", headers=headers).status_code == 204
    assert _episodes(client, headers, item["id"])["season_ratings"] == []
    # nothing left to remove: still fine
    assert client.delete(f"/media/{item['id']}/seasons/1/rating", headers=headers).status_code == 204


def test_rating_survives_unwatching_but_season_is_no_longer_rateable(client, show):
    """Unwatching an episode keeps the grade (a mistaken unmark must not
    destroy it) but takes the season off the rateable list and refuses a
    new grade until it is finished again."""
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    _rate(client, headers, item["id"], 1, 88)
    _watch(client, headers, item["id"], 1, 2, watched=False)
    body = _episodes(client, headers, item["id"])
    assert body["season_ratings"] == [{"season": 1, "rating": 88}]
    assert body["completed_seasons"] == []
    assert _rate(client, headers, item["id"], 1, 50).status_code == 409
    # clearing is still allowed
    assert client.delete(f"/media/{item['id']}/seasons/1/rating", headers=headers).status_code == 204


def test_set_and_clear_publish_library_changed(client, show, monkeypatch):
    from renar_backend.routers import seasons

    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    events = []
    monkeypatch.setattr(seasons, "publish_event", lambda user_id, name: events.append(name))
    _rate(client, headers, item["id"], 1, 88)
    client.delete(f"/media/{item['id']}/seasons/1/rating", headers=headers)
    client.delete(f"/media/{item['id']}/seasons/1/rating", headers=headers)  # no-op: no event
    assert events == ["library_changed", "library_changed"]


def test_concurrent_first_rating_updates_instead_of_failing(client, show, monkeypatch):
    """Two first ratings racing: the loser's INSERT hits the unique
    constraint and its grade is applied to the winner's row (200, no 500)."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    original_commit = Session.commit
    raced = []

    def patched_commit(self):
        if not raced and any(isinstance(obj, SeasonRating) for obj in self.new):
            raced.append(True)
            other = SessionLocal()
            try:
                other.add(SeasonRating(media_item_id=item["id"], season=1, rating=10))
                original_commit(other)
            finally:
                other.close()
            raise IntegrityError("INSERT INTO season_ratings", {}, Exception("unique violation"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", patched_commit)
    r = _rate(client, headers, item["id"], 1, 77)
    assert r.status_code == 200, r.text
    assert r.json() == {"season": 1, "rating": 77}
    monkeypatch.undo()
    assert _episodes(client, headers, item["id"])["season_ratings"] == [{"season": 1, "rating": 77}]


def test_first_rating_racing_a_set_then_clear_asks_to_retry(client, show, monkeypatch):
    """The loser of a race finds the winner's row already cleared again:
    there is nothing to update, so it answers 409 (not a 500) and stores
    nothing."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    original_commit = Session.commit

    def patched_commit(self):
        if any(isinstance(obj, SeasonRating) for obj in self.new):
            raise IntegrityError("INSERT INTO season_ratings", {}, Exception("unique violation"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", patched_commit)
    r = _rate(client, headers, item["id"], 1, 77)
    assert r.status_code == 409
    assert r.json()["detail"] == "Try again"
    monkeypatch.undo()
    assert _episodes(client, headers, item["id"])["season_ratings"] == []


def test_rating_constraint_in_the_table(client, show):
    from sqlalchemy.exc import IntegrityError

    item, _ = show
    db = SessionLocal()
    try:
        db.add(SeasonRating(media_item_id=item["id"], season=1, rating=101))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


# ---------- lifecycle ----------


def test_deleting_the_show_removes_its_season_ratings(client, show):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    _rate(client, headers, item["id"], 1, 88)
    assert client.delete(f"/media/{item['id']}", headers=headers).status_code == 204
    db = SessionLocal()
    try:
        assert db.query(SeasonRating).count() == 0
    finally:
        db.close()


def test_deleting_the_account_removes_its_season_ratings(client, show, alice):
    from conftest import hard_delete

    item, headers = show
    user, _ = alice
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    _rate(client, headers, item["id"], 1, 88)
    hard_delete(user["id"])
    db = SessionLocal()
    try:
        assert db.query(SeasonRating).count() == 0
    finally:
        db.close()


# ---------- export / import ----------


def _wait(client, headers, url: str, done) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        body = client.get(url, headers=headers).json()
        if done(body):
            return body
        time.sleep(0.05)
    raise AssertionError(f"{url} never finished")


def _import(client, headers, rows: list[dict]) -> dict:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr("{}", "profile.json")
        zf.writestr(json.dumps(rows), "library.json")
    r = client.post("/import", files={"file": ("x.7z", buf.getvalue(), "application/x-7z-compressed")}, headers=headers)
    assert r.status_code == 202, r.text
    body = _wait(client, headers, "/import/status", lambda b: b["finished"])
    assert body["error"] is None, body
    return body


def test_export_carries_season_ratings(client, show, tmp_path):
    item, headers = show
    _watch(client, headers, item["id"], 1, 1)
    _watch(client, headers, item["id"], 1, 2)
    _rate(client, headers, item["id"], 1, 88)
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait(client, headers, "/export/data/status", lambda b: b["state"] in ("ready", "failed"))
    r = client.get("/export/data/download", headers=headers)
    assert r.status_code == 200, r.text
    with py7zr.SevenZipFile(io.BytesIO(r.content), "r") as zf:
        zf.extractall(path=tmp_path)
    library = json.loads((tmp_path / "library.json").read_text())
    assert library[0]["season_ratings"] == [{"season": 1, "rating": 88}]


def test_import_restores_season_ratings_and_skips_bad_rows(client, alice):
    """Valid season grades come back; an existing grade is never
    overwritten; malformed rows (bad season, bad rating, not an object, a
    repeated season) are skipped without failing the import."""
    _, headers = alice
    item = _show(client, headers, tmdb_id=9_000_901, title="Probe")
    db = SessionLocal()
    try:
        db.add(SeasonRating(media_item_id=item["id"], season=1, rating=40))
        db.commit()
    finally:
        db.close()
    _import(
        client,
        headers,
        [
            {
                "media_type": "tv_show",
                "title": "Probe",
                "tmdb_id": 9_000_901,
                "status": "watching",
                "season_ratings": [
                    {"season": 1, "rating": 99},  # already rated: kept at 40
                    {"season": 2, "rating": 75},
                    {"season": 2, "rating": 10},  # repeated season: first wins
                    {"season": 3, "rating": 0},
                    {"season": 4, "rating": "9"},
                    {"season": -1, "rating": 50},
                    {"season": "5", "rating": 50},
                    {"season": True, "rating": 50},
                    {"rating": 50},
                    "junk",
                ],
            }
        ],
    )
    assert _episodes(client, headers, item["id"])["season_ratings"] == [
        {"season": 1, "rating": 40},
        {"season": 2, "rating": 75},
    ]


def test_import_without_season_ratings_key_is_fine(client, alice):
    """Exports made before season ratings existed have no such key."""
    _, headers = alice
    _import(client, headers, [{"media_type": "tv_show", "title": "Old", "tmdb_id": 9_000_902, "status": "watching"}])
    db = SessionLocal()
    try:
        assert db.query(SeasonRating).count() == 0
    finally:
        db.close()


# ---------- a show whose episode catalog isn't synced yet ----------

SEASON_ONE = {
    "episodes": [{"episode_number": 1, "air_date": "2020-01-01"}, {"episode_number": 2, "air_date": "2020-01-08"}]
}


@pytest.fixture
def fresh_show(client, alice):
    """A just-added show: TMDB says it has one season, but nothing has
    synced its episodes into the catalog yet. Returns (item, headers)."""
    _, headers = alice
    item = _show(client, headers)
    db = SessionLocal()
    try:
        db.get(LibraryEntry, item["id"]).title_ref.total_seasons = 1
        db.commit()
    finally:
        db.close()
    return item, headers


def _tmdb_up(monkeypatch) -> list:
    calls: list = []

    def fake(db, media_type, tmdb_id, kind, path, season=0, language="en", newer_than=None):
        calls.append(season)
        return SEASON_ONE

    monkeypatch.setattr(tmdb_store, "cached_tmdb", fake)
    return calls


def _tmdb_down(monkeypatch) -> None:
    def fake(*args, **kwargs):
        raise HTTPException(status_code=502, detail="TMDB unreachable")

    monkeypatch.setattr(tmdb_store, "cached_tmdb", fake)


def test_new_show_syncs_its_catalog_on_the_first_episode_write(client, fresh_show, monkeypatch):
    """Without this a show added moments ago could never have a complete
    season: nothing but Upcoming and the notifier filled its catalog."""
    item, headers = fresh_show
    calls = _tmdb_up(monkeypatch)
    assert _watch(client, headers, item["id"], 1, 1)["season_completed"] is False
    assert _watch(client, headers, item["id"], 1, 2)["season_completed"] is True
    assert calls == [1]  # synced once; later writes find the rows
    assert _rate(client, headers, item["id"], 1, 80).status_code == 200


def test_episode_write_survives_tmdb_being_down_and_list_syncs_later(client, fresh_show, monkeypatch):
    item, headers = fresh_show
    _tmdb_down(monkeypatch)
    for number in (1, 2):
        assert _watch(client, headers, item["id"], 1, number)["season_completed"] is False
    assert _episodes(client, headers, item["id"])["completed_seasons"] == []
    _tmdb_up(monkeypatch)
    assert _episodes(client, headers, item["id"])["completed_seasons"] == [1]


def test_rating_syncs_the_catalog_before_refusing(client, fresh_show, monkeypatch):
    item, headers = fresh_show
    _tmdb_down(monkeypatch)
    for number in (1, 2):
        _watch(client, headers, item["id"], 1, number)
    assert _rate(client, headers, item["id"], 1, 80).status_code == 409
    _tmdb_up(monkeypatch)
    assert _rate(client, headers, item["id"], 1, 80).status_code == 200


def test_ensure_seasons_synced_only_syncs_when_a_season_is_missing(client, show, monkeypatch):
    item, _ = show
    synced: list = []
    monkeypatch.setattr(tmdb_store, "sync_show_episodes", lambda db, title, deadline=None: synced.append(title.id))
    db = SessionLocal()
    try:
        title = db.get(LibraryEntry, item["id"]).title_ref
        tmdb_store.ensure_seasons_synced(db, title, {1, 3})  # total_seasons unknown: nothing to sync from
        title.total_seasons = 3
        tmdb_store.ensure_seasons_synced(db, None, {1})
        tmdb_store.ensure_seasons_synced(db, title, set())
        tmdb_store.ensure_seasons_synced(db, title, {1, 2})  # both in the catalog
        # specials and a season past the show's last can't be fetched: asking
        # for them must not start a sync on every call
        tmdb_store.ensure_seasons_synced(db, title, {0, 4})
        assert synced == []
        tmdb_store.ensure_seasons_synced(db, title, {0, 1, 3})
        assert synced == [title.id]
        title.tmdb_id = None
        tmdb_store.ensure_seasons_synced(db, title, {9})
        assert synced == [title.id]
        db.rollback()
    finally:
        db.close()
