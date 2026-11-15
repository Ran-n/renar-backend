#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:50.106302
Revised: 2026/11/14 00:22:50.969246

Reviews: whitelist-gated create, edit/delete own, one-per-title,
ownership, and the admin whitelist toggle.
"""

import pytest

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

    r = client.post(
        f"/admin/users/{alice_user['id']}/unwhitelist-review", headers=admin_enabled, follow_redirects=False
    )
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
    r = client.post(f"/admin/users/{user['id']}/whitelist-review", headers=admin_enabled, follow_redirects=False)
    assert r.status_code == 303

    r = _post_review(client, headers)
    assert r.status_code == 201, r.text

    db = SessionLocal()
    try:
        assert db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user["id"]).count() == 1
    finally:
        db.close()

    r = client.post(f"/admin/users/{user['id']}/unwhitelist-review", headers=admin_enabled, follow_redirects=False)
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


# ---------- like / dislike ----------


def _reviewed(client, alice) -> tuple[dict, dict]:
    """A review by alice; returns (review, alice's headers)."""
    user, headers = alice
    _whitelist(user["id"])
    r = _post_review(client, headers)
    assert r.status_code == 201, r.text
    return r.json(), headers


def _listed(client, headers) -> dict:
    r = client.get("/media/reviews", params={"media_type": "film", "tmdb_id": 949}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()[0]


def test_new_review_has_no_reactions(client, alice):
    review, headers = _reviewed(client, alice)
    for body in (review, _listed(client, headers)):
        assert (body["likes"], body["dislikes"]) == (0, 0)
        assert body["liked_by_me"] is False
        assert body["disliked_by_me"] is False


def test_review_like_unlike_roundtrip(client, alice, bob):
    """A like shows in the count for everyone and as `liked_by_me` only for
    the user who left it; un-liking removes it; repeating either is a no-op."""
    review, a = _reviewed(client, alice)
    _, b = bob
    for _ in range(2):  # the second like must not add a second row
        assert client.post(f"/media/reviews/{review['id']}/like", headers=b).status_code == 204
    assert _listed(client, b)["likes"] == 1
    assert _listed(client, b)["liked_by_me"] is True
    assert _listed(client, a)["likes"] == 1
    assert _listed(client, a)["liked_by_me"] is False
    for _ in range(2):
        assert client.delete(f"/media/reviews/{review['id']}/like", headers=b).status_code == 204
    assert _listed(client, b)["likes"] == 0
    assert _listed(client, b)["liked_by_me"] is False


def test_review_dislike_undislike_roundtrip(client, alice, bob):
    review, _ = _reviewed(client, alice)
    _, b = bob
    assert client.post(f"/media/reviews/{review['id']}/dislike", headers=b).status_code == 204
    listed = _listed(client, b)
    assert (listed["likes"], listed["dislikes"], listed["disliked_by_me"]) == (0, 1, True)
    assert client.delete(f"/media/reviews/{review['id']}/dislike", headers=b).status_code == 204
    assert _listed(client, b)["dislikes"] == 0


def test_review_like_and_dislike_are_mutually_exclusive(client, alice, bob):
    """Reacting the other way flips the one row; un-liking never retracts a
    dislike (and the reverse)."""
    review, _ = _reviewed(client, alice)
    _, b = bob
    client.post(f"/media/reviews/{review['id']}/like", headers=b)
    client.post(f"/media/reviews/{review['id']}/dislike", headers=b)
    listed = _listed(client, b)
    assert (listed["likes"], listed["dislikes"]) == (0, 1)
    assert listed["liked_by_me"] is False
    assert listed["disliked_by_me"] is True
    client.delete(f"/media/reviews/{review['id']}/like", headers=b)  # wrong kind: no-op
    assert _listed(client, b)["dislikes"] == 1
    client.post(f"/media/reviews/{review['id']}/like", headers=b)
    listed = _listed(client, b)
    assert (listed["likes"], listed["dislikes"]) == (1, 0)
    client.delete(f"/media/reviews/{review['id']}/dislike", headers=b)  # wrong kind: no-op
    assert _listed(client, b)["likes"] == 1


def test_review_reactions_count_every_user(client, alice, bob, make_user):
    review, a = _reviewed(client, alice)
    _, b = bob
    _, c = make_user("carol")
    client.post(f"/media/reviews/{review['id']}/like", headers=a)  # own review: allowed
    client.post(f"/media/reviews/{review['id']}/like", headers=b)
    client.post(f"/media/reviews/{review['id']}/dislike", headers=c)
    listed = _listed(client, a)
    assert (listed["likes"], listed["dislikes"]) == (2, 1)


def test_review_reaction_on_missing_review_not_found(client, alice):
    _, headers = alice
    assert client.post("/media/reviews/9999/like", headers=headers).status_code == 404
    assert client.post("/media/reviews/9999/dislike", headers=headers).status_code == 404
    # removing a reaction that cannot exist is a no-op, same as comments
    assert client.delete("/media/reviews/9999/like", headers=headers).status_code == 204
    assert client.delete("/media/reviews/9999/dislike", headers=headers).status_code == 204


def test_review_reactions_need_auth(client, alice):
    review, _ = _reviewed(client, alice)
    for method in (client.post, client.delete):
        for kind in ("like", "dislike"):
            assert method(f"/media/reviews/{review['id']}/{kind}").status_code == 401


def test_review_reactions_survive_edit_and_die_with_review(client, alice, bob):
    """Editing a review keeps its reactions (and returns them); deleting it
    removes their rows."""
    from renar_backend.models import ReviewLike

    review, a = _reviewed(client, alice)
    _, b = bob
    client.post(f"/media/reviews/{review['id']}/like", headers=b)
    r = client.patch(f"/media/reviews/{review['id']}", json={"text": "Still great.", "rating": 90}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["likes"] == 1
    assert client.delete(f"/media/reviews/{review['id']}", headers=a).status_code == 204
    db = SessionLocal()
    try:
        assert db.query(ReviewLike).count() == 0
    finally:
        db.close()


def test_review_like_value_constraint(client, alice, bob):
    """The table itself refuses anything but +1/-1."""
    from sqlalchemy.exc import IntegrityError

    from renar_backend.models import ReviewLike

    review, _ = _reviewed(client, alice)
    user_b, _ = bob
    db = SessionLocal()
    try:
        db.add(ReviewLike(review_id=review["id"], user_id=user_b["id"], value=5))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_review_like_concurrent_integrity_error_is_noop(client, alice, bob, monkeypatch):
    """Two simultaneous likes from one user: the loser's INSERT hits the
    unique constraint and is swallowed as "already liked" (204, no 500)."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from renar_backend.models import ReviewLike

    review, _ = _reviewed(client, alice)
    _, b = bob
    original_commit = Session.commit

    def patched_commit(self):
        if any(isinstance(obj, ReviewLike) for obj in self.new):
            raise IntegrityError("INSERT INTO review_likes", {}, Exception("unique violation"))
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", patched_commit)
    assert client.post(f"/media/reviews/{review['id']}/like", headers=b).status_code == 204


def test_delete_account_removes_review_reactions_both_ways(client, alice, bob):
    """Deleting an account removes the reactions it left on others' reviews
    and the reactions others left on its reviews (no orphan rows, no FK
    error from the bulk review delete)."""
    from conftest import hard_delete

    from renar_backend.models import Review, ReviewLike

    review, a = _reviewed(client, alice)
    user_a, _ = alice
    user_b, b = bob
    _whitelist(user_b["id"])
    r = _post_review(client, b, tmdb_id=950, title="Collateral")
    assert r.status_code == 201, r.text
    client.post(f"/media/reviews/{review['id']}/like", headers=b)  # bob on alice's
    client.post(f"/media/reviews/{r.json()['id']}/dislike", headers=a)  # alice on bob's

    hard_delete(user_a["id"])

    db = SessionLocal()
    try:
        assert db.query(ReviewLike).count() == 0
        assert db.query(Review).count() == 1
    finally:
        db.close()
