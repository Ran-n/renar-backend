#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:49.855061
Revised: 2026/08/27 09:56:07.596509

Soft-delete account deletion: DELETE /auth/me starts a grace period instead
of purging immediately (see users/accounts.py's request_deletion/
cancel_deletion/purge_expired_deletions and the account_purge periodic task).
"""

from datetime import timedelta

import pytest
from conftest import ADMIN_BASIC as BASIC
from conftest import PASSWORD, hard_delete

from renar_backend.database import SessionLocal
from renar_backend.models import SiteSettings, User, utcnow
from renar_backend.social.notifier import purge_expired_deletions_once

pytestmark = pytest.mark.regression


def _user_row(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.get(User, user_id)
    finally:
        db.close()


def test_delete_me_sets_deletion_requested_at_and_stays_usable(client, alice):
    user, headers = alice
    assert client.delete("/auth/me", headers=headers).status_code == 204

    row = _user_row(user["id"])
    assert row is not None
    assert row.deletion_requested_at is not None

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["deletion_requested_at"] is not None


def test_cancel_deletion_endpoint_clears_it(client, alice):
    user, headers = alice
    client.delete("/auth/me", headers=headers)

    r = client.post("/auth/me/cancel-deletion", headers=headers)
    assert r.status_code == 200
    assert r.json()["deletion_requested_at"] is None
    assert _user_row(user["id"]).deletion_requested_at is None


def test_logging_back_in_auto_cancels_pending_deletion(client, alice):
    user, headers = alice
    client.delete("/auth/me", headers=headers)
    assert _user_row(user["id"]).deletion_requested_at is not None

    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200
    assert _user_row(user["id"]).deletion_requested_at is None


# ---------- web-reachable deletion page (no app install required) ----------


def test_account_deletion_page_renders(client):
    r = client.get("/auth/account-deletion")
    assert r.status_code == 200
    assert "Delete your Renar account" in r.text
    assert 'action="/auth/account-deletion"' in r.text


def test_account_deletion_form_starts_grace_period(client, alice):
    user, _ = alice
    r = client.post("/auth/account-deletion", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200
    assert "Deletion requested" in r.text
    assert _user_row(user["id"]).deletion_requested_at is not None


def test_account_deletion_form_wrong_password_rejected(client, alice):
    user, _ = alice
    r = client.post("/auth/account-deletion", data={"username": "alice", "password": "wrong-password"})
    assert r.status_code == 200
    assert "Deletion requested" not in r.text
    assert _user_row(user["id"]).deletion_requested_at is None


def test_account_deletion_form_unknown_account_same_generic_error(client, alice):
    """No user enumeration: an unknown account and a wrong password for a
    real account must produce the same page."""
    known_wrong = client.post("/auth/account-deletion", data={"username": "alice", "password": "wrong-password"})
    unknown = client.post("/auth/account-deletion", data={"username": "no-such-user", "password": "wrong-password"})
    assert known_wrong.status_code == unknown.status_code == 200
    assert "Incorrect username or password" in known_wrong.text
    assert "Incorrect username or password" in unknown.text


def test_purge_removes_accounts_past_grace_period(client, alice):
    user, headers = alice
    client.delete("/auth/me", headers=headers)

    db = SessionLocal()
    try:
        row = db.get(User, user["id"])
        row.deletion_requested_at = utcnow() - timedelta(days=999)
        db.commit()
    finally:
        db.close()

    n = purge_expired_deletions_once()
    assert n == 1
    assert _user_row(user["id"]) is None


def test_purge_leaves_accounts_still_within_grace_period(client, alice):
    user, headers = alice
    client.delete("/auth/me", headers=headers)

    n = purge_expired_deletions_once()
    assert n == 0
    assert _user_row(user["id"]) is not None


def test_purge_respects_admin_configured_grace_days(client, alice):
    from renar_backend import site_settings as site_settings_mod

    db = SessionLocal()
    try:
        from renar_backend.site_settings import get_site_settings

        ss = db.get(SiteSettings, 1) or get_site_settings(db)
        ss.deletion_grace_days = 1
        db.commit()
    finally:
        db.close()
    site_settings_mod.invalidate()  # bypass the 5s TTL cache register()/login() already warmed

    user, headers = alice
    client.delete("/auth/me", headers=headers)
    db = SessionLocal()
    try:
        row = db.get(User, user["id"])
        row.deletion_requested_at = utcnow() - timedelta(days=2)
        db.commit()
    finally:
        db.close()

    n = purge_expired_deletions_once()
    assert n == 1
    assert _user_row(user["id"]) is None


def test_admin_can_cancel_a_pending_deletion(client, alice, admin_enabled):
    user, headers = alice
    client.delete("/auth/me", headers=headers)

    r = client.post(f"/admin/users/{user['id']}/cancel-deletion", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303
    assert _user_row(user["id"]).deletion_requested_at is None


def test_hard_delete_still_works_regardless_of_pending_deletion_flag(client, alice):
    """accounts.delete_account (the admin hard-delete / purge-job path) must
    still work on an account with no pending deletion at all — the flag is
    optional, not a precondition for the real purge."""
    user, _ = alice
    hard_delete(user["id"])
    assert _user_row(user["id"]) is None
