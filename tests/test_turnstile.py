#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/19 00:00:00.000000
Revised: 2026/08/21 16:27:43.371727

Cloudflare Turnstile gate on /auth/register. Mocks the siteverify HTTP call
(no real network dependency in the suite) — verify_turnstile() itself is a
thin wrapper around that one call, so mocking it is exercising the same
code path a real Cloudflare response would hit.
"""

from renar_backend.config import settings
from renar_backend.users import turnstile as turnstile_module

PASSWORD = "password123"


class _FakeResponse:
    def __init__(self, success: bool):
        self._success = success

    def raise_for_status(self):
        pass

    def json(self):
        return {"success": self._success}


def _configure_turnstile(monkeypatch, *, siteverify_success: bool):
    """Enable Turnstile for one test and return a callable that restores the
    conftest default (unconfigured — see conftest.py's env setup)."""
    settings.prod_turnstile_site_key = "test-site-key"
    settings.prod_turnstile_secret_key = "test-secret-key"
    monkeypatch.setattr(turnstile_module.http_client, "post", lambda *a, **kw: _FakeResponse(siteverify_success))

    def cleanup():
        settings.prod_turnstile_site_key = ""
        settings.prod_turnstile_secret_key = ""

    return cleanup


def test_registration_status_exposes_site_key_when_configured(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        r = client.get("/auth/registration-status")
        assert r.status_code == 200
        assert r.json()["turnstile_site_key"] == "test-site-key"
    finally:
        cleanup()


def test_registration_status_hides_site_key_when_unconfigured(client):
    r = client.get("/auth/registration-status")
    assert r.status_code == 200
    assert r.json()["turnstile_site_key"] is None


def test_register_rejects_missing_token_when_configured(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        r = client.post(
            "/auth/register",
            json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
        )
        assert r.status_code == 400
        assert "verification" in r.json()["detail"].lower()
    finally:
        cleanup()


def test_register_rejects_failed_verification(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=False)
    try:
        r = client.post(
            "/auth/register",
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": PASSWORD,
                "turnstile_token": "bogus-token",
            },
        )
        assert r.status_code == 400
    finally:
        cleanup()


def test_register_succeeds_with_valid_token(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        r = client.post(
            "/auth/register",
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": PASSWORD,
                "turnstile_token": "good-token",
            },
        )
        assert r.status_code == 201, r.text
    finally:
        cleanup()


def test_register_unaffected_when_turnstile_unconfigured(client):
    # No monkeypatch, no configured keys — same as every other pre-existing
    # register test: the check is a no-op when TURNSTILE_SECRET_KEY is empty.
    r = client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


def test_turnstile_session_404_when_unconfigured(client):
    r = client.post("/auth/turnstile-session")
    assert r.status_code == 404


def test_turnstile_session_returns_session_and_site_key_when_configured(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        r = client.post("/auth/turnstile-session")
        assert r.status_code == 200
        body = r.json()
        assert body["site_key"] == "test-site-key"
        assert len(body["session_id"]) > 10
    finally:
        cleanup()


def test_turnstile_widget_serves_html_with_site_key(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        session_id = client.post("/auth/turnstile-session").json()["session_id"]
        r = client.get(f"/auth/turnstile-widget/{session_id}")
        assert r.status_code == 200
        assert 'data-sitekey="test-site-key"' in r.text
        assert "challenges.cloudflare.com/turnstile/v0/api.js" in r.text
    finally:
        cleanup()


def test_turnstile_widget_404_for_unknown_session(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        r = client.get("/auth/turnstile-widget/does-not-exist")
        assert r.status_code == 404
    finally:
        cleanup()


def test_turnstile_token_roundtrip_via_callback(client, monkeypatch):
    """The widget page's own JS hits turnstile-callback; the register screen
    polls turnstile-token — this is that round trip end to end."""
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        session_id = client.post("/auth/turnstile-session").json()["session_id"]

        r = client.get(f"/auth/turnstile-token/{session_id}")
        assert r.json()["token"] is None

        r = client.post(f"/auth/turnstile-callback/{session_id}", params={"token": "resolved-abc"})
        assert r.status_code == 200

        r = client.get(f"/auth/turnstile-token/{session_id}")
        assert r.json()["token"] == "resolved-abc"

        # token consumed on first successful poll — the session shouldn't
        # linger and answer the same token again
        r = client.get(f"/auth/turnstile-token/{session_id}")
        assert r.json()["token"] is None
    finally:
        cleanup()


def test_turnstile_callback_404_for_unknown_session(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        r = client.post("/auth/turnstile-callback/does-not-exist", params={"token": "x"})
        assert r.status_code == 404
    finally:
        cleanup()


def test_turnstile_enabled_flag_off_disables_check_even_with_keys_set(client, monkeypatch):
    """TURNSTILE_ENABLED=false must be a real off switch, independent of
    whether the keys are still populated — see config.py's own docstring on
    why the flag exists separately from the keys."""
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    settings.turnstile_enabled = False
    try:
        status_resp = client.get("/auth/registration-status")
        assert status_resp.json()["turnstile_site_key"] is None

        r = client.post(
            "/auth/register",
            json={"username": "alice", "email": "alice@example.com", "password": PASSWORD},
        )
        assert r.status_code == 201, r.text
    finally:
        settings.turnstile_enabled = True
        cleanup()


def test_registration_status_is_not_cacheable(client):
    """A carrier/ISP transparent proxy caching this response for even a few
    minutes would mean an admin's Turnstile toggle doesn't reliably take
    effect — see docs on this endpoint. Applies regardless of whether
    Turnstile is configured, so no monkeypatching needed here."""
    r = client.get("/auth/registration-status")
    assert r.headers["cache-control"] == "no-store"


def test_turnstile_token_is_not_cacheable(client, monkeypatch):
    """Even more important than registration-status: a cached stale
    {"token": null} would make the register screen's poll loop wait out its
    full timeout after the widget already resolved."""
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        session_id = client.post("/auth/turnstile-session").json()["session_id"]
        r = client.get(f"/auth/turnstile-token/{session_id}")
        assert r.headers["cache-control"] == "no-store"
    finally:
        cleanup()


def test_turnstile_widget_page_is_not_cacheable(client, monkeypatch):
    cleanup = _configure_turnstile(monkeypatch, siteverify_success=True)
    try:
        session_id = client.post("/auth/turnstile-session").json()["session_id"]
        r = client.get(f"/auth/turnstile-widget/{session_id}")
        assert r.headers["cache-control"] == "no-store"
    finally:
        cleanup()
