#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.707791
Revised: 2026/09/03 14:06:02.207669

AbuseGuardMiddleware + login backoff: what gets stopped, and — just as
important for a commercial deployment — what must never be flagged.

The main app runs with the guard disabled (see conftest), so these tests
build a minimal app of their own with the middleware attached.
"""

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.models import BannedIP
from renar_backend.users import security
from renar_backend.users.security import (
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

    @app.get("/auth/turnstile-widget/{session_id}")
    def turnstile_widget(session_id: str):
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


def test_turnstile_widget_csp_allows_cloudflare_script():
    """Regression: the blanket `default-src 'none'` on every non-admin route
    silently blocked the widget page's own inline <script> and Cloudflare's
    https://challenges.cloudflare.com/turnstile/v0/api.js — the checkbox
    never rendered (blank page), independent of any domain-allowlist issue
    on the Cloudflare dashboard side."""
    r = make_headers_client().get("/auth/turnstile-widget/some-session")
    csp = r.headers["Content-Security-Policy"]
    assert "https://challenges.cloudflare.com" in csp
    assert "'unsafe-inline'" in csp
    assert "frame-ancestors 'none'" in csp


# ---------------------------------------------------------------------------
# Unit tests — pure / low-level security helpers
# ---------------------------------------------------------------------------


def test_prune_removes_stale_entries():
    """_prune discards deque entries older than the cutoff (line 332)."""
    import time
    from collections import deque

    from renar_backend.users.security import _prune

    dq = deque([1.0, 2.0, 3.0, time.time()])
    _prune(dq, time.time() - 0.1)  # cutoff 100ms ago — only the recent entry survives
    assert len(dq) == 1


def test_reset_login_backoff_clears_all_tracked_failures():
    """reset_login_backoff removes failures across every IP for the account (lines 318-322)."""
    from renar_backend.users.security import reset_login_backoff

    for ip in ("1.2.3.4", "5.6.7.8", "9.9.9.9"):
        note_login_failure("charlie", ip)
    reset_login_backoff("charlie")
    # All IPs cleared — no 429 should be raised for charlie
    check_login_allowed("charlie", "1.2.3.4")
    check_login_allowed("charlie", "5.6.7.8")
    check_login_allowed("charlie", "9.9.9.9")


def test_client_ip_reads_x_forwarded_for_when_trust_proxy_enabled():
    """client_ip returns the rightmost X-Forwarded-For hop when trust_proxy_headers=True
    (lines 337-341)."""
    from renar_backend import site_settings as _ss
    from renar_backend.database import SessionLocal
    from renar_backend.users.security import client_ip

    db = SessionLocal()
    try:
        from renar_backend.site_settings import get_site_settings

        ss = get_site_settings(db)
        ss.trust_proxy_headers = True
        db.commit()
    finally:
        db.close()
    _ss._cache_ts = 0.0  # invalidate cache so next call re-reads

    class _FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class _FakeRequest:
        headers = _FakeHeaders({"x-forwarded-for": "203.0.113.1, 10.0.0.1"})
        client = type("c", (), {"host": "10.0.0.1"})()

    assert client_ip(_FakeRequest()) == "10.0.0.1"


def test_client_ip_falls_back_to_client_host_when_no_forwarded_header():
    """When trust_proxy_headers=True but X-Forwarded-For is absent, fall back to client.host."""
    from renar_backend import site_settings as _ss
    from renar_backend.database import SessionLocal
    from renar_backend.users.security import client_ip

    db = SessionLocal()
    try:
        from renar_backend.site_settings import get_site_settings

        ss = get_site_settings(db)
        ss.trust_proxy_headers = True
        db.commit()
    finally:
        db.close()
    _ss._cache_ts = 0.0

    class _FakeHeaders(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class _FakeRequest:
        headers = _FakeHeaders({})  # no x-forwarded-for
        client = type("c", (), {"host": "192.168.1.1"})()

    assert client_ip(_FakeRequest()) == "192.168.1.1"


# ---------------------------------------------------------------------------
# DB-exception paths — monkeypatch SessionLocal to raise
# ---------------------------------------------------------------------------


def test_load_permabans_db_exception_is_swallowed(monkeypatch):
    """_load_permabans catches any DB error and logs it (lines 124-125)."""
    from renar_backend.users import security

    monkeypatch.setattr(security, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    security._permabans_loaded = False
    security._load_permabans()  # must not raise
    assert not security._permabans_loaded  # stays False on error


def test_permaban_db_exception_still_adds_to_memory_but_raises(monkeypatch):
    """permaban adds to the in-memory set (effective immediately, line 129)
    even when the DB write fails — but the DB failure itself now propagates
    rather than being silently swallowed (see the fuzz-discovered "no silent
    failure" fix: a caller like POST /svc/bans must be able to tell a ban
    didn't actually persist, instead of always getting back {"status": "ok"})."""
    from renar_backend.users import security

    monkeypatch.setattr(security, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    security._permabanned.discard("9.8.7.6")
    with pytest.raises(RuntimeError, match="db down"):
        security.permaban("9.8.7.6", "test")
    assert "9.8.7.6" in security._permabanned  # memory set updated despite DB error


def test_permaban_duplicate_handles_integrity_error():
    """A second permaban call for the same IP hits the unique constraint on
    banned_ips.ip — the IntegrityError is caught silently (lines 135-136)."""
    from renar_backend.users import security

    security.permaban("10.0.0.200", "first hit")
    security.permaban("10.0.0.200", "second hit")  # must not raise
    assert "10.0.0.200" in security._permabanned


def test_strike_and_maybe_ban_db_exception_returns_fallback(monkeypatch):
    """When the DB is unreachable, strike_and_maybe_ban returns a safe fallback
    (1 strike, short ban) instead of propagating (lines 210-212)."""
    from renar_backend.users import security

    monkeypatch.setattr(security, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    count, until = security.strike_and_maybe_ban("1.2.3.99", "test")
    assert count == 1
    assert until is not None and until > 0


def test_load_active_temp_bans_db_exception_returns_empty(monkeypatch):
    """load_active_temp_bans logs and returns {} when DB is unreachable (lines 231-232)."""
    from renar_backend.users import security

    monkeypatch.setattr(security, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    result = security.load_active_temp_bans()
    assert result == {}


# ---------------------------------------------------------------------------
# load_active_temp_bans — datetime and expiry branches
# ---------------------------------------------------------------------------


def test_load_active_temp_bans_with_naive_datetime(monkeypatch):
    """When the DB driver returns a timezone-naive banned_until, the code attaches
    UTC tzinfo before comparing (line 228). Monkeypatch the query so the test
    doesn't depend on the driver's own timezone handling."""
    from datetime import UTC, datetime, timedelta

    from renar_backend.users import security
    from renar_backend.users.security import load_active_temp_bans

    naive_future = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)

    class _FakeQuery:
        def filter(self, *a, **kw):
            return self

        def all(self):
            return [("203.0.113.50", naive_future)]

    class _FakeDB:
        def query(self, *a):
            return _FakeQuery()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(security, "SessionLocal", lambda: _FakeDB())
    result = load_active_temp_bans()
    assert "203.0.113.50" in result


def test_load_active_temp_bans_excludes_already_expired():
    """A Strike whose banned_until is in the past must NOT appear in the result
    (the False branch of `if banned_until > now_dt:`, line 229->226)."""
    from datetime import UTC, datetime, timedelta

    from renar_backend.database import SessionLocal
    from renar_backend.models import Strike
    from renar_backend.users.security import load_active_temp_bans

    past = datetime.now(UTC) - timedelta(hours=2)
    with SessionLocal() as db:
        db.add(Strike(ip="203.0.113.51", count=1, reason="test", last_offense_at=datetime.now(UTC), banned_until=past))
        db.commit()

    result = load_active_temp_bans()
    assert "203.0.113.51" not in result


# ---------------------------------------------------------------------------
# _cleanup_old_strikes — enabled/disabled/exception branches
# ---------------------------------------------------------------------------


def test_cleanup_old_strikes_when_disabled(monkeypatch):
    """When the strike_cleanup task is disabled, _cleanup_old_strikes returns
    immediately without touching the DB (line 241)."""
    from renar_backend import task_runs
    from renar_backend.users import security

    monkeypatch.setattr(task_runs, "is_enabled", lambda key: False)
    security._last_strike_cleanup = 0.0
    security._cleanup_old_strikes(0.0)  # must return early without DB access


def test_cleanup_old_strikes_db_exception_is_swallowed(monkeypatch):
    """A DB error during strike cleanup is logged and swallowed (lines 253-255)."""
    from renar_backend import task_runs
    from renar_backend.users import security

    monkeypatch.setattr(task_runs, "is_enabled", lambda key: True)
    monkeypatch.setattr(task_runs, "get_interval_minutes", lambda key: 0)  # interval = 0 → always runs
    security._last_strike_cleanup = 0.0
    monkeypatch.setattr(security, "SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    security._cleanup_old_strikes(security.time.time())  # must not raise


# ---------------------------------------------------------------------------
# Middleware instance-level tests — sweep and temp-ban loading
# ---------------------------------------------------------------------------


def test_sweep_removes_expired_temp_bans_from_dict():
    """_sweep deletes entries from banned_until whose `until` is in the past (line 409)."""
    import time
    from unittest.mock import MagicMock

    from renar_backend.users.security import AbuseGuardMiddleware

    mw = AbuseGuardMiddleware(MagicMock())
    mw.banned_until = {"expired.ip": time.time() - 100, "live.ip": time.time() + 3600}
    mw._sweep(time.time())
    assert "expired.ip" not in mw.banned_until
    assert "live.ip" in mw.banned_until


def test_sweep_prunes_oversized_tracker(monkeypatch):
    """When a tracker dict exceeds 10 000 entries, _sweep removes stale ones (lines 406-407)."""
    import time
    from unittest.mock import MagicMock

    from renar_backend import task_runs
    from renar_backend.users.security import AbuseGuardMiddleware

    # Prevent _cleanup_old_strikes from touching the DB during this test
    monkeypatch.setattr(task_runs, "is_enabled", lambda key: False)

    mw = AbuseGuardMiddleware(MagicMock())
    now = time.time()
    # Inject 10 001 stale hits (200 s old, well past the 60 s window)
    for i in range(10_001):
        mw.hits[f"10.{i // 65536}.{(i // 256) % 256}.{i % 256}"].append(now - 200)

    assert len(mw.hits) == 10_001
    mw._sweep(now)
    assert len(mw.hits) == 0


def test_active_temp_bans_loaded_on_first_dispatch():
    """On the first request through a fresh AbuseGuardMiddleware instance,
    active temp bans from the DB are loaded into banned_until (line 418)."""
    from datetime import UTC, datetime, timedelta

    from renar_backend.database import SessionLocal
    from renar_backend.models import Strike

    future = datetime.now(UTC) + timedelta(hours=1)
    with SessionLocal() as db:
        db.add(
            Strike(
                ip="testclient", count=1, reason="pre-existing", last_offense_at=datetime.now(UTC), banned_until=future
            )
        )
        db.commit()

    client = make_client()
    r = client.get("/")
    assert r.status_code == 429  # temp ban loaded from DB, request denied


def test_expired_temp_ban_is_cleared_on_next_request(monkeypatch):
    """When an IP's ban epoch has passed, dispatch removes it from banned_until
    and allows the request through (line 433)."""
    import time as _time_mod

    from renar_backend.users import security

    client = make_client()
    # Trigger a temp ban via flood
    for _ in range(41):
        client.get("/")
    assert client.get("/health").status_code == 429  # currently banned

    # Fast-forward time past every ban and rate-limit window
    far_future = _time_mod.time() + 90_000  # 25 hours ahead
    monkeypatch.setattr(security.time, "time", lambda: far_future)
    r = client.get("/health")
    # Ban expired → request goes through (health is always uncounted)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Middleware — flood escalates to permaban at strike threshold
# ---------------------------------------------------------------------------


def test_flood_ban_escalates_to_permaban_at_threshold():
    """When the offense count reaches strike_ban_threshold, _ban calls permaban
    instead of setting a temp ban (lines 388-390)."""
    from renar_backend import site_settings as _ss
    from renar_backend.database import SessionLocal
    from renar_backend.users import security

    db = SessionLocal()
    try:
        from renar_backend.site_settings import get_site_settings

        ss = get_site_settings(db)
        ss.strike_ban_threshold = 1  # first offense = permaban
        db.commit()
    finally:
        db.close()
    _ss._cache_ts = 0.0  # invalidate cache

    client = make_client()
    # Trigger flood ban (> 40 req/min per guard_settings)
    for _ in range(41):
        client.get("/")

    # After the first ban, count=1 >= threshold=1 → permabanned, not temp-banned
    r = client.get("/")
    assert r.status_code == 403  # permanent ban

    # Confirm in-memory mirror was updated
    assert "testclient" in security._permabanned
