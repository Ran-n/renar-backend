#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/27 11:17:50.133869

HTTP layer for TheTVDB v4 (tvdb_http.py) — previously the lowest-coverage
module in the backend (35%, per docs/backlog.md's Testing entry). Covers
login caching/forced-refresh, the 401-triggers-relogin-then-retry path, and
every "TVDB has nothing to offer" fallback (unconfigured, login failure,
non-200 response, network error) that every caller here treats as a plain
None rather than an error worth surfacing.
"""

import httpx
import pytest

from renar_backend.config import settings
from renar_backend.tvdb import tvdb_http


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


@pytest.fixture(autouse=True)
def _reset_token_cache():
    tvdb_http._token = None
    tvdb_http._token_expiry = 0.0
    yield
    tvdb_http._token = None
    tvdb_http._token_expiry = 0.0


@pytest.fixture(autouse=True)
def _tvdb_key(monkeypatch):
    monkeypatch.setattr(settings, "tvdb_api_key", "test-key")


def test_login_returns_none_when_api_key_unset(monkeypatch):
    monkeypatch.setattr(settings, "tvdb_api_key", "")
    assert tvdb_http._login() is None


def test_login_caches_token_across_calls(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kw):
        calls["n"] += 1
        return FakeResponse(200, {"data": {"token": "tok1"}})

    monkeypatch.setattr(tvdb_http.http_client, "post", fake_post)
    assert tvdb_http._login() == "tok1"
    assert tvdb_http._login() == "tok1"
    assert calls["n"] == 1  # second call served from cache, no second POST


def test_login_force_bypasses_cache(monkeypatch):
    tokens = iter(["tok1", "tok2"])

    def fake_post(url, **kw):
        return FakeResponse(200, {"data": {"token": next(tokens)}})

    monkeypatch.setattr(tvdb_http.http_client, "post", fake_post)
    assert tvdb_http._login() == "tok1"
    assert tvdb_http._login(force=True) == "tok2"


def test_login_returns_none_on_request_failure(monkeypatch):
    def fake_post(url, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(tvdb_http.http_client, "post", fake_post)
    assert tvdb_http._login() is None


def test_tvdb_get_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "tvdb_api_key", "")
    assert tvdb_http.tvdb_get("/series/1") is None


def test_tvdb_get_returns_none_when_login_fails(monkeypatch):
    monkeypatch.setattr(tvdb_http, "_login", lambda force=False: None)
    assert tvdb_http.tvdb_get("/series/1") is None


def test_tvdb_get_happy_path(monkeypatch):
    monkeypatch.setattr(tvdb_http, "_login", lambda force=False: "tok1")
    monkeypatch.setattr(tvdb_http.http_client, "get", lambda url, **kw: FakeResponse(200, {"data": {"name": "Dark"}}))
    assert tvdb_http.tvdb_get("/series/1") == {"name": "Dark"}


def test_tvdb_get_non_200_returns_none(monkeypatch):
    monkeypatch.setattr(tvdb_http, "_login", lambda force=False: "tok1")
    monkeypatch.setattr(tvdb_http.http_client, "get", lambda url, **kw: FakeResponse(404))
    assert tvdb_http.tvdb_get("/series/1") is None


def test_tvdb_get_401_relogs_in_and_retries(monkeypatch):
    login_calls = {"n": 0}

    def fake_login(force=False):
        login_calls["n"] += 1
        return "tok2" if force else "tok1"

    responses = iter([FakeResponse(401), FakeResponse(200, {"data": {"name": "Dark"}})])
    monkeypatch.setattr(tvdb_http, "_login", fake_login)
    monkeypatch.setattr(tvdb_http.http_client, "get", lambda url, **kw: next(responses))

    assert tvdb_http.tvdb_get("/series/1") == {"name": "Dark"}
    assert login_calls["n"] == 2  # initial + forced relogin


def test_tvdb_get_401_then_relogin_fails_returns_none(monkeypatch):
    def fake_login(force=False):
        return None if force else "tok1"

    monkeypatch.setattr(tvdb_http, "_login", fake_login)
    monkeypatch.setattr(tvdb_http.http_client, "get", lambda url, **kw: FakeResponse(401))
    assert tvdb_http.tvdb_get("/series/1") is None


def test_tvdb_get_returns_none_on_request_exception(monkeypatch):
    monkeypatch.setattr(tvdb_http, "_login", lambda force=False: "tok1")

    def fake_get(url, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(tvdb_http.http_client, "get", fake_get)
    assert tvdb_http.tvdb_get("/series/1") is None
