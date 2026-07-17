#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 17:01:06.338846
Revised: 2026/07/16 13:43:22.558615

The /svc/bans and /svc/strikes endpoints the frontend's own anti-abuse guard
uses to share this server's persisted ban/strike state.
"""

import time

import pytest

from xoutaim_backend import site_settings
from xoutaim_backend.config import settings
from xoutaim_backend.database import SessionLocal
from xoutaim_backend.models import BannedIP, SiteSettings, Strike
from xoutaim_backend.users import security

SECRET = "test-internal-secret"


@pytest.fixture(autouse=True)
def _service_secret():
    settings.internal_service_secret = SECRET
    yield
    settings.internal_service_secret = ""
    security._permabanned.clear()
    security._permabans_loaded = False


def test_missing_secret_looks_like_no_route(client):
    assert client.get("/svc/bans").status_code == 404
    assert client.post("/svc/bans", json={"ip": "1.2.3.4", "reason": "x"}).status_code == 404


def test_wrong_secret_looks_like_no_route(client):
    r = client.get("/svc/bans", headers={"X-Internal-Secret": "wrong"})
    assert r.status_code == 404


def test_secret_unset_always_404(client):
    settings.internal_service_secret = ""
    r = client.get("/svc/bans", headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 404


def test_list_bans_returns_persisted_ips(client):
    with SessionLocal() as db:
        db.add(BannedIP(ip="203.0.113.9", reason="honeypot hit: /.env"))
        db.commit()
    r = client.get("/svc/bans", headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert r.json() == {"ips": ["203.0.113.9"], "temp_bans": {}}


def test_add_ban_persists_and_permabans(client):
    r = client.post(
        "/svc/bans",
        json={"ip": "198.51.100.4", "reason": "frontend honeypot hit: /wp-login.php"},
        headers={"X-Internal-Secret": SECRET},
    )
    assert r.status_code == 200
    assert "198.51.100.4" in security._permabanned
    with SessionLocal() as db:
        ban = db.query(BannedIP).filter(BannedIP.ip == "198.51.100.4").one()
        assert "wp-login.php" in ban.reason


def test_missing_secret_looks_like_no_route_for_strikes(client):
    assert client.post("/svc/strikes", json={"ip": "1.2.3.4", "reason": "x"}).status_code == 404


def test_first_strike_returns_temporary_ban(client):
    r = client.post(
        "/svc/strikes",
        json={"ip": "198.51.100.5", "reason": "frontend flood: >2000 req/min"},
        headers={"X-Internal-Secret": SECRET},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["permanent"] is False
    assert body["banned_until"] > time.time()
    with SessionLocal() as db:
        strike = db.query(Strike).filter(Strike.ip == "198.51.100.5").one()
        assert strike.count == 1


def test_strike_shows_up_in_temp_bans_list(client):
    client.post(
        "/svc/strikes",
        json={"ip": "198.51.100.6", "reason": "frontend flood"},
        headers={"X-Internal-Secret": SECRET},
    )
    r = client.get("/svc/bans", headers={"X-Internal-Secret": SECRET})
    assert "198.51.100.6" in r.json()["temp_bans"]


def test_repeated_strikes_escalate_to_permaban(client, monkeypatch):
    monkeypatch.setattr(settings, "strike_ban_threshold", 3)
    with SessionLocal() as db:
        row = db.get(SiteSettings, 1)
        if row is None:
            row = SiteSettings(id=1)
            db.add(row)
        row.strike_ban_threshold = 3
        db.commit()
    site_settings.invalidate()
    ip = "198.51.100.7"
    for _ in range(2):
        r = client.post(
            "/svc/strikes",
            json={"ip": ip, "reason": "frontend flood"},
            headers={"X-Internal-Secret": SECRET},
        )
        assert r.json()["permanent"] is False
    r = client.post(
        "/svc/strikes",
        json={"ip": ip, "reason": "frontend flood"},
        headers={"X-Internal-Secret": SECRET},
    )
    assert r.json() == {"permanent": True, "banned_until": None}
    assert ip in security._permabanned
    with SessionLocal() as db:
        assert db.query(BannedIP).filter(BannedIP.ip == ip).count() == 1
