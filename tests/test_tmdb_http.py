#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/09/01
Revised: 2026/09/02 10:58:40.837886

In-memory cache hit/miss, JWT Bearer auth, non-numeric Retry-After fallback,
and all-network-error exhaustion in tmdb_http.tmdb_get / _retry_delay.

Follows the same no-real-sleep pattern as test_tmdb_retry.py.
"""

import httpx
import pytest
from fastapi import HTTPException

from renar_backend.config import settings
from renar_backend.tmdb import tmdb_http


class FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def _tmdb_key(monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "test-key")


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(tmdb_http.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def _clear_cache():
    tmdb_http._cache._data.clear()
    yield
    tmdb_http._cache._data.clear()


# ---------------------------------------------------------------------------
# _retry_delay
# ---------------------------------------------------------------------------


def test_retry_delay_non_numeric_retry_after_falls_back_to_exponential():
    """Non-numeric Retry-After header must fall through to exponential backoff."""
    delay = tmdb_http._retry_delay(1, "not-a-number")
    assert delay == tmdb_http._BACKOFF_BASE_SECONDS * (2**0)


def test_retry_delay_numeric_retry_after_is_capped():
    delay = tmdb_http._retry_delay(1, "999")
    assert delay == tmdb_http._RETRY_AFTER_CAP_SECONDS


def test_retry_delay_none_retry_after_uses_exponential():
    delay = tmdb_http._retry_delay(2, None)
    assert delay == tmdb_http._BACKOFF_BASE_SECONDS * (2**1)


# ---------------------------------------------------------------------------
# cache hit / miss / store
# ---------------------------------------------------------------------------


def test_cache_hit_skips_http_call(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(tmdb_http.http_client, "get", fake_get)

    data1 = tmdb_http.tmdb_get("/movie/1", cache=True)
    assert data1 == {"ok": True}
    assert calls["n"] == 1

    # Second call must be served from cache without a new HTTP request.
    data2 = tmdb_http.tmdb_get("/movie/1", cache=True)
    assert data2 == {"ok": True}
    assert calls["n"] == 1


def test_cache_stores_result_after_successful_fetch(monkeypatch):
    payload = {"cached": True}
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        return FakeResponse(200, payload)

    monkeypatch.setattr(tmdb_http.http_client, "get", fake_get)

    tmdb_http.tmdb_get("/movie/2", cache=True)
    tmdb_http.tmdb_get("/movie/2", cache=True)
    # Result written to cache (line 138) means the second call costs no HTTP.
    assert calls["n"] == 1


def test_cache_disabled_fetches_every_time(monkeypatch):
    """cache=False must never serve a cached value — each call hits the network."""
    call_count = {"n": 0}

    def counting_get(url, **kw):
        call_count["n"] += 1
        return FakeResponse(200, {"call": call_count["n"]})

    monkeypatch.setattr(tmdb_http.http_client, "get", counting_get)

    d1 = tmdb_http.tmdb_get("/movie/5", cache=False)
    d2 = tmdb_http.tmdb_get("/movie/5", cache=False)
    assert d1 != d2
    assert call_count["n"] == 2


def test_cache_params_are_part_of_the_key(monkeypatch):
    """Calls with different params must be cached independently."""
    responses = iter([{"p": 1}, {"p": 2}])
    monkeypatch.setattr(tmdb_http.http_client, "get", lambda url, **kw: FakeResponse(200, next(responses)))

    d1 = tmdb_http.tmdb_get("/movie/3", params={"a": "1"}, cache=True)
    d2 = tmdb_http.tmdb_get("/movie/3", params={"a": "2"}, cache=True)
    assert d1 != d2


# ---------------------------------------------------------------------------
# JWT Bearer auth
# ---------------------------------------------------------------------------


def test_jwt_api_key_sent_as_authorization_header(monkeypatch):
    jwt_key = "eyJhbGciOiJIUzI1NiJ9.test.payload"
    monkeypatch.setattr(settings, "tmdb_api_key", jwt_key)

    captured = {}

    def fake_get(url, params=None, headers=None):
        captured["headers"] = dict(headers or {})
        captured["params"] = dict(params or {})
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(tmdb_http.http_client, "get", fake_get)
    tmdb_http.tmdb_get("/movie/1", cache=False)

    assert captured["headers"].get("Authorization") == f"Bearer {jwt_key}"
    assert "api_key" not in captured["params"]


def test_non_jwt_api_key_sent_as_query_param(monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "v3key-abc")

    captured = {}

    def fake_get(url, params=None, headers=None):
        captured["params"] = dict(params or {})
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(tmdb_http.http_client, "get", fake_get)
    tmdb_http.tmdb_get("/movie/1", cache=False)

    assert captured["params"].get("api_key") == "v3key-abc"
    assert "Authorization" not in captured.get("headers", {})


# ---------------------------------------------------------------------------
# All attempts fail with network error → resp is None → 502
# ---------------------------------------------------------------------------


def test_all_attempts_network_error_raises_502(monkeypatch):
    calls = {"n": 0}

    def fail_always(url, **kw):
        calls["n"] += 1
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(tmdb_http.http_client, "get", fail_always)

    with pytest.raises(HTTPException) as exc:
        tmdb_http.tmdb_get("/movie/1", cache=False)

    assert exc.value.status_code == 502
    assert "Could not reach TMDB" in exc.value.detail
    # All attempts must have been tried.
    assert calls["n"] == tmdb_http._MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Missing API key raises 503
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_503(monkeypatch):
    monkeypatch.setattr(settings, "tmdb_api_key", "")

    with pytest.raises(HTTPException) as exc:
        tmdb_http.tmdb_get("/movie/1", cache=False)

    assert exc.value.status_code == 503
