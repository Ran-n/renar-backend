#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.984505
Revised: 2026/09/02 10:57:36.960211

Auth endpoints: register, login, me, profile, password change, account delete.
"""

import base64
import io
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSWORD, hard_delete, login, register
from PIL import Image as PILImage
from sqlalchemy.exc import IntegrityError

from renar_backend.database import SessionLocal
from renar_backend.models import (
    Comment,
    CommentReport,
    EmailConfirmationCode,
    EpisodeWatch,
    ImportJob,
    InviteCode,
    LibraryEntry,
    LoginEvent,
    SiteSettings,
    User,
    WatchEvent,
    utcnow,
)

pytestmark = pytest.mark.regression

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
    assert r.json() == {
        "registration_open": True,
        "invite_only": False,
        "turnstile_site_key": None,
        "email_confirmation_enabled": True,
    }


def test_registration_status_reflects_invite_only(client):
    _set_site_settings(invite_only=True, registration_open=False)
    r = client.get("/auth/registration-status")
    assert r.status_code == 200
    assert r.json() == {
        "registration_open": False,
        "invite_only": True,
        "turnstile_site_key": None,
        "email_confirmation_enabled": True,
    }


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


def test_login_username_with_nul_byte_unauthorized_not_500(client):
    # Postgres text columns reject NUL bytes outright — filtering by one
    # unguarded would otherwise be an unhandled DataError (500), not a
    # normal login rejection (found by tests/test_fuzz.py).
    r = client.post("/auth/login", data={"username": "alice\x00", "password": PASSWORD})
    assert r.status_code == 401


def test_register_username_with_nul_byte_rejected_not_500(client):
    r = client.post(
        "/auth/register",
        json={"username": "alice\x00", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 422


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
    assert r.status_code == 200
    assert r.json()["access_token"]
    old = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert old.status_code == 401
    login(client, "alice", "newpassword456")


def test_change_password_invalidates_previously_issued_token(client, alice):
    """A token issued before the password change must stop working — even
    though it hasn't expired — since it's exactly the kind of leaked/stolen
    credential a password change is meant to invalidate."""
    _, headers = alice
    r = client.post(
        "/auth/change_password",
        json={"current_password": PASSWORD, "new_password": "newpassword456"},
        headers=headers,
    )
    assert r.status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 401

    new_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=new_headers).status_code == 200


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
    user, headers = alice
    item = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26},
        headers=headers,
    ).json()
    client.put(f"/media/{item['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{item['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    hard_delete(user["id"])
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
    user, headers = alice
    hard_delete(user["id"])
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_self_delete_is_soft_and_does_not_remove_library(client, alice):
    """DELETE /auth/me now starts a grace period (see
    test_account_deletion.py) rather than purging immediately — the account,
    its token, and its library must all remain fully intact right after."""
    _, headers = alice
    item = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26},
        headers=headers,
    ).json()

    assert client.delete("/auth/me", headers=headers).status_code == 204
    assert client.get(f"/media/{item['id']}", headers=headers).status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["deletion_requested_at"] is not None


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
    alice_user, a_headers = alice
    bob_user, b_headers = bob
    mine = _comment(client, a_headers)
    _comment(client, b_headers, text="reply from bob", parent_id=mine["id"])

    hard_delete(alice_user["id"])

    db = SessionLocal()
    try:
        assert db.query(Comment).count() == 0  # bob's reply fell with the subtree
        assert db.get(User, bob_user["id"]) is not None
    finally:
        db.close()


def test_delete_account_with_reports_on_my_comments(client, alice, bob):
    """Someone reported my comment: deleting my account must drop the report
    with the comment, not crash on the comment_id FK."""
    alice_user, a_headers = alice
    _, b_headers = bob
    mine = _comment(client, a_headers)
    assert client.post(f"/comments/{mine['id']}/report", json={"reason": "spam"}, headers=b_headers).status_code == 204

    hard_delete(alice_user["id"])

    db = SessionLocal()
    try:
        assert db.query(CommentReport).count() == 0
    finally:
        db.close()


def test_delete_account_after_reporting_others(client, alice, bob):
    """I reported someone else's comment: deleting my account must drop my
    report but leave their comment alone."""
    alice_user, a_headers = alice
    bob_user, b_headers = bob
    bobs = _comment(client, b_headers)
    assert client.post(f"/comments/{bobs['id']}/report", json={"reason": "spam"}, headers=a_headers).status_code == 204

    hard_delete(alice_user["id"])

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


def test_activity_touch_throttled_within_interval(client):
    user = register(client, "alice")
    headers = login(client)
    client.get("/auth/me", headers=headers)
    first = _user_row(user["id"]).last_active_at

    client.get("/auth/me", headers=headers)
    second = _user_row(user["id"]).last_active_at
    assert second == first  # within the throttle window, no new write


def test_activity_touch_fires_again_after_interval(client):
    user = register(client, "alice")
    headers = login(client)
    client.get("/auth/me", headers=headers)

    db = SessionLocal()
    try:
        db.get(User, user["id"]).last_active_at = datetime.now(UTC) - timedelta(minutes=20)
        db.commit()
    finally:
        db.close()
    stale = _user_row(user["id"]).last_active_at

    client.get("/auth/me", headers=headers)
    refreshed = _user_row(user["id"]).last_active_at
    assert refreshed > stale


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
    hard_delete(user["id"])

    db = SessionLocal()
    try:
        assert db.query(LoginEvent).count() == 0
    finally:
        db.close()


def test_delete_account_with_import_job_row_does_not_fkey_violate(client, alice):
    """Regression: accounts.delete_account must DELETE the import_jobs row
    before deleting the user — the FK is NOT NULL and has no DB-level
    ON DELETE CASCADE, so the plain db.delete(user) call that existed before
    pass-1 would crash with a FK violation for any user who had ever started
    a TV Time import."""
    user, headers = alice
    db = SessionLocal()
    try:
        db.add(ImportJob(user_id=user["id"], kind="tvtime", finished=True))
        db.commit()
    finally:
        db.close()

    hard_delete(user["id"])

    db = SessionLocal()
    try:
        assert db.query(ImportJob).filter(ImportJob.user_id == user["id"]).count() == 0
    finally:
        db.close()


def test_delete_account_nulls_out_created_invite_codes(client, alice):
    """Regression: accounts.delete_account must NULL the invite_codes.created_by_user_id
    FK before deleting the user — the FK is nullable (codes outlive their creator),
    but a plain db.delete(user) with no prior NULL-out crashes when the FK is set."""
    user, headers = alice
    db = SessionLocal()
    try:
        db.add(InviteCode(code="TESTCODE123", created_by_user_id=user["id"], max_uses=5))
        db.commit()
    finally:
        db.close()

    hard_delete(user["id"])

    db = SessionLocal()
    try:
        code = db.query(InviteCode).filter(InviteCode.code == "TESTCODE123").first()
        assert code is not None  # the code is preserved (still valid for others)
        assert code.created_by_user_id is None  # FK nulled, not deleted
    finally:
        db.close()


def test_authenticated_request_bumps_activity(client, alice):
    user, headers = alice

    assert client.get("/auth/me", headers=headers).status_code == 200

    row = _user_row(user["id"])
    assert row.last_active_at is not None


# ---------- banned account (auth.py lines 315, 354) ----------


def _ban_user(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).banned = True
        db.commit()
    finally:
        db.close()


def test_login_banned_account_returns_403(client):
    """Banned users are rejected at login with 403 (line 315 in auth.py)."""
    user = register(client, "alice")
    _ban_user(user["id"])
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 403
    assert "banned" in r.json()["detail"].lower()


def test_confirm_email_banned_user_returns_403(client):
    """_authenticate_for_confirmation also checks banned (line 354 in auth.py)."""
    db = SessionLocal()
    try:
        # Register without auto-confirm so the account needs confirmation.
        r = client.post(
            "/auth/register",
            json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
        )
        assert r.status_code == 201
        user_id = r.json()["id"]
        _ban_user(user_id)
    finally:
        db.close()

    r = client.post(
        "/auth/confirm-email",
        json={"username": "alice", "password": PASSWORD, "code": "000000"},
    )
    assert r.status_code == 403
    assert "banned" in r.json()["detail"].lower()


# ---------- register IntegrityError race (lines 268-272) ----------


def test_register_race_condition_returns_409(client, monkeypatch):
    """Two registrations that race past the duplicate-check SELECT both land
    the same 409 — the IntegrityError path inside register (lines 268-272)."""
    import sqlalchemy.orm

    original_commit = sqlalchemy.orm.Session.commit
    call_count = [0]

    def _raise_on_user_commit(self):
        call_count[0] += 1
        # Allow the first commit (site_settings creation) and raise on the
        # second (User row insert) to simulate the race condition.
        if call_count[0] >= 2:
            sqlalchemy.orm.Session.commit = original_commit
            raise IntegrityError("", {}, Exception("duplicate"))
        return original_commit(self)

    monkeypatch.setattr(sqlalchemy.orm.Session, "commit", _raise_on_user_commit)

    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 409


# ---------- unknown confirmation purpose (lines 402-407) ----------


def test_confirm_email_unknown_purpose_returns_400(client):
    """An EmailConfirmationCode row with an unknown purpose field results in
    a 400 error (the else branch at lines 402-407 in auth.py)."""
    from renar_backend.users.email_confirmation import hash_code

    # Register without auto-confirm.
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201
    user_id = r.json()["id"]

    CODE = "424242"

    db = SessionLocal()
    try:
        db.add(
            EmailConfirmationCode(
                user_id=user_id,
                code_hash=hash_code(CODE),
                purpose="unknown_purpose",
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/auth/confirm-email",
        json={"username": "alice", "password": PASSWORD, "code": CODE},
    )
    assert r.status_code == 400
    assert "unknown" in r.json()["detail"].lower()


# ---------- resend_confirmation with pending_email (lines 512-521) ----------


def _set_user_attrs(user_id: int, **attrs) -> None:
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        for k, v in attrs.items():
            setattr(u, k, v)
        db.commit()
    finally:
        db.close()


def test_resend_confirmation_with_pending_email_change_confirm(client, alice):
    """When user has pending_email and latest code is change_confirm, resend
    sends change_confirm again (branch 519 in auth.py)."""
    from renar_backend.users.email_confirmation import hash_code

    user, headers = alice

    # Simulate a pending email-change at the change_confirm stage:
    # pending_email is set, latest unconsumed code has purpose=change_confirm.
    _set_user_attrs(user["id"], pending_email="new@example.com", email_confirmed=False)

    db = SessionLocal()
    try:
        db.add(
            EmailConfirmationCode(
                user_id=user["id"],
                code_hash=hash_code("424242"),
                purpose="change_confirm",
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/auth/resend-confirmation",
        json={"username": "alice", "password": PASSWORD},
    )
    assert r.status_code == 204


def test_resend_confirmation_with_pending_email_change_authorize(client):
    """When user has pending_email and latest code is NOT change_confirm, resend
    sends change_authorize to the original address (branch 521 in auth.py)."""
    # Register (creates a "register" code automatically).
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201
    user_id = r.json()["id"]

    # Simulate a pending email-change: pending_email set, latest code is "register" not "change_confirm".
    _set_user_attrs(user_id, pending_email="pending@example.com")

    r = client.post(
        "/auth/resend-confirmation",
        json={"username": "alice", "password": PASSWORD},
    )
    assert r.status_code == 204


# ---------- update_profile email change (lines 576->585) ----------


def test_update_profile_email_change_initiates_two_step_flow(client, alice):
    """Changing email to a new non-taken address starts the two-step
    change_authorize/change_confirm flow: pending_email is set (lines 582-584)."""
    user, headers = alice
    r = client.patch("/auth/profile", json={"email": "newalice@example.com"}, headers=headers)
    assert r.status_code == 200
    # The email field itself hasn't moved yet; pending_email is set.
    db = SessionLocal()
    try:
        u = db.get(User, user["id"])
        assert u.pending_email == "newalice@example.com"
        assert not u.email_confirmed
    finally:
        db.close()


# ---------- update_profile avatar (lines 594, 595->598) ----------


def _png_b64_auth(color: tuple[int, int, int] = (200, 30, 30)) -> str:
    img = PILImage.new("RGB", (20, 30), color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def _set_premium_auth(user_id: int, days: int = 30) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=days)
        db.commit()
    finally:
        db.close()


def test_update_profile_clear_avatar(client, alice):
    """Setting avatar_b64 to empty string clears the avatar (lines 594-598 in
    auth.py — avatar_b64 present but falsy → user.avatar_id = None)."""
    _, headers = alice
    # First set an avatar.
    r = client.patch("/auth/profile", json={"avatar_b64": _png_b64_auth()}, headers=headers)
    assert r.status_code == 200
    assert r.json()["avatar"] is not None
    # Then clear it.
    r = client.patch("/auth/profile", json={"avatar_b64": ""}, headers=headers)
    assert r.status_code == 200
    assert r.json()["avatar"] is None


# ---------- update_profile background (lines 599-613) ----------


def test_update_profile_background_without_premium_returns_403(client, alice):
    """Non-premium user cannot set a background image (lines 599-602)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"background_b64": _png_b64_auth()}, headers=headers)
    assert r.status_code == 403
    assert "premium" in r.json()["detail"].lower()


def test_update_profile_background_with_premium(client, alice):
    """Premium user can set then clear a background image (lines 603-613)."""
    user, headers = alice
    _set_premium_auth(user["id"])
    r = client.patch("/auth/profile", json={"background_b64": _png_b64_auth()}, headers=headers)
    assert r.status_code == 200
    assert r.json()["background"] is not None
    # Clear it.
    r = client.patch("/auth/profile", json={"background_b64": ""}, headers=headers)
    assert r.status_code == 200
    assert r.json()["background"] is None


# ---------- update_profile theme (lines 615-620) ----------


def test_update_profile_premium_theme_without_premium_returns_403(client, alice):
    """Non-premium user cannot set a premium theme (lines 615-620)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"theme": "midnight"}, headers=headers)
    assert r.status_code == 403
    assert "premium" in r.json()["detail"].lower()


def test_update_profile_free_theme_allowed(client, alice):
    """gruvbox is a free theme — no premium needed."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"theme": "gruvbox"}, headers=headers)
    assert r.status_code == 200


# ---------- update_profile other fields (622, 624, 626) ----------


def test_update_profile_show_original_titles(client, alice):
    """show_original_titles can be toggled without premium (line 622)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"show_original_titles": True}, headers=headers)
    assert r.status_code == 200
    assert r.json()["show_original_titles"] is True


def test_update_profile_home_hero_enabled(client, alice):
    """home_hero_enabled can be toggled (line 624)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"home_hero_enabled": False}, headers=headers)
    assert r.status_code == 200
    assert r.json()["home_hero_enabled"] is False


def test_update_profile_home_on_launch(client, alice):
    """home_on_launch can be toggled (line 626)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"home_on_launch": False}, headers=headers)
    assert r.status_code == 200
    assert r.json()["home_on_launch"] is False


# ---------- update_profile progress_style (lines 628-633) ----------


def test_update_profile_premium_progress_style_without_premium_returns_403(client, alice):
    """Non-premium user cannot set a premium progress style (lines 628-632)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"home_progress_style": "capsule"}, headers=headers)
    assert r.status_code == 403
    assert "premium" in r.json()["detail"].lower()


def test_update_profile_free_progress_style_allowed(client, alice):
    """'rings' is the free progress style (line 633)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"home_progress_style": "rings"}, headers=headers)
    assert r.status_code == 200


# ---------- update_profile episode_label_style (lines 635-640) ----------


def test_update_profile_premium_episode_label_without_premium_returns_403(client, alice):
    """Non-premium user cannot set a premium episode label style (lines 635-639)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"episode_label_style": "standard"}, headers=headers)
    assert r.status_code == 403
    assert "premium" in r.json()["detail"].lower()


def test_update_profile_free_episode_label_allowed(client, alice):
    """'cross' is the free episode label style (line 640)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"episode_label_style": "cross"}, headers=headers)
    assert r.status_code == 200


# ---------- update_profile has_seen_welcome (line 642) ----------


def test_update_profile_has_seen_welcome(client, alice):
    """has_seen_welcome can be set to True (line 642 in auth.py)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"has_seen_welcome": True}, headers=headers)
    assert r.status_code == 200
    assert r.json()["has_seen_welcome"] is True


def test_banned_account_token_rejected_with_403(client, alice):
    """A token issued before a ban is rejected with 403 on subsequent authenticated
    requests — covers auth.py get_current_user's banned branch (line 105)."""
    user, headers = alice
    with SessionLocal() as db:
        db.get(User, user["id"]).banned = True
        db.commit()
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 403
    assert "banned" in r.json()["detail"].lower()


def test_profile_update_invalid_theme_rejected(client, alice):
    """An unrecognized theme name must be 422 — covers schemas.ProfileUpdate
    _valid_theme's ValueError branch (lines 324-326)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"theme": "neon_flamingo"}, headers=headers)
    assert r.status_code == 422


def test_profile_update_invalid_progress_style_rejected(client, alice):
    """An unrecognized home_progress_style must be 422 — covers
    _valid_progress_style (lines 331-333)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"home_progress_style": "not_a_style"}, headers=headers)
    assert r.status_code == 422


def test_profile_update_invalid_episode_label_style_rejected(client, alice):
    """An unrecognized episode_label_style must be 422 — covers
    _valid_episode_label_style (lines 338-340)."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"episode_label_style": "not_a_style"}, headers=headers)
    assert r.status_code == 422
