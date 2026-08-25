#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:50.106302
Revised: 2026/08/24 15:31:01.810896

Reviews: whitelist-gated create, edit/delete own, one-per-title,
ownership, and the admin whitelist toggle.
"""

import pytest
from conftest import ADMIN_BASIC as BASIC

from renar_backend.database import SessionLocal
from renar_backend.models import ReviewWhitelist, User

pytestmark = pytest.mark.regression


def _whitelist(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.add(ReviewWhitelist(user_id=user_id))
        db.commit()
    finally:
        db.close()


def _post_review(client, headers, **overrides) -> dict:
    params = {"media_type": "film", "tmdb_id": 949, "title": "Heat"}
    params.update(overrides)
    payload = {"text": "A genuine masterpiece.", "rating": 95}
    r = client.post("/media/reviews", params=params, json=payload, headers=headers)
    return r


def test_non_whitelisted_user_cannot_post_review(client, alice):
    _, headers = alice
    r = _post_review(client, headers)
    assert r.status_code == 403


def test_whitelisted_user_can_create_edit_delete_own_review(client, alice):
    user, headers = alice
    _whitelist(user["id"])

    r = _post_review(client, headers)
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["mine"] is True
    assert review["rating"] == 95

    r = client.patch(f"/media/reviews/{review['id']}", json={"text": "Revised opinion.", "rating": 80}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["rating"] == 80

    assert client.delete(f"/media/reviews/{review['id']}", headers=headers).status_code == 204


def test_one_review_per_title_enforced(client, alice):
    user, headers = alice
    _whitelist(user["id"])
    _post_review(client, headers)
    r = _post_review(client, headers)
    assert r.status_code == 409


def test_others_can_read_but_not_edit_or_delete(client, alice, bob):
    alice_user, a_headers = alice
    _, b_headers = bob
    _whitelist(alice_user["id"])
    review = _post_review(client, a_headers).json()

    listed = client.get("/media/reviews", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert len(listed) == 1
    assert listed[0]["mine"] is False

    assert (
        client.patch(f"/media/reviews/{review['id']}", json={"text": "x", "rating": 1}, headers=b_headers).status_code
        == 404
    )
    assert client.delete(f"/media/reviews/{review['id']}", headers=b_headers).status_code == 404


def test_review_carries_reviewer_badge(client, alice, bob):
    alice_user, a_headers = alice
    _, b_headers = bob
    _whitelist(alice_user["id"])
    _post_review(client, a_headers)

    (listed,) = client.get("/media/reviews", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert listed["is_reviewer"] is True


def test_review_reviewer_badge_false_after_whitelist_revoked(client, alice, bob, admin_enabled):
    alice_user, a_headers = alice
    _, b_headers = bob
    _whitelist(alice_user["id"])
    _post_review(client, a_headers)

    r = client.post(f"/admin/users/{alice_user['id']}/unwhitelist-review", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    (listed,) = client.get("/media/reviews", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert listed["is_reviewer"] is False


def test_me_reports_is_reviewer_mirroring_can_review(client, alice):
    user, headers = alice
    assert client.get("/auth/me", headers=headers).json()["is_reviewer"] is False

    _whitelist(user["id"])
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_reviewer"] is True
    assert me["is_reviewer"] == me["can_review"]


def test_admin_whitelist_toggle_round_trip(client, alice, admin_enabled):
    user, headers = alice
    r = client.post(f"/admin/users/{user['id']}/whitelist-review", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    r = _post_review(client, headers)
    assert r.status_code == 201, r.text

    db = SessionLocal()
    try:
        assert db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user["id"]).count() == 1
    finally:
        db.close()

    r = client.post(f"/admin/users/{user['id']}/unwhitelist-review", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    me = client.get("/auth/me", headers=headers).json()
    assert me["can_review"] is False


def test_delete_account_removes_reviews_and_whitelist(client, alice):
    from conftest import hard_delete

    from renar_backend.models import Review

    user, headers = alice
    _whitelist(user["id"])
    _post_review(client, headers)

    hard_delete(user["id"])

    db = SessionLocal()
    try:
        assert db.query(Review).count() == 0
        assert db.query(ReviewWhitelist).count() == 0
        assert db.get(User, user["id"]) is None
    finally:
        db.close()
