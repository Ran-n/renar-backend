#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:21:53.369566
Revised: 2026/11/22 01:52:27.914560

Reporting reviews and profiles to the moderators: report/unreport,
`reported_by_me`, cleanup on review and account deletion, and the two admin
pages that list the reports.
"""

import logging

import pytest
from conftest import hard_delete
from sqlalchemy.exc import IntegrityError

from renar_backend.database import SessionLocal
from renar_backend.models import ReviewReport, ReviewWhitelist, UserReport
from renar_backend.social import reports

FILM = {"media_type": "film", "tmdb_id": 949}
SECRET_REASON = "spoilers and insults"


@pytest.fixture
def carol(make_user):
    return make_user("carol")


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


def _listed_review(client, headers) -> dict:
    return client.get("/media/reviews", params=FILM, headers=headers).json()[0]


def _count(model) -> int:
    with SessionLocal() as db:
        return db.query(model).count()


# ---------- reviews ----------


def test_review_report_roundtrip_flips_reported_by_me(client, alice, bob):
    alice_user, headers = alice
    _, bob_headers = bob
    review = _review(client, alice_user, headers)
    assert review["reported_by_me"] is False
    path = f"/media/reviews/{review['id']}/report"

    assert client.post(path, json={"reason": f"  {SECRET_REASON}  "}, headers=bob_headers).status_code == 204
    assert _listed_review(client, bob_headers)["reported_by_me"] is True
    assert _listed_review(client, headers)["reported_by_me"] is False  # the author never sees who reported
    with SessionLocal() as db:
        assert db.query(ReviewReport).one().reason == SECRET_REASON  # stripped

    assert client.delete(path, headers=bob_headers).status_code == 204
    assert _listed_review(client, bob_headers)["reported_by_me"] is False
    assert _count(ReviewReport) == 0


def test_review_report_is_idempotent_and_reason_is_optional(client, alice, bob):
    alice_user, headers = alice
    _, bob_headers = bob
    review = _review(client, alice_user, headers)
    path = f"/media/reviews/{review['id']}/report"
    assert client.post(path, headers=bob_headers).status_code == 204
    assert client.post(path, headers=bob_headers).status_code == 204
    assert _count(ReviewReport) == 1
    assert client.delete(path, headers=bob_headers).status_code == 204
    assert client.delete(path, headers=bob_headers).status_code == 204


def test_review_report_own_review_rejected(client, alice):
    user, headers = alice
    review = _review(client, user, headers)
    r = client.post(f"/media/reviews/{review['id']}/report", headers=headers)
    assert r.status_code == 400
    assert _count(ReviewReport) == 0


def test_review_report_unknown_review_and_auth(client, alice):
    _, headers = alice
    assert client.post("/media/reviews/9999/report", headers=headers).status_code == 404
    assert client.delete("/media/reviews/9999/report", headers=headers).status_code == 204
    assert client.post("/media/reviews/1/report").status_code == 401
    assert client.delete("/media/reviews/1/report").status_code == 401


def test_review_report_reason_too_long_rejected(client, alice, bob):
    alice_user, headers = alice
    _, bob_headers = bob
    review = _review(client, alice_user, headers)
    r = client.post(f"/media/reviews/{review['id']}/report", json={"reason": "x" * 501}, headers=bob_headers)
    assert r.status_code == 422


def test_deleting_a_review_deletes_its_reports(client, alice, bob):
    alice_user, headers = alice
    _, bob_headers = bob
    review = _review(client, alice_user, headers)
    client.post(f"/media/reviews/{review['id']}/report", headers=bob_headers)
    assert client.delete(f"/media/reviews/{review['id']}", headers=headers).status_code == 204
    assert _count(ReviewReport) == 0


# ---------- profiles ----------


def test_user_report_roundtrip_flips_reported_by_me(client, alice, bob):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    path = f"/users/{bob_user['id']}/report"
    assert client.get(f"/users/{bob_user['id']}", headers=headers).json()["reported_by_me"] is False

    assert client.post(path, json={"reason": SECRET_REASON}, headers=headers).status_code == 204
    assert client.get(f"/users/{bob_user['id']}", headers=headers).json()["reported_by_me"] is True
    # per reporter, and visible in list endpoints too
    assert client.get("/users/search", params={"q": "bob"}, headers=headers).json()[0]["reported_by_me"] is True
    assert client.get(f"/users/{alice_user['id']}", headers=bob_headers).json()["reported_by_me"] is False

    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(f"/users/{bob_user['id']}", headers=headers).json()["reported_by_me"] is False


def test_user_report_is_idempotent(client, alice, bob):
    _, headers = alice
    bob_user, _ = bob
    path = f"/users/{bob_user['id']}/report"
    assert client.post(path, headers=headers).status_code == 204
    assert client.post(path, headers=headers).status_code == 204
    assert _count(UserReport) == 1
    assert client.delete(path, headers=headers).status_code == 204
    assert client.delete(path, headers=headers).status_code == 204


def test_user_report_self_unknown_and_auth(client, alice):
    user, headers = alice
    r = client.post(f"/users/{user['id']}/report", headers=headers)
    assert r.status_code == 400
    assert client.post("/users/9999/report", headers=headers).status_code == 404
    assert client.delete("/users/9999/report", headers=headers).status_code == 204
    assert client.post(f"/users/{user['id']}/report").status_code == 401
    assert _count(UserReport) == 0


def test_user_report_across_a_block_is_404(client, alice, bob):
    """A blocked profile looks like a missing one everywhere, reports included."""
    _, headers = alice
    bob_user, bob_headers = bob
    alice_user, _ = alice
    client.post(f"/users/{bob_user['id']}/block", headers=headers)
    assert client.post(f"/users/{bob_user['id']}/report", headers=headers).status_code == 404
    assert client.post(f"/users/{alice_user['id']}/report", headers=bob_headers).status_code == 404


# ---------- account deletion ----------


def test_account_deletion_removes_reports_by_and_about_the_user(client, alice, bob, carol):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    carol_user, carol_headers = carol
    alice_review = _review(client, alice_user, headers)
    carol_review = _review(client, carol_user, carol_headers)
    # about alice: her review and her profile, both reported by bob
    client.post(f"/media/reviews/{alice_review['id']}/report", headers=bob_headers)
    client.post(f"/users/{alice_user['id']}/report", headers=bob_headers)
    # by alice: carol's review and bob's profile
    client.post(f"/media/reviews/{carol_review['id']}/report", headers=headers)
    client.post(f"/users/{bob_user['id']}/report", headers=headers)
    # unrelated to alice: must survive
    client.post(f"/media/reviews/{carol_review['id']}/report", headers=bob_headers)
    client.post(f"/users/{carol_user['id']}/report", headers=bob_headers)

    hard_delete(alice_user["id"])

    with SessionLocal() as db:
        assert [(r.review_id, r.reporter_id) for r in db.query(ReviewReport)] == [(carol_review["id"], bob_user["id"])]
        assert [(r.reported_user_id, r.reporter_id) for r in db.query(UserReport)] == [
            (carol_user["id"], bob_user["id"])
        ]


# ---------- logging and races ----------


def test_reports_are_logged_with_ids_never_the_reason(client, alice, bob, caplog):
    alice_user, headers = alice
    bob_user, bob_headers = bob
    review = _review(client, alice_user, headers)
    with caplog.at_level(logging.INFO, logger="renar_backend.social.reports"):
        client.post(f"/media/reviews/{review['id']}/report", json={"reason": SECRET_REASON}, headers=bob_headers)
        client.post(f"/users/{alice_user['id']}/report", json={"reason": SECRET_REASON}, headers=bob_headers)
        client.delete(f"/users/{alice_user['id']}/report", headers=bob_headers)
    messages = [r.getMessage() for r in caplog.records]
    assert f"review_reports: {review['id']} reported by user {bob_user['id']}" in messages
    assert f"user_reports: {alice_user['id']} reported by user {bob_user['id']}" in messages
    assert f"user_reports: report on {alice_user['id']} retracted by user {bob_user['id']}" in messages
    assert SECRET_REASON not in caplog.text


def test_concurrent_report_keeps_the_first(alice, bob, monkeypatch, caplog):
    alice_user, _ = alice
    bob_user, _ = bob
    with SessionLocal() as db:

        def _lose_the_race():
            raise IntegrityError("insert", {}, Exception("uq_user_report"))

        monkeypatch.setattr(db, "commit", _lose_the_race)
        with caplog.at_level(logging.INFO, logger="renar_backend.social.reports"):
            stored = reports.add_report(
                db,
                UserReport,
                UserReport.reported_user_id,
                bob_user["id"],
                UserReport.reporter_id,
                alice_user["id"],
                "",
            )
    assert stored is False
    assert "kept the first" in caplog.text


# ---------- admin pages ----------


def test_admin_reported_reviews_page_shows_count_reasons_and_delete(client, admin_enabled, alice, bob, carol):
    alice_user, headers = alice
    _, bob_headers = bob
    _, carol_headers = carol
    review = _review(client, alice_user, headers)
    client.post(f"/media/reviews/{review['id']}/report", json={"reason": "<b>rude</b>"}, headers=bob_headers)
    client.post(f"/media/reviews/{review['id']}/report", headers=carol_headers)

    page = client.get("/admin/reported-reviews", headers=admin_enabled)
    assert page.status_code == 200
    assert "&#x2691; 2" in page.text
    assert "alice" in page.text and "Heat" in page.text
    assert "&lt;b&gt;rude&lt;/b&gt;" in page.text and "<b>rude</b>" not in page.text  # reasons are escaped

    r = client.post(
        f"/admin/reported-reviews/{review['id']}/delete",
        data={"reason": "harassment"},
        headers=admin_enabled,
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert _count(ReviewReport) == 0
    assert client.get("/media/reviews", params=FILM, headers=headers).json() == []
    assert "No reported reviews" in client.get("/admin/reported-reviews", headers=admin_enabled).text
    missing = client.post(f"/admin/reported-reviews/{review['id']}/delete", headers=admin_enabled)
    assert missing.status_code == 404


def test_admin_reported_users_page_lists_user_with_count_and_link(client, admin_enabled, alice, bob, carol):
    alice_user, _ = alice
    _, bob_headers = bob
    _, carol_headers = carol
    assert "No reported users" in client.get("/admin/reported-users", headers=admin_enabled).text
    client.post(f"/users/{alice_user['id']}/report", json={"reason": "offensive avatar"}, headers=bob_headers)
    client.post(f"/users/{alice_user['id']}/report", headers=carol_headers)

    page = client.get("/admin/reported-users", headers=admin_enabled)
    assert page.status_code == 200
    assert "&#x2691; 2" in page.text
    assert "offensive avatar" in page.text
    assert f'href="/admin/users/{alice_user["id"]}"' in page.text


def test_admin_report_pages_require_admin(client, admin_enabled):
    for path in ("/admin/reported-reviews", "/admin/reported-users"):
        assert client.get(path, follow_redirects=False).status_code != 200


def test_admin_dashboard_links_both_report_pages(client, admin_enabled):
    page = client.get("/admin", headers=admin_enabled).text
    assert "/admin/reported-reviews" in page
    assert "/admin/reported-users" in page
