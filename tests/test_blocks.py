#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:21:52.614876
Revised: 2026/11/15 02:45:14.449393

Blocking users: block/unblock/list, and everything a block hides, both ways
(profile, library, follow, search, follower lists, comments with their reply
subtree, reviews), plus cleanup on account deletion and the GDPR export.
"""

import io
import json
import logging

import py7zr
import pytest
from conftest import hard_delete
from sqlalchemy.exc import IntegrityError

from renar_backend.database import SessionLocal
from renar_backend.models import Follow, ReviewWhitelist, User, UserBlock
from renar_backend.social import blocks
from renar_backend.users.export import build_export

FILM = {"media_type": "film", "tmdb_id": 949}


@pytest.fixture
def carol(make_user):
    return make_user("carol")


def _block(client, headers, user_id: int) -> None:
    assert client.post(f"/users/{user_id}/block", headers=headers).status_code == 204


def _comment(client, headers, text: str = "A classic.", parent_id: int | None = None) -> dict:
    payload = {**FILM, "title": "Heat", "text": text}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    r = client.post("/comments", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _comments(client, headers) -> list[dict]:
    return client.get("/comments", params=FILM, headers=headers).json()


def _review(client, user: dict, headers) -> dict:
    with SessionLocal() as db:
        db.add(ReviewWhitelist(user_id=user["id"]))
        db.commit()
    r = client.post(
        "/media/reviews",
        params={**FILM, "title": "Heat"},
        json={"text": "A genuine masterpiece.", "rating": 95},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _block_rows() -> list[tuple[int, int]]:
    with SessionLocal() as db:
        return [(b.blocker_id, b.blocked_id) for b in db.query(UserBlock).all()]


# ---------- block / unblock / list ----------


def test_block_list_unblock_roundtrip(client, alice, bob):
    _, headers = alice
    bob_user, _ = bob
    assert client.get("/users/blocked", headers=headers).json() == []

    _block(client, headers, bob_user["id"])
    blocked = client.get("/users/blocked", headers=headers).json()
    assert [u["username"] for u in blocked] == ["bob"]
    assert "email" not in blocked[0]

    assert client.delete(f"/users/{bob_user['id']}/block", headers=headers).status_code == 204
    assert client.get("/users/blocked", headers=headers).json() == []


def test_blocked_list_is_newest_first_and_only_my_own_blocks(client, alice, bob, carol):
    _, headers = alice
    bob_user, bob_headers = bob
    carol_user, _ = carol
    _block(client, headers, bob_user["id"])
    _block(client, headers, carol_user["id"])
    assert [u["username"] for u in client.get("/users/blocked", headers=headers).json()] == ["carol", "bob"]
    # being blocked doesn't put the blocker in my list: only the blocker may undo it
    assert client.get("/users/blocked", headers=bob_headers).json() == []


def test_blocked_route_is_not_read_as_a_user_id(client, alice):
    """`/users/blocked` must be matched before `/users/{user_id}` (422 otherwise)."""
    _, headers = alice
    assert client.get("/users/blocked", headers=headers).status_code == 200


def test_block_requires_auth(client, alice):
    user, _ = alice
    assert client.post(f"/users/{user['id']}/block").status_code == 401
    assert client.delete(f"/users/{user['id']}/block").status_code == 401
    assert client.get("/users/blocked").status_code == 401


def test_block_and_unblock_are_idempotent(client, alice, bob):
    _, headers = alice
    bob_user, _ = bob
    _block(client, headers, bob_user["id"])
    _block(client, headers, bob_user["id"])
    assert len(_block_rows()) == 1
    assert client.delete(f"/users/{bob_user['id']}/block", headers=headers).status_code == 204
    assert client.delete(f"/users/{bob_user['id']}/block", headers=headers).status_code == 204
    assert _block_rows() == []


def test_block_self_rejected(client, alice):
    user, headers = alice
    r = client.post(f"/users/{user['id']}/block", headers=headers)
    assert r.status_code == 400
    assert r.json()["detail"] == "You can't block yourself"
    assert _block_rows() == []


def test_block_unknown_user_not_found(client, alice):
    _, headers = alice
    assert client.post("/users/9999/block", headers=headers).status_code == 404
    # nothing to undo: same no-op as unfollow
    assert client.delete("/users/9999/block", headers=headers).status_code == 204


def test_blocked_user_can_block_back(client, alice, bob):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    _block(client, headers, bob_user["id"])
    _block(client, bob_headers, alice_user["id"])
    assert sorted(_block_rows()) == sorted([(alice_user["id"], bob_user["id"]), (bob_user["id"], alice_user["id"])])
    # one side unblocking leaves the other's block standing
    client.delete(f"/users/{bob_user['id']}/block", headers=headers)
    assert client.get(f"/users/{bob_user['id']}", headers=headers).status_code == 404


def test_block_deletes_follows_both_ways_and_unblock_does_not_restore(client, alice, bob):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    client.post(f"/users/{bob_user['id']}/follow", headers=headers)
    client.post(f"/users/{alice_user['id']}/follow", headers=bob_headers)

    _block(client, headers, bob_user["id"])
    with SessionLocal() as db:
        assert db.query(Follow).count() == 0
    assert client.get("/feed", headers=headers).json() == []

    client.delete(f"/users/{bob_user['id']}/block", headers=headers)
    assert client.get(f"/users/{bob_user['id']}", headers=headers).json()["is_following"] is False


def test_block_and_unblock_are_logged(client, alice, bob, caplog):
    alice_user, headers = alice
    bob_user, _ = bob
    with caplog.at_level(logging.INFO, logger="renar_backend.social.blocks"):
        _block(client, headers, bob_user["id"])
        client.delete(f"/users/{bob_user['id']}/block", headers=headers)
    messages = [r.getMessage() for r in caplog.records]
    assert f"user {alice_user['id']} blocked user {bob_user['id']}" in messages
    assert f"user {alice_user['id']} unblocked user {bob_user['id']}" in messages


def test_concurrent_block_keeps_the_first(alice, bob, monkeypatch, caplog):
    """Two simultaneous block requests: the loser's INSERT trips the unique
    pair, which is reported as "already blocked", not an error."""
    alice_user, _ = alice
    bob_user, _ = bob
    with SessionLocal() as db:

        def _lose_the_race():
            raise IntegrityError("insert", {}, Exception("uq_user_block_pair"))

        monkeypatch.setattr(db, "commit", _lose_the_race)
        with caplog.at_level(logging.INFO, logger="renar_backend.social.blocks"):
            assert blocks.block_user(db, alice_user["id"], bob_user["id"]) is False
    assert "kept the first" in caplog.text


# ---------- what a block hides ----------


@pytest.mark.parametrize("blocker", ["alice", "bob"])
def test_profile_media_and_follow_404_both_ways(client, alice, bob, blocker):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    if blocker == "alice":
        _block(client, headers, bob_user["id"])
    else:
        _block(client, bob_headers, alice_user["id"])

    for viewer, target in ((headers, bob_user), (bob_headers, alice_user)):
        for path in (f"/users/{target['id']}", f"/users/{target['id']}/media"):
            r = client.get(path, headers=viewer)
            assert r.status_code == 404
            assert r.json()["detail"] == "User not found"  # same as a user that doesn't exist
        assert client.get(f"/users/{target['id']}/following", headers=viewer).status_code == 404
        assert client.get(f"/users/{target['id']}/followers", headers=viewer).status_code == 404
        assert client.post(f"/users/{target['id']}/follow", headers=viewer).status_code == 404
    with SessionLocal() as db:
        assert db.query(Follow).count() == 0


def test_search_and_follow_lists_exclude_blocked_both_ways(client, alice, bob, carol):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    carol_user, carol_headers = carol
    # carol follows both, and both follow carol
    for target in (alice_user, bob_user):
        client.post(f"/users/{target['id']}/follow", headers=carol_headers)
    client.post(f"/users/{carol_user['id']}/follow", headers=headers)
    client.post(f"/users/{carol_user['id']}/follow", headers=bob_headers)

    _block(client, headers, bob_user["id"])

    def names(path: str, viewer: dict, **params) -> list[str]:
        return sorted(u["username"] for u in client.get(path, params=params, headers=viewer).json())

    assert names("/users/search", headers, q="b") == []
    assert names("/users/search", bob_headers, q="alice") == []
    assert names("/users/search", carol_headers, q="b") == ["bob"]  # third parties are unaffected
    assert names(f"/users/{carol_user['id']}/following", headers) == ["alice"]
    assert names(f"/users/{carol_user['id']}/followers", headers) == ["alice"]
    assert names(f"/users/{carol_user['id']}/following", bob_headers) == ["bob"]
    assert names(f"/users/{carol_user['id']}/followers", bob_headers) == ["bob"]
    assert names(f"/users/{carol_user['id']}/followers", carol_headers) == ["alice", "bob"]


@pytest.mark.regression
def test_comments_by_blocked_user_and_their_reply_subtree_are_hidden(client, alice, bob, carol):
    """Guards the subtree rule: a reply under a hidden comment is hidden too
    (it makes no sense without the comment it answers), while replies by
    other people elsewhere stay."""
    _, headers = alice
    bob_user, bob_headers = bob
    _, carol_headers = carol
    bob_root = _comment(client, bob_headers, "bob root")
    _comment(client, carol_headers, "carol under bob", parent_id=bob_root["id"])
    alice_root = _comment(client, headers, "alice root")
    bob_reply = _comment(client, bob_headers, "bob under alice", parent_id=alice_root["id"])
    _comment(client, carol_headers, "carol under bob's reply", parent_id=bob_reply["id"])
    carol_reply = _comment(client, carol_headers, "carol under alice", parent_id=alice_root["id"])

    _block(client, headers, bob_user["id"])

    seen = _comments(client, headers)
    assert [c["text"] for c in seen] == ["alice root"]
    assert [r["id"] for r in seen[0]["replies"]] == [carol_reply["id"]]

    # and the other way: bob no longer sees alice's thread, nor his reply in it
    assert [c["text"] for c in _comments(client, bob_headers)] == ["bob root"]

    # a third party still sees everything
    carol_view = _comments(client, carol_headers)
    assert sorted(c["text"] for c in carol_view) == ["alice root", "bob root"]


def test_reply_to_blocked_users_comment_404s_both_ways(client, alice, bob):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    alice_comment = _comment(client, headers, "alice")
    bob_comment = _comment(client, bob_headers, "bob")
    _block(client, headers, bob_user["id"])

    for viewer, parent in ((headers, bob_comment), (bob_headers, alice_comment)):
        r = client.post(
            "/comments", json={**FILM, "title": "Heat", "text": "hi", "parent_id": parent["id"]}, headers=viewer
        )
        assert r.status_code == 404
        assert r.json()["detail"] == "Parent comment not found"  # same as a missing comment


def test_reviews_hidden_both_ways(client, alice, bob, carol):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    _, carol_headers = carol
    _review(client, alice_user, headers)
    _review(client, bob_user, bob_headers)
    _block(client, headers, bob_user["id"])

    def authors(viewer: dict) -> list[str]:
        return sorted(r["username"] for r in client.get("/media/reviews", params=FILM, headers=viewer).json())

    assert authors(headers) == ["alice"]
    assert authors(bob_headers) == ["bob"]
    assert authors(carol_headers) == ["alice", "bob"]


def test_unblock_makes_everything_visible_again(client, alice, bob):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    _comment(client, bob_headers, "bob root")
    _review(client, bob_user, bob_headers)
    _block(client, headers, bob_user["id"])
    client.delete(f"/users/{bob_user['id']}/block", headers=headers)

    assert client.get(f"/users/{bob_user['id']}", headers=headers).status_code == 200
    assert client.get(f"/users/{alice_user['id']}", headers=bob_headers).status_code == 200
    assert [c["text"] for c in _comments(client, headers)] == ["bob root"]
    assert len(client.get("/media/reviews", params=FILM, headers=headers).json()) == 1
    assert client.post(f"/users/{bob_user['id']}/follow", headers=headers).status_code == 204


# ---------- cleanup and export ----------


@pytest.mark.parametrize("deleted", ["blocker", "blocked"])
def test_account_deletion_removes_block_rows_on_both_sides(client, alice, bob, deleted):
    alice_user, headers = alice
    bob_user, _ = bob
    _block(client, headers, bob_user["id"])
    hard_delete(alice_user["id"] if deleted == "blocker" else bob_user["id"])
    assert _block_rows() == []


def test_export_lists_my_blocked_users_only(client, alice, bob, carol, tmp_path):
    alice_user, headers = alice
    bob_user, _ = bob
    carol_user, carol_headers = carol
    _block(client, headers, bob_user["id"])
    _block(client, carol_headers, alice_user["id"])  # a block against alice isn't hers to export

    with SessionLocal() as db:
        archive = build_export(db.get(User, alice_user["id"]), db)
    with py7zr.SevenZipFile(io.BytesIO(archive), "r") as zf:
        zf.extractall(path=tmp_path)
    social = json.loads((tmp_path / "social.json").read_text(encoding="utf-8"))
    assert [b["username"] for b in social["blocked_users"]] == ["bob"]
    assert social["blocked_users"][0]["blocked_at"]
