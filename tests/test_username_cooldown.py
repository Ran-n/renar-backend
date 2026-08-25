#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:50.236908
Revised: 2026/08/24 12:37:50.236908

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
        json={"username": "alice", "email": "someone-else@example.com", "password": PASSWORD},
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
        json={"username": "alice", "email": "someone-else@example.com", "password": PASSWORD},
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
        json={"username": "alice", "email": "someone-else@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


def test_unrelated_username_unaffected_by_someone_elses_cooldown(client, alice):
    user, _ = alice
    hard_delete(user["id"])

    r = client.post(
        "/auth/register",
        json={"username": "bob", "email": "bob@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
