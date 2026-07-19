#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.823858
Revised: 2026/07/18 19:33:28.035486

Aggregated statistics endpoint + service health routes.
"""


def test_health_routes(client):
    assert client.get("/health").json() == {"status": "ok"}
    root = client.get("/").json()
    assert root["status"] == "ok"


def test_stats_requires_auth(client):
    assert client.get("/stats").status_code == 401


def test_stats_empty_library(client, alice):
    _, headers = alice
    s = client.get("/stats", headers=headers).json()
    assert s["total_items"] == 0
    assert s["total_watch_minutes"] == 0
    assert s["films_watched"] == 0
    assert s["episodes_watched"] == 0
    assert s["avg_rating"] is None


def test_stats_counts_completed_film(client, alice):
    _, headers = alice
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170, "rating": 9},
        headers=headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "want_to_watch"},
        headers=headers,
    )
    s = client.get("/stats", headers=headers).json()
    assert s["total_items"] == 2
    assert s["films_watched"] == 1
    assert s["film_minutes"] == 170
    assert s["avg_rating"] == 9.0
    assert s["by_status"]["completed"] == 1
    assert s["by_type"]["film"] == 2


def test_stats_counts_tv_episodes(client, alice):
    _, headers = alice
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2, 3]},
        headers=headers,
    )
    s = client.get("/stats", headers=headers).json()
    assert s["episodes_watched"] == 3
    assert s["tv_minutes"] == 3 * 50
    assert s["shows_watching"] == 1
    assert s["episodes_last_7_days"] == 3
    assert s["current_streak_days"] >= 1


def test_stats_only_own_items(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed"},
        headers=bob_headers,
    )
    s = client.get("/stats", headers=alice_headers).json()
    assert s["total_items"] == 0
