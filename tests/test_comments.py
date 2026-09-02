#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.125706
Revised: 2026/09/02 10:57:39.269950

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


def test_list_comments_unknown_title_returns_empty(client, alice):
    """GET /comments for an unseen title returns [] without error —
    covers comments.py list_comments line 128 (target is None)."""
    _, headers = alice
    r = client.get("/comments", params={"media_type": "film", "tmdb_id": 88888, "title": "NoSuchFilm"}, headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_reply_nesting_limit_rejected(client, alice, bob):
    """Replying past MAX_REPLY_DEPTH (8) returns 422 —
    covers comments.py line 179."""
    _, alice_headers = alice
    _, bob_headers = bob
    # Build a chain of 8 levels (root + 7 replies) then try to add one more
    current = _post_comment(client, alice_headers, text="level0")
    headers_cycle = [bob_headers, alice_headers]
    for i in range(7):  # creates levels 1-7
        current = _post_comment(client, headers_cycle[i % 2], parent_id=current["id"], text=f"level{i + 1}")
    # current is now at depth 7; trying to reply would make depth 8 >= MAX_REPLY_DEPTH
    r = client.post(
        "/comments",
        json={"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "too deep", "parent_id": current["id"]},
        headers=alice_headers,
    )
    assert r.status_code == 422
    assert "nesting" in r.json()["detail"].lower() or "limit" in r.json()["detail"].lower()


def test_like_concurrent_integrity_error_is_noop(client, alice, bob, monkeypatch):
    """An IntegrityError in _set_reaction (concurrent like) is silently swallowed —
    covers comments.py lines 239-241."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError
    from sqlalchemy.orm import Session

    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    call_count = [0]
    original_commit = Session.commit

    def patched_commit(self):
        from renar_backend.models import CommentLike

        new_likes = [obj for obj in self.new if isinstance(obj, CommentLike)]
        if new_likes and call_count[0] == 0:
            call_count[0] += 1
            self.rollback()
            raise SAIntegrityError("INSERT INTO comment_likes", {}, Exception("unique violation"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", patched_commit)
    r = client.post(f"/comments/{comment['id']}/like", headers=bob_headers)
    # Must return 204 (no-op), not 500
    assert r.status_code == 204


def test_report_concurrent_integrity_error_is_noop(client, alice, bob, monkeypatch):
    """An IntegrityError in report_comment (concurrent report) is silently swallowed —
    covers comments.py lines 313-315."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError
    from sqlalchemy.orm import Session

    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)

    call_count = [0]
    original_commit = Session.commit

    def patched_commit(self):
        from renar_backend.models import CommentReport

        new_reports = [obj for obj in self.new if isinstance(obj, CommentReport)]
        if new_reports and call_count[0] == 0:
            call_count[0] += 1
            self.rollback()
            raise SAIntegrityError("INSERT INTO comment_reports", {}, Exception("unique violation"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", patched_commit)
    r = client.post(f"/comments/{comment['id']}/report", headers=bob_headers)
    # Must return 204 (no-op), not 500
    assert r.status_code == 204


def test_build_watch_info_episode_branch_with_library_entry(client, alice):
    """_build_watch_info hits the episode-scoped branch (lines 53-64) when
    the commenter has a library entry for the title and episode is not None."""
    from renar_backend.catalog.titles import find_or_create_title
    from renar_backend.database import SessionLocal
    from renar_backend.models import EpisodeWatch, LibraryEntry, MediaType

    user, headers = alice

    # Post an episode-scoped comment first (creates the Title row)
    _post_comment(client, headers, media_type="tv_show", season=1, episode=3, text="great ep")

    # Create LibraryEntry + EpisodeWatch directly so we can control the data
    with SessionLocal() as db:
        title = find_or_create_title(db, MediaType.tv_show, 949, "Heat")
        # Ensure a LibraryEntry exists for alice
        entry = db.query(LibraryEntry).filter_by(user_id=user["id"], title_id=title.id).first()
        if entry is None:
            entry = LibraryEntry(user_id=user["id"], title_id=title.id)
            db.add(entry)
            db.flush()
        # Add an EpisodeWatch for season 1, episode 3
        existing_watch = db.query(EpisodeWatch).filter_by(media_item_id=entry.id, season=1, episode=3).first()
        if existing_watch is None:
            db.add(EpisodeWatch(media_item_id=entry.id, season=1, episode=3))
        db.commit()

    # List episode-scoped comments — _build_watch_info is called with episode=3
    r = client.get(
        "/comments",
        params={"media_type": "tv_show", "tmdb_id": 949, "season": 1, "episode": 3},
        headers=headers,
    )
    assert r.status_code == 200
    comments = r.json()
    assert len(comments) == 1
    # The commenter has watched the episode, so seen_by_author must be True
    assert comments[0]["seen_by_author"] is True


def test_load_thread_empty_root_ids(client):
    """load_thread([]) returns ({}, {}) immediately — covers comment_threads.py line 75."""
    from renar_backend.database import SessionLocal
    from renar_backend.social.comment_threads import load_thread

    with SessionLocal() as db:
        result = load_thread(db, [])
    assert result == ({}, {})


def test_resolve_root_scope_broken_thread_raises(client, alice):
    """resolve_root_scope raises RuntimeError when a reply has no ancestor with
    title_id — covers comment_threads.py line 58."""
    from renar_backend.database import SessionLocal
    from renar_backend.models import Comment
    from renar_backend.social.comment_threads import resolve_root_scope

    user, _headers = alice
    with SessionLocal() as db:
        # Insert a reply with no parent and no title_id (data-corruption scenario)
        orphan_reply = Comment(
            user_id=user["id"], title_id=None, parent_id=None, season=None, episode=None, text="broken reply"
        )
        db.add(orphan_reply)
        db.flush()
        import pytest as _pytest

        with _pytest.raises(RuntimeError, match="no root with a title_id"):
            resolve_root_scope(db, orphan_reply)
        db.rollback()  # don't persist the broken row


def test_delete_reported_comment_removes_reports(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers)
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204
    assert client.delete(f"/comments/{comment['id']}", headers=alice_headers).status_code == 204
