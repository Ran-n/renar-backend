#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 17:01:06.338846
Revised: 2026/09/02 10:58:16.587085

The /svc/bans and /svc/strikes endpoints the frontend's own anti-abuse guard
uses to share this server's persisted ban/strike state.
"""

import time

import pytest

from renar_backend import site_settings
from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.models import BannedIP, SiteSettings, Strike
from renar_backend.users import security

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


def test_repeated_wrong_secret_strikes_the_caller(client):
    for _ in range(5):
        r = client.get("/svc/bans", headers={"X-Internal-Secret": "wrong"})
        assert r.status_code == 404
    with SessionLocal() as db:
        assert db.query(Strike).filter(Strike.ip == "testclient").count() == 0

    r = client.get("/svc/bans", headers={"X-Internal-Secret": "wrong"})
    assert r.status_code == 404
    with SessionLocal() as db:
        strike = db.query(Strike).filter(Strike.ip == "testclient").one()
        assert strike.count == 1


def test_exempt_ip_never_strikes_even_with_wrong_secret(client):
    """The frontend itself calls this from localhost — a stale/misconfigured
    local deployment retrying with a wrong secret must never end up banning
    the machine it's running on."""
    with SessionLocal() as db:
        row = db.get(SiteSettings, 1)
        if row is None:
            row = SiteSettings(id=1)
            db.add(row)
        row.exempt_ips = ["testclient"]
        db.commit()
    site_settings.invalidate()

    for _ in range(10):
        r = client.get("/svc/bans", headers={"X-Internal-Secret": "wrong"})
        assert r.status_code == 404
    with SessionLocal() as db:
        assert db.query(Strike).filter(Strike.ip == "testclient").count() == 0


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


def test_old_auth_failures_pruned_from_window(client, monkeypatch):
    """Entries older than 1 minute are pruned from the sliding window —
    covers svc.py _require_internal_secret's failures.popleft() (line 74)."""
    import time as _time

    from renar_backend.routers import svc

    old_ts = _time.time() - 120.0  # 2 minutes ago — outside the 1-minute window
    svc._auth_failures["testclient"].append(old_ts)
    # This request prunes the old entry and appends the new one; count stays 1
    client.get("/svc/bans", headers={"X-Internal-Secret": "wrong"})
    assert old_ts not in svc._auth_failures["testclient"]


def test_repeated_wrong_secret_from_non_exempt_ip_triggers_permaban(client, monkeypatch):
    """After enough wrong-secret attempts the non-exempt caller is permabanned —
    covers svc.py _require_internal_secret's permaban branch (line 79)."""
    from renar_backend.models import SiteSettings

    with SessionLocal() as db:
        row = db.get(SiteSettings, 1)
        if row is None:
            row = SiteSettings(id=1)
            db.add(row)
        row.strike_ban_threshold = 1
        db.commit()
    from renar_backend import site_settings as ss_mod

    ss_mod.invalidate()

    # Drive enough wrong-secret requests to trigger a strike (> _FAIL_LIMIT_PER_MINUTE)
    # then have that single strike immediately trigger a permaban (threshold=1).
    from renar_backend.routers import svc

    svc._auth_failures.clear()
    for _ in range(6):  # _FAIL_LIMIT_PER_MINUTE + 1
        client.get("/svc/bans", headers={"X-Internal-Secret": "wrong"})

    assert "testclient" in security._permabanned


def test_permaban_db_failure_surfaces_as_500(client, monkeypatch):
    """A DB failure in permaban() must propagate rather than be silently swallowed.

    Before the fix, permaban() caught all exceptions and only logged them,
    returning normally — so POST /svc/bans always replied 200 "ok" even when
    the ban was never persisted. After the fix, the exception is re-raised.

    Starlette's TestClient default (raise_server_exceptions=True) propagates
    the unhandled exception as a Python exception rather than capturing it as an
    HTTP 500 response; pytest.raises is the correct way to assert this.  In a
    real uvicorn deployment the same uncaught exception becomes HTTP 500.

    The in-memory ban is still applied before the DB attempt (that line runs
    unconditionally), so the ban is effective for the life of the process even
    though the DB write failed.
    """

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(security, "SessionLocal", _explode)
    with pytest.raises(RuntimeError, match="simulated DB failure"):
        client.post(
            "/svc/bans",
            json={"ip": "10.255.0.1", "reason": "db-failure-test"},
            headers={"X-Internal-Secret": SECRET},
        )
    # In-memory ban was applied before the DB attempt — enforcement still works.
    assert "10.255.0.1" in security._permabanned
