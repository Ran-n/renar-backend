#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:23.769899
Revised: 2026/11/10 11:04:47.797141

Admin panel sign-in: the login page (username + password + authenticator
code), the session cookie, its expiry and invalidation, logout, the strike
on a failed sign-in, and the API token the APK upload script uses instead.

Runs on the real Postgres test schema; strikes land in the real ``strikes``
table. Time is frozen in the middle of a TOTP step (``frozen_now``) so a
code computed by the test can't roll over to the next step mid-test.
"""

import time
import types
from urllib.parse import quote

import jwt
import pyotp
import pytest
from conftest import ADMIN_API_TOKEN, ADMIN_CREDS, ADMIN_TOTP_SECRET

from renar_backend import site_settings
from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.main import app
from renar_backend.models import Strike, User
from renar_backend.users import admin_session
from renar_backend.users.auth import create_access_token

pytestmark = pytest.mark.regression

USER, PASSWORD = ADMIN_CREDS
TOTP = pyotp.TOTP(ADMIN_TOTP_SECRET)


@pytest.fixture
def frozen_now(monkeypatch):
    """A clock frozen mid-step, 15-45 s in the past: never ahead of pyjwt's
    own (unfrozen) clock, which rejects an ``iat`` in the future."""
    now = (int(time.time()) // 30) * 30 - 15
    monkeypatch.setattr(admin_session, "time", types.SimpleNamespace(time=lambda: now))
    return now


def login(client, *, username=USER, password=PASSWORD, code=None, next_path=None, now=None):
    data = {"username": username, "password": password, "code": code if code is not None else TOTP.at(now)}
    if next_path is not None:
        data["next"] = next_path
    return client.post("/admin/login", data=data, follow_redirects=False)


def strike_count() -> int:
    with SessionLocal() as db:
        row = db.query(Strike).filter(Strike.ip == "testclient").first()
        return row.count if row else 0


# ---------- configuration ----------


@pytest.mark.parametrize("field", ["admin_username", "admin_password", "admin_totp_secret"])
def test_unconfigured_returns_503(client, admin_enabled, monkeypatch, field):
    monkeypatch.setattr(settings, field, "")
    assert client.get("/admin", follow_redirects=False).status_code == 503
    assert client.get("/admin/login").status_code == 503
    assert login(client, code="123456").status_code == 503


# ---------- logged-out access ----------


def test_get_redirects_to_login_with_next(client, admin_enabled):
    r = client.get("/admin/users?q=a", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/login?next={quote('/admin/users?q=a', safe='')}"


def test_post_without_session_is_401(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/delete", follow_redirects=False)
    assert r.status_code == 401
    assert "Session expired" in r.text
    with SessionLocal() as db:
        assert db.get(User, user["id"]) is not None


def test_login_page_renders_form(client, admin_enabled):
    r = client.get("/admin/login?next=/admin/users")
    assert r.status_code == 200
    for needle in (
        'name="username"',
        'autocomplete="current-password"',
        'autocomplete="one-time-code"',
        'inputmode="numeric"',
        'value="/admin/users"',
    ):
        assert needle in r.text


# ---------- signing in ----------


def test_login_success_sets_cookie_and_redirects(client, admin_enabled, frozen_now):
    r = login(client, next_path="/admin/users", now=frozen_now)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/users"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{admin_session.COOKIE_NAME}=")
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=strict" in lowered
    assert "path=/admin" in lowered
    assert f"max-age={admin_session.SESSION_SECONDS}" in lowered
    assert "secure" not in lowered  # plain http here; https sets it
    # the client's jar now holds the session
    assert client.get("/admin/users", follow_redirects=False).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [{"password": PASSWORD[::-1]}, {"username": "rooot"}, {"code": "000000"}],
    ids=["wrong_password", "wrong_username", "wrong_code"],
)
def test_wrong_credentials(client, admin_enabled, frozen_now, overrides):
    if overrides.get("code") == TOTP.at(frozen_now):
        overrides = {"code": "111111"}
    r = login(client, now=frozen_now, **overrides)
    assert r.status_code == 401
    assert "Wrong username, password or code." in r.text
    assert "set-cookie" not in r.headers
    # the username is kept, the password is not echoed back
    assert PASSWORD not in r.text


def test_non_numeric_or_short_code_rejected(client, admin_enabled, frozen_now):
    assert login(client, code="abcdef", now=frozen_now).status_code == 401
    assert login(client, code=TOTP.at(frozen_now)[:5], now=frozen_now).status_code == 401


def test_code_with_space_accepted(client, admin_enabled, frozen_now):
    code = TOTP.at(frozen_now)
    assert login(client, code=f"{code[:3]} {code[3:]}").status_code == 303


def test_code_previous_step_accepted(client, admin_enabled, frozen_now):
    assert login(client, code=TOTP.at(frozen_now - 30)).status_code == 303


def test_code_next_step_accepted(client, admin_enabled, frozen_now):
    assert login(client, code=TOTP.at(frozen_now + 30)).status_code == 303


def test_code_two_steps_old_rejected(client, admin_enabled, frozen_now):
    code = TOTP.at(frozen_now - 60)
    if code in {TOTP.at(frozen_now + d) for d in (-30, 0, 30)}:
        pytest.skip("two-steps-old code collides with an accepted one")
    assert login(client, code=code).status_code == 401


def test_code_replay_rejected(client, admin_enabled, frozen_now):
    code = TOTP.at(frozen_now)
    assert login(client, code=code).status_code == 303
    client.cookies.clear()
    assert login(client, code=code).status_code == 401


def test_older_step_after_newer_rejected(client, admin_enabled, frozen_now):
    """Signing in with the current code burns the previous step's too."""
    assert login(client, code=TOTP.at(frozen_now)).status_code == 303
    client.cookies.clear()
    assert login(client, code=TOTP.at(frozen_now - 30)).status_code == 401


@pytest.mark.parametrize(
    "target",
    [
        "//evil.com",
        "https://evil.com",
        "/admin-evil",
        "/elsewhere",
        "/admin\\..\\x",
        "/admin/../x",
        "/admin/..",
        "",
        "/adminx",
    ],
)
def test_unsafe_next_ignored(client, admin_enabled, frozen_now, target):
    r = login(client, next_path=target, now=frozen_now)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"


def test_safe_next_kept(client, admin_enabled, frozen_now):
    r = login(client, next_path="/admin/users?page=2", now=frozen_now)
    assert r.headers["location"] == "/admin/users?page=2"


def test_logged_in_get_login_redirects_home(client, admin_enabled):
    r = client.get("/admin/login", headers=admin_enabled, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"


# ---------- strikes ----------


def test_failed_login_records_strike(client, admin_enabled, frozen_now):
    assert strike_count() == 0
    login(client, password="nope", now=frozen_now)
    assert strike_count() == 1


def test_failed_login_exempt_ip_no_strike(client, admin_enabled, frozen_now):
    with SessionLocal() as db:
        row = site_settings.get_site_settings(db)
        row.exempt_ips = [*row.exempt_ips, "testclient"]
        db.commit()
    site_settings._cache_ts = 0.0
    assert login(client, password="nope", now=frozen_now).status_code == 401
    assert strike_count() == 0


def test_successful_login_records_no_strike(client, admin_enabled, frozen_now):
    login(client, now=frozen_now)
    assert strike_count() == 0


# ---------- session validity ----------


def test_expired_session_redirects(client, admin_enabled):
    token = admin_session.issue_session(USER, now=time.time() - admin_session.SESSION_SECONDS - 5)
    r = client.get("/admin", headers={"Cookie": f"{admin_session.COOKIE_NAME}={token}"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/login")


@pytest.mark.parametrize("field", ["admin_password", "admin_username", "admin_totp_secret"])
def test_rotated_credential_kills_session(client, admin_enabled, monkeypatch, field):
    assert client.get("/admin", headers=admin_enabled, follow_redirects=False).status_code == 200
    rotated = "KRSXG5DTMVRXEZLUKRSXG5DTMVRXEZLU" if field == "admin_totp_secret" else "rotated-value"
    monkeypatch.setattr(settings, field, rotated)
    assert client.get("/admin", headers=admin_enabled, follow_redirects=False).status_code == 303


def test_user_access_token_not_admin_session(client, admin_enabled, alice):
    user, _ = alice
    token = create_access_token(user["id"])
    r = client.get("/admin", headers={"Cookie": f"{admin_session.COOKIE_NAME}={token}"}, follow_redirects=False)
    assert r.status_code == 303


def test_admin_session_not_accepted_as_app_token(client, admin_enabled):
    token = admin_session.issue_session(USER)
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_forged_session_rejected(client, admin_enabled):
    claims = jwt.decode(
        admin_session.issue_session(USER), settings.secret_key, algorithms=["HS256"], audience=admin_session.AUDIENCE
    )
    forged = jwt.encode(claims, "some-other-key-0123456789abcdef0123", algorithm="HS256")
    r = client.get("/admin", headers={"Cookie": f"{admin_session.COOKIE_NAME}={forged}"}, follow_redirects=False)
    assert r.status_code == 303


def test_garbage_cookie_redirects(client, admin_enabled):
    r = client.get("/admin", headers={"Cookie": f"{admin_session.COOKIE_NAME}=not-a-jwt"}, follow_redirects=False)
    assert r.status_code == 303


# ---------- logout ----------


def test_logout_clears_cookie(client, admin_enabled, frozen_now):
    login(client, now=frozen_now)
    assert client.get("/admin", follow_redirects=False).status_code == 200
    r = client.post("/admin/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith(f"{admin_session.COOKIE_NAME}=")
    assert "max-age=0" in cookie
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_logout_get_not_allowed(client, admin_enabled):
    assert client.get("/admin/logout", headers=admin_enabled).status_code == 405


def _all_routes():
    """Every route with its full path. FastAPI >= 0.139 keeps an included
    router as one nested entry in ``app.routes``; its effective contexts
    carry the prefixed paths."""
    for route in app.routes:
        if hasattr(route, "effective_route_contexts"):
            yield from route.effective_route_contexts()
        else:
            yield route


def test_every_admin_page_has_logout_button(client, admin_enabled, alice):
    """Every parameterless admin HTML page (plus the per-user ones) carries
    the Log out form; a new page without it fails here."""
    user, _ = alice
    skip = {"/admin/login", "/admin/logout", "/admin/app-releases/{release_id}/download"}
    pages = set()
    for route in _all_routes():
        path = route.path
        if not (path == "/admin" or path.startswith("/admin/")) or "GET" not in (route.methods or set()):
            continue
        if path in skip:
            continue
        pages.add(path.replace("{user_id}", str(user["id"])))
    assert "/admin/users" in pages
    params = {"/admin/usage/endpoint": {"method": "GET", "path": "/media"}}
    for path in sorted(pages):
        if "{" in path:
            continue  # other ids (comment, release, ...) have no fixture here
        r = client.get(path, params=params.get(path), headers=admin_enabled)
        if "text/html" not in r.headers.get("content-type", ""):
            continue  # CSV / JSON exports
        assert r.status_code == 200, (path, r.status_code)
        assert 'action="/admin/logout"' in r.text, path


# ---------- API token (scripts: the APK upload) ----------


def test_api_token_reaches_upload_route(client, admin_enabled):
    r = client.post("/admin/app-releases/999/delete", headers={"Authorization": f"Bearer {ADMIN_API_TOKEN}"})
    assert r.status_code == 404  # authorised; the release just doesn't exist


def test_wrong_api_token_401(client, admin_enabled):
    r = client.post("/admin/app-releases/999/delete", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_basic_auth_on_api_route_401(client, admin_enabled):
    r = client.post("/admin/app-releases/999/delete", auth=ADMIN_CREDS)
    assert r.status_code == 401


def test_api_token_unset_never_matches(client, admin_enabled, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_token", "")
    r = client.post("/admin/app-releases/999/delete", headers={"Authorization": "Bearer "})
    assert r.status_code == 401


def test_api_token_does_not_open_html_pages(client, admin_enabled):
    r = client.get("/admin", headers={"Authorization": f"Bearer {ADMIN_API_TOKEN}"}, follow_redirects=False)
    assert r.status_code == 303
