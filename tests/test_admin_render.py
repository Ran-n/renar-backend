#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:10.880370
Revised: 2026/11/13 15:35:10.880370

Admin panel rendering and handler corners: timestamp/chart helpers, invite
states, the per-endpoint usage breakdown with anonymous traffic, comment
moderation labels (episode scope, replies, avatars), a sign-in strike that
escalates to a permanent ban, and a double-submitted reviewer whitelist.
"""

from datetime import timedelta

import pytest
from _race_helpers import commit_elsewhere, hide_selects

from renar_backend.database import SessionLocal
from renar_backend.models import (
    Comment,
    EndpointStat,
    Image,
    InviteCode,
    MediaType,
    ReviewWhitelist,
    Title,
    User,
    utcnow,
)
from renar_backend.routers.admin import _html, invites, login, moderation
from renar_backend.users import security


@pytest.fixture
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# _html helpers
# ---------------------------------------------------------------------------


def test_fmt_ts_shows_a_dash_for_no_timestamp():
    assert _html._fmt_ts(None) == "&mdash;"


def test_daily_counts_ignore_missing_and_out_of_window_timestamps():
    now = utcnow()
    series = _html._daily_counts([None, now - timedelta(days=90), now, now], days=7)

    assert len(series) == 7
    assert series[-1] == (now.date(), 2)
    assert sum(c for _, c in series) == 2


def test_daily_chart_keeps_a_tiny_bar_visible():
    today = utcnow().date()
    series = [(today - timedelta(days=1), 1), (today, 500)]

    chart = _html._render_daily_chart("Logins", series, "logins")

    # 1/500 of the plot height would be a sub-pixel sliver; it's drawn at 2
    assert chart.count("<path") == 2
    assert "No activity yet" not in chart


# ---------------------------------------------------------------------------
# invites
# ---------------------------------------------------------------------------


def _invite(**fields) -> InviteCode:
    fields.setdefault("code", "ABCDEFGH")
    fields.setdefault("uses", 0)
    fields.setdefault("revoked", False)
    fields.setdefault("created_at", utcnow())
    return InviteCode(**fields)


def test_invite_state_revoked_wins():
    now = utcnow()
    code = _invite(revoked=True, expires_at=now - timedelta(days=1), max_uses=1, uses=1)

    assert invites._invite_state(code, now) == ("revoked", False, False)


def test_invite_state_expired_with_uses_left():
    now = utcnow()
    code = _invite(expires_at=now - timedelta(hours=1), max_uses=5, uses=2)

    assert invites._invite_state(code, now) == ("expired", True, False)


def test_render_invites_unlimited_and_revoked_codes():
    page = invites._render_invites([
        _invite(code="UNLIMITED", max_uses=None, uses=7),
        _invite(code="REVOKED1", revoked=True, max_uses=3, uses=1),
    ])

    assert "7 / &infin;" in page
    assert "/restore" in page
    assert "Restore invite [REVOKED1]?" in page


# ---------------------------------------------------------------------------
# usage breakdown
# ---------------------------------------------------------------------------


def test_endpoint_detail_lists_anonymous_traffic(client, admin_enabled, alice):
    user, _ = alice
    commit_elsewhere(
        EndpointStat(method="GET", path="/health", user_id=None, count=4),
        EndpointStat(method="GET", path="/health", user_id=user["id"], count=2),
    )

    r = client.get("/admin/usage/endpoint", params={"method": "GET", "path": "/health"}, headers=admin_enabled)

    assert r.status_code == 200
    assert "anonymous" in r.text
    assert user["username"] in r.text


# ---------------------------------------------------------------------------
# moderation
# ---------------------------------------------------------------------------


def test_comment_moderation_labels_episode_scope_replies_and_avatars(db):
    avatar = Image(hash="ab" * 32, size_bytes=1)
    db.add(avatar)
    db.flush()
    author = User(username="critic", email="critic@example.com", password_hash="x", avatar_id=avatar.id)
    title = Title(media_type=MediaType.tv_show, tmdb_id=70523, title="Dark")
    db.add_all([author, title])
    db.flush()
    root = Comment(user_id=author.id, title_id=title.id, season=1, episode=3, text="That ending!")
    db.add(root)
    db.flush()
    reply = Comment(user_id=author.id, parent_id=root.id, text="Agreed")
    db.add(reply)
    db.flush()

    assert (
        moderation._comment_target(db, root)
        == '<span class="type-pill">tv show</span> Dark <span class="td-count">S1E3</span>'
    )
    assert moderation._comment_target(db, reply).endswith('<span class="td-count">&#x21B3; reply</span>')
    page = moderation._render_comments(db, [root, reply], {}, {}, 2, None)
    assert f'<img class="avatar" src="/images/{avatar.hash}"' in page


# ---------------------------------------------------------------------------
# sign-in strikes
# ---------------------------------------------------------------------------


def test_repeated_failed_sign_in_becomes_a_permanent_ban(client, monkeypatch):
    bans = []
    monkeypatch.setattr(security, "strike_and_maybe_ban", lambda ip, reason: (5, None))
    monkeypatch.setattr(security, "permaban", lambda ip, reason: bans.append((ip, reason)))
    monkeypatch.setattr(security, "note_temp_ban", lambda ip, until: pytest.fail("not a temp ban"))

    login._strike("203.0.113.9")

    assert bans == [("203.0.113.9", "5 repeated offenses: admin login failed")]


# ---------------------------------------------------------------------------
# reviewer whitelist double submit
# ---------------------------------------------------------------------------


def test_whitelist_review_tolerates_a_double_submit(client, admin_enabled, alice):
    user, _ = alice
    commit_elsewhere(ReviewWhitelist(user_id=user["id"]))  # the first submit's insert
    remove = hide_selects(SessionLocal, ReviewWhitelist, times=1)  # the second submit checked before it landed
    try:
        r = client.post(f"/admin/users/{user['id']}/whitelist-review", headers=admin_enabled, follow_redirects=False)
    finally:
        remove()

    assert r.status_code == 303
    db = SessionLocal()
    try:
        assert db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user["id"]).count() == 1
    finally:
        db.close()
