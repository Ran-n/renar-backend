#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.681273
Revised: 2026/07/16 09:54:31.933339

Social graph: search, public profiles, follow/unfollow, feed.
"""


def test_search_finds_others_but_not_self(client, alice, bob):
    _, headers = alice
    results = client.get("/users/search", params={"q": "b"}, headers=headers).json()
    assert [u["username"] for u in results] == ["bob"]
    results = client.get("/users/search", params={"q": "alice"}, headers=headers).json()
    assert results == []


def test_search_requires_query(client, alice):
    _, headers = alice
    assert client.get("/users/search", headers=headers).status_code == 422


def test_get_user_public_profile(client, alice, bob):
    _, headers = alice
    bob_user, _ = bob
    r = client.get(f"/users/{bob_user['id']}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "bob"
    assert body["is_me"] is False
    assert body["is_following"] is False
    assert "email" not in body  # public profile must not leak the email


def test_get_missing_user_not_found(client, alice):
    _, headers = alice
    assert client.get("/users/9999", headers=headers).status_code == 404


def test_public_profile_shows_total_watch_minutes(client, alice, bob):
    _, headers = alice
    bob_user, bob_headers = bob
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "runtime_minutes": 117, "status": "completed"},
        headers=bob_headers,
    )
    profile = client.get(f"/users/{bob_user['id']}", headers=headers).json()
    assert profile["total_watch_minutes"] == 117


def test_follow_unfollow_roundtrip(client, alice, bob):
    _, headers = alice
    bob_user, bob_headers = bob

    assert client.post(f"/users/{bob_user['id']}/follow", headers=headers).status_code == 204
    profile = client.get(f"/users/{bob_user['id']}", headers=headers).json()
    assert profile["is_following"] is True
    assert profile["followers"] == 1

    followers = client.get(f"/users/{bob_user['id']}/followers", headers=bob_headers).json()
    assert [u["username"] for u in followers] == ["alice"]

    assert client.delete(f"/users/{bob_user['id']}/follow", headers=headers).status_code == 204
    profile = client.get(f"/users/{bob_user['id']}", headers=headers).json()
    assert profile["is_following"] is False
    assert profile["followers"] == 0


def test_follow_is_idempotent(client, alice, bob):
    _, headers = alice
    bob_user, _ = bob
    client.post(f"/users/{bob_user['id']}/follow", headers=headers)
    client.post(f"/users/{bob_user['id']}/follow", headers=headers)
    assert client.get(f"/users/{bob_user['id']}", headers=headers).json()["followers"] == 1


def test_follow_self_rejected(client, alice):
    user, headers = alice
    assert client.post(f"/users/{user['id']}/follow", headers=headers).status_code == 400


def test_follow_missing_user_not_found(client, alice):
    _, headers = alice
    assert client.post("/users/9999/follow", headers=headers).status_code == 404


def test_following_list(client, alice, bob):
    alice_user, headers = alice
    bob_user, _ = bob
    client.post(f"/users/{bob_user['id']}/follow", headers=headers)
    following = client.get(f"/users/{alice_user['id']}/following", headers=headers).json()
    assert [u["username"] for u in following] == ["bob"]


def test_following_list_paginated(client, alice, make_user):
    alice_user, headers = alice
    followed = [make_user(f"followed{i}")[0] for i in range(3)]
    for user in followed:
        client.post(f"/users/{user['id']}/follow", headers=headers)

    # newest-followed first (created_at desc), so page order is reversed
    page1 = client.get(f"/users/{alice_user['id']}/following", params={"limit": 2, "offset": 0}, headers=headers).json()
    page2 = client.get(f"/users/{alice_user['id']}/following", params={"limit": 2, "offset": 2}, headers=headers).json()
    assert [u["username"] for u in page1] == ["followed2", "followed1"]
    assert [u["username"] for u in page2] == ["followed0"]

    unpaginated = client.get(f"/users/{alice_user['id']}/following", headers=headers).json()
    assert len(unpaginated) == 3


def test_followers_list_paginated(client, bob, make_user):
    bob_user, _ = bob
    followers = [make_user(f"follower{i}") for i in range(3)]
    for _, hdrs in followers:
        client.post(f"/users/{bob_user['id']}/follow", headers=hdrs)

    page1 = client.get(f"/users/{bob_user['id']}/followers", params={"limit": 2, "offset": 0}, headers=hdrs).json()
    page2 = client.get(f"/users/{bob_user['id']}/followers", params={"limit": 2, "offset": 2}, headers=hdrs).json()
    assert [u["username"] for u in page1] == ["follower2", "follower1"]
    assert [u["username"] for u in page2] == ["follower0"]


def test_following_list_default_limit(client, alice, make_user):
    alice_user, headers = alice
    followed = [make_user(f"followed{i}")[0] for i in range(65)]
    for user in followed:
        client.post(f"/users/{user['id']}/follow", headers=headers)

    capped = client.get(f"/users/{alice_user['id']}/following", headers=headers).json()
    assert len(capped) == 60  # default page size when `limit` is omitted

    page2 = client.get(f"/users/{alice_user['id']}/following", params={"offset": 60}, headers=headers).json()
    assert len(page2) == 5


def test_followers_list_default_limit(client, bob, make_user):
    bob_user, _ = bob
    followers = [make_user(f"follower{i}") for i in range(65)]
    for _, hdrs in followers:
        client.post(f"/users/{bob_user['id']}/follow", headers=hdrs)

    capped = client.get(f"/users/{bob_user['id']}/followers", headers=hdrs).json()
    assert len(capped) == 60  # default page size when `limit` is omitted

    page2 = client.get(f"/users/{bob_user['id']}/followers", params={"offset": 60}, headers=hdrs).json()
    assert len(page2) == 5


def test_user_media_is_visible_to_others(client, alice, bob):
    _, headers = alice
    bob_user, bob_headers = bob
    client.post("/media", json={"media_type": "film", "title": "Alien"}, headers=bob_headers)
    items = client.get(f"/users/{bob_user['id']}/media", headers=headers).json()
    assert [i["title"] for i in items] == ["Alien"]


def test_feed_empty_without_follows(client, alice):
    _, headers = alice
    assert client.get("/feed", headers=headers).json() == []


def test_feed_shows_followed_users_activity(client, alice, bob):
    _, headers = alice
    bob_user, bob_headers = bob
    client.post(f"/users/{bob_user['id']}/follow", headers=headers)
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed", "rating": 10},
        headers=bob_headers,
    )
    feed = client.get("/feed", headers=headers).json()
    assert len(feed) == 1
    entry = feed[0]
    assert entry["username"] == "bob"
    assert entry["title"] == "Alien"
    assert entry["status"] == "completed"


def test_social_endpoints_require_auth(client):
    assert client.get("/feed").status_code == 401
    assert client.get("/users/search", params={"q": "a"}).status_code == 401
