#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/09/01
Revised: 2026/09/02 10:58:43.396505

routers/tmdb.py coverage gaps: _map_results/skip, _map_local_titles with
poster_overrides, search/trending/popular success and fallback paths,
_map_details TV runtime fallback, image proxy error paths, alternate
posters/backdrops/episode-stills endpoints, fetch_poster_bytes, and film
credits.
"""

import httpx
import pytest
from fastapi import HTTPException, status

from renar_backend.routers import tmdb as tmdb_router
from renar_backend.tmdb import tmdb_http, tmdb_store

RAW_TV = {
    "name": "The Show",
    "first_air_date": "2020-01-05",
    "overview": "A show about tests.",
    "tagline": "Trust nothing.",
    "status": "Returning Series",
    "episode_run_time": [40],
    "number_of_episodes": 16,
    "number_of_seasons": 2,
    "genres": [{"name": "Drama"}],
    "poster_path": "/p.jpg",
    "next_episode_to_air": {"air_date": "2030-01-01"},
}

RAW_FILM = {
    "title": "The Film",
    "release_date": "2020-06-01",
    "runtime": 120,
    "overview": "A film.",
    "poster_path": "/fp.jpg",
}


def add_show(client, headers, monkeypatch, tmdb_id: int = 100) -> dict:
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_TV)
    r = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "The Show", "tmdb_id": tmdb_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def add_film(client, headers, monkeypatch, tmdb_id: int = 200) -> dict:
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: RAW_FILM)
    r = client.post(
        "/media",
        json={"media_type": "film", "title": "The Film", "tmdb_id": tmdb_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# _map_results
# ---------------------------------------------------------------------------


def test_map_results_skips_result_without_title_or_name():
    """Results without a 'name'/'title' field must be silently dropped."""
    raw = [
        {"id": 1},  # no name or title → continue (line 80)
        {"id": 2, "name": "Good Show", "first_air_date": "2021-01-01", "vote_average": 7.5, "vote_count": 500},
    ]
    results = tmdb_router._map_results(raw)
    assert len(results) == 1
    assert results[0]["tmdb_id"] == 2


def test_map_results_respects_limit():
    raw = [{"id": i, "name": f"Show {i}"} for i in range(30)]
    assert len(tmdb_router._map_results(raw, limit=5)) == 5


# ---------------------------------------------------------------------------
# _map_local_titles
# ---------------------------------------------------------------------------


def test_map_local_titles_applies_poster_overrides():
    """poster_overrides must replace the default poster_url on a matched title."""

    class FakeTitle:
        tmdb_id = 1
        title = "Local Show"
        year = 2021
        poster_url = "https://image.tmdb.org/t/p/w500/default.jpg"
        overview = "An overview"

    results = tmdb_router._map_local_titles([FakeTitle()], poster_overrides={1: "https://example.com/custom.jpg"})
    assert results[0]["poster_url"] == "https://example.com/custom.jpg"


def test_map_local_titles_no_overrides_keeps_default():
    class FakeTitle:
        tmdb_id = 2
        title = "Another Show"
        year = 2022
        poster_url = "https://image.tmdb.org/t/p/w500/def.jpg"
        overview = ""

    results = tmdb_router._map_local_titles([FakeTitle()], poster_overrides=None)
    assert results[0]["poster_url"] == "https://image.tmdb.org/t/p/w500/def.jpg"


# ---------------------------------------------------------------------------
# _map_details
# ---------------------------------------------------------------------------


def test_map_details_tv_runtime_from_last_episode_to_air():
    """When episode_run_time is empty, runtime must come from last_episode_to_air."""
    data = {
        "episode_run_time": [],
        "last_episode_to_air": {"runtime": 47},
        "number_of_episodes": 10,
        "number_of_seasons": 1,
        "seasons": [],
    }
    result = tmdb_router._map_details("tv_show", 1, data)
    assert result["runtime_minutes"] == 47


def test_map_details_film_sets_runtime():
    data = {"title": "The Film", "release_date": "2021-01-01", "runtime": 130}
    result = tmdb_router._map_details("film", 1, data)
    assert result["runtime_minutes"] == 130
    assert result["total_episodes"] is None


# ---------------------------------------------------------------------------
# /search — happy path (lines 139-140)
# ---------------------------------------------------------------------------


def test_search_tmdb_happy_path_returns_results(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {
            "results": [
                {
                    "id": 42,
                    "name": "Dark",
                    "first_air_date": "2017-12-01",
                    "poster_path": "/dark.jpg",
                    "overview": "Time travel.",
                    "vote_average": 8.8,
                    "vote_count": 3000,
                }
            ]
        },
    )
    r = client.get("/tmdb/search", params={"media_type": "tv_show", "query": "dark"}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["title"] == "Dark"
    assert r.json()[0]["vote_average"] == 88


def test_search_tmdb_skips_result_without_title(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {
            "results": [
                {"id": 1},  # no name → skipped
                {"id": 2, "name": "Valid", "vote_average": 0, "vote_count": 0},
            ]
        },
    )
    r = client.get("/tmdb/search", params={"media_type": "tv_show", "query": "test"}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["tmdb_id"] == 2


# ---------------------------------------------------------------------------
# /trending — fallback (lines 152-158)
# ---------------------------------------------------------------------------


def test_trending_falls_back_to_local_catalog_on_502(client, alice, monkeypatch):
    _, headers = alice
    add_show(client, headers, monkeypatch, tmdb_id=100)

    def _trending_down(path, params=None):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB trending down")

    monkeypatch.setattr(tmdb_router, "tmdb_get", _trending_down)
    r = client.get("/tmdb/trending", params={"media_type": "tv_show"}, headers=headers)
    assert r.status_code == 200
    ids = [x["tmdb_id"] for x in r.json()]
    assert 100 in ids


def test_trending_non_down_error_propagates(client, alice, monkeypatch):
    _, headers = alice

    def _tmdb_404(path, params=None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    monkeypatch.setattr(tmdb_router, "tmdb_get", _tmdb_404)
    r = client.get("/tmdb/trending", params={"media_type": "tv_show"}, headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /popular — success path (lines 180-182) and non-down error (line 175)
# ---------------------------------------------------------------------------


def test_popular_tmdb_happy_path_returns_results(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {
            "results": [
                {
                    "id": 5,
                    "name": "Popular Show",
                    "first_air_date": "2022-01-01",
                    "vote_average": 7.0,
                    "vote_count": 100,
                }
            ]
        },
    )
    r = client.get("/tmdb/popular", params={"media_type": "tv_show"}, headers=headers)
    assert r.status_code == 200
    assert r.json()[0]["title"] == "Popular Show"


def test_popular_non_down_error_propagates(client, alice, monkeypatch):
    """A non-502/503/504 TMDB error must propagate, not fall back to local catalog."""
    _, headers = alice

    def _tmdb_401(path, params=None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    monkeypatch.setattr(tmdb_router, "tmdb_get", _tmdb_401)
    r = client.get("/tmdb/popular", params={"media_type": "tv_show"}, headers=headers)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# /image proxy error paths
# ---------------------------------------------------------------------------


def test_image_proxy_invalid_size_returns_404(client):
    """Sizes not in ALLOWED_IMAGE_SIZES must be rejected."""
    r = client.get("/tmdb/image/w9999/poster.jpg")
    assert r.status_code == 404


def test_image_proxy_path_traversal_returns_404(client):
    r = client.get("/tmdb/image/w342/../../etc/passwd.jpg")
    assert r.status_code == 404


def test_image_proxy_invalid_extension_returns_404(client):
    r = client.get("/tmdb/image/w342/poster.bmp")
    assert r.status_code == 404


def test_image_proxy_http_error_returns_502(client, monkeypatch):
    def raise_error(url, **kw):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(tmdb_http.http_client, "get", raise_error)
    r = client.get("/tmdb/image/w342/poster.jpg")
    assert r.status_code == 502


def test_image_proxy_non_200_tmdb_response_returns_404(client, monkeypatch):
    class FakeNotFound:
        status_code = 404
        content = b""

    monkeypatch.setattr(tmdb_http.http_client, "get", lambda url, **kw: FakeNotFound())
    r = client.get("/tmdb/image/w342/poster.jpg")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /posters (alternate_posters)
# ---------------------------------------------------------------------------


def test_alternate_posters_returns_list(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {"posters": [{"file_path": "/p1.jpg"}, {"file_path": "/p2.jpg"}]},
    )
    r = client.get("/tmdb/posters", params={"media_type": "film", "tmdb_id": 1}, headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["url"].endswith("/p1.jpg")
    assert "preview_url" in items[0]


def test_alternate_posters_skips_entry_without_file_path(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {"posters": [{"file_path": "/ok.jpg"}, {"other": "no_file_path"}]},
    )
    r = client.get("/tmdb/posters", params={"media_type": "film", "tmdb_id": 1}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# /backdrops (alternate_backdrops)
# ---------------------------------------------------------------------------


def test_alternate_backdrops_returns_list(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {"backdrops": [{"file_path": "/b1.jpg"}]},
    )
    r = client.get("/tmdb/backdrops", params={"media_type": "tv_show", "tmdb_id": 1}, headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert items[0]["url"].endswith("/b1.jpg")
    assert "preview_url" in items[0]


# ---------------------------------------------------------------------------
# /episode-stills (alternate_episode_stills)
# ---------------------------------------------------------------------------


def test_alternate_episode_stills_returns_list(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        tmdb_router,
        "tmdb_get",
        lambda path, params=None: {"stills": [{"file_path": "/s1.jpg"}, {"file_path": "/s2.jpg"}]},
    )
    r = client.get(
        "/tmdb/episode-stills",
        params={"tmdb_id": 1, "season": 1, "episode": 3},
        headers=headers,
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert items[0]["url"].endswith("/s1.jpg")


# ---------------------------------------------------------------------------
# fetch_poster_bytes
# ---------------------------------------------------------------------------


def test_fetch_poster_bytes_happy_path(monkeypatch):
    class FakeOK:
        status_code = 200
        content = b"image bytes"

    monkeypatch.setattr(tmdb_http.http_client, "get", lambda url, **kw: FakeOK())
    result = tmdb_router.fetch_poster_bytes("https://image.tmdb.org/t/p/w500/poster.jpg")
    assert result == b"image bytes"


def test_fetch_poster_bytes_http_error_raises_502(monkeypatch):
    def raise_error(url, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(tmdb_http.http_client, "get", raise_error)
    from fastapi import HTTPException as FHTTPException

    with pytest.raises(FHTTPException) as exc:
        tmdb_router.fetch_poster_bytes("https://image.tmdb.org/t/p/w500/poster.jpg")
    assert exc.value.status_code == 502


def test_fetch_poster_bytes_non_200_raises_404(monkeypatch):
    class FakeNotFound:
        status_code = 404
        content = b""

    monkeypatch.setattr(tmdb_http.http_client, "get", lambda url, **kw: FakeNotFound())
    from fastapi import HTTPException as FHTTPException

    with pytest.raises(FHTTPException) as exc:
        tmdb_router.fetch_poster_bytes("https://image.tmdb.org/t/p/w500/poster.jpg")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# /credits — film path (lines 416-417: directors + "Directed by")
# ---------------------------------------------------------------------------


def test_credits_film_returns_directors_and_directed_by_role(client, alice, monkeypatch):
    _, headers = alice
    add_film(client, headers, monkeypatch, tmdb_id=200)

    credits_data = {
        "cast": [{"name": "Actor A", "character": "Lead"}],
        "crew": [
            {"name": "Dan Director", "job": "Director", "profile_path": "/d.jpg"},
            {"name": "Eve Editor", "job": "Editor"},
        ],
    }
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: credits_data)
    r = client.get("/tmdb/credits", params={"media_type": "film", "tmdb_id": 200}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["director_role"] == "Directed by"
    assert any(d["name"] == "Dan Director" for d in body["directors"])
    # Editor must appear in crew, not directors.
    assert not any(d["name"] == "Eve Editor" for d in body["directors"])
    assert any(c["name"] == "Eve Editor" for c in body["crew"])


def test_credits_film_untracked_title_still_works(client, alice, monkeypatch):
    """Film credits endpoint must work even when the title is not in the library."""
    _, headers = alice
    credits_data = {
        "cast": [],
        "crew": [{"name": "Bob", "job": "Director"}],
    }
    monkeypatch.setattr(tmdb_store, "tmdb_get", lambda path, params=None, cache=True: credits_data)
    r = client.get("/tmdb/credits", params={"media_type": "film", "tmdb_id": 999}, headers=headers)
    assert r.status_code == 200
    assert r.json()["director_role"] == "Directed by"
