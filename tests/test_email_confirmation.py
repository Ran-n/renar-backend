#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 13:10:00.000000
Revised: 2026/07/21 09:51:08.297553

Registration/email-change confirmation codes (users/email_confirmation.py,
routers/auth.py's /auth/confirm-email + /auth/resend-confirmation) and the
ranking-exploit fix they unblock (routers/stats.py._compute_ranking only
counting email_confirmed users). conftest.register()/make_user() auto-confirm
for the rest of the suite (see conftest._confirm_email) — these tests
register through the API directly to exercise the unconfirmed path itself.
"""

from datetime import timedelta

import pytest
from conftest import ADMIN_BASIC as BASIC
from conftest import PASSWORD

from renar_backend.database import SessionLocal
from renar_backend.models import AppCounters, EmailConfirmationCode, SiteSettings, User, utcnow
from renar_backend.users import email_confirmation as ec

CODE = "424242"

# Every required field save_settings needs, minus the toggles under test —
# matches test_admin.py's payload shape.
_BASE_SETTINGS_PAYLOAD = {
    "registration_open": "1",
    "rate_limit_per_minute": "600",
    "flood_ban_per_minute": "2000",
    "auth_rate_limit_per_minute": "30",
    "register_per_hour_per_ip": "20",
    "login_backoff_threshold": "5",
    "login_backoff_account_threshold": "30",
    "login_backoff_minutes": "15",
    "probe_ban_threshold": "12",
    "probe_window_minutes": "10",
    "ban_minutes": "60",
    "strike_ban_threshold": "5",
    "tmdb_db_cache_hours": "24",
}


@pytest.fixture
def fixed_code(monkeypatch):
    """create_and_send_code calls generate_code() unqualified from inside its
    own module — patching the module attribute intercepts that call, so
    tests can know the plaintext code without ever seeing the (bcrypt-hashed)
    DB row's real value."""
    monkeypatch.setattr(ec, "generate_code", lambda: CODE)
    return CODE


def _raw_register(client, username: str = "alice", email: str | None = None) -> dict:
    r = client.post(
        "/auth/register",
        json={"username": username, "email": email or f"{username}@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _set_created_at(user_id: int, when) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).created_at = when
        db.commit()
    finally:
        db.close()


def _get_user(user_id: int) -> User | None:
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if u is not None:
            db.expunge(u)
        return u
    finally:
        db.close()


# ---------- register creates a pending code ----------


def test_register_creates_unconfirmed_user_with_pending_code(client):
    user = _raw_register(client)
    assert _get_user(user["id"]).email_confirmed is False

    db = SessionLocal()
    try:
        codes = db.query(EmailConfirmationCode).filter(EmailConfirmationCode.user_id == user["id"]).all()
    finally:
        db.close()
    assert len(codes) == 1
    assert codes[0].purpose == "register"
    assert codes[0].consumed_at is None


# ---------- confirm-email ----------


def test_confirm_email_with_correct_code_confirms(client, fixed_code):
    user = _raw_register(client)
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"
    assert _get_user(user["id"]).email_confirmed is True


def test_confirm_email_wrong_code_increments_attempts_and_fails(client, fixed_code):
    user = _raw_register(client)
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "000000"})
    assert r.status_code == 400
    assert _get_user(user["id"]).email_confirmed is False

    db = SessionLocal()
    try:
        code = db.query(EmailConfirmationCode).filter(EmailConfirmationCode.user_id == user["id"]).first()
        assert code.attempts == 1
    finally:
        db.close()


def test_confirm_email_expired_code_rejected(client, fixed_code):
    user = _raw_register(client)
    db = SessionLocal()
    try:
        code = db.query(EmailConfirmationCode).filter(EmailConfirmationCode.user_id == user["id"]).first()
        code.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_confirm_email_too_many_attempts_burns_code(client, fixed_code):
    user = _raw_register(client)
    for _ in range(ec.MAX_ATTEMPTS):
        r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "000000"})
        assert r.status_code == 400
    # even the RIGHT code no longer works — the row was burned, not just the attempt
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    assert r.status_code == 400
    assert "attempts" in r.json()["detail"].lower() or "new code" in r.json()["detail"].lower()
    assert _get_user(user["id"]).email_confirmed is False


def test_confirm_email_wrong_password_401(client, fixed_code):
    _raw_register(client)
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": "wrong-password", "code": fixed_code})
    assert r.status_code == 401


def test_confirm_email_no_pending_confirmation_400(client, fixed_code):
    _raw_register(client)
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    assert r.status_code == 200
    # already confirmed, prior code consumed — nothing left to confirm
    r2 = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    assert r2.status_code == 400


# ---------- resend-confirmation ----------


def test_resend_confirmation_invalidates_prior_code(client, monkeypatch):
    codes_issued = iter(["111111", "222222"])
    monkeypatch.setattr(ec, "generate_code", lambda: next(codes_issued))
    user = _raw_register(client)

    r = client.post("/auth/resend-confirmation", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 204

    db = SessionLocal()
    try:
        rows = (
            db.query(EmailConfirmationCode)
            .filter(EmailConfirmationCode.user_id == user["id"])
            .order_by(EmailConfirmationCode.created_at)
            .all()
        )
    finally:
        db.close()
    assert len(rows) == 2
    assert rows[0].consumed_at is not None  # the register code was invalidated
    assert rows[1].consumed_at is None

    # the OLD code no longer works even though it was never wrong/expired
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "111111"})
    assert r.status_code == 400
    # the NEW one does
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "222222"})
    assert r.status_code == 200


def test_resend_confirmation_throttled_after_limit(client, fixed_code, monkeypatch):
    monkeypatch.setattr(ec.settings, "abuse_guard_enabled", True)
    _raw_register(client)
    for _ in range(ec.RESEND_LIMIT):
        r = client.post("/auth/resend-confirmation", json={"username": "alice", "password": PASSWORD})
        assert r.status_code == 204
    r = client.post("/auth/resend-confirmation", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_resend_confirmation_already_confirmed_400(client, fixed_code):
    _raw_register(client)
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    r = client.post("/auth/resend-confirmation", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 400


# ---------- change-unconfirmed-email (fixing a typo before first confirm) ----------


def test_change_unconfirmed_email_before_first_confirm(client, monkeypatch):
    codes_issued = iter(["111111", "222222"])
    monkeypatch.setattr(ec, "generate_code", lambda: next(codes_issued))
    user = _raw_register(client, "alice", email="typo@example.com")

    r = client.post(
        "/auth/change-unconfirmed-email",
        json={"username": "alice", "password": PASSWORD, "email": "Fixed@Example.com"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "fixed@example.com"  # normalized
    assert _get_user(user["id"]).email == "fixed@example.com"

    # the OLD code (sent to the typo'd address) is dead; the new one confirms
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "111111"})
    assert r.status_code == 400
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "222222"})
    assert r.status_code == 200
    assert _get_user(user["id"]).email_confirmed is True


def test_change_unconfirmed_email_rejects_once_confirmed(client, fixed_code):
    _raw_register(client)
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    r = client.post(
        "/auth/change-unconfirmed-email",
        json={"username": "alice", "password": PASSWORD, "email": "somewhere-else@example.com"},
    )
    assert r.status_code == 400


def test_change_unconfirmed_email_rejects_mid_two_step_change(client, monkeypatch):
    codes_issued = iter(["111111", "222222"])
    monkeypatch.setattr(ec, "generate_code", lambda: next(codes_issued))
    _raw_register(client)
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "111111"})
    headers = {
        "Authorization": "Bearer "
        + client.post("/auth/login", data={"username": "alice", "password": PASSWORD}).json()["access_token"]
    }
    client.patch("/auth/profile", json={"email": "changed@example.com"}, headers=headers)
    # pending_email is now set — the quick-edit shortcut must defer to the
    # two-step flow, not let a bare password redirect the account's email
    r = client.post(
        "/auth/change-unconfirmed-email",
        json={"username": "alice", "password": PASSWORD, "email": "attacker-picked@example.com"},
    )
    assert r.status_code == 400


def test_change_unconfirmed_email_rejects_taken_address(client, fixed_code):
    _raw_register(client, "alice")
    _raw_register(client, "bob")
    r = client.post(
        "/auth/change-unconfirmed-email",
        json={"username": "alice", "password": PASSWORD, "email": "bob@example.com"},
    )
    assert r.status_code == 409


# ---------- login grace period ----------


def test_login_within_grace_period_succeeds_unconfirmed(client):
    _raw_register(client)
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200


def test_login_after_grace_period_blocked(client):
    user = _raw_register(client)
    _set_created_at(user["id"], utcnow() - timedelta(days=ec.EMAIL_CONFIRMATION_GRACE_DAYS + 1))
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["detail"] == "email_not_confirmed"


def test_login_after_grace_period_succeeds_once_confirmed(client, fixed_code):
    user = _raw_register(client)
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    _set_created_at(user["id"], utcnow() - timedelta(days=ec.EMAIL_CONFIRMATION_GRACE_DAYS + 1))
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200


# ---------- grandfathering (accounts that predate this feature) ----------


def _set_grandfathered(user_id: int, value: bool = True) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).email_confirmation_grandfathered = value
        db.commit()
    finally:
        db.close()


def test_grandfathered_account_never_blocked_at_login(client):
    """Regression: an account whose created_at already predates the grace
    period at the moment this feature was migrated in must never be blocked
    — see migration ffffe2b24717's docstring for the bug this prevents
    (measuring grace from created_at would give a pre-existing user base
    zero actual grace period on rollout day)."""
    user = _raw_register(client)
    _set_grandfathered(user["id"])
    _set_created_at(user["id"], utcnow() - timedelta(days=365))  # far past any grace period
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200


def test_non_grandfathered_account_still_blocked_at_login(client):
    """The exemption must be per-account, not a global bypass — a freshly
    registered account (grandfathered=False, the default) is still gated
    normally."""
    user = _raw_register(client)
    _set_created_at(user["id"], utcnow() - timedelta(days=365))
    r = client.post("/auth/login", data={"username": "alice", "password": PASSWORD})
    assert r.status_code == 403


def test_grandfathered_account_still_excluded_from_ranking_until_confirmed(client):
    """Grandfathering exempts the login block and cleanup, not the ranking
    filter — the whole point of the feature is who counts on the
    leaderboard, and that's unaffected by when the account was created."""
    user = _raw_register(client)
    _set_grandfathered(user["id"])
    headers = _login_headers(client, "alice")
    db = SessionLocal()
    try:
        db.get(User, user["id"]).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()
    r = client.get("/stats/ranking", headers=headers).json()
    assert r["total_users"] == 0  # still not confirmed — doesn't count


def test_cleanup_exempts_grandfathered_accounts(client):
    user = _raw_register(client)
    _set_grandfathered(user["id"])
    _set_created_at(user["id"], utcnow() - timedelta(days=ec.CLEANUP_AFTER_DAYS + 1))

    db = SessionLocal()
    try:
        removed = ec.cleanup_unconfirmed_accounts(db)
    finally:
        db.close()
    assert removed == 0
    assert _get_user(user["id"]) is not None


def test_cleanup_still_removes_non_grandfathered_stale_accounts(client):
    user = _raw_register(client)  # grandfathered=False (default) — a real new signup
    _set_created_at(user["id"], utcnow() - timedelta(days=ec.CLEANUP_AFTER_DAYS + 1))

    db = SessionLocal()
    try:
        removed = ec.cleanup_unconfirmed_accounts(db)
    finally:
        db.close()
    assert removed == 1
    assert _get_user(user["id"]) is None


# ---------- email normalization ----------


def test_email_normalization_case_insensitive_duplicate(client):
    _raw_register(client, "alice", email="Alice@Example.com")
    r = client.post(
        "/auth/register",
        json={"username": "alice2", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 409

    db = SessionLocal()
    try:
        stored = db.query(User).filter(User.username == "alice").first()
        assert stored.email == "alice@example.com"
    finally:
        db.close()


# ---------- two-step email change ----------


def test_email_change_two_step_flow(client, monkeypatch):
    codes_issued = iter(["111111", "222222", "333333"])
    monkeypatch.setattr(ec, "generate_code", lambda: next(codes_issued))
    user = _raw_register(client)
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "111111"})
    headers = {
        "Authorization": "Bearer "
        + client.post("/auth/login", data={"username": "alice", "password": PASSWORD}).json()["access_token"]
    }
    assert _get_user(user["id"]).email_confirmed is True

    r = client.patch("/auth/profile", json={"email": "alice-new@example.com"}, headers=headers)
    assert r.status_code == 200
    changed = _get_user(user["id"])
    assert changed.email == "alice@example.com"  # not swapped yet
    assert changed.pending_email == "alice-new@example.com"
    assert changed.email_confirmed is False  # revoked until the new address re-proves ownership

    # step 1: the OLD address authorizes the change
    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "222222"})
    assert r.status_code == 200
    assert r.json()["status"] == "change_pending_new_email"
    mid = _get_user(user["id"])
    assert mid.email == "alice@example.com"  # still not swapped
    assert mid.email_confirmed is False

    # step 2: the NEW address confirms itself — a third code was generated
    # (change_authorize's own confirm call above already scheduled it)
    db = SessionLocal()
    try:
        latest = (
            db.query(EmailConfirmationCode)
            .filter(EmailConfirmationCode.user_id == user["id"], EmailConfirmationCode.consumed_at.is_(None))
            .order_by(EmailConfirmationCode.created_at.desc())
            .first()
        )
        assert latest.purpose == "change_confirm"
    finally:
        db.close()

    r = client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": "333333"})
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"
    final = _get_user(user["id"])
    assert final.email == "alice-new@example.com"
    assert final.pending_email is None
    assert final.email_confirmed is True


# ---------- ranking exclusion (the actual exploit fix) ----------


def test_ranking_excludes_unconfirmed_users(client, fixed_code):
    alice = _raw_register(client, "alice")
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    alice_headers = _login_headers(client, "alice")

    bob = _raw_register(client, "bob")  # never confirmed — the throwaway-account case
    bob_headers = _login_headers(client, "bob")

    db = SessionLocal()
    try:
        for uid in (alice["id"], bob["id"]):
            db.get(User, uid).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()

    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 500},
        headers=bob_headers,
    )

    r = client.get("/stats/ranking", headers=alice_headers).json()
    # bob's 500 minutes would outrank alice's 0 if counted — but bob is
    # unconfirmed, so alice is #1 of 1, not #2 of 2.
    assert r["total_users"] == 1
    assert r["rank"] == 1

    db = SessionLocal()
    try:
        assert db.get(AppCounters, 1).total_users == 1
    finally:
        db.close()


def _login_headers(client, username: str) -> dict:
    r = client.post("/auth/login", data={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_ranking_counter_increments_when_user_confirms(client, fixed_code):
    _raw_register(client, "alice")
    db = SessionLocal()
    try:
        before = db.get(AppCounters, 1).total_users
    finally:
        db.close()
    assert before == 0

    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})

    db = SessionLocal()
    try:
        after = db.get(AppCounters, 1).total_users
    finally:
        db.close()
    assert after == 1


# ---------- account deletion with a pending code ----------


def test_self_delete_with_pending_confirmation_code_does_not_fkey_violate(client):
    """Regression: accounts.delete_account must clear EmailConfirmationCode
    rows before deleting the user, same as every other FK'd table — a fresh
    registration always has one pending row, so this is the common case, not
    an edge case."""
    user = _raw_register(client)
    headers = _login_headers(client, "alice")
    r = client.delete("/auth/me", headers=headers)
    assert r.status_code == 204
    assert _get_user(user["id"]) is None


# ---------- cleanup loop ----------


def test_cleanup_removes_stale_unconfirmed_accounts(client):
    user = _raw_register(client)
    _set_created_at(user["id"], utcnow() - timedelta(days=ec.CLEANUP_AFTER_DAYS + 1))

    db = SessionLocal()
    try:
        removed = ec.cleanup_unconfirmed_accounts(db)
    finally:
        db.close()
    assert removed == 1
    assert _get_user(user["id"]) is None


def test_cleanup_keeps_confirmed_accounts_regardless_of_age(client, fixed_code):
    user = _raw_register(client)
    client.post("/auth/confirm-email", json={"username": "alice", "password": PASSWORD, "code": fixed_code})
    _set_created_at(user["id"], utcnow() - timedelta(days=ec.CLEANUP_AFTER_DAYS + 1))

    db = SessionLocal()
    try:
        removed = ec.cleanup_unconfirmed_accounts(db)
    finally:
        db.close()
    assert removed == 0
    assert _get_user(user["id"]) is not None


def test_cleanup_keeps_recent_unconfirmed_accounts(client):
    _raw_register(client)  # created "now" — well within CLEANUP_AFTER_DAYS
    db = SessionLocal()
    try:
        removed = ec.cleanup_unconfirmed_accounts(db)
    finally:
        db.close()
    assert removed == 0


# ---------- admin kill switch (email_confirmation_enabled) ----------


def _set_email_confirmation_enabled(client, enabled: bool) -> None:
    payload = dict(_BASE_SETTINGS_PAYLOAD)
    if enabled:
        payload["email_confirmation_enabled"] = "1"
    r = client.post("/admin/settings", data=payload, auth=BASIC, follow_redirects=False)
    assert r.status_code == 303, r.text


def test_new_registration_auto_confirmed_when_feature_disabled(client, admin_enabled):
    _set_email_confirmation_enabled(client, False)
    user = _raw_register(client)
    assert _get_user(user["id"]).email_confirmed is True

    db = SessionLocal()
    try:
        codes = db.query(EmailConfirmationCode).filter(EmailConfirmationCode.user_id == user["id"]).count()
    finally:
        db.close()
    assert codes == 0  # no code created/sent — nothing to confirm


def test_disabling_feature_bulk_confirms_existing_unconfirmed_users(client, admin_enabled):
    user = _raw_register(client)  # feature still on by default — starts unconfirmed
    assert _get_user(user["id"]).email_confirmed is False

    before = SessionLocal()
    try:
        counter_before = before.get(AppCounters, 1).total_users
    finally:
        before.close()
    assert counter_before == 0

    _set_email_confirmation_enabled(client, False)

    assert _get_user(user["id"]).email_confirmed is True
    after = SessionLocal()
    try:
        assert after.get(AppCounters, 1).total_users == 1  # trigger fired for the bulk UPDATE too
    finally:
        after.close()


def test_reenabling_feature_does_not_unconfirm_bulk_confirmed_users(client, admin_enabled):
    user = _raw_register(client)
    _set_email_confirmation_enabled(client, False)
    assert _get_user(user["id"]).email_confirmed is True

    _set_email_confirmation_enabled(client, True)
    assert _get_user(user["id"]).email_confirmed is True  # not retroactively re-locked

    db = SessionLocal()
    try:
        assert db.get(SiteSettings, 1).email_confirmation_enabled is True
    finally:
        db.close()
