#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.262466
Revised: 2026/08/24 11:07:30.470331

Per-episode tracking: set/unset, bulk, progress sync, rewatches, ratings.
"""

from datetime import date, timedelta

from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeWatch, LibraryEntry, Title, WatchEvent
from renar_backend.tmdb import tmdb_store


def _show(client, headers, **overrides) -> dict:
    payload = {"media_type": "tv_show", "title": "Dark", "total_episodes": 3}
    payload.update(overrides)
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _watched(client, headers, item_id) -> list[tuple[int, int]]:
    body = client.get(f"/media/{item_id}/episodes", headers=headers).json()
    return [(w["season"], w["episode"]) for w in body["watched"]]


def _set_title_for_entry(client, headers, item_id: int, **fields) -> None:
    db = SessionLocal()
    try:
        entry = db.get(LibraryEntry, item_id)
        for k, v in fields.items():
            setattr(entry.title_ref, k, v)
        db.commit()
    finally:
        db.close()


def _season_payload(*episodes: tuple[int, str, str | None]) -> dict:
    return {"episodes": [{"episode_number": n, "name": name, "air_date": air_date} for n, name, air_date in episodes]}


# ---------- set / unset ----------


def test_set_episode_marks_watched_and_syncs_progress(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True}, headers=headers)
    assert r.status_code == 200

    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["episodes_watched"] == 1
    assert (item["current_season"], item["current_episode"]) == (1, 2)
    assert item["status"] == "watching"  # auto-promoted from want_to_watch


def test_unset_episode_removes_watch(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": False}, headers=headers)
    assert _watched(client, headers, show["id"]) == []


def test_unset_episode_clears_watch_events(client, alice):
    # Unmarking an episode watched must clear its WatchEvent history too, not
    # just the EpisodeWatch cache row — otherwise remarking it watched later
    # creates another WatchEvent on top of the orphaned one(s), and the
    # rewatch/rating history dialog accumulates stale duplicate entries.
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": False}, headers=headers)

    db = SessionLocal()
    try:
        remaining = (
            db.query(WatchEvent)
            .filter(WatchEvent.media_item_id == show["id"], WatchEvent.season == 1, WatchEvent.episode == 1)
            .count()
        )
        assert remaining == 0
    finally:
        db.close()

    # Remarking watched afterward starts a fresh single-entry history, not a
    # third event stacked on the two orphaned ones.
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    events = client.get(f"/media/{show['id']}/rewatch-events?season=1&episode=1", headers=headers).json()
    assert len(events) == 1


def test_bulk_unmark_clears_watch_events(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1], "watched": False},
        headers=headers,
    )

    db = SessionLocal()
    try:
        remaining = (
            db.query(WatchEvent)
            .filter(WatchEvent.media_item_id == show["id"], WatchEvent.season == 1, WatchEvent.episode == 1)
            .count()
        )
        assert remaining == 0
    finally:
        db.close()


def test_set_episode_with_rating(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(
        f"/media/{show['id']}/episodes/1/1",
        json={"watched": True, "rating": 9},
        headers=headers,
    )
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 9
    assert body["episode_avg"] == 9.0


def test_set_episode_invalid_rating_rejected(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.put(
        f"/media/{show['id']}/episodes/1/1",
        json={"watched": True, "rating": 0},
        headers=headers,
    )
    assert r.status_code == 422


def test_set_episode_on_other_users_show_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    show = _show(client, alice_headers)
    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=bob_headers)
    assert r.status_code == 404


def test_set_episode_future_air_date_rejected(client, alice, monkeypatch):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    future = date.today() + timedelta(days=10)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Future Ep", future.isoformat()),
        ),
    )
    assert client.get("/upcoming/history", headers=headers).status_code == 200  # seeds Episode catalog

    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    assert r.status_code == 422
    assert "not aired" in r.json()["detail"].lower()


def test_set_episode_past_air_date_allowed(client, alice, monkeypatch):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    past = date.today() - timedelta(days=3)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Aired Ep", past.isoformat()),
        ),
    )
    assert client.get("/upcoming/history", headers=headers).status_code == 200

    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    assert r.status_code == 200


def test_set_episode_no_catalog_row_allowed(client, alice):
    """Episode not in our catalog (no tmdb_id / no Episode row) → no guard."""
    _, headers = alice
    show = _show(client, headers)  # no tmdb_id
    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    assert r.status_code == 200


def test_set_episode_null_air_date_allowed(client, alice, monkeypatch):
    """Episode in catalog but air_date is NULL → no guard (treat as possibly aired)."""
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Unknown Date", None),
        ),
    )
    assert client.get("/upcoming/history", headers=headers).status_code == 200

    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    assert r.status_code == 200


def test_bulk_episodes_future_air_date_rejected(client, alice, monkeypatch):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523, total_episodes=3)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    past = date.today() - timedelta(days=3)
    future = date.today() + timedelta(days=10)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Aired", past.isoformat()),
            (2, "Future", future.isoformat()),
        ),
    )
    assert client.get("/upcoming/history", headers=headers).status_code == 200

    r = client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2]},
        headers=headers,
    )
    assert r.status_code == 422
    assert "not aired" in r.json()["detail"].lower()

    # Only the aired episode (ep 1) can be marked
    r = client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1]},
        headers=headers,
    )
    assert r.status_code == 200


def test_watching_all_episodes_completes_show(client, alice):
    _, headers = alice
    show = _show(client, headers, total_episodes=2)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True}, headers=headers)
    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["status"] == "completed"


def test_unwatching_an_episode_reverts_completed_to_watching(client, alice):
    _, headers = alice
    show = _show(client, headers, total_episodes=2)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True}, headers=headers)
    assert client.get(f"/media/{show['id']}", headers=headers).json()["status"] == "completed"

    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": False}, headers=headers)
    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["status"] == "watching"
    assert item["episodes_watched"] == 1


def test_unwatching_last_episode_reverts_completed_to_want_to_watch(client, alice):
    _, headers = alice
    show = _show(client, headers, total_episodes=1)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    assert client.get(f"/media/{show['id']}", headers=headers).json()["status"] == "completed"

    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": False}, headers=headers)
    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["status"] == "want_to_watch"
    assert item["episodes_watched"] == 0


# ---------- bulk ----------


def test_bulk_mark_creates_watch_events(client, alice):
    # Bulk-marking (e.g. "mark whole season watched") must create the same
    # initial WatchEvent as the single-episode toggle does — otherwise these
    # episodes show as watched but have empty rewatch/rating history forever.
    _, headers = alice
    show = _show(client, headers, total_episodes=10)
    client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2]},
        headers=headers,
    )
    events = client.get(f"/media/{show['id']}/rewatch-events?season=1&episode=1", headers=headers).json()
    assert len(events) == 1
    assert events[0]["is_initial"] is True


def test_bulk_mark_and_unmark(client, alice):
    _, headers = alice
    show = _show(client, headers, total_episodes=10)
    r = client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2, 3]},
        headers=headers,
    )
    assert r.status_code == 200
    assert _watched(client, headers, show["id"]) == [(1, 1), (1, 2), (1, 3)]

    client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [2, 3], "watched": False},
        headers=headers,
    )
    assert _watched(client, headers, show["id"]) == [(1, 1)]


def test_bulk_empty_episode_list_rejected(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": []},
        headers=headers,
    )
    assert r.status_code == 422


# ---------- rewatch ----------


def test_whole_item_rewatch_counts(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    client.patch(f"/media/{film['id']}", json={"status": "completed"}, headers=headers)
    for _ in range(2):
        r = client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
        assert r.status_code == 200
    assert r.json()["rewatch_count"] == 2


def test_rewatch_unfinished_title_rejected(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    r = client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
    assert r.status_code == 422


def test_rewatching_completed_film_keeps_status_completed(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    client.patch(f"/media/{film['id']}", json={"status": "completed"}, headers=headers)
    r = client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
    assert r.json()["item_status"] == "completed"
    r = client.request("DELETE", f"/media/{film['id']}/rewatch", json={}, headers=headers)
    assert r.json()["item_status"] == "completed"


def test_list_and_delete_specific_rewatch_event(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    client.patch(f"/media/{film['id']}", json={"status": "completed"}, headers=headers)
    for _ in range(3):
        client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)

    events = client.get(f"/media/{film['id']}/rewatch-events", headers=headers).json()
    # 3 rewatches + the 1 initial-watch event created by the status=completed
    # PATCH above (film first-watch, is_initial=True — excluded from
    # rewatch_count but still a real WatchEvent row in the raw list)
    assert len(events) == 4
    assert all("id" in e and "watched_at" in e for e in events)

    middle_id = events[1]["id"]
    r = client.delete(f"/media/{film['id']}/rewatch-events/{middle_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["rewatch_count"] == 2

    remaining = client.get(f"/media/{film['id']}/rewatch-events", headers=headers).json()
    assert middle_id not in [e["id"] for e in remaining]


def test_delete_rewatch_event_not_found(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    r = client.delete(f"/media/{film['id']}/rewatch-events/999999", headers=headers)
    assert r.status_code == 404


def test_deleting_latest_rewatch_event_falls_back_cache_rating(client, alice):
    # Deleting the newest event (via the per-event trash icon, not undo_
    # rewatch) must refresh the cache rating too — otherwise the headline
    # kept showing the just-deleted event's rating with nothing backing it.
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 40}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    events = client.get(f"/media/{show['id']}/rewatch-events?season=1&episode=1", headers=headers).json()
    latest_id = events[0]["id"]
    client.patch(f"/media/{show['id']}/rewatch-events/{latest_id}", json={"rating": 90}, headers=headers)
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 90

    r = client.delete(f"/media/{show['id']}/rewatch-events/{latest_id}", headers=headers)
    assert r.status_code == 200

    # Falls back to the first watch's rating (40), not left stuck at 90.
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 40


def test_deleting_non_latest_rewatch_event_does_not_change_cache_rating(client, alice):
    # A bare rewatch (no rating attached) never syncs the cache column in the
    # first place — it stays at whatever the previous watch-through set it to,
    # until something explicitly rates the new latest watch-through (see
    # test_editing_non_latest_watch_event_rating_does_not_change_headline).
    # Deleting the OLD (non-latest, but still cache-sourcing) event here must
    # not retroactively yank the cache down to the still-unrated latest rewatch.
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 40}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    events = client.get(f"/media/{show['id']}/rewatch-events?season=1&episode=1", headers=headers).json()
    oldest_id = events[-1]["id"]  # the initial event — not the scope's latest (the rewatch is)
    client.delete(f"/media/{show['id']}/rewatch-events/{oldest_id}", headers=headers)

    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 40  # untouched — the deleted event wasn't the cache source


def test_episode_rewatch_counts(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rewatch_count"] == 1
    assert _watched(client, headers, show["id"]) == [(1, 1)]


def test_rewatch_unwatched_episode_rejected(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 422
    assert _watched(client, headers, show["id"]) == []


def test_rewatch_season_without_episode_rejected(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.post(f"/media/{show['id']}/rewatch", json={"season": 1}, headers=headers)
    assert r.status_code == 422


# ---------- undo rewatch ----------


def test_undo_rewatch_decrements_without_unwatching(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rewatch_count"] == 2

    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 200
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rewatch_count"] == 1
    # still watched — undo only removed the extra rewatch, not the watch itself
    assert _watched(client, headers, show["id"]) == [(1, 1)]


def test_undo_rewatch_falls_back_to_previous_rating(client, alice):
    """Undoing the latest rewatch falls back to the previously-latest
    WatchEvent's rating (the first watch, rated 90) rather than always
    clearing to None. rating_cleared is False because the cache column value
    (90) did not change."""
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 90}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 200
    # Cache stays at 90 (the first-watch rating), so nothing "cleared"
    assert r.json()["rating_cleared"] is False

    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 90
    assert body["watched"][0]["rewatch_count"] == 0


def test_undo_rewatch_falls_back_to_none_when_previous_unrated(client, alice):
    """When the previous (now-latest after undo) WatchEvent had no rating,
    the cache column becomes None and rating_cleared is True."""
    _, headers = alice
    show = _show(client, headers)
    # First watch, no rating
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    # Rate via rewatch endpoint (creates a new WatchEvent, unrated)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    # Rate the rewatch via the per-event endpoint
    body = client.get(f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers).json()
    latest_event_id = body[0]["id"]
    client.patch(
        f"/media/{show['id']}/rewatch-events/{latest_event_id}",
        json={"rating": 80},
        headers=headers,
    )

    # Undo the rewatch — falls back to the first-watch WatchEvent (rating=None)
    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rating_cleared"] is True  # 80 → None: a genuine change

    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] is None
    assert body["watched"][0]["rewatch_count"] == 0


def test_undo_rewatch_without_rating_reports_not_cleared(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 200
    # Previous WatchEvent (first watch) also has no rating, so nothing changed
    assert r.json()["rating_cleared"] is False


def test_undo_rewatch_of_initial_watch_event_succeeds(client, alice):
    """set_episode now creates a WatchEvent for the first watch. DELETE /rewatch
    can delete it (no explicit rewatch needed for there to be an event to undo).
    The EpisodeWatch row stays in place; the WatchEvent is gone."""
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    # Should succeed: there IS a WatchEvent (the initial one)
    assert r.status_code == 200
    assert r.json()["rating_cleared"] is False
    # Episode is still watched (EpisodeWatch stays); zero WatchEvents remain
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rewatch_count"] == 0


def test_undo_rewatch_season_without_episode_rejected(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1}, headers=headers)
    assert r.status_code == 422


def test_undo_whole_item_rewatch(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    client.patch(f"/media/{film['id']}", json={"status": "completed"}, headers=headers)
    client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
    r = client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
    assert r.json()["rewatch_count"] == 2

    r = client.request("DELETE", f"/media/{film['id']}/rewatch", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rewatch_count"] == 1


# ---------- combined score ----------


def test_combined_score_needs_all_episodes_rated(client, alice):
    _, headers = alice
    show = _show(client, headers, total_episodes=2, rating=8)
    client.put(
        f"/media/{show['id']}/episodes/1/1",
        json={"watched": True, "rating": 6},
        headers=headers,
    )
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["combined_score"] is None  # only 1 of 2 episodes rated

    client.put(
        f"/media/{show['id']}/episodes/1/2",
        json={"watched": True, "rating": 10},
        headers=headers,
    )
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["episode_avg"] == 8.0
    assert body["combined_score"] == 8.0


# ---------- status -> completed backfills aired episodes ----------


def test_status_completed_marks_only_aired_episodes_watched(client, alice, monkeypatch):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = date.today() - timedelta(days=3)
    unaired = date.today() + timedelta(days=10)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Pilot", aired.isoformat()),
            (2, "Second", aired.isoformat()),
            (3, "Unaired", unaired.isoformat()),
        ),
    )

    r = client.patch(f"/media/{show['id']}", json={"status": "completed"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["episodes_watched"] == 2
    assert _watched(client, headers, show["id"]) == [(1, 1), (1, 2)]


def test_status_completed_backfill_creates_watch_events(client, alice, monkeypatch):
    # Same rule as the bulk-mark endpoint: episodes backfilled by setting
    # status straight to "completed" must get an initial WatchEvent too, not
    # just an EpisodeWatch row — otherwise their rating/rewatch history is
    # silently empty despite showing as watched.
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = date.today() - timedelta(days=3)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload((1, "Pilot", aired.isoformat())),
    )

    client.patch(f"/media/{show['id']}", json={"status": "completed"}, headers=headers)
    events = client.get(f"/media/{show['id']}/rewatch-events?season=1&episode=1", headers=headers).json()
    assert len(events) == 1
    assert events[0]["is_initial"] is True


def test_status_completed_with_explicit_episodes_watched_skips_auto_mark(client, alice, monkeypatch):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = date.today() - timedelta(days=3)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload((1, "Pilot", aired.isoformat())),
    )

    r = client.patch(f"/media/{show['id']}", json={"status": "completed", "episodes_watched": 5}, headers=headers)
    assert r.status_code == 200
    assert r.json()["episodes_watched"] == 5
    assert _watched(client, headers, show["id"]) == []


def test_status_completed_without_tmdb_id_is_noop(client, alice):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show")

    r = client.patch(f"/media/{show['id']}", json={"status": "completed"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["episodes_watched"] == 0
    assert _watched(client, headers, show["id"]) == []


def test_status_completed_does_not_remark_already_watched_episodes(client, alice, monkeypatch):
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = date.today() - timedelta(days=3)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Pilot", aired.isoformat()), (2, "Two", aired.isoformat())
        ),
    )
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 7}, headers=headers)

    r = client.patch(f"/media/{show['id']}", json={"status": "completed"}, headers=headers)
    assert r.status_code == 200
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    watched_by_ep = {(w["season"], w["episode"]): w["rating"] for w in body["watched"]}
    assert watched_by_ep == {(1, 1): 7, (1, 2): None}


# ---------- catching up on a continuing show auto-completes ----------


def test_marking_all_aired_episodes_completes_show_even_when_total_episodes_counts_unaired(client, alice, monkeypatch):
    # Title.total_episodes (3) reflects TMDB's flat number_of_episodes, which
    # already counts episode 3 even though it hasn't aired yet — once the
    # Episode catalog is synced (here: via the app's existing lazy-sync path,
    # same one /upcoming/history and the notifier job use), a user manually
    # catching up on the two episodes that HAVE aired should promote the show
    # to "completed" ("Caught up"), not get stuck waiting for a threshold (3)
    # that won't be reachable until episode 3 airs.
    _, headers = alice
    show = _show(client, headers, media_type="tv_show", tmdb_id=70523, total_episodes=3)
    _set_title_for_entry(client, headers, show["id"], total_seasons=1)
    aired = date.today() - timedelta(days=3)
    unaired = date.today() + timedelta(days=10)
    monkeypatch.setattr(
        tmdb_store,
        "tmdb_get",
        lambda path, params=None, cache=True: _season_payload(
            (1, "Ep1", aired.isoformat()), (2, "Ep2", aired.isoformat()), (3, "Ep3", unaired.isoformat())
        ),
    )
    # seeds the Episode catalog the same way /upcoming/history does — the
    # per-episode toggle endpoint itself does NOT sync it (too costly to hit
    # TMDB on every single checkbox click), so this fix only takes effect
    # once something else has populated the catalog
    assert client.get("/upcoming/history", headers=headers).status_code == 200

    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True}, headers=headers)

    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["episodes_watched"] == 2
    assert item["status"] == "completed"


# ---------- community episode ratings ----------


def test_episode_ratings_average_across_users(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_show = _show(client, alice_headers, tmdb_id=70523)
    bob_show = _show(client, bob_headers, tmdb_id=70523)
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": True, "rating": 80}, headers=alice_headers)
    client.put(f"/media/{bob_show['id']}/episodes/1/1", json={"watched": True, "rating": 60}, headers=bob_headers)

    r = client.get(
        "/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=alice_headers
    )
    assert r.status_code == 200
    assert r.json() == {"average": 70, "count": 2}


def test_episode_ratings_ignores_other_episodes(client, alice):
    _, headers = alice
    show = _show(client, headers, tmdb_id=70523)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 80}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True, "rating": 20}, headers=headers)

    r = client.get("/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=headers)
    assert r.json() == {"average": 80, "count": 1}


def test_episode_ratings_no_data(client, alice):
    _, headers = alice
    r = client.get("/media/episode-ratings", params={"tmdb_id": 999999, "season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"average": None, "count": 0}


def test_episode_ratings_average_updates_when_rating_changed(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_show = _show(client, alice_headers, tmdb_id=70523)
    bob_show = _show(client, bob_headers, tmdb_id=70523)
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": True, "rating": 80}, headers=alice_headers)
    client.put(f"/media/{bob_show['id']}/episodes/1/1", json={"watched": True, "rating": 60}, headers=bob_headers)
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": True, "rating": 40}, headers=alice_headers)

    r = client.get(
        "/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=alice_headers
    )
    assert r.json() == {"average": 50, "count": 2}


def test_episode_ratings_drops_when_rating_cleared(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_show = _show(client, alice_headers, tmdb_id=70523)
    bob_show = _show(client, bob_headers, tmdb_id=70523)
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": True, "rating": 80}, headers=alice_headers)
    client.put(f"/media/{bob_show['id']}/episodes/1/1", json={"watched": True, "rating": 60}, headers=bob_headers)
    # re-PUT with no rating field (defaults to None) clears alice's rating
    # without unmarking the episode as watched
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": True}, headers=alice_headers)

    r = client.get(
        "/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=alice_headers
    )
    assert r.json() == {"average": 60, "count": 1}


def test_episode_ratings_drops_when_episode_unwatched(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alice_show = _show(client, alice_headers, tmdb_id=70523)
    bob_show = _show(client, bob_headers, tmdb_id=70523)
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": True, "rating": 80}, headers=alice_headers)
    client.put(f"/media/{bob_show['id']}/episodes/1/1", json={"watched": True, "rating": 60}, headers=bob_headers)
    # unmark watched entirely — deletes the underlying EpisodeWatch row
    client.put(f"/media/{alice_show['id']}/episodes/1/1", json={"watched": False}, headers=alice_headers)

    r = client.get(
        "/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=alice_headers
    )
    assert r.json() == {"average": 60, "count": 1}


# ---------- per-rewatch ratings ----------


def test_first_episode_watch_creates_watch_event_with_rating(client, alice):
    """Rating a title/episode for the first time (no prior rewatch) creates
    exactly one WatchEvent with that rating."""
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 85}, headers=headers)

    db = SessionLocal()
    try:
        events = db.query(WatchEvent).filter(WatchEvent.media_item_id == show["id"]).all()
        assert len(events) == 1
        assert events[0].rating == 85
        assert events[0].season == 1
        assert events[0].episode == 1
        assert events[0].is_initial is True
    finally:
        db.close()


def test_rewatch_creates_second_watch_event_and_headline_stays_latest(client, alice):
    """A rewatch creates a second WatchEvent. The headline rating follows only
    the latest WatchEvent's rating, not a sum of both — the community aggregate
    (episode_rating_aggregates) also reflects only the one cached value."""
    _, headers = alice
    show = _show(client, headers, tmdb_id=70523)

    # First watch: rate 70
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 70}, headers=headers)
    # Rewatch (no rating yet)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    db = SessionLocal()
    try:
        events = db.query(WatchEvent).filter(WatchEvent.media_item_id == show["id"]).all()
        assert len(events) == 2
    finally:
        db.close()

    # Rate the rewatch (the new latest event) via the per-event endpoint
    history = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    latest_event_id = history[0]["id"]  # newest first
    client.patch(
        f"/media/{show['id']}/rewatch-events/{latest_event_id}",
        json={"rating": 90},
        headers=headers,
    )

    # Headline rating is 90 (the rewatch), NOT 160 or an average of 70+90
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 90

    # Community aggregate reflects only the one cached EpisodeWatch.rating
    r = client.get("/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=headers)
    assert r.json() == {"average": 90, "count": 1}


def test_editing_non_latest_watch_event_rating_does_not_change_headline(client, alice):
    """Editing a non-latest (historical) WatchEvent's rating does NOT change
    the item's headline rating or the community aggregate."""
    _, headers = alice
    show = _show(client, headers, tmdb_id=70523)

    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 70}, headers=headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    history = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    # History is newest-first; the LAST entry is the oldest (initial watch, rating=70)
    oldest_event_id = history[-1]["id"]

    # Edit the historical (non-latest) event rating — should NOT propagate
    r = client.patch(
        f"/media/{show['id']}/rewatch-events/{oldest_event_id}",
        json={"rating": 50},
        headers=headers,
    )
    assert r.status_code == 200

    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    # Cache column (EpisodeWatch.rating) stays at 70: it was set by the initial
    # set_episode call and a rewatch does NOT reset it (no rating was attached
    # to the rewatch event). Editing the historical non-latest event to 50 must
    # NOT propagate to the cache either — only the latest event drives the cache.
    assert body["watched"][0]["rating"] == 70


def test_editing_latest_watch_event_rating_updates_headline_and_aggregate(client, alice):
    """Editing the LATEST WatchEvent's rating updates the headline/aggregate."""
    _, headers = alice
    show = _show(client, headers, tmdb_id=70523)

    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 70}, headers=headers)

    history = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    latest_event_id = history[0]["id"]

    r = client.patch(
        f"/media/{show['id']}/rewatch-events/{latest_event_id}",
        json={"rating": 95},
        headers=headers,
    )
    assert r.status_code == 200

    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 95

    r = client.get("/media/episode-ratings", params={"tmdb_id": 70523, "season": 1, "episode": 1}, headers=headers)
    assert r.json() == {"average": 95, "count": 1}


def test_undo_rewatch_falls_back_headline_to_previous_watch_through_rating(client, alice):
    """After two rated watch-throughs, undo_rewatch falls back the headline
    rating to the now-remaining (first-watch) event's rating, not to None."""
    _, headers = alice
    show = _show(client, headers)

    # First watch: rated 80
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 80}, headers=headers)
    # Rewatch
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    # Rate the rewatch via the per-event endpoint
    history = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    client.patch(
        f"/media/{show['id']}/rewatch-events/{history[0]['id']}",
        json={"rating": 90},
        headers=headers,
    )

    # Headline is 90 (the rewatch)
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 90

    # Undo the rewatch → falls back to the first-watch event (rating 80)
    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rating_cleared"] is True  # 90 → 80: genuinely changed

    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rating"] == 80
    assert body["watched"][0]["rewatch_count"] == 0


def test_patch_rewatch_event_not_found(client, alice):
    """PATCH on a nonexistent event id returns 404."""
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    r = client.patch(f"/media/{film['id']}/rewatch-events/999999", json={"rating": 80}, headers=headers)
    assert r.status_code == 404


def test_list_rewatch_events_includes_rating(client, alice):
    """list_rewatch_events returns rating in each event dict."""
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True, "rating": 75}, headers=headers)

    events = client.get(
        f"/media/{show['id']}/rewatch-events", params={"season": 1, "episode": 1}, headers=headers
    ).json()
    assert len(events) == 1
    assert "rating" in events[0]
    assert events[0]["rating"] == 75


def test_migration_backfill_rated_items_get_watch_event(client, alice):
    """Verify the migration backfill logic: a rated episode that has no prior
    WatchEvent should produce exactly one WatchEvent via the application's
    normal path (set_episode). This is an integration check of the live code
    path, not a direct test of the Alembic migration SQL (which is run against
    a real DB, not the in-memory test schema)."""
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True, "rating": 88}, headers=headers)

    db = SessionLocal()
    try:
        events = (
            db.query(WatchEvent)
            .filter(WatchEvent.media_item_id == show["id"], WatchEvent.season == 1, WatchEvent.episode == 2)
            .all()
        )
        assert len(events) == 1
        assert events[0].rating == 88

        # The EpisodeWatch cache column is in sync with the WatchEvent
        ew = (
            db.query(EpisodeWatch)
            .filter(EpisodeWatch.media_item_id == show["id"], EpisodeWatch.season == 1, EpisodeWatch.episode == 2)
            .first()
        )
        assert ew is not None
        assert ew.rating == 88
    finally:
        db.close()


def test_film_patch_rating_creates_watch_event_and_updates_aggregate(client, alice):
    """PATCH /media/{id} with a rating for a film (via update_media) writes
    through to WatchEvent.rating and keeps the community aggregate in sync."""
    _, headers = alice
    film = client.post(
        "/media", json={"media_type": "film", "title": "Heat", "status": "completed"}, headers=headers
    ).json()

    r = client.patch(f"/media/{film['id']}", json={"rating": 82}, headers=headers)
    assert r.status_code == 200
    assert r.json()["rating"] == 82

    db = SessionLocal()
    try:
        events = db.query(WatchEvent).filter(WatchEvent.media_item_id == film["id"]).all()
        # create_media with status=completed → 1 WatchEvent; _write_rating finds it and sets rating
        assert any(e.rating == 82 for e in events)

        entry = db.query(LibraryEntry).filter(LibraryEntry.id == film["id"]).first()
        assert entry.rating == 82

        title = db.query(Title).filter(Title.id == entry.title_id).first()
        assert title.rating_sum == 82
        assert title.rating_count == 1
    finally:
        db.close()
