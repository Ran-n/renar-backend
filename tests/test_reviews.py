#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:50.106302
Revised: 2026/09/02 10:58:09.669589

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


def test_reviewer_ids_empty_set_returns_empty(client):
    """reviewer_ids() with an empty iterable returns set() without querying —
    covers reviews.py line 42."""
    from renar_backend.routers.reviews import reviewer_ids

    with SessionLocal() as db:
        result = reviewer_ids(db, [])
    assert result == set()


def test_list_reviews_no_tmdb_id_no_title_rejected(client, alice):
    """GET /media/reviews with neither tmdb_id nor title returns 422 —
    covers reviews.py _require_target line 49."""
    _, headers = alice
    r = client.get("/media/reviews", params={"media_type": "film"}, headers=headers)
    assert r.status_code == 422


def test_create_review_no_tmdb_id_no_title_rejected(client, alice):
    """POST /media/reviews with neither tmdb_id nor title returns 422 —
    covers reviews.py _require_target line 49 via create path."""
    user, headers = alice
    _whitelist(user["id"])
    r = client.post(
        "/media/reviews",
        params={"media_type": "film"},
        json={"text": "Great film.", "rating": 90},
        headers=headers,
    )
    assert r.status_code == 422


def test_list_reviews_unknown_title_returns_empty(client, alice):
    """GET /media/reviews for an unseen tmdb_id returns [] without error —
    covers reviews.py line 95."""
    _, headers = alice
    params = {"media_type": "film", "tmdb_id": 99999, "title": "Unknown Film"}
    r = client.get("/media/reviews", params=params, headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_create_review_tmdb_id_only_unknown_title_rejected(client, alice):
    """POST /media/reviews with tmdb_id only for an unknown title returns 422 —
    covers reviews.py _resolve_target lines 74-80."""
    user, headers = alice
    _whitelist(user["id"])
    r = client.post(
        "/media/reviews",
        params={"media_type": "film", "tmdb_id": 77777},
        json={"text": "Great film.", "rating": 90},
        headers=headers,
    )
    assert r.status_code == 422
    assert "tmdb_id" in r.json()["detail"].lower() or "title" in r.json()["detail"].lower()


def test_create_review_integrity_error_returns_409(client, alice, monkeypatch):
    """When db.commit() raises IntegrityError past the Python-level duplicate
    check, the handler returns 409 — covers reviews.py lines 129-133."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError
    from sqlalchemy.orm import Session

    user, headers = alice
    _whitelist(user["id"])

    call_count = [0]
    original_commit = Session.commit

    def patched_commit(self):
        from renar_backend.models import Review as ReviewModel

        new_reviews = [obj for obj in self.new if isinstance(obj, ReviewModel)]
        if new_reviews and call_count[0] == 0:
            call_count[0] += 1
            self.rollback()
            raise SAIntegrityError("INSERT INTO reviews", {}, Exception("unique violation"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", patched_commit)

    r = client.post(
        "/media/reviews",
        params={"media_type": "film", "tmdb_id": 949, "title": "Heat"},
        json={"text": "A genuine masterpiece.", "rating": 95},
        headers=headers,
    )
    assert r.status_code == 409


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
