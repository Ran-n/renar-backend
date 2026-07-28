#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.847810
Revised: 2026/07/17 18:08:59.133057

Admin panel: HTTP Basic gate and the user-delete action.
"""

from datetime import timedelta

from conftest import ADMIN_BASIC as BASIC
from conftest import PASSWORD

from renar_backend.database import SessionLocal
from renar_backend.models import (
    Comment,
    CommentLike,
    CommentReport,
    InviteCode,
    LibraryEntry,
    LoginEvent,
    Notification,
    PeriodicTaskRun,
    SiteSettings,
    User,
    utcnow,
)


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


def test_admin_edit_email_normalized(client, admin_enabled, alice, bob):
    """Mirrors self-service registration's normalization — an admin edit must
    not be able to create a case-variant duplicate of another account's
    email (the unique index is case-sensitive, so only app-level
    normalization catches this)."""
    alice_user, _ = alice
    bob_user, _ = bob
    r = client.post(f"/admin/users/{alice_user['id']}/edit", data={"email": "  New@Example.com  "}, auth=BASIC)
    assert r.status_code in (200, 303)
    r = client.get(f"/admin/users/{alice_user['id']}", auth=BASIC)
    assert "new@example.com" in r.text

    conflict = client.post(f"/admin/users/{bob_user['id']}/edit", data={"email": " NEW@EXAMPLE.COM "}, auth=BASIC)
    assert conflict.status_code == 409


def test_admin_edit_username_normalized(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/edit", data={"username": "  spaced  "}, auth=BASIC)
    assert r.status_code in (200, 303)
    r = client.get(f"/admin/users/{user['id']}", auth=BASIC)
    assert "spaced" in r.text
    assert "  spaced  " not in r.text


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


# ---------- site settings ----------


def test_admin_settings_page_renders(client, admin_enabled):
    r = client.get("/admin/settings", auth=BASIC)
    assert r.status_code == 200
    assert "Site Settings" in r.text
    assert "registration_open" in r.text
    # periodic-task toggles moved to their own page (see periodic tasks tests)
    assert "episode_check_enabled" not in r.text
    assert "/admin/periodic-tasks" in r.text


def test_admin_settings_page_requires_auth(client, admin_enabled):
    assert client.get("/admin/settings").status_code == 401


def test_admin_settings_post_updates_and_persists(client, admin_enabled):
    payload = {
        "registration_open": "1",
        "rate_limit_per_minute": "500",
        "flood_ban_per_minute": "1800",
        "auth_rate_limit_per_minute": "25",
        "register_per_hour_per_ip": "15",
        "login_backoff_threshold": "4",
        "login_backoff_account_threshold": "20",
        "login_backoff_minutes": "10",
        "probe_ban_threshold": "8",
        "probe_window_minutes": "7",
        "ban_minutes": "45",
        "strike_ban_threshold": "3",
        "tmdb_db_cache_hours": "24",
        # invite_only omitted → False (unchecked checkbox)
    }
    r = client.post("/admin/settings", data=payload, auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        row = db.get(SiteSettings, 1)
        assert row is not None
        assert row.rate_limit_per_minute == 500
        assert row.ban_minutes == 45
        assert row.strike_ban_threshold == 3
        assert row.invite_only is False
        assert row.registration_open is True
    finally:
        db.close()


def test_admin_settings_page_renders_exempt_ip_pills(client, admin_enabled):
    payload = {
        "registration_open": "1",
        "rate_limit_per_minute": "500",
        "flood_ban_per_minute": "1800",
        "auth_rate_limit_per_minute": "25",
        "register_per_hour_per_ip": "15",
        "login_backoff_threshold": "4",
        "login_backoff_account_threshold": "20",
        "login_backoff_minutes": "10",
        "probe_ban_threshold": "8",
        "probe_window_minutes": "7",
        "ban_minutes": "45",
        "strike_ban_threshold": "3",
        "tmdb_db_cache_hours": "24",
        "exempt_ips": "127.0.0.1, ::1",
    }
    client.post("/admin/settings", data=payload, auth=BASIC)

    r = client.get("/admin/settings", auth=BASIC)
    assert r.status_code == 200
    # one pill per exempt IP, plus the hidden field the form actually submits
    assert '<span class="tag-pill" data-ip="127.0.0.1">127.0.0.1' in r.text
    assert '<span class="tag-pill" data-ip="::1">::1' in r.text
    assert 'name="exempt_ips" value="127.0.0.1, ::1"' in r.text


def test_admin_settings_invite_only_toggle(client, admin_enabled):
    payload = {
        "registration_open": "1",
        "invite_only": "1",
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
    r = client.post("/admin/settings", data=payload, auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        row = db.get(SiteSettings, 1)
        assert row.invite_only is True
    finally:
        db.close()


# ---------- periodic tasks ----------


def test_admin_periodic_tasks_page_renders(client, admin_enabled):
    r = client.get("/admin/periodic-tasks", auth=BASIC)
    assert r.status_code == 200
    assert "Episode check" in r.text
    assert "Never run" in r.text


def test_admin_periodic_tasks_grouped_by_media_type(client, admin_enabled):
    r = client.get("/admin/periodic-tasks", auth=BASIC)
    for group in ("TV Shows", "Films", "Security"):
        assert group in r.text
    # both TV-show tasks land under the same "TV Shows" section
    tv_section = r.text.split("TV Shows", 1)[1].split("Films", 1)[0]
    assert "Episode check" in tv_section
    assert "Episode history sync" in tv_section


def test_admin_periodic_tasks_page_requires_auth(client, admin_enabled):
    assert client.get("/admin/periodic-tasks").status_code == 401


def test_admin_periodic_tasks_toggle_persists(client, admin_enabled):
    r = client.post(
        "/admin/periodic-tasks/toggle",
        data={"task_key": "film_check", "value": "0"},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        row = db.get(PeriodicTaskRun, "film_check")
        assert row.enabled is False
    finally:
        db.close()

    assert "Disabled" in client.get("/admin/periodic-tasks", auth=BASIC).text


def test_admin_periodic_tasks_toggle_is_atomized(client, admin_enabled):
    """Disabling episode_check must not disable episode_history_sync — the
    whole point of splitting them into separate task_keys."""
    from renar_backend import task_runs

    client.post(
        "/admin/periodic-tasks/toggle",
        data={"task_key": "episode_check", "value": "0"},
        auth=BASIC,
    )
    assert task_runs.is_enabled("episode_check") is False
    assert task_runs.is_enabled("episode_history_sync") is True


def test_admin_periodic_tasks_toggle_rejects_unknown_task(client, admin_enabled):
    r = client.post(
        "/admin/periodic-tasks/toggle",
        data={"task_key": "not_a_real_task", "value": "1"},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(PeriodicTaskRun, "not_a_real_task") is None
    finally:
        db.close()


def test_admin_periodic_tasks_toggle_requires_auth(client, admin_enabled):
    r = client.post("/admin/periodic-tasks/toggle", data={"task_key": "film_check", "value": "0"})
    assert r.status_code == 401


def test_admin_periodic_tasks_shows_recorded_run(client, admin_enabled):
    from renar_backend import task_runs
    from renar_backend.models import utcnow

    task_runs.record_run("episode_check", utcnow(), "ok", "3 new notifications")
    r = client.get("/admin/periodic-tasks", auth=BASIC)
    assert "3 new notifications" in r.text
    assert "OK" in r.text


def test_admin_periodic_tasks_shows_error_status(client, admin_enabled):
    from renar_backend import task_runs
    from renar_backend.models import utcnow

    task_runs.record_run("strike_cleanup", utcnow(), "error", "db timeout")
    r = client.get("/admin/periodic-tasks", auth=BASIC)
    assert "db timeout" in r.text
    assert "Error" in r.text


def test_admin_periodic_tasks_interval_persists(client, admin_enabled):
    r = client.post(
        "/admin/periodic-tasks/interval",
        data={"task_key": "episode_check", "minutes": "45"},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        row = db.get(PeriodicTaskRun, "episode_check")
        assert row.interval_minutes == 45
    finally:
        db.close()

    assert 'value="45"' in client.get("/admin/periodic-tasks", auth=BASIC).text


def test_admin_periodic_tasks_interval_is_atomized(client, admin_enabled):
    """Rescheduling episode_check must not reschedule episode_history_sync —
    each task keeps its own interval, same as its own enable flag."""
    from renar_backend import task_runs

    client.post(
        "/admin/periodic-tasks/interval",
        data={"task_key": "episode_check", "minutes": "30"},
        auth=BASIC,
    )
    assert task_runs.get_interval_minutes("episode_check") == 30
    assert task_runs.get_interval_minutes("episode_history_sync") == 360  # untouched default


def test_admin_periodic_tasks_interval_rejects_out_of_range(client, admin_enabled):
    r = client.post(
        "/admin/periodic-tasks/interval",
        data={"task_key": "film_check", "minutes": "0"},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(PeriodicTaskRun, "film_check") is None
    finally:
        db.close()


def test_admin_periodic_tasks_interval_rejects_unknown_task(client, admin_enabled):
    r = client.post(
        "/admin/periodic-tasks/interval",
        data={"task_key": "not_a_real_task", "minutes": "30"},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(PeriodicTaskRun, "not_a_real_task") is None
    finally:
        db.close()


def test_admin_periodic_tasks_interval_requires_auth(client, admin_enabled):
    r = client.post("/admin/periodic-tasks/interval", data={"task_key": "film_check", "minutes": "30"})
    assert r.status_code == 401


# ---------- invite codes ----------


def test_admin_invites_page_renders(client, admin_enabled):
    r = client.get("/admin/invites", auth=BASIC)
    assert r.status_code == 200
    assert "Invite Codes" in r.text


def test_admin_invites_page_requires_auth(client, admin_enabled):
    assert client.get("/admin/invites").status_code == 401


def test_admin_create_invite_code(client, admin_enabled):
    r = client.post(
        "/admin/invites/create",
        data={"max_uses": "3"},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        assert code is not None
        assert code.max_uses == 3
        assert code.uses == 0
        assert code.revoked is False
        assert code.created_by_user_id is None
    finally:
        db.close()


def test_admin_create_unlimited_invite_code(client, admin_enabled):
    r = client.post(
        "/admin/invites/create",
        data={"max_uses": ""},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        assert code is not None
        assert code.max_uses is None
    finally:
        db.close()


def test_admin_create_invite_rejects_zero_uses(client, admin_enabled):
    r = client.post("/admin/invites/create", data={"max_uses": "0"}, auth=BASIC)
    assert r.status_code == 422


def test_admin_create_invite_appears_on_page(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)
    r = client.get("/admin/invites", auth=BASIC)
    assert r.status_code == 200

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        assert code.code in r.text
    finally:
        db.close()


def test_admin_create_invite_records_admin_username(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        assert code.created_by_user_id is None
        assert code.created_by_admin == "root"
    finally:
        db.close()

    r = client.get("/admin/invites", auth=BASIC)
    assert 'class="td-email">root</td>' in r.text


def test_admin_revoke_invite_marks_revoked(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "5"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code_id = code.id
        assert code.revoked is False
    finally:
        db.close()

    r = client.post(f"/admin/invites/{code_id}/revoke", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        code = db.get(InviteCode, code_id)
        assert code.revoked is True
    finally:
        db.close()


def test_admin_restore_invite_clears_revoked(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "5"}, auth=BASIC)

    db = SessionLocal()
    try:
        code_id = db.query(InviteCode).first().id
    finally:
        db.close()

    client.post(f"/admin/invites/{code_id}/revoke", auth=BASIC)

    r = client.post(f"/admin/invites/{code_id}/restore", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(InviteCode, code_id).revoked is False
    finally:
        db.close()


def test_admin_restore_invite_missing_returns_404(client, admin_enabled):
    r = client.post("/admin/invites/999999/restore", auth=BASIC)
    assert r.status_code == 404


def test_admin_delete_invite_removes_row(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "5"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code_id = code.id
    finally:
        db.close()

    r = client.post(f"/admin/invites/{code_id}/delete", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(InviteCode, code_id) is None
    finally:
        db.close()


def test_admin_delete_invite_missing_returns_404(client, admin_enabled):
    r = client.post("/admin/invites/999999/delete", auth=BASIC)
    assert r.status_code == 404


def test_admin_invites_page_shows_reset_uses_when_only_exhausted(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code.uses = 1
        code.last_used_at = utcnow()
        # expires_at left None (never) — not expired, only exhausted
        db.commit()
    finally:
        db.close()

    r = client.get("/admin/invites", auth=BASIC)
    assert 'data-status="exhausted"' in r.text
    assert "Reset uses" in r.text
    assert '<details class="restore-expiry">' not in r.text


def test_admin_reset_invite_uses_clears_uses(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code_id = code.id
        code.uses = 1
        code.last_used_at = utcnow()
        db.commit()
    finally:
        db.close()

    r = client.post(f"/admin/invites/{code_id}/reset-uses", auth=BASIC, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        code = db.get(InviteCode, code_id)
        assert code.uses == 0
        assert code.max_uses == 1  # cap itself is untouched
    finally:
        db.close()


def test_admin_reset_invite_uses_missing_returns_404(client, admin_enabled):
    r = client.post("/admin/invites/999999/reset-uses", auth=BASIC)
    assert r.status_code == 404


def test_admin_restore_invite_expiry_sets_new_expiry_and_resets_uses(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "5"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code_id = code.id
        code.uses = 5
        code.expires_at = utcnow() - timedelta(days=1)  # already expired
        db.commit()
    finally:
        db.close()

    new_expires = (utcnow() + timedelta(days=30)).isoformat()
    r = client.post(
        f"/admin/invites/{code_id}/restore-expiry",
        data={"expires_at": new_expires},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        code = db.get(InviteCode, code_id)
        assert code.uses == 0
        assert code.expires_at > utcnow()
    finally:
        db.close()


def test_admin_restore_invite_expiry_blank_means_never(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "5"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code_id = code.id
        code.expires_at = utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    r = client.post(
        f"/admin/invites/{code_id}/restore-expiry",
        data={"expires_at": ""},
        auth=BASIC,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    try:
        assert db.get(InviteCode, code_id).expires_at is None
    finally:
        db.close()


def test_admin_restore_invite_expiry_missing_returns_404(client, admin_enabled):
    r = client.post("/admin/invites/999999/restore-expiry", auth=BASIC, data={"expires_at": ""})
    assert r.status_code == 404


def test_admin_invites_page_labels_exhaustion_before_expiry(client, admin_enabled):
    """A code that hit its use cap before it expired should show as
    "Exhausted", not "Expired", even though the expiry check runs first."""
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code.uses = 1
        # exhausted two days ago, expires only one day ago: exhaustion first
        code.last_used_at = utcnow() - timedelta(days=2)
        code.expires_at = utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    r = client.get("/admin/invites", auth=BASIC)
    assert 'data-status="exhausted"' in r.text
    # also past expires_at, so the combined restore-expiry action (which
    # resets both expires_at and uses together) shows instead of the
    # uses-only reset button.
    assert '<details class="restore-expiry">' in r.text
    assert "Reset uses" not in r.text


def test_admin_invites_page_shows_both_pills_when_expired_and_exhausted(client, admin_enabled):
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code.uses = 1
        code.last_used_at = utcnow() - timedelta(days=2)
        code.expires_at = utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    r = client.get("/admin/invites", auth=BASIC)
    assert '<div class="status-pills">' in r.text
    assert ">Expired<" in r.text
    assert ">Exhausted<" in r.text


def test_admin_invites_page_labels_expiry_before_exhaustion(client, admin_enabled):
    """A code that expired before it was ever fully used should still show
    as "Expired", not "Exhausted"."""
    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)

    db = SessionLocal()
    try:
        code = db.query(InviteCode).first()
        code.uses = 1
        # expired two days ago, last used only one day ago: expiry first
        code.expires_at = utcnow() - timedelta(days=2)
        code.last_used_at = utcnow() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    r = client.get("/admin/invites", auth=BASIC)
    assert 'data-status="expired"' in r.text


def test_revoked_invite_cannot_register(client, admin_enabled):
    from renar_backend import site_settings

    # enable invite-only via the admin panel
    payload_settings = {
        "registration_open": "1",
        "invite_only": "1",
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
    client.post("/admin/settings", data=payload_settings, auth=BASIC)
    site_settings.invalidate()

    client.post("/admin/invites/create", data={"max_uses": "1"}, auth=BASIC)
    db = SessionLocal()
    try:
        code_row = db.query(InviteCode).first()
        code_id = code_row.id
        code_val = code_row.code
    finally:
        db.close()

    client.post(f"/admin/invites/{code_id}/revoke", auth=BASIC)

    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD, "invite_code": code_val},
    )
    assert r.status_code == 400
