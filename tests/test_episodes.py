#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.262466
Revised: 2026/07/07 13:25:17.262466

Per-episode tracking: set/unset, bulk, progress sync, rewatches, ratings.
"""


def _show(client, headers, **overrides) -> dict:
    payload = {"media_type": "tv_show", "title": "Dark", "total_episodes": 3}
    payload.update(overrides)
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _watched(client, headers, item_id) -> list[tuple[int, int]]:
    body = client.get(f"/media/{item_id}/episodes", headers=headers).json()
    return [(w["season"], w["episode"]) for w in body["watched"]]


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


def test_watching_all_episodes_completes_show(client, alice):
    _, headers = alice
    show = _show(client, headers, total_episodes=2)
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.put(f"/media/{show['id']}/episodes/1/2", json={"watched": True}, headers=headers)
    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["status"] == "completed"


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
