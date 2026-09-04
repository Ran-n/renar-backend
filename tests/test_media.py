#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.395578
Revised: 2026/09/02 10:57:57.736172

Media library CRUD, filters, ownership, and community ratings.
"""

import base64
import io
from datetime import timedelta

import pytest
from PIL import Image as PILImage

from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeWatch, Notification, User, WatchEvent, utcnow
from renar_backend.tmdb import tmdb_store

pytestmark = pytest.mark.regression

RAW_FILM = {
    "title": "Lanterns",
    "release_date": "2024-01-01",
    "runtime": 100,
    "genres": [{"name": "Drama"}],
    "poster_path": "/lanterns.jpg",
}


def _create(client, headers, **overrides) -> dict:
    payload = {"media_type": "film", "title": "Heat"}
    payload.update(overrides)
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- create ----------


def test_create_film(client, alice):
    _, headers = alice
    item = _create(client, headers, year=1995, rating=9, status="completed")
    assert item["title"] == "Heat"
    assert item["year"] == 1995
    assert item["rating"] == 9
    assert item["status"] == "completed"


def test_create_duplicate_title_conflicts(client, alice):
    _, headers = alice
    _create(client, headers)
    r = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers)
    assert r.status_code == 409


def test_same_title_allowed_for_other_user(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers)
    _create(client, bob_headers)


def test_create_requires_auth(client):
    r = client.post("/media", json={"media_type": "film", "title": "Heat"})
    assert r.status_code == 401


def test_create_invalid_rating_rejected(client, alice):
    _, headers = alice
    r = client.post("/media", json={"media_type": "film", "title": "Heat", "rating": 101}, headers=headers)
    assert r.status_code == 422


def test_create_empty_title_rejected(client, alice):
    _, headers = alice
    r = client.post("/media", json={"media_type": "film", "title": ""}, headers=headers)
    assert r.status_code == 422


def test_create_unknown_media_type_rejected(client, alice):
    _, headers = alice
    r = client.post("/media", json={"media_type": "vinyl", "title": "Heat"}, headers=headers)
    assert r.status_code == 422


# ---------- list / filters ----------


def test_list_only_own_items(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers)
    _create(client, bob_headers, title="Alien")
    titles = [i["title"] for i in client.get("/media", headers=alice_headers).json()]
    assert titles == ["Heat"]


def test_list_filters(client, alice):
    _, headers = alice
    _create(client, headers, title="Heat", status="completed")
    _create(client, headers, media_type="tv_show", title="Dark", status="watching")

    by_type = client.get("/media", params={"media_type": "tv_show"}, headers=headers).json()
    assert [i["title"] for i in by_type] == ["Dark"]

    by_status = client.get("/media", params={"status_filter": "completed"}, headers=headers).json()
    assert [i["title"] for i in by_status] == ["Heat"]

    by_search = client.get("/media", params={"search": "ark"}, headers=headers).json()
    assert [i["title"] for i in by_search] == ["Dark"]


def test_list_pagination(client, alice):
    _, headers = alice
    for i in range(5):
        _create(client, headers, title=f"Title {i}")

    page1 = client.get("/media", params={"limit": 2, "offset": 0}, headers=headers).json()
    page2 = client.get("/media", params={"limit": 2, "offset": 2}, headers=headers).json()
    page3 = client.get("/media", params={"limit": 2, "offset": 4}, headers=headers).json()

    assert [i["title"] for i in page1] == ["Title 4", "Title 3"]
    assert [i["title"] for i in page2] == ["Title 2", "Title 1"]
    assert [i["title"] for i in page3] == ["Title 0"]

    no_limit_given = client.get("/media", headers=headers).json()
    assert len(no_limit_given) == 5


def test_list_default_limit(client, alice):
    _, headers = alice
    for i in range(65):
        _create(client, headers, title=f"Title {i}")

    capped = client.get("/media", headers=headers).json()
    assert len(capped) == 60  # default page size when `limit` is omitted

    page2 = client.get("/media", params={"offset": 60}, headers=headers).json()
    assert len(page2) == 5


def test_list_limit_bounds(client, alice):
    """limit must be 1..2000; out-of-range values are rejected with 422."""
    _, headers = alice
    # zero is below ge=1
    assert client.get("/media", params={"limit": 0}, headers=headers).status_code == 422
    # 2001 is above le=2000
    assert client.get("/media", params={"limit": 2001}, headers=headers).status_code == 422
    # negative offset is below ge=0
    assert client.get("/media", params={"offset": -1}, headers=headers).status_code == 422
    # boundary values are accepted
    assert client.get("/media", params={"limit": 1}, headers=headers).status_code == 200
    assert client.get("/media", params={"limit": 2000}, headers=headers).status_code == 200


def test_list_keys(client, alice, bob):
    _, headers = alice
    _, bob_headers = bob
    _create(client, headers, title="Heat", tmdb_id=101)
    _create(client, headers, media_type="tv_show", title="Some Show", url="https://example.com/show")
    _create(client, bob_headers, title="Alien", tmdb_id=202)  # someone else's — must not leak

    keys = client.get("/media/keys", headers=headers).json()
    assert {(k["media_type"], k["tmdb_id"], k["title"]) for k in keys} == {
        ("film", 101, "Heat"),
        ("tv_show", None, "Some Show"),
    }
    assert next(k for k in keys if k["title"] == "Some Show")["url"] == "https://example.com/show"


def test_get_media_by_tmdb(client, alice):
    _, headers = alice
    created = _create(client, headers, title="Heat", tmdb_id=101)

    found = client.get("/media/by_tmdb", params={"media_type": "film", "tmdb_id": 101}, headers=headers)
    assert found.status_code == 200
    assert found.json()["id"] == created["id"]

    missing = client.get("/media/by_tmdb", params={"media_type": "film", "tmdb_id": 999}, headers=headers)
    assert missing.status_code == 404


def test_get_media_by_tmdb_not_other_users(client, alice, bob):
    _, headers = alice
    _, bob_headers = bob
    _create(client, bob_headers, title="Alien", tmdb_id=202)

    r = client.get("/media/by_tmdb", params={"media_type": "film", "tmdb_id": 202}, headers=headers)
    assert r.status_code == 404


def test_list_favorites_only_paginated(client, alice):
    _, headers = alice
    _create(client, headers, title="Heat", is_favorite=True)
    _create(client, headers, title="Alien", is_favorite=False)
    _create(client, headers, title="Dark", media_type="tv_show", is_favorite=True)

    favorites = client.get("/media", params={"favorites_only": True}, headers=headers).json()
    assert {i["title"] for i in favorites} == {"Heat", "Dark"}

    favorites_page1 = client.get(
        "/media", params={"favorites_only": True, "limit": 1, "offset": 0}, headers=headers
    ).json()
    favorites_page2 = client.get(
        "/media", params={"favorites_only": True, "limit": 1, "offset": 1}, headers=headers
    ).json()
    assert [i["title"] for i in favorites_page1] == ["Dark"]
    assert [i["title"] for i in favorites_page2] == ["Heat"]


# ---------- order_by=last_watched ----------


def test_order_by_last_watched_ignores_non_watch_edits(client, alice):
    """Only genuine watch activity should move an item under
    order_by=last_watched; a favorite toggle still bumps updated_at (the
    default order) but must not touch last_watched_at."""
    _, headers = alice
    a = _create(client, headers, media_type="tv_show", title="A")
    b = _create(client, headers, media_type="tv_show", title="B")
    _create(client, headers, media_type="tv_show", title="C")  # never watched

    client.put(f"/media/{a['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.put(f"/media/{b['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    # touches updated_at only — must not count as watch activity
    client.patch(f"/media/{a['id']}", json={"is_favorite": True}, headers=headers)

    default_order = [i["title"] for i in client.get("/media", headers=headers).json()]
    assert default_order == ["A", "B", "C"]  # updated_at desc: the favorite edit put A back on top

    watched_order = [
        i["title"] for i in client.get("/media", params={"order_by": "last_watched"}, headers=headers).json()
    ]
    assert watched_order == ["B", "A", "C"]  # B's episode watch is more recent than A's; C never watched sorts last


def test_order_by_last_watched_status_to_watching_counts(client, alice):
    """Manually marking a show 'watching' (no episodes marked yet) must
    outrank an item with no watch activity at all — the whole point is
    surfacing it on Home without the user having to also find and mark an
    episode."""
    _, headers = alice
    _create(client, headers, media_type="tv_show", title="Untouched")
    marked = _create(client, headers, media_type="tv_show", title="Marked", status="want_to_watch")
    client.patch(f"/media/{marked['id']}", json={"status": "watching"}, headers=headers)

    order = [i["title"] for i in client.get("/media", params={"order_by": "last_watched"}, headers=headers).json()]
    assert order == ["Marked", "Untouched"]


def test_order_by_last_watched_status_to_completed_counts_for_films(client, alice):
    """Films have no episode rows at all, so marking one 'completed' IS the
    watch signal — it must count the same as an episode watch would for a
    show."""
    _, headers = alice
    _create(client, headers, title="Untouched")
    watched_film = _create(client, headers, title="Watched Film", status="want_to_watch")
    client.patch(f"/media/{watched_film['id']}", json={"status": "completed"}, headers=headers)

    order = [i["title"] for i in client.get("/media", params={"order_by": "last_watched"}, headers=headers).json()]
    assert order == ["Watched Film", "Untouched"]


def test_order_by_last_watched_create_with_watching_status_counts(client, alice):
    _, headers = alice
    _create(client, headers, title="Untouched", status="want_to_watch")
    _create(client, headers, title="Fresh Watch", status="watching")

    order = [i["title"] for i in client.get("/media", params={"order_by": "last_watched"}, headers=headers).json()]
    assert order == ["Fresh Watch", "Untouched"]


# ---------- get / patch / ownership ----------


def test_get_item(client, alice):
    _, headers = alice
    item = _create(client, headers)
    r = client.get(f"/media/{item['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Heat"


def test_get_missing_item_not_found(client, alice):
    _, headers = alice
    assert client.get("/media/9999", headers=headers).status_code == 404


def test_get_other_users_item_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    item = _create(client, alice_headers)
    assert client.get(f"/media/{item['id']}", headers=bob_headers).status_code == 404


def test_patch_updates_fields(client, alice):
    _, headers = alice
    item = _create(client, headers)
    r = client.patch(
        f"/media/{item['id']}",
        json={"rating": 8, "status": "completed", "is_favorite": True},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["rating"], body["status"], body["is_favorite"]) == (8, "completed", True)


def test_patch_film_rejects_tv_only_fields(client, alice):
    _, headers = alice
    item = _create(client, headers)
    r = client.patch(f"/media/{item['id']}", json={"episodes_watched": 1}, headers=headers)
    assert r.status_code == 422
    r = client.patch(f"/media/{item['id']}", json={"current_season": 1, "current_episode": 2}, headers=headers)
    assert r.status_code == 422


def test_patch_other_users_item_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    item = _create(client, alice_headers)
    r = client.patch(f"/media/{item['id']}", json={"rating": 1}, headers=bob_headers)
    assert r.status_code == 404


# ---------- relink (tmdb_id) ----------


def test_patch_relink_unmatched_entry_fetches_and_backfills(client, alice, monkeypatch):
    _, headers = alice
    item = _create(client, headers, title="Lanterns")  # no tmdb_id: unmatched, as an import would leave it
    assert item["tmdb_id"] is None

    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_FILM)
    r = client.patch(f"/media/{item['id']}", json={"tmdb_id": 501}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tmdb_id"] == 501
    assert body["poster_url"] and "lanterns.jpg" in body["poster_url"]
    assert body["runtime_minutes"] == 100


def test_patch_relink_reuses_existing_title_without_tmdb_fetch(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    tracked = _create(client, bob_headers, title="No One Could Live Here", tmdb_id=501)
    unmatched = _create(client, alice_headers, title="Aqui no hay quien viva")

    r = client.patch(f"/media/{unmatched['id']}", json={"tmdb_id": tracked["tmdb_id"]}, headers=alice_headers)
    assert r.status_code == 200, r.text
    assert r.json()["tmdb_id"] == 501


def test_patch_relink_conflicts_with_existing_duplicate(client, alice):
    _, headers = alice
    tracked = _create(client, headers, title="No One Could Live Here", tmdb_id=501)
    unmatched = _create(client, headers, title="Aqui no hay quien viva")

    r = client.patch(f"/media/{unmatched['id']}", json={"tmdb_id": tracked["tmdb_id"]}, headers=headers)
    assert r.status_code == 409
    assert "No One Could Live Here" in r.json()["detail"]


def test_patch_relink_already_linked_entry_rejected(client, alice):
    _, headers = alice
    item = _create(client, headers, tmdb_id=501)
    r = client.patch(f"/media/{item['id']}", json={"tmdb_id": 999}, headers=headers)
    assert r.status_code == 422


# ---------- delete ----------


def test_delete_removes_item_and_history(client, alice):
    user, headers = alice
    item = _create(client, headers, media_type="tv_show", title="Dark")
    client.put(f"/media/{item['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{item['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    db = SessionLocal()
    try:
        db.add(
            Notification(
                user_id=user["id"],
                media_item_id=item["id"],
                title="New episode: Dark",
                body="S01E02",
            )
        )
        db.commit()
    finally:
        db.close()

    assert client.delete(f"/media/{item['id']}", headers=headers).status_code == 204
    assert client.get(f"/media/{item['id']}", headers=headers).status_code == 404

    db = SessionLocal()
    try:
        assert db.query(EpisodeWatch).count() == 0
        assert db.query(WatchEvent).count() == 0
        assert db.query(Notification).count() == 0
    finally:
        db.close()


def test_delete_other_users_item_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    item = _create(client, alice_headers)
    assert client.delete(f"/media/{item['id']}", headers=bob_headers).status_code == 404
    assert client.get(f"/media/{item['id']}", headers=alice_headers).status_code == 200


# ---------- multi-session sync (events.publish fanout) ----------


def test_create_update_delete_episode_publish_library_changed(client, alice):
    """Every library-mutating endpoint should fan out `library_changed` to the
    user's other open sessions (see events.py/routers/events.py) so a second
    tab picks up the change without waiting on its own next navigation."""
    from renar_backend import events

    user, headers = alice
    queue = events.subscribe(user["id"])
    try:
        item = _create(client, headers, media_type="tv_show", title="Dark")
        assert queue.get_nowait() == "library_changed"

        client.patch(f"/media/{item['id']}", json={"is_favorite": True}, headers=headers)
        assert queue.get_nowait() == "library_changed"

        client.put(f"/media/{item['id']}/episodes/1/1", json={"watched": True}, headers=headers)
        assert queue.get_nowait() == "library_changed"

        client.delete(f"/media/{item['id']}", headers=headers)
        assert queue.get_nowait() == "library_changed"
    finally:
        events.unsubscribe(user["id"], queue)


# ---------- community ratings ----------


def test_ratings_average_across_users(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers, tmdb_id=949, rating=80)
    _create(client, bob_headers, tmdb_id=949, rating=70)
    r = client.get("/media/ratings", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers)
    assert r.status_code == 200
    assert r.json() == {"average": 75, "count": 2}


def test_ratings_by_title_when_no_tmdb_id(client, alice):
    _, headers = alice
    _create(client, headers, rating=8)
    r = client.get("/media/ratings", params={"media_type": "film", "title": "Heat"}, headers=headers)
    assert r.json() == {"average": 8.0, "count": 1}


def test_ratings_requires_tmdb_id_or_title(client, alice):
    _, headers = alice
    r = client.get("/media/ratings", params={"media_type": "film"}, headers=headers)
    assert r.status_code == 422


def test_ratings_batch(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers, tmdb_id=949, rating=80)
    _create(client, bob_headers, tmdb_id=949, rating=70)
    _create(client, alice_headers, tmdb_id=27205, rating=60)
    r = client.post(
        "/media/ratings/batch",
        json={"media_type": "film", "tmdb_ids": [949, 27205, 12345]},
        headers=alice_headers,
    )
    assert r.status_code == 200
    assert r.json() == {
        "949": {"average": 75, "count": 2},
        "27205": {"average": 60, "count": 1},
    }


def test_ratings_batch_requires_at_least_one_id(client, alice):
    _, headers = alice
    r = client.post("/media/ratings/batch", json={"media_type": "film", "tmdb_ids": []}, headers=headers)
    assert r.status_code == 422


# ---------- rating aggregate maintenance (titles.rating_sum/rating_count,
# trigger-maintained — see db_triggers.py) ----------


def test_ratings_average_updates_when_rating_changed(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_item = _create(client, alice_headers, tmdb_id=949, rating=80)
    _create(client, bob_headers, tmdb_id=949, rating=70)
    r = client.patch(f"/media/{alice_item['id']}", json={"rating": 60}, headers=alice_headers)
    assert r.status_code == 200
    r = client.get("/media/ratings", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers)
    assert r.json() == {"average": 65, "count": 2}


def test_ratings_average_drops_when_rating_cleared(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_item = _create(client, alice_headers, tmdb_id=949, rating=80)
    _create(client, bob_headers, tmdb_id=949, rating=70)
    r = client.patch(f"/media/{alice_item['id']}", json={"rating": None}, headers=alice_headers)
    assert r.status_code == 200
    r = client.get("/media/ratings", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers)
    assert r.json() == {"average": 70, "count": 1}


def test_ratings_average_drops_when_item_deleted(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_item = _create(client, alice_headers, tmdb_id=949, rating=80)
    _create(client, bob_headers, tmdb_id=949, rating=70)
    r = client.delete(f"/media/{alice_item['id']}", headers=alice_headers)
    assert r.status_code == 204
    r = client.get("/media/ratings", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers)
    assert r.json() == {"average": 70, "count": 1}


def test_ratings_none_left_after_all_deleted(client, alice):
    _, headers = alice
    item = _create(client, headers, tmdb_id=949, rating=80)
    r = client.delete(f"/media/{item['id']}", headers=headers)
    assert r.status_code == 204
    r = client.get("/media/ratings", params={"media_type": "film", "tmdb_id": 949}, headers=headers)
    assert r.json() == {"average": None, "count": 0}


def test_status_revert_to_want_to_watch_clears_rating_and_watch_events(client, alice):
    # Reverting a film's status all the way back to "want to watch" is "this
    # was never watched" — matches the episode-level unmark rule. Without
    # this, the rating cache and the whole-item WatchEvent(s) stuck around,
    # so re-completing the film later showed a stale rating from a "watch"
    # that, per the status field at the time, never happened.
    _, headers = alice
    item = _create(client, headers, tmdb_id=949, status="completed", rating=80)

    r = client.patch(f"/media/{item['id']}", json={"status": "want_to_watch"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rating"] is None

    db = SessionLocal()
    try:
        remaining = (
            db.query(WatchEvent)
            .filter(WatchEvent.media_item_id == item["id"], WatchEvent.season.is_(None), WatchEvent.episode.is_(None))
            .count()
        )
        assert remaining == 0
    finally:
        db.close()

    # Re-completing afterward starts fresh — no stale rating resurfaces.
    r = client.patch(f"/media/{item['id']}", json={"status": "completed"}, headers=headers)
    assert r.json()["rating"] is None


def test_status_already_want_to_watch_does_not_clear_rating(client, alice):
    # An item can be rated directly while still want_to_watch (_write_rating's
    # defensive fallback creates a WatchEvent for it). Re-sending the same
    # "want_to_watch" status in an unrelated PATCH must not wipe that rating —
    # only an actual transition INTO want_to_watch from something else should.
    _, headers = alice
    item = _create(client, headers, tmdb_id=949, rating=80)
    assert item["status"] == "want_to_watch"

    r = client.patch(
        f"/media/{item['id']}", json={"status": "want_to_watch", "notes": "still want to watch"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["rating"] == 80


# ---------- helpers shared by new coverage tests ----------


def _set_premium(user_id: int, days: int = 30) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _png_b64(color: tuple[int, int, int] = (200, 30, 30)) -> str:
    img = PILImage.new("RGB", (20, 30), color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


# ---------- list_media with lang param (lines 235-244) ----------


def test_list_media_lang_param_triggers_background_warmup(client, alice):
    """When lang!=en and a title has no cached translation, list_media adds a
    background warmup task. This exercises lines 235-244 in media.py."""
    _, headers = alice
    _create(client, headers, title="Dark", media_type="tv_show")
    # No TmdbCache rows exist → every entry is in missing_ids → warmup task added.
    r = client.get("/media", params={"lang": "es"}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_list_media_lang_en_skips_translation_path(client, alice):
    """lang=en short-circuits the translation block entirely."""
    _, headers = alice
    _create(client, headers, title="Dark", media_type="tv_show")
    r = client.get("/media", params={"lang": "en"}, headers=headers)
    assert r.status_code == 200


# ---------- episode_ratings with existing title but no aggregate (line 441) ----------


def test_episode_ratings_title_exists_but_no_aggregate(client, alice):
    """title_id is found (title exists) but no EpisodeRatingAggregate row:
    returns the null sentinel, hitting line 441 in media.py."""
    _, headers = alice
    # Create a tv_show with a tmdb_id so Title row exists in DB.
    _create(client, headers, media_type="tv_show", tmdb_id=70523)
    # Ask for episode-ratings without ever rating any episode.
    r = client.get(
        "/media/episode-ratings",
        params={"tmdb_id": 70523, "season": 1, "episode": 1},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json() == {"average": None, "count": 0}


# ---------- _derive_season_episode early returns (lines 462, 471-472) ----------


def test_patch_episodes_watched_zero_skips_derive_season(client, alice):
    """PATCH with episodes_watched=0 (no explicit season/ep) triggers
    _derive_season_episode but returns early on line 462 (not item.episodes_watched)."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    r = client.patch(f"/media/{show['id']}", json={"episodes_watched": 0}, headers=headers)
    assert r.status_code == 200
    # episodes_watched stays 0, no season/episode derived
    assert r.json()["episodes_watched"] == 0


def test_patch_episodes_watched_without_catalog_rows(client, alice):
    """PATCH with episodes_watched=5 triggers _derive_season_episode; when there
    are no Episode rows for the title the function returns early (lines 471-472)."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    r = client.patch(f"/media/{show['id']}", json={"episodes_watched": 5}, headers=headers)
    assert r.status_code == 200
    # episodes_watched updated; current_season/current_episode stay None (no catalog)
    assert r.json()["episodes_watched"] == 5


# ---------- tmdb_id=null in PATCH (branch 575->582) ----------


def test_patch_media_tmdb_id_null_is_noop(client, alice):
    """Sending tmdb_id=null in a PATCH enters the 'if tmdb_id in changed' block
    but skips _relink_tmdb since tmdb_id is None (branch 575->582)."""
    _, headers = alice
    item = _create(client, headers, title="Dark", media_type="tv_show")
    # tmdb_id=null in JSON → enters block, tmdb_id is None, relink skipped
    r = client.patch(f"/media/{item['id']}", json={"tmdb_id": None, "notes": "x"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["notes"] == "x"


# ---------- custom posters / backdrops (728->731, 746-752, 763-771) ----------


def test_clear_custom_poster_no_existing_poster_is_noop(client, alice):
    """Clearing a custom poster when none is set (old_image_id is None) takes
    the False branch at line 728 and still commits cleanly."""
    user, headers = alice
    _set_premium(user["id"])
    item = _create(client, headers, title="Dark", media_type="tv_show")
    # No poster was ever set; clear should succeed without GC-ing anything.
    r = client.delete(f"/media/{item['id']}/poster", headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_poster_url"] is None


def test_clear_custom_poster_removes_existing_poster(client, alice):
    """Clearing when a custom poster exists (old_image_id is not None) flushes
    and GC-s the old image (True branch at 728->731)."""
    user, headers = alice
    _set_premium(user["id"])
    item = _create(client, headers, title="Dark", media_type="tv_show")
    # Set a custom poster first.
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    # Now clear it.
    r = client.delete(f"/media/{item['id']}/poster", headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_poster_url"] is None


def test_set_custom_backdrop_requires_premium(client, alice):
    """set_custom_backdrop is premium-gated — non-premium user gets 403."""
    _, headers = alice
    item = _create(client, headers, title="Dark", media_type="tv_show")
    r = client.put(f"/media/{item['id']}/backdrop", json={"image_b64": _png_b64()}, headers=headers)
    assert r.status_code == 403


def test_set_custom_backdrop_with_premium(client, alice):
    """Premium user can set a custom backdrop (covers lines 746-752)."""
    user, headers = alice
    _set_premium(user["id"])
    item = _create(client, headers, title="Dark", media_type="tv_show")
    r = client.put(f"/media/{item['id']}/backdrop", json={"image_b64": _png_b64()}, headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_backdrop_url"] is not None


def test_clear_custom_backdrop(client, alice):
    """Clear a custom backdrop — covers lines 763-771 (the False branch when
    no backdrop was set, and the True branch after setting one)."""
    user, headers = alice
    _set_premium(user["id"])
    item = _create(client, headers, title="Dark", media_type="tv_show")
    # Clear when none set (old_image_id is None).
    r = client.delete(f"/media/{item['id']}/backdrop", headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_backdrop_url"] is None
    # Set then clear (old_image_id is not None).
    client.put(f"/media/{item['id']}/backdrop", json={"image_b64": _png_b64()}, headers=headers)
    r = client.delete(f"/media/{item['id']}/backdrop", headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_backdrop_url"] is None


# ---------- custom episode stills (lines 778, 803-817, 830-838) ----------


def test_set_custom_episode_still_requires_premium(client, alice):
    """set_custom_episode_still is premium-gated."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    r = client.put(f"/media/{show['id']}/episodes/1/1/still", json={"image_b64": _png_b64()}, headers=headers)
    assert r.status_code == 403


def test_set_and_clear_custom_episode_still(client, alice):
    """Premium user: set a still then clear it (covers 803-817 and 830-838)."""
    user, headers = alice
    _set_premium(user["id"])
    show = _create(client, headers, media_type="tv_show", title="Dark")
    # Set the still (covers 803-817, including existing=None branch and existing branch).
    r = client.put(f"/media/{show['id']}/episodes/1/1/still", json={"image_b64": _png_b64()}, headers=headers)
    assert r.status_code == 200
    assert r.json()["still_url"] is not None
    # Update it (still already exists → updates still_image_id).
    r2 = client.put(
        f"/media/{show['id']}/episodes/1/1/still", json={"image_b64": _png_b64((30, 200, 30))}, headers=headers
    )
    assert r2.status_code == 200
    # Clear the still (covers 830-838, still is not None).
    r3 = client.delete(f"/media/{show['id']}/episodes/1/1/still", headers=headers)
    assert r3.status_code == 200
    assert r3.json()["still_url"] is None


def test_clear_episode_still_when_none_exists(client, alice):
    """Clearing a still that was never set — still is None, so no GC happens."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    r = client.delete(f"/media/{show['id']}/episodes/1/1/still", headers=headers)
    assert r.status_code == 200
    assert r.json()["still_url"] is None


# ---------- undo_rewatch edge cases (1075, 1131) ----------


def test_undo_rewatch_with_no_watch_events_returns_404(client, alice):
    """DELETE /rewatch when there are no WatchEvents at all returns 404
    (line 1075 in media.py)."""
    _, headers = alice
    _create(client, headers, title="Heat", status="completed")
    # No rewatches added → no WatchEvent for the film scope at all.
    # (The initial WatchEvent from status=completed IS present but let's use
    # a raw show that was never touched.)
    show = _create(client, headers, title="Dark", media_type="tv_show")
    # PUT then immediately DELETE the watch event so there are zero WatchEvents left.
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    # Undo from episode scope where episode was never watched.
    show2 = _create(client, headers, title="Mindhunter", media_type="tv_show")
    r = client.request("DELETE", f"/media/{show2['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 404


def test_undo_rewatch_film_scope_updates_item_rating(client, alice):
    """Undoing a film rewatch falls back item.rating to the prior event's
    rating (line 1131 in media.py — item.rating = new_rating when season is None)."""
    _, headers = alice
    film = _create(client, headers, title="Heat", status="completed", rating=80)
    # Add a rewatch without a rating.
    client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
    # Undo that rewatch — falls back to first-event rating (80).
    r = client.request("DELETE", f"/media/{film['id']}/rewatch", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["overall_rating"] == 80


# ---------- delete_rewatch_event coverage (1186, 1197->1199) ----------


def test_delete_latest_rewatch_event_film_scope_updates_rating(client, alice):
    """Deleting the latest film-scope WatchEvent updates item.rating (line 1186)."""
    _, headers = alice
    film = _create(client, headers, title="Heat", status="completed", rating=90)
    # Add a second watch event (rewatch), rate it differently via per-event endpoint.
    client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
    events = client.get(f"/media/{film['id']}/rewatch-events", headers=headers).json()
    latest_id = events[0]["id"]
    client.patch(f"/media/{film['id']}/rewatch-events/{latest_id}", json={"rating": 70}, headers=headers)
    # Delete the latest event → rating should fall back to 90 (first event).
    r = client.delete(f"/media/{film['id']}/rewatch-events/{latest_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["overall_rating"] == 90


def test_delete_latest_rewatch_event_episode_scope_updates_cache(client, alice):
    """Deleting the latest episode-scoped WatchEvent updates the EpisodeWatch
    cache column (lines 1197->1199 in media.py — cache_watch.rating = new_rating)."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 70}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    events = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    # events[0] is the rewatch (latest); rate it.
    latest_id = events[0]["id"]
    client.patch(f"/media/{show['id']}/rewatch-events/{latest_id}", json={"rating": 90}, headers=headers)
    # Delete the latest event → cache falls back to 70.
    r = client.delete(f"/media/{show['id']}/rewatch-events/{latest_id}", headers=headers)
    assert r.status_code == 200
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 70


# ---------- update_rewatch_event_rating coverage (1242, 1253->1255) ----------


def test_update_rewatch_event_rating_film_scope_updates_item_rating(client, alice):
    """PATCH on the latest film-scope WatchEvent updates item.rating (line 1242)."""
    _, headers = alice
    film = _create(client, headers, title="Heat", status="completed")
    events = client.get(f"/media/{film['id']}/rewatch-events", headers=headers).json()
    latest_id = events[0]["id"]
    r = client.patch(f"/media/{film['id']}/rewatch-events/{latest_id}", json={"rating": 85}, headers=headers)
    assert r.status_code == 200
    assert r.json()["overall_rating"] == 85


def test_update_rewatch_event_rating_episode_scope_updates_cache(client, alice):
    """PATCH on the latest episode WatchEvent propagates to EpisodeWatch.rating
    (lines 1253->1255 in media.py — cache_watch.rating = data.rating)."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 60}, headers=headers)
    events = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    latest_id = events[0]["id"]
    r = client.patch(f"/media/{show['id']}/rewatch-events/{latest_id}", json={"rating": 95}, headers=headers)
    assert r.status_code == 200
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 95


# ---------- _write_rating with no WatchEvent and rating=None (line 1347) ----------


def test_write_rating_noop_when_no_event_and_rating_is_none(client, alice):
    """Patching rating=None on a want_to_watch item (no WatchEvent yet) hits
    the _write_rating early return at line 1347 (if rating is None: return)."""
    _, headers = alice
    # Item created as want_to_watch — no WatchEvent exists yet.
    item = _create(client, headers, title="Heat", status="want_to_watch")
    assert item["rating"] is None
    # Patching with rating=None should be a no-op (no WatchEvent created).
    r = client.patch(f"/media/{item['id']}", json={"rating": None}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rating"] is None


# ---------- set_episode with watched=False on unwatched ep (branch 1408->1420) ----------


def test_set_episode_unwatch_never_watched_is_noop(client, alice):
    """PUT /episodes/1/1 with watched=False on an episode that was never marked
    watched takes the elif-is-False branch (1408->1420), a clean no-op."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark")
    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": False}, headers=headers)
    assert r.status_code == 200
    assert r.json()["item_episodes_watched"] == 0


# ---------- bulk_episodes re-marking already-marked episodes (branch 1451->1443) ----------


def test_bulk_episodes_remark_already_watched_is_noop(client, alice):
    """Bulk-marking episodes that are already marked watched — the inner
    if/elif in the loop both miss, looping back via branch 1451->1443."""
    _, headers = alice
    show = _create(client, headers, media_type="tv_show", title="Dark", total_episodes=5)
    # Mark ep 1 & 2 watched first.
    client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2], "watched": True},
        headers=headers,
    )
    # Bulk-mark the same eps again (already exist → neither branch taken).
    r = client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2], "watched": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["item_episodes_watched"] == 2


# ---------- list_rewatch_events boundary (pass 2 audit) ----------


def test_list_rewatch_events_limit_rejects_out_of_range(client, alice):
    """limit must be 1-200; out-of-range values are rejected with 422."""
    _, headers = alice
    film = _create(client, headers, title="Heat", status="completed")
    r = client.get(f"/media/{film['id']}/rewatch-events", params={"limit": 0}, headers=headers)
    assert r.status_code == 422
    r = client.get(f"/media/{film['id']}/rewatch-events", params={"limit": 201}, headers=headers)
    assert r.status_code == 422


def test_list_rewatch_events_offset_pagination(client, alice):
    """offset>0 skips that many events; combined with limit the caller can
    page through a long history without receiving an unbounded response."""
    _, headers = alice
    film = _create(client, headers, title="Heat", status="completed")
    # 3 rewatches on top of the initial watch event = 4 total
    for _ in range(3):
        client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)

    all_events = client.get(f"/media/{film['id']}/rewatch-events", headers=headers).json()
    assert len(all_events) == 4

    # offset=1 should skip the newest event (newest-first ordering)
    page = client.get(f"/media/{film['id']}/rewatch-events", params={"limit": 2, "offset": 1}, headers=headers).json()
    assert len(page) == 2
    assert page[0]["id"] == all_events[1]["id"]
