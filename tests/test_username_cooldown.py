#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:50.236908
Revised: 2026/11/22 01:52:30.201812

Anti username-squatter cooldown: a username freed by account deletion stays
blocked from re-registration for SiteSettings.username_cooldown_days.

Uses conftest.hard_delete (accounts.delete_account directly) rather than
DELETE /auth/me: the self-service endpoint now only starts a grace period
(see test_account_deletion.py) — a username isn't actually released until
the account is really purged, whether via the grace-period's own purge job
or an admin hard delete. These tests are about the release/cooldown
mechanism itself, not the grace-period flow.
"""

from datetime import timedelta

import pytest
from conftest import PASSWORD, hard_delete, register

from renar_backend.database import SessionLocal
from renar_backend.models import ReleasedUsername, SiteSettings, utcnow

pytestmark = pytest.mark.regression


def test_deleting_account_releases_username_into_cooldown(client, alice):
    user, _ = alice
    hard_delete(user["id"])

    db = SessionLocal()
    try:
        row = db.query(ReleasedUsername).filter(ReleasedUsername.username == "alice").first()
        assert row is not None
    finally:
        db.close()


def test_reregistering_released_username_immediately_is_rejected(client):
    user = register(client, "alice")
    hard_delete(user["id"])

    r = client.post(
        "/auth/register",
        json={"accepts_terms": True, "username": "alice", "email": "someone-else@example.com", "password": PASSWORD},
    )
    assert r.status_code == 409


def test_reregistering_after_cooldown_expires_is_allowed(client):
    user = register(client, "alice")
    hard_delete(user["id"])

    db = SessionLocal()
    try:
        row = db.query(ReleasedUsername).filter(ReleasedUsername.username == "alice").first()
        row.released_at = utcnow() - timedelta(days=999)
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/auth/register",
        json={"accepts_terms": True, "username": "alice", "email": "someone-else@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


def test_cooldown_respects_admin_configured_window(client):
    db = SessionLocal()
    try:
        ss = db.get(SiteSettings, 1)
        if ss is None:
            from renar_backend.site_settings import get_site_settings

            ss = get_site_settings(db)
        ss.username_cooldown_days = 1
        db.commit()
    finally:
        db.close()

    user = register(client, "alice")
    hard_delete(user["id"])

    db = SessionLocal()
    try:
        row = db.query(ReleasedUsername).filter(ReleasedUsername.username == "alice").first()
        row.released_at = utcnow() - timedelta(days=2)
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/auth/register",
        json={"accepts_terms": True, "username": "alice", "email": "someone-else@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


def test_unrelated_username_unaffected_by_someone_elses_cooldown(client, alice):
    user, _ = alice
    hard_delete(user["id"])

    r = client.post(
        "/auth/register",
        json={"accepts_terms": True, "username": "bob", "email": "bob@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


def test_purge_forgets_released_usernames_past_the_cooldown(client):
    """Rows older than the cooldown are deleted, newer ones stay, and the
    returned count is right (privacy policy: former usernames are kept only
    for the cooldown)."""
    from renar_backend.social.notifier import purge_released_usernames_once

    old = register(client, "oldname")
    new = register(client, "newname")
    hard_delete(old["id"])
    hard_delete(new["id"])
    db = SessionLocal()
    try:
        row = db.query(ReleasedUsername).filter(ReleasedUsername.username == "oldname").one()
        row.released_at = utcnow() - timedelta(days=31)
        db.commit()
    finally:
        db.close()

    assert purge_released_usernames_once() == 1

    db = SessionLocal()
    try:
        left = sorted(r.username for r in db.query(ReleasedUsername))
    finally:
        db.close()
    assert left == ["newname"]


def test_account_purge_run_records_forgotten_usernames(monkeypatch):
    """The account_purge run's task_runs message carries both counts."""
    import asyncio

    from renar_backend import task_runs
    from renar_backend.social import notifier

    monkeypatch.setattr(task_runs, "is_enabled", lambda key: True)
    monkeypatch.setattr(task_runs, "get_interval_minutes", lambda key: 5)
    monkeypatch.setattr(notifier, "purge_expired_deletions_once", lambda: 2)
    monkeypatch.setattr(notifier, "purge_released_usernames_once", lambda: 4)
    monkeypatch.setattr(notifier, "purge_expired_decisions_once", lambda: 1)
    recorded = []
    monkeypatch.setattr(task_runs, "record_run", lambda key, started, status, detail: recorded.append(detail))
    sleeps = []

    class _Stop(Exception):
        pass

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise _Stop

    monkeypatch.setattr(notifier.asyncio, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        asyncio.run(notifier._account_purge_loop())
    assert recorded == ["2 accounts removed, 4 released usernames forgotten, 1 moderation decisions deleted"]
