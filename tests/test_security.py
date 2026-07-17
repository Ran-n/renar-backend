#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.707791
Revised: 2026/07/11 15:23:12.394399

AbuseGuardMiddleware + login backoff: what gets stopped, and — just as
important for a commercial deployment — what must never be flagged.

The main app runs with the guard disabled (see conftest), so these tests
build a minimal app of their own with the middleware attached.
"""

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from xoutaim_backend.config import settings
from xoutaim_backend.database import SessionLocal
from xoutaim_backend.models import BannedIP
from xoutaim_backend.users import security
from xoutaim_backend.users.security import (
    AbuseGuardMiddleware,
    OriginCheckMiddleware,
    SecurityHeadersMiddleware,
    check_login_allowed,
    note_login_failure,
)


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(AbuseGuardMiddleware)

    @app.get("/")
    def home():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/media/{item_id}")
    def media(item_id: int):
        raise HTTPException(status_code=404, detail="No such item")

    @app.post("/auth/login")
    def login():
        return {"ok": True}

    @app.post("/auth/register")
    def register():
        return {"ok": True}

    return TestClient(app)


@pytest.fixture(autouse=True)
def guard_settings(monkeypatch):
    """Small limits so tests don't need thousands of requests."""
    monkeypatch.setattr(settings, "abuse_guard_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 20)
    monkeypatch.setattr(settings, "flood_ban_per_minute", 40)
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 5)
    monkeypatch.setattr(settings, "register_per_hour_per_ip", 3)
    monkeypatch.setattr(settings, "login_backoff_threshold", 3)
    monkeypatch.setattr(settings, "login_backoff_account_threshold", 6)
    monkeypatch.setattr(settings, "login_backoff_minutes", 15)
    monkeypatch.setattr(settings, "probe_ban_threshold", 4)
    monkeypatch.setattr(settings, "probe_window_minutes", 10)
    monkeypatch.setattr(settings, "ban_minutes", 60)
    # module-level trackers must not leak between tests (_fresh_db already
    # emptied the banned_ips table; reset the in-memory mirror to match)
    security._login_failures_by_key.clear()
    security._login_failures_by_account.clear()
    security._permabanned.clear()
    security._permabans_loaded = False


# --- what must never be flagged -------------------------------------------


def test_normal_traffic_passes():
    client = make_client()
    assert all(client.get("/").status_code == 200 for _ in range(15))


def test_endpoint_404s_are_not_probes():
    """A real route answering 404 (deleted item, stale link) never bans."""
    client = make_client()
    codes = [client.get(f"/media/{i}").status_code for i in range(10)]
    assert codes == [404] * 10
    assert client.get("/").status_code == 200


def test_valid_token_404s_are_not_probes():
    """An outdated app calling removed endpoints must not get users banned."""
    client = make_client()
    token = jwt.encode({"sub": "1"}, settings.secret_key, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    codes = [client.get(f"/gone-endpoint-{i}", headers=headers).status_code for i in range(6)]
    assert codes == [404] * 6
    assert client.get("/").status_code == 200


def test_soft_rate_limit_throttles_without_ban():
    """An office/CGNAT burst gets 429s, recovers, and is never banned."""
    client = make_client()
    codes = [client.get("/").status_code for _ in range(25)]
    assert codes[:20] == [200] * 20
    assert set(codes[20:]) == {429}
    # not banned: uncounted endpoints still answer
    assert client.get("/health").status_code == 200


def test_health_checks_are_uncounted():
    client = make_client()
    assert all(client.get("/health").status_code == 200 for _ in range(30))
    assert client.get("/").status_code == 200


# --- what gets stopped ------------------------------------------------------


def test_flood_gets_banned():
    client = make_client()
    codes = [client.get("/").status_code for _ in range(41)]
    assert codes[-1] == 429
    # banned now: even uncounted endpoints refuse
    assert client.get("/health").status_code == 429


def test_unknown_path_probing_gets_banned():
    client = make_client()
    codes = [client.get(f"/no-such-path-{i}").status_code for i in range(4)]
    assert codes == [404] * 4
    assert client.get("/").status_code == 429


def test_invalid_token_does_not_shield_probing():
    client = make_client()
    headers = {"Authorization": "Bearer garbage"}
    for i in range(4):
        client.get(f"/no-such-path-{i}", headers=headers)
    assert client.get("/").status_code == 429


def test_honeypot_instant_permanent_ban():
    client = make_client()
    r = client.get("/.env")
    assert r.status_code == 404  # trap looks like any other missing path
    assert client.get("/").status_code == 403

    # the ban was persisted, with the trap path recorded
    with SessionLocal() as db:
        ban = db.query(BannedIP).filter(BannedIP.ip == "testclient").one()
        assert "/.env" in ban.reason


def test_honeypot_ban_survives_restart():
    client = make_client()
    client.get("/.env")
    # simulate a server restart: in-memory state gone, database intact
    security._permabanned.clear()
    security._permabans_loaded = False
    fresh_client = make_client()
    assert fresh_client.get("/").status_code == 403


def test_lift_permaban_restores_access():
    client = make_client()
    client.get("/.env")
    assert client.get("/").status_code == 403
    # what the admin unban endpoint does: drop the row + the memory mirror
    with SessionLocal() as db:
        db.query(BannedIP).filter(BannedIP.ip == "testclient").delete()
        db.commit()
    security.lift_permaban("testclient")
    assert client.get("/").status_code == 200


def test_honeypot_prefix_instant_ban():
    client = make_client()
    assert client.get("/wp-admin/setup-config.php").status_code == 404
    assert client.get("/").status_code == 403


def test_robots_txt_advertises_the_bait():
    client = make_client()
    r = client.get("/robots.txt")
    assert r.status_code == 200
    assert "/internal/" in r.text
    # a scanner following the bait gets banned
    client.get("/internal/secrets")
    assert client.get("/").status_code == 403


def test_default_admin_path_is_not_a_trap():
    client = make_client()
    client.get("/admin")  # 404 here (no admin router in the mini app), but no ban
    assert client.get("/").status_code == 200


def test_renamed_admin_turns_default_path_into_honeypot(monkeypatch):
    monkeypatch.setattr(settings, "admin_path", "/panel-x7k2")
    client = make_client()
    assert client.get("/admin/users").status_code == 404
    assert client.get("/").status_code == 403


def test_auth_requests_throttled_per_ip():
    client = make_client()
    codes = [client.post("/auth/login").status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    # throttled, not banned
    assert client.get("/").status_code == 200


def test_register_throttled_per_hour():
    client = make_client()
    codes = [client.post("/auth/register").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


# --- per-account login backoff ----------------------------------------------


def test_login_backoff_per_account_and_ip():
    for _ in range(3):
        note_login_failure("alice", "1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        check_login_allowed("alice", "1.2.3.4")
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    # same account from the owner's own IP is unaffected
    check_login_allowed("alice", "5.6.7.8")
    # other accounts from the attacker's IP are unaffected
    check_login_allowed("bob", "1.2.3.4")


def test_login_backoff_across_ips_blunts_stuffing():
    for i in range(6):
        note_login_failure("alice", f"10.0.0.{i}")
    with pytest.raises(HTTPException):
        check_login_allowed("alice", "10.9.9.9")  # a fresh IP is still blocked


def test_admin_bans_page_and_unban(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "boss")
    monkeypatch.setattr(settings, "admin_password", "pw")
    with SessionLocal() as db:
        ban = BannedIP(ip="203.0.113.7", reason="honeypot hit: /.env")
        db.add(ban)
        db.commit()
        ban_id = ban.id
    security._permabanned.add("203.0.113.7")

    page = client.get("/admin/bans", auth=("boss", "pw"))
    assert page.status_code == 200
    assert "203.0.113.7" in page.text

    r = client.post(f"/admin/bans/{ban_id}/delete", auth=("boss", "pw"), follow_redirects=False)
    assert r.status_code == 303
    assert "203.0.113.7" not in security._permabanned
    with SessionLocal() as db:
        assert db.query(BannedIP).count() == 0


def test_login_backoff_case_insensitive():
    for _ in range(3):
        note_login_failure("Alice", "1.2.3.4")
    with pytest.raises(HTTPException):
        check_login_allowed("alice", "1.2.3.4")


# --- origin check (CSRF defense-in-depth) ------------------------------------


def make_origin_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware)

    @app.get("/things")
    def read():
        return {"ok": True}

    @app.post("/things")
    def create():
        return {"ok": True}

    return TestClient(app)


def test_post_without_origin_passes():
    """Non-browser clients (the app, curl) send no Origin header at all."""
    assert make_origin_client().post("/things").status_code == 200


def test_same_origin_post_passes():
    """The admin panel's own <form method=post> buttons."""
    r = make_origin_client().post("/things", headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_allowlisted_origin_post_passes():
    r = make_origin_client().post("/things", headers={"Origin": settings.cors_origins[0]})
    assert r.status_code == 200


def test_foreign_origin_post_rejected():
    r = make_origin_client().post("/things", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Origin not allowed"


def test_null_origin_post_rejected():
    """`Origin: null` is what sandboxed iframes and opaque contexts send."""
    r = make_origin_client().post("/things", headers={"Origin": "null"})
    assert r.status_code == 403


def test_foreign_origin_get_passes():
    """Safe methods are never blocked (CORS handles read protection)."""
    r = make_origin_client().get("/things", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


# --- security headers ---------------------------------------------------------


def make_headers_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/admin/users")
    def admin_page():
        return {"ok": True}

    @app.get("/titles")
    def api_route():
        return {"ok": True}

    return TestClient(app)


def test_admin_referrer_policy_preserves_origin_header():
    """Must NOT be `no-referrer`: per the Fetch spec the Origin header follows
    the referrer policy on non-CORS POSTs, so `no-referrer` makes browsers
    send `Origin: null` on the panel's own form buttons and OriginCheck
    rejects them (regression: every admin POST answered 403)."""
    r = make_headers_client().get("/admin/users")
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_api_routes_send_no_referrer():
    r = make_headers_client().get("/titles")
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["Content-Security-Policy"].startswith("default-src 'none'")
