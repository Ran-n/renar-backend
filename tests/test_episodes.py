#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.262466
Revised: 2026/07/28 10:20:35.347592

Per-episode tracking: set/unset, bulk, progress sync, rewatches, ratings.
"""

from datetime import date, timedelta

from renar_backend.database import SessionLocal
from renar_backend.models import LibraryEntry
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
    for _ in range(2):
        r = client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)
        assert r.status_code == 200
    assert r.json()["rewatch_count"] == 2


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
    for _ in range(3):
        client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers)

    events = client.get(f"/media/{film['id']}/rewatch-events", headers=headers).json()
    assert len(events) == 3
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


def test_episode_rewatch_marks_watched_and_counts(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.post(f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    body = client.get(f"/media/{show['id']}/episodes", headers=headers).json()
    assert body["watched"][0]["rewatch_count"] == 1
    assert _watched(client, headers, show["id"]) == [(1, 1)]


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


def test_undo_rewatch_with_nothing_to_undo_is_404(client, alice):
    _, headers = alice
    show = _show(client, headers)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    assert r.status_code == 404


def test_undo_rewatch_season_without_episode_rejected(client, alice):
    _, headers = alice
    show = _show(client, headers)
    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1}, headers=headers)
    assert r.status_code == 422


def test_undo_whole_item_rewatch(client, alice):
    _, headers = alice
    film = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
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
