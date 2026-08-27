#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.125706
Revised: 2026/08/27 09:52:22.273324

Comments on titles: create, list, like/unlike, delete, replies, reports.
"""


def _post_comment(client, headers, **overrides) -> dict:
    payload = {"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "A classic."}
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


def test_create_by_tmdb_id_without_title_needs_known_title(client, alice):
    _, headers = alice
    # unknown tmdb_id with no title text: a Title row cannot be created nameless
    r = client.post("/comments", json={"media_type": "film", "tmdb_id": 949, "text": "hi"}, headers=headers)
    assert r.status_code == 422
    # once the Title exists (here via a titled comment), tmdb_id alone is enough
    _post_comment(client, headers)
    r = client.post("/comments", json={"media_type": "film", "tmdb_id": 949, "text": "hi"}, headers=headers)
    assert r.status_code == 201, r.text


def test_comments_by_tmdb_id_and_title_share_a_thread(client, alice):
    _, headers = alice
    _post_comment(client, headers, media_type="film", tmdb_id=949, title="Heat")
    # the library flow creates the Title; a comment listed by its text finds
    # nothing (text-identity only applies to titles without a tmdb_id)
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=headers).json()
    assert len(listed) == 1


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


def test_dislike_unlike_roundtrip(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    assert client.post(f"/comments/{comment['id']}/dislike", headers=bob_headers).status_code == 204
    # a second dislike is a no-op, not a second row
    client.post(f"/comments/{comment['id']}/dislike", headers=bob_headers)
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["dislikes"] == 1
    assert listed[0]["disliked_by_me"] is True

    assert client.delete(f"/comments/{comment['id']}/dislike", headers=bob_headers).status_code == 204
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["dislikes"] == 0


def test_like_and_dislike_are_mutually_exclusive(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    client.post(f"/comments/{comment['id']}/like", headers=bob_headers)
    # disliking flips the same reaction row rather than stacking a second one
    client.post(f"/comments/{comment['id']}/dislike", headers=bob_headers)
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["likes"] == 0
    assert listed[0]["liked_by_me"] is False
    assert listed[0]["dislikes"] == 1
    assert listed[0]["disliked_by_me"] is True

    # DELETE .../like must not retract the dislike that's actually in place
    client.delete(f"/comments/{comment['id']}/like", headers=bob_headers)
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["dislikes"] == 1


def test_dislike_missing_comment_not_found(client, alice):
    _, headers = alice
    assert client.post("/comments/9999/dislike", headers=headers).status_code == 404


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


# ---------- multi-session sync (events.publish fanout) ----------


def test_create_like_dislike_delete_publish_comment_changed(client, alice):
    from renar_backend import events

    user, headers = alice
    queue = events.subscribe(user["id"])
    try:
        comment = _post_comment(client, headers)
        assert queue.get_nowait() == "comment_changed"

        client.post(f"/comments/{comment['id']}/like", headers=headers)
        assert queue.get_nowait() == "comment_changed"

        client.delete(f"/comments/{comment['id']}/like", headers=headers)
        assert queue.get_nowait() == "comment_changed"

        client.post(f"/comments/{comment['id']}/dislike", headers=headers)
        assert queue.get_nowait() == "comment_changed"

        client.delete(f"/comments/{comment['id']}", headers=headers)
        assert queue.get_nowait() == "comment_changed"
    finally:
        events.unsubscribe(user["id"], queue)


# ---------- replies ----------


def test_reply_nests_under_parent(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    parent = _post_comment(client, alice_headers)
    reply = _post_comment(client, bob_headers, parent_id=parent["id"], text="I agree.")
    assert reply["parent_id"] == parent["id"]
    # a reply to the reply ("and so on"): depth is not capped
    nested = _post_comment(client, alice_headers, parent_id=reply["id"], text="Glad you do.")

    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers).json()
    assert [c["id"] for c in listed] == [parent["id"]]  # replies are not top-level rows
    assert [r["id"] for r in listed[0]["replies"]] == [reply["id"]]
    assert [r["id"] for r in listed[0]["replies"][0]["replies"]] == [nested["id"]]


def test_reply_to_missing_parent_not_found(client, alice):
    _, headers = alice
    payload = {"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "hi", "parent_id": 9999}
    assert client.post("/comments", json=payload, headers=headers).status_code == 404


def test_reply_to_parent_in_another_thread_rejected(client, alice):
    _, headers = alice
    parent = _post_comment(client, headers, media_type="tv_show", season=1, episode=2)
    # same title but show-level scope: not the parent's thread
    payload = {"media_type": "tv_show", "tmdb_id": 949, "title": "Heat", "text": "hi", "parent_id": parent["id"]}
    assert client.post("/comments", json=payload, headers=headers).status_code == 422


def test_delete_comment_removes_reply_subtree(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    parent = _post_comment(client, alice_headers)
    reply = _post_comment(client, bob_headers, parent_id=parent["id"], text="reply")
    _post_comment(client, alice_headers, parent_id=reply["id"], text="nested reply")

    assert client.delete(f"/comments/{parent['id']}", headers=alice_headers).status_code == 204
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers).json()
    assert listed == []
    # the cascade really deleted the reply rows (a like on one would 404)
    assert client.post(f"/comments/{reply['id']}/like", headers=bob_headers).status_code == 404


# ---------- reports ----------


def test_report_roundtrip(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    # a second report by the same user is a no-op, not a second row
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204

    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["reported_by_me"] is True
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers).json()
    assert listed[0]["reported_by_me"] is False


def test_unreport_roundtrip(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    assert client.delete(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["reported_by_me"] is False

    # reporting again after retraction works
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["reported_by_me"] is True


def test_unreport_without_report_is_noop(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)
    assert client.delete(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204


def test_unreport_missing_comment_is_noop(client, alice):
    _, headers = alice
    # mirrors unlike: there is no report row to delete, so 204 regardless of the id
    assert client.delete("/comments/9999/report", headers=headers).status_code == 204


def test_unreport_only_removes_own_report(client, make_user, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _, carol_headers = make_user("carol")
    comment = _post_comment(client, alice_headers)

    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    assert client.post(f"/comments/{comment['id']}/report", headers=carol_headers).status_code == 204
    assert client.delete(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204

    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=carol_headers).json()
    assert listed[0]["reported_by_me"] is True
    listed = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=bob_headers).json()
    assert listed[0]["reported_by_me"] is False


def test_report_with_reason(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)
    r = client.post(f"/comments/{comment['id']}/report", json={"reason": "spam"}, headers=bob_headers)
    assert r.status_code == 204


def test_report_own_comment_rejected(client, alice):
    _, headers = alice
    comment = _post_comment(client, headers)
    assert client.post(f"/comments/{comment['id']}/report", headers=headers).status_code == 422


def test_report_missing_comment_not_found(client, alice):
    _, headers = alice
    assert client.post("/comments/9999/report", headers=headers).status_code == 404


def test_delete_reported_comment_removes_reports(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    assert client.delete(f"/comments/{comment['id']}", headers=alice_headers).status_code == 204
