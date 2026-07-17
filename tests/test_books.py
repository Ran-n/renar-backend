#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 00:00:00.000000

Books router: Open Library search, trending, and cover-proxy endpoints.

Outbound HTTP calls are patched via monkeypatch on the module-level
httpx.Client instance (_http.get), following the same pattern as
test_youtube.py.
"""

import time

import httpx
import pytest

from renar_backend.routers import books as books_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OL_DOC = {
    "title": "The Pragmatic Programmer",
    "first_publish_year": 1999,
    "author_name": ["David Thomas", "Andrew Hunt"],
    "cover_i": 12345,
    "number_of_pages_median": 352,
}

OL_WORK = {
    "title": "Clean Code",
    "first_publish_year": 2008,
    "author_names": ["Robert C. Martin"],
    "cover_i": 67890,
    "number_of_pages_median": 431,
}


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset the module-level TTL cache and miss cache before every test."""
    books_router._cache._data.clear()
    books_router._cover_misses.clear()
    yield
    books_router._cache._data.clear()
    books_router._cover_misses.clear()


# ---------------------------------------------------------------------------
# /books/search
# ---------------------------------------------------------------------------


def test_search_happy_path(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(200, {"docs": [OL_DOC]}),
    )

    r = client.get("/books/search", params={"query": "pragmatic"}, headers=headers)
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    book = results[0]
    assert book["title"] == "The Pragmatic Programmer"
    assert book["year"] == 1999
    assert book["author"] == "David Thomas, Andrew Hunt"
    assert book["pages"] == 352
    assert book["poster_url"] == "/books/cover/12345"


def test_search_empty_results(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(200, {"docs": []}),
    )

    r = client.get("/books/search", params={"query": "zzzzzzzzzz"}, headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_search_upstream_non_200(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(503),
    )

    r = client.get("/books/search", params={"query": "python"}, headers=headers)
    assert r.status_code == 502


def test_search_network_error(client, alice, monkeypatch):
    _, headers = alice

    def _raise(url, params=None):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(books_router._http, "get", _raise)

    r = client.get("/books/search", params={"query": "python"}, headers=headers)
    assert r.status_code == 502


def test_search_skips_docs_without_title(client, alice, monkeypatch):
    _, headers = alice
    docs = [{"first_publish_year": 2000}, OL_DOC]  # first doc has no title
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(200, {"docs": docs}),
    )

    r = client.get("/books/search", params={"query": "anything"}, headers=headers)
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["title"] == "The Pragmatic Programmer"


def test_search_no_cover_id(client, alice, monkeypatch):
    _, headers = alice
    doc_no_cover = {**OL_DOC}
    doc_no_cover.pop("cover_i", None)
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(200, {"docs": [doc_no_cover]}),
    )

    r = client.get("/books/search", params={"query": "pragmatic"}, headers=headers)
    assert r.status_code == 200
    assert r.json()[0]["poster_url"] is None


def test_search_requires_auth(client):
    r = client.get("/books/search", params={"query": "python"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /books/trending
# ---------------------------------------------------------------------------


def test_trending_happy_path(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(200, {"works": [OL_WORK]}),
    )

    r = client.get("/books/trending", headers=headers)
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    book = results[0]
    assert book["title"] == "Clean Code"
    # trending uses author_names → mapped to author_name by the router
    assert book["author"] == "Robert C. Martin"


def test_trending_missing_works_key(client, alice, monkeypatch):
    """If OL returns a response without 'works', treat as empty list."""
    _, headers = alice
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(200, {}),
    )

    r = client.get("/books/trending", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_trending_upstream_non_200(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url, params=None: FakeResponse(429),
    )

    r = client.get("/books/trending", headers=headers)
    assert r.status_code == 502


def test_trending_network_error(client, alice, monkeypatch):
    _, headers = alice

    def _raise(url, params=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(books_router._http, "get", _raise)

    r = client.get("/books/trending", headers=headers)
    assert r.status_code == 502


def test_trending_requires_auth(client):
    r = client.get("/books/trending")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /books/cover/{cover_id}
# ---------------------------------------------------------------------------


def test_cover_happy_path(client, monkeypatch):
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url: FakeResponse(200, content=b"x" * 600),
    )

    r = client.get("/books/cover/12345")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers.get("cache-control", "").startswith("public")


def test_cover_not_found_tiny_content(client, monkeypatch):
    """OL returns < 500 bytes for unknown cover IDs — treat as 404."""
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url: FakeResponse(200, content=b"x" * 10),
    )

    r = client.get("/books/cover/99999")
    assert r.status_code == 404


def test_cover_not_found_non_200(client, monkeypatch):
    monkeypatch.setattr(
        books_router._http,
        "get",
        lambda url: FakeResponse(404, content=b""),
    )

    r = client.get("/books/cover/99999")
    assert r.status_code == 404


def test_cover_in_memory_miss_cache(client, monkeypatch):
    """A cover_id already in the miss cache must short-circuit without hitting OL."""
    called = []

    def _track(url):
        called.append(url)
        return FakeResponse(404, content=b"")

    monkeypatch.setattr(books_router._http, "get", _track)

    # Seed the miss cache with a future expiry
    books_router._cover_misses[55555] = time.time() + 3600

    r = client.get("/books/cover/55555")
    assert r.status_code == 404
    assert not called, "should have returned 404 from miss cache without calling OL"


def test_cover_network_error(client, monkeypatch):
    def _raise(url):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(books_router._http, "get", _raise)

    r = client.get("/books/cover/12345")
    assert r.status_code == 502
