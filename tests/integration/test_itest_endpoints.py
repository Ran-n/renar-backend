#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 14:25:45.656080
Revised: 2026/11/13 14:25:45.656080

The live test server's own `_itest/*` shortcuts (_test_server.py). Both this
repo's integration suite and renar-frontend's lean on them for state no real
API can reach yet (email confirmation, premium, reviewer whitelist, seeded
notifications, next-episode data), so a shortcut that silently stopped
working would make every downstream test that uses it lie. Each one is
checked for its visible effect through the real API, plus its
unknown-target answer (`{"ok": false}`, never a 500).

`/_itest/drop_schema` is exercised by the `live_server` fixture's teardown.
"""

import uuid

import pytest

from .conftest import register_and_login

pytestmark = pytest.mark.integration

_MISSING_USER = "itest_no_such_user"


def _new_user(http_client, live_server) -> tuple[str, dict]:
    username = f"itest_{uuid.uuid4().hex[:10]}"
    return username, register_and_login(http_client, live_server, username)


def test_confirm_email_unknown_user(http_client):
    r = http_client.post(f"/_itest/confirm_email/{_MISSING_USER}")
    assert r.status_code == 200
    assert r.json() == {"ok": False}


def test_set_premium_makes_user_premium(http_client, live_server):
    username, headers = _new_user(http_client, live_server)
    assert http_client.get("/auth/me", headers=headers).json()["is_premium"] is False
    r = http_client.post(f"/_itest/set_premium/{username}", params={"days": 3})
    assert r.json() == {"ok": True}
    assert http_client.get("/auth/me", headers=headers).json()["is_premium"] is True


def test_set_premium_unknown_user(http_client):
    assert http_client.post(f"/_itest/set_premium/{_MISSING_USER}").json() == {"ok": False}


def test_whitelist_reviewer_is_idempotent(http_client, live_server):
    username, headers = _new_user(http_client, live_server)
    assert http_client.get("/auth/me", headers=headers).json()["is_reviewer"] is False
    for _ in range(2):  # second call takes the already-whitelisted path
        assert http_client.post(f"/_itest/whitelist_reviewer/{username}").json() == {"ok": True}
    assert http_client.get("/auth/me", headers=headers).json()["is_reviewer"] is True


def test_whitelist_reviewer_unknown_user(http_client):
    assert http_client.post(f"/_itest/whitelist_reviewer/{_MISSING_USER}").json() == {"ok": False}


def test_seed_notification_shows_up(http_client, live_server):
    username, headers = _new_user(http_client, live_server)
    r = http_client.post(f"/_itest/seed_notification/{username}", params={"title": "Seeded", "body": "Hello"})
    body = r.json()
    assert body["ok"] is True
    notifications = http_client.get("/notifications", headers=headers).json()
    assert [(n["id"], n["title"], n["body"]) for n in notifications] == [(body["id"], "Seeded", "Hello")]


def test_seed_notification_unknown_user(http_client):
    assert http_client.post(f"/_itest/seed_notification/{_MISSING_USER}").json() == {"ok": False}


def test_set_next_episode_feeds_upcoming(http_client, live_server):
    _, headers = _new_user(http_client, live_server)
    show = http_client.post(
        "/media",
        json={"title": "Itest Show", "media_type": "tv_show", "status": "watching", "tmdb_id": 900124},
        headers=headers,
    ).json()
    r = http_client.post(f"/_itest/set_next_episode/{show['id']}", params={"days_until": 2, "season": 3, "episode": 4})
    assert r.json() == {"ok": True}
    upcoming = http_client.get("/upcoming", headers=headers).json()
    assert [(u["item_id"], u["days_until"], u["season"], u["episode"]) for u in upcoming] == [(show["id"], 2, 3, 4)]


def test_set_next_episode_unknown_item(http_client):
    r = http_client.post("/_itest/set_next_episode/2147483647", params={"days_until": 1})
    assert r.json() == {"ok": False}
