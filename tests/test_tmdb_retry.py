#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000

Retry/backoff behavior of tmdb_get against transient TMDB failures (429s,
5xx, network errors) — see docs/backlog.md's "Transient TMDB failures
permanently degrade an entry" and tmdb_http.py's tmdb_get docstring.
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
    """Retries are exercised for real, but must not actually wait — records
    the delays instead so a test can assert backoff/Retry-After behavior."""
    delays: list[float] = []
    monkeypatch.setattr(tmdb_http.time, "sleep", lambda s: delays.append(s))
    return delays


def _queue(monkeypatch, responses: list):
    calls = {"n": 0}

    def fake_get(url, **kw):
        item = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(tmdb_http.http_client, "get", fake_get)
    return calls


def test_retries_on_429_then_succeeds(monkeypatch, _no_real_sleep):
    calls = _queue(monkeypatch, [FakeResponse(429), FakeResponse(200, {"ok": True})])
    data = tmdb_http.tmdb_get("/movie/1", cache=False)
    assert data == {"ok": True}
    assert calls["n"] == 2
    assert len(_no_real_sleep) == 1


def test_retries_on_5xx_then_succeeds(monkeypatch, _no_real_sleep):
    calls = _queue(monkeypatch, [FakeResponse(503), FakeResponse(200, {"ok": True})])
    data = tmdb_http.tmdb_get("/movie/1", cache=False)
    assert data == {"ok": True}
    assert calls["n"] == 2


def test_retries_on_network_error_then_succeeds(monkeypatch, _no_real_sleep):
    calls = _queue(monkeypatch, [httpx.ConnectError("boom"), FakeResponse(200, {"ok": True})])
    data = tmdb_http.tmdb_get("/movie/1", cache=False)
    assert data == {"ok": True}
    assert calls["n"] == 2


def test_gives_up_after_max_attempts(monkeypatch, _no_real_sleep):
    calls = _queue(monkeypatch, [FakeResponse(429), FakeResponse(429), FakeResponse(429)])
    with pytest.raises(HTTPException) as exc:
        tmdb_http.tmdb_get("/movie/1", cache=False)
    assert exc.value.status_code == 502
    assert calls["n"] == tmdb_http._MAX_ATTEMPTS
    assert len(_no_real_sleep) == tmdb_http._MAX_ATTEMPTS - 1


def test_does_not_retry_404(monkeypatch, _no_real_sleep):
    calls = _queue(monkeypatch, [FakeResponse(404)])
    with pytest.raises(HTTPException) as exc:
        tmdb_http.tmdb_get("/movie/1", cache=False)
    assert exc.value.status_code == 404
    assert calls["n"] == 1
    assert _no_real_sleep == []


def test_does_not_retry_401(monkeypatch, _no_real_sleep):
    calls = _queue(monkeypatch, [FakeResponse(401)])
    with pytest.raises(HTTPException) as exc:
        tmdb_http.tmdb_get("/movie/1", cache=False)
    assert exc.value.status_code == 502
    assert calls["n"] == 1
    assert _no_real_sleep == []


def test_honors_retry_after_header_capped(monkeypatch, _no_real_sleep):
    calls = _queue(
        monkeypatch,
        [FakeResponse(429, headers={"Retry-After": "30"}), FakeResponse(200, {"ok": True})],
    )
    tmdb_http.tmdb_get("/movie/1", cache=False)
    assert calls["n"] == 2
    assert _no_real_sleep == [tmdb_http._RETRY_AFTER_CAP_SECONDS]
