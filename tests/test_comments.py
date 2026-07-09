#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.125706
Revised: 2026/07/07 13:25:17.125706

Comments on titles: create, list, like/unlike, delete.
"""


def _post_comment(client, headers, **overrides) -> dict:
    payload = {"media_type": "film", "tmdb_id": 949, "text": "A classic."}
    payload.update(overrides)
    r = client.post("/comments", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_by_tmdb_id(client, alice):
    _, headers = alice
    comment = _post_comment(client, headers)
    assert comment["username"] == "alice"
    assert comment["mine"] is True
    assert comment["likes"] == 0

    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=headers).json()
    assert [c["id"] for c in listed] == [comment["id"]]


def test_create_by_title_fallback(client, alice):
    _, headers = alice
    _post_comment(client, headers, tmdb_id=None, title="Obscure Film")
    listed = client.get("/comments", params={"media_type": "film", "title": "Obscure Film"}, headers=headers).json()
    assert len(listed) == 1


def test_create_without_target_rejected(client, alice):
    _, headers = alice
    r = client.post("/comments", json={"media_type": "film", "text": "hi"}, headers=headers)
    assert r.status_code == 422


def test_create_empty_text_rejected(client, alice):
    _, headers = alice
    r = client.post("/comments", json={"media_type": "film", "tmdb_id": 949, "text": ""}, headers=headers)
    assert r.status_code == 422


def test_list_without_target_rejected(client, alice):
    _, headers = alice
    r = client.get("/comments", params={"media_type": "film"}, headers=headers)
    assert r.status_code == 422


def test_episode_comments_are_scoped(client, alice):
    _, headers = alice
    _post_comment(client, headers, media_type="tv_show", season=1, episode=2, text="wow")
    show_level = client.get("/comments", params={"media_type": "tv_show", "tmdb_id": 949}, headers=headers).json()
    assert show_level == []  # episode comment must not appear at show level
    episode_level = client.get(
        "/comments",
        params={"media_type": "tv_show", "tmdb_id": 949, "season": 1, "episode": 2},
        headers=headers,
    ).json()
    assert len(episode_level) == 1


def test_comments_are_global_across_users(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert [c["id"] for c in listed] == [comment["id"]]
    assert listed[0]["mine"] is False


def test_like_unlike_roundtrip(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    assert client.post(f"/comments/{comment['id']}/like", headers=bob_headers).status_code == 204
    # a second like is a no-op, not a second row
    client.post(f"/comments/{comment['id']}/like", headers=bob_headers)
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["likes"] == 1
    assert listed[0]["liked_by_me"] is True

    assert client.delete(f"/comments/{comment['id']}/like", headers=bob_headers).status_code == 204
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["likes"] == 0


def test_like_missing_comment_not_found(client, alice):
    _, headers = alice
    assert client.post("/comments/9999/like", headers=headers).status_code == 404


def test_delete_own_comment(client, alice):
    _, headers = alice
    comment = _post_comment(client, headers)
    assert client.delete(f"/comments/{comment['id']}", headers=headers).status_code == 204
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=headers).json()
    assert listed == []


def test_delete_other_users_comment_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)
    assert client.delete(f"/comments/{comment['id']}", headers=bob_headers).status_code == 404
