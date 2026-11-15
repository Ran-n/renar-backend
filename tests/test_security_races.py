#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:11.439510
Revised: 2026/11/13 15:35:11.439510

Abuse-guard corners: the first strike for an IP raced by a concurrent
request (found and not found on re-read), an exempt IP skipping the guard
entirely, and a temp ban recorded elsewhere (svc / admin sign-in) being
picked up by the running middleware.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest
from _race_helpers import commit_elsewhere, hide_selects
from fastapi import FastAPI
from fastapi.testclient import TestClient

from renar_backend import site_settings
from renar_backend.database import SessionLocal
from renar_backend.models import Strike
from renar_backend.users import security
from renar_backend.users.security import AbuseGuardMiddleware


@pytest.fixture
def hidden_strikes():
    removers = []

    def _hide(times):
        removers.append(hide_selects(SessionLocal, Strike, times=times))

    yield _hide
    for remove in removers:
        remove()


def test_first_strike_race_escalates_the_winners_row(client, hidden_strikes):
    commit_elsewhere(Strike(ip="198.51.100.7", count=2, reason="flood", last_offense_at=datetime.now(UTC)))
    hidden_strikes(1)  # our SELECT ran before the other request's INSERT committed

    count, until = security.strike_and_maybe_ban("198.51.100.7", "probe")

    assert count == 3
    db = SessionLocal()
    try:
        row = db.query(Strike).filter(Strike.ip == "198.51.100.7").one()
        assert (row.count, row.reason) == (3, "probe")
    finally:
        db.close()


def test_first_strike_race_forgives_a_stale_winner_row(client, hidden_strikes):
    old = datetime.now(UTC) - timedelta(days=3)
    commit_elsewhere(Strike(ip="198.51.100.8", count=4, reason="flood", last_offense_at=old))
    hidden_strikes(1)

    count, _ = security.strike_and_maybe_ban("198.51.100.8", "probe")

    assert count == 1


def test_first_strike_race_with_no_row_still_temp_bans(client, hidden_strikes, caplog):
    commit_elsewhere(Strike(ip="198.51.100.9", count=1, reason="flood", last_offense_at=datetime.now(UTC)))
    hidden_strikes(None)
    before = time.time()

    count, until = security.strike_and_maybe_ban("198.51.100.9", "probe")

    assert count == 1
    assert until > before
    assert "neither insertable nor findable" in caplog.text


# ---------------------------------------------------------------------------
# middleware
# ---------------------------------------------------------------------------


def _guarded_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(AbuseGuardMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return TestClient(app)


def _set_exempt(ips: list[str]) -> None:
    db = SessionLocal()
    try:
        site_settings.get_site_settings(db).exempt_ips = ips
        db.commit()
    finally:
        db.close()
    site_settings.invalidate()


def test_exempt_ip_bypasses_even_a_permanent_ban(client, monkeypatch):
    monkeypatch.setattr(security, "_permabanned", {"testclient"})
    monkeypatch.setattr(security, "_permabans_loaded", True)
    _set_exempt(["testclient"])

    assert _guarded_app().get("/ping").status_code == 200


def test_temp_ban_noted_elsewhere_reaches_the_running_guard(client, monkeypatch):
    monkeypatch.setattr(security, "_external_temp_bans", {})
    guarded = _guarded_app()
    assert guarded.get("/ping").status_code == 200  # guard up, nothing banned

    security.note_temp_ban("testclient", time.time() + 600)

    assert guarded.get("/ping").status_code == 429  # temp ban: Too Many Requests
    assert security._external_temp_bans == {}
