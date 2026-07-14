#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.847810
Revised: 2026/07/10 18:15:03.483025

Admin panel: HTTP Basic gate and the user-delete action.
"""

from conftest import ADMIN_BASIC as BASIC
from conftest import PASSWORD

from xoutaim_backend.database import SessionLocal
from xoutaim_backend.models import Comment, CommentLike, CommentReport, LibraryEntry, LoginEvent, Notification, User


def test_admin_unavailable_until_configured(client):
    r = client.get("/admin", auth=BASIC)
    assert r.status_code == 503


def test_admin_wrong_credentials_unauthorized(client, admin_enabled):
    assert client.get("/admin", auth=("root", "wrong")).status_code == 401
    assert client.get("/admin").status_code == 401


def test_admin_dashboard_and_user_list(client, admin_enabled, alice):
    assert client.get("/admin", auth=BASIC).status_code == 200
    r = client.get("/admin/users", auth=BASIC)
    assert r.status_code == 200
    assert "alice" in r.text


def test_admin_delete_user_removes_all_data(client, admin_enabled, alice):
    user, headers = alice
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat"},
        headers=headers,
    )
    db = SessionLocal()
    try:
        db.add(Notification(user_id=user["id"], title="t", body="b"))
        db.commit()
    finally:
        db.close()

    r = client.post(f"/admin/users/{user['id']}/delete", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(User, user["id"]) is None
        assert db.query(LibraryEntry).count() == 0
        assert db.query(Notification).count() == 0
    finally:
        db.close()


def test_admin_delete_missing_user_not_found(client, admin_enabled):
    r = client.post("/admin/users/9999/delete", auth=BASIC)
    assert r.status_code == 404


def test_admin_user_list_shows_usage_stats(client, admin_enabled, alice):
    r = client.get("/admin/users", auth=BASIC)
    assert r.status_code == 200
    for column in ("Logins", "Requests", "Last login", "Last active"):
        assert column in r.text


def test_admin_user_list_links_to_detail(client, admin_enabled, alice):
    user, _ = alice
    r = client.get("/admin/users", auth=BASIC)
    assert f'href="/admin/users/{user["id"]}"' in r.text


# ---------- admin account actions ----------


def test_admin_edit_username(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/edit", data={"username": "renamed"}, auth=BASIC, follow_redirects=False)
    assert r.status_code == 303
    assert "renamed" in client.get("/admin/users", auth=BASIC).text


def test_admin_edit_username_conflict(client, admin_enabled, alice, bob):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/edit", data={"username": "bob"}, auth=BASIC)
    assert r.status_code == 409


def test_admin_edit_email(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/edit", data={"email": "moved@example.com"}, auth=BASIC)
    assert r.status_code in (200, 303)


def test_admin_edit_email_invalid_rejected(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/edit", data={"email": "not-an-email"}, auth=BASIC)
    assert r.status_code == 422


def test_admin_set_password_takes_effect(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(
        f"/admin/users/{user['id']}/password", data={"new_password": "brandnew99"}, auth=BASIC, follow_redirects=False
    )
    assert r.status_code == 303
    assert client.post("/auth/login", data={"username": "alice", "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", data={"username": "alice", "password": "brandnew99"}).status_code == 200


def test_admin_set_password_too_short_rejected(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/password", data={"new_password": "short"}, auth=BASIC)
    assert r.status_code == 422


def test_admin_edit_unknown_user_not_found(client, admin_enabled):
    assert client.post("/admin/users/9999/edit", data={"username": "x"}, auth=BASIC).status_code == 404
    assert (
        client.post("/admin/users/9999/password", data={"new_password": "longenough1"}, auth=BASIC).status_code == 404
    )


def test_admin_account_actions_require_auth(client, admin_enabled, alice):
    user, _ = alice
    assert client.post(f"/admin/users/{user['id']}/edit", data={"username": "x"}).status_code == 401
    assert client.post(f"/admin/users/{user['id']}/password", data={"new_password": "longenough1"}).status_code == 401


# ---------- per-user detail / stats page ----------


def test_admin_user_detail_requires_auth(client, admin_enabled, alice):
    user, _ = alice
    assert client.get(f"/admin/users/{user['id']}").status_code == 401


def test_admin_user_detail_renders_charts(client, admin_enabled, alice):
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers)
    client.post("/comments", json={"media_type": "film", "title": "Heat", "text": "great"}, headers=headers)

    r = client.get(f"/admin/users/{user['id']}", auth=BASIC)
    assert r.status_code == 200
    for section in (
        "Connections per day",
        "Watches per day",
        "Comments per day",
        "Library adds per day",
        "Library by type",
        "Library by status",
    ):
        assert section in r.text
    assert user["username"] in r.text


def test_admin_user_detail_has_requests_per_day_and_actions(client, admin_enabled, alice):
    user, headers = alice
    client.get("/auth/me", headers=headers)  # generate request usage
    r = client.get(f"/admin/users/{user['id']}", auth=BASIC)
    assert r.status_code == 200
    # requests show as a per-day chart, with a link to the endpoint breakdown page;
    # no per-endpoint list lives on this page
    assert "Requests per day" in r.text
    assert "Requests by endpoint" not in r.text
    assert f"/admin/users/{user['id']}/endpoints" in r.text
    assert "/admin/usage/endpoint?" not in r.text
    # account-action controls
    assert "Account actions" in r.text
    assert f'action="/admin/users/{user["id"]}/edit"' in r.text
    assert f'action="/admin/users/{user["id"]}/password"' in r.text


def test_admin_user_detail_unknown_not_found(client, admin_enabled):
    assert client.get("/admin/users/9999", auth=BASIC).status_code == 404


def test_admin_delete_user_removes_login_events(client, admin_enabled, alice):
    user, _ = alice  # fixture login created one event
    db = SessionLocal()
    try:
        assert db.query(LoginEvent).count() == 1
    finally:
        db.close()

    r = client.post(f"/admin/users/{user['id']}/delete", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.query(LoginEvent).count() == 0
    finally:
        db.close()


# ---------- comment manager ----------


def _post_comment(client, headers, text: str) -> dict:
    r = client.post(
        "/comments",
        json={"media_type": "film", "title": "Heat", "text": text},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_admin_comments_requires_auth(client, admin_enabled):
    assert client.get("/admin/comments").status_code == 401


def test_admin_comments_page_shows_text(client, admin_enabled, alice):
    _, headers = alice
    _post_comment(client, headers, "an amazing heist movie")

    r = client.get("/admin/comments", auth=BASIC)
    assert r.status_code == 200
    assert "an amazing heist movie" in r.text
    assert "alice" in r.text


def test_admin_comments_filter_by_user(client, admin_enabled, alice, bob):
    alice_user, alice_headers = alice
    _, bob_headers = bob
    _post_comment(client, alice_headers, "from alice")
    _post_comment(client, bob_headers, "from bob")

    r = client.get(f"/admin/comments?user_id={alice_user['id']}", auth=BASIC)
    assert r.status_code == 200
    assert "from alice" in r.text
    assert "from bob" not in r.text


def test_admin_comments_filter_unknown_user_not_found(client, admin_enabled):
    assert client.get("/admin/comments?user_id=9999", auth=BASIC).status_code == 404


def test_admin_delete_comment_removes_comment_and_likes(client, admin_enabled, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers, "soon to be gone")
    assert client.post(f"/comments/{comment['id']}/like", headers=bob_headers).status_code == 204

    r = client.post(f"/admin/comments/{comment['id']}/delete", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.query(Comment).count() == 0
        assert db.query(CommentLike).count() == 0
    finally:
        db.close()


def test_admin_delete_missing_comment_not_found(client, admin_enabled):
    assert client.post("/admin/comments/9999/delete", auth=BASIC).status_code == 404


def test_admin_comments_page_shows_report_count(client, admin_enabled, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    comment = _post_comment(client, alice_headers, "reported comment")
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204

    r = client.get("/admin/comments", auth=BASIC)
    assert r.status_code == 200
    assert "Reports" in r.text
    assert "&#x2691; 1" in r.text


def test_admin_delete_user_removes_filed_reports(client, admin_enabled, alice, bob):
    _, alice_headers = alice
    bob_user, bob_headers = bob
    comment = _post_comment(client, alice_headers, "flagged by bob")
    assert client.post(f"/comments/{comment['id']}/report", headers=bob_headers).status_code == 204

    r = client.post(f"/admin/users/{bob_user['id']}/delete", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.query(CommentReport).count() == 0  # bob's report went with him
        assert db.query(Comment).count() == 1  # alice's comment stays
    finally:
        db.close()
