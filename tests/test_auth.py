#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.984505
Revised: 2026/07/16 13:37:27.159098

Auth endpoints: register, login, me, profile, password change, account delete.
"""

import secrets
from datetime import UTC, datetime, timedelta

from conftest import PASSWORD, login, register

from renar_backend.database import SessionLocal
from renar_backend.models import (
    Comment,
    CommentReport,
    EpisodeWatch,
    InviteCode,
    LibraryEntry,
    LoginEvent,
    SiteSettings,
    User,
    WatchEvent,
)

# ---------- register ----------


def test_register_returns_user_without_password(client):
    user = register(client, "alice")
    assert user["username"] == "alice"
    assert user["email"] == "alice@example.com"
    assert user["avatar"] is None
    assert user["language"] == "en"
    assert "password" not in user
    assert "password_hash" not in user


def test_register_duplicate_username_conflicts(client):
    register(client, "alice")
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "other@example.com", "password": PASSWORD},
    )
    assert r.status_code == 409


def test_register_duplicate_email_conflicts(client):
    register(client, "alice")
    r = client.post(
        "/auth/register",
        json={"username": "alice2", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 409


def test_register_short_password_rejected(client):
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "short"},
    )
    assert r.status_code == 422


def test_register_password_over_72_bytes_rejected(client):
    # bcrypt 5.x raises on >72-byte input; must be a 422, never a 500
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": "x" * 73},
    )
    assert r.status_code == 422


def test_register_bad_email_rejected(client):
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "not-an-email", "password": PASSWORD},
    )
    assert r.status_code == 422


# ---------- registration_open and invite_only (site_settings) ----------


def _set_site_settings(**kwargs):
    """Directly write site_settings fields for test setup."""
    db = SessionLocal()
    try:
        row = db.get(SiteSettings, 1)
        if row is None:
            row = SiteSettings(id=1, registration_open=True, invite_only=False)
            db.add(row)
        for k, v in kwargs.items():
            setattr(row, k, v)
        db.commit()
    finally:
        db.close()


def _make_invite(max_uses=1, uses=0, revoked=False, expires_at=None) -> str:
    code = secrets.token_urlsafe(10)
    db = SessionLocal()
    try:
        db.add(
            InviteCode(
                code=code,
                created_by_user_id=None,
                max_uses=max_uses,
                uses=uses,
                expires_at=expires_at,
                revoked=revoked,
            )
        )
        db.commit()
    finally:
        db.close()
    return code


def test_registration_status_defaults(client):
    r = client.get("/auth/registration-status")
    assert r.status_code == 200
    assert r.json() == {"registration_open": True, "invite_only": False}


def test_registration_status_reflects_invite_only(client):
    _set_site_settings(invite_only=True, registration_open=False)
    r = client.get("/auth/registration-status")
    assert r.status_code == 200
    assert r.json() == {"registration_open": False, "invite_only": True}


def test_registration_closed_returns_403(client):
    _set_site_settings(registration_open=False)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 403


def test_invite_only_missing_code_returns_400(client):
    _set_site_settings(invite_only=True, registration_open=True)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 400
    assert "invite code" in r.json()["detail"].lower()


def test_invite_only_invalid_code_returns_400(client):
    _set_site_settings(invite_only=True, registration_open=True)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": "bogus"},
    )
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower()


def test_invite_only_revoked_code_returns_400(client):
    code = _make_invite(revoked=True)
    _set_site_settings(invite_only=True, registration_open=True)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": code},
    )
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower()


def test_invite_only_expired_code_returns_400(client):
    past = datetime.now(UTC) - timedelta(hours=1)
    code = _make_invite(expires_at=past)
    _set_site_settings(invite_only=True, registration_open=True)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": code},
    )
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_invite_only_exhausted_code_returns_400(client):
    code = _make_invite(max_uses=1, uses=1)
    _set_site_settings(invite_only=True, registration_open=True)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": code},
    )
    assert r.status_code == 400
    assert "used" in r.json()["detail"].lower()


def test_invite_only_valid_code_registers_and_increments_uses(client):
    code = _make_invite(max_uses=2)
    _set_site_settings(invite_only=True, registration_open=True)
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": code},
    )
    assert r.status_code == 201

    db = SessionLocal()
    try:
        row = db.query(InviteCode).filter(InviteCode.code == code).first()
        assert row.uses == 1
    finally:
        db.close()


def test_invite_only_single_use_code_exhausted_after_one_registration(client):
    code = _make_invite(max_uses=1)
    _set_site_settings(invite_only=True, registration_open=True)
    r1 = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": code},
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": PASSWORD, "invite_code": code},
    )
    assert r2.status_code == 400


def test_invite_only_unlimited_code_never_exhausts(client):
    code = _make_invite(max_uses=None)
    _set_site_settings(invite_only=True, registration_open=True)
    for username in ("alice", "bob", "carol"):
        r = client.post(
            "/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": PASSWORD,
                "invite_code": code,
            },
        )
        assert r.status_code == 201

    db = SessionLocal()
    try:
        row = db.query(InviteCode).filter(InviteCode.code == code).first()
        assert row.uses == 3
        assert row.max_uses is None
    finally:
        db.close()


# ---------- login ----------


def test_login_with_username(client):
    register(client, "alice")
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_with_email(client):
    register(client, "alice")
    r = client.post("/auth/login", data={"username": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 200


def test_login_wrong_password_unauthorized(client):
    register(client, "alice")
    r = client.post("/auth/login", data={"username": "alice", "password": "wrongwrong"})
    assert r.status_code == 401


def test_login_unknown_user_unauthorized(client):
    r = client.post("/auth/login", data={"username": "ghost", "password": PASSWORD})
    assert r.status_code == 401


def test_login_over_72_byte_password_unauthorized_not_500(client):
    # bcrypt.checkpw raises ValueError on long input; must map to 401
    register(client, "alice")
    r = client.post("/auth/login", data={"username": "alice", "password": "x" * 100})
    assert r.status_code == 401


# ---------- me / tokens ----------


def test_me_returns_current_user(client, alice):
    user, headers = alice
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == user["id"]


def test_me_without_token_unauthorized(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_garbage_token_unauthorized(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


# ---------- profile ----------


def test_update_profile_username(client, alice):
    _, headers = alice
    r = client.patch("/auth/profile", json={"username": "alice2"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice2"


def test_update_profile_taken_username_conflicts(client, alice, bob):
    _, headers = alice
    r = client.patch("/auth/profile", json={"username": "bob"}, headers=headers)
    assert r.status_code == 409


def test_update_profile_taken_email_conflicts(client, alice, bob):
    _, headers = alice
    r = client.patch("/auth/profile", json={"email": "bob@example.com"}, headers=headers)
    assert r.status_code == 409


def test_update_profile_invalid_avatar_rejected(client, alice):
    _, headers = alice
    r = client.patch("/auth/profile", json={"avatar_b64": "bm90IGFuIGltYWdl"}, headers=headers)
    assert r.status_code == 422


def test_update_profile_language(client, alice):
    _, headers = alice
    r = client.patch("/auth/profile", json={"language": "gl"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["language"] == "gl"
    # persists across requests, not just echoed back
    assert client.get("/auth/me", headers=headers).json()["language"] == "gl"


def test_update_profile_invalid_language_rejected(client, alice):
    _, headers = alice
    r = client.patch("/auth/profile", json={"language": "not-a-lang-code!"}, headers=headers)
    assert r.status_code == 422


# ---------- change password ----------


def test_change_password_roundtrip(client, alice):
    _, headers = alice
    r = client.post(
        "/auth/change_password",
        json={"current_password": PASSWORD, "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 204
    old = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert old.status_code == 401
    login(client, "alice", "newpassword456")


def test_change_password_wrong_current_unauthorized(client, alice):
    _, headers = alice
    r = client.post(
        "/auth/change_password",
        json={"current_password": "wrongwrong", "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 401


def test_change_password_over_72_bytes_rejected(client, alice):
    _, headers = alice
    r = client.post(
        "/auth/change_password",
        json={"current_password": PASSWORD, "new_password": "x" * 73},
        headers=headers,
    )
    assert r.status_code == 422


# ---------- delete account ----------


def test_delete_account_removes_user_and_library(client, alice):
    _, headers = alice
    item = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26},
        headers=headers,
    ).json()
    client.put(f"/media/{item['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{item['id']}/rewatch", json={}, headers=headers)

    assert client.delete("/auth/me", headers=headers).status_code == 204
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 401

    db = SessionLocal()
    try:
        assert db.query(LibraryEntry).count() == 0
        assert db.query(EpisodeWatch).count() == 0
        assert db.query(WatchEvent).count() == 0
    finally:
        db.close()


def test_deleted_account_token_is_invalid(client, alice):
    _, headers = alice
    client.delete("/auth/me", headers=headers)
    assert client.get("/auth/me", headers=headers).status_code == 401


def _comment(client, headers, text="hi", parent_id=None) -> dict:
    r = client.post(
        "/comments",
        json={"media_type": "film", "title": "Heat", "text": text, "parent_id": parent_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_delete_account_with_replies_from_others(client, alice, bob):
    """Another user's reply hangs off my comment: deleting my account must
    delete the whole thread (reply subtree), not crash on the parent_id FK."""
    _, a_headers = alice
    bob_user, b_headers = bob
    mine = _comment(client, a_headers)
    _comment(client, b_headers, text="reply from bob", parent_id=mine["id"])

    assert client.delete("/auth/me", headers=a_headers).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(Comment).count() == 0  # bob's reply fell with the subtree
        assert db.get(User, bob_user["id"]) is not None
    finally:
        db.close()


def test_delete_account_with_reports_on_my_comments(client, alice, bob):
    """Someone reported my comment: deleting my account must drop the report
    with the comment, not crash on the comment_id FK."""
    _, a_headers = alice
    _, b_headers = bob
    mine = _comment(client, a_headers)
    assert client.post(f"/comments/{mine['id']}/report", json={"reason": "spam"}, headers=b_headers).status_code == 204

    assert client.delete("/auth/me", headers=a_headers).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(CommentReport).count() == 0
    finally:
        db.close()


def test_delete_account_after_reporting_others(client, alice, bob):
    """I reported someone else's comment: deleting my account must drop my
    report but leave their comment alone."""
    _, a_headers = alice
    bob_user, b_headers = bob
    bobs = _comment(client, b_headers)
    assert client.post(f"/comments/{bobs['id']}/report", json={"reason": "spam"}, headers=a_headers).status_code == 204

    assert client.delete("/auth/me", headers=a_headers).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(CommentReport).count() == 0
        assert db.query(Comment).filter(Comment.user_id == bob_user["id"]).count() == 1
    finally:
        db.close()


# ---------- usage statistics ----------


def _user_row(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.get(User, user_id)
    finally:
        db.close()


def test_login_updates_usage_stats(client):
    user = register(client, "alice")
    login(client)
    login(client)

    row = _user_row(user["id"])
    assert row.last_active_at is not None


def test_login_records_login_event(client):
    user = register(client, "alice")
    login(client)
    login(client)

    db = SessionLocal()
    try:
        assert db.query(LoginEvent).filter(LoginEvent.user_id == user["id"]).count() == 2
    finally:
        db.close()


def test_failed_login_records_no_event(client):
    user = register(client, "alice")
    client.post("/auth/login", data={"username": "alice", "password": "wrong-password-1"})

    db = SessionLocal()
    try:
        assert db.query(LoginEvent).filter(LoginEvent.user_id == user["id"]).count() == 0
    finally:
        db.close()


def test_delete_account_removes_login_events(client, alice):
    user, headers = alice  # fixture logged in once -> one event
    assert client.delete("/auth/me", headers=headers).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(LoginEvent).count() == 0
    finally:
        db.close()


def test_authenticated_request_bumps_activity(client, alice):
    user, headers = alice

    assert client.get("/auth/me", headers=headers).status_code == 200

    row = _user_row(user["id"])
    assert row.last_active_at is not None
