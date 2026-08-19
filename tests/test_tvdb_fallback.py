#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 00:00:00.000000

Unit tests for _match_show's TVDB-as-fallback-identity branch — reached
only when every TMDB avenue (crosswalk by tvdb_id, TVDB-name retry, plain
title search) has come up empty. See test_imports.py for the full import-
level behavior (existing_map reconciliation, backfill on later TMDB match).
"""

import renar_backend.users.tvtime_import as imports_mod

EXTENDED = {
    "id": 200,
    "name": "No One Could Live Here",
    "aliases": [{"name": "Aqui no hay quien viva"}],
    "image": "https://artworks.thetvdb.com/banners/posters/200.jpg",
    "overview": "A building full of neighbors.",
    "status": {"name": "Ended"},
    "averageRuntime": 70,
    "year": "2003",
}

EPISODES = [
    {"season": 1, "episode_number": 1, "name": "Pilot", "air_date": "2003-09-22"},
    {"season": 1, "episode_number": 2, "name": "Episode Two", "air_date": "2003-09-29"},
    {"season": 2, "episode_number": 1, "name": "S2E1", "air_date": None},
]


def _no_tmdb_match(monkeypatch):
    """Every TMDB avenue _match_show tries comes up empty."""
    monkeypatch.setattr(imports_mod, "_find_tv_by_tvdb", lambda tvdb_id: None)
    monkeypatch.setattr(imports_mod, "_search_tv", lambda name: None)


def test_match_show_falls_back_to_tvdb_when_tmdb_has_nothing(monkeypatch):
    _no_tmdb_match(monkeypatch)
    monkeypatch.setattr(imports_mod, "fetch_series_extended", lambda tvdb_id: EXTENDED)
    monkeypatch.setattr(imports_mod, "fetch_series_episodes", lambda tvdb_id: EPISODES)

    found, details, tvdb_fallback = imports_mod._match_show("200", "Aqui no hay quien viva")

    assert found is None
    assert details == {}
    assert tvdb_fallback["tvdb_id"] == 200
    assert tvdb_fallback["name"] == "No One Could Live Here"
    assert tvdb_fallback["poster_url"] == "https://artworks.thetvdb.com/banners/posters/200.jpg"
    assert tvdb_fallback["total_episodes"] == 3
    assert tvdb_fallback["total_seasons"] == 2
    assert tvdb_fallback["episodes"] == EPISODES


def test_match_show_returns_nothing_when_tvdb_also_has_nothing(monkeypatch):
    _no_tmdb_match(monkeypatch)
    monkeypatch.setattr(imports_mod, "fetch_series_extended", lambda tvdb_id: None)

    found, details, tvdb_fallback = imports_mod._match_show("200", "Something Obscure")

    assert found is None
    assert details == {}
    assert tvdb_fallback is None


def test_match_show_skips_tvdb_fallback_without_a_tvdb_id():
    """TV Time only ever omits tv_show_id for a row with no show at all —
    _process_show already returns early for that — but _match_show itself
    must not crash or fetch anything if it's ever called with one empty."""
    found, details, tvdb_fallback = imports_mod._match_show("", "No TVDB id")
    assert found is None
    assert tvdb_fallback is None


def test_match_show_prefers_tmdb_over_tvdb(monkeypatch):
    monkeypatch.setattr(imports_mod, "_find_tv_by_tvdb", lambda tvdb_id: {"id": 501, "name": "TMDB Name"})
    monkeypatch.setattr(imports_mod, "tmdb_get", lambda path: {})
    fetch_calls = []
    monkeypatch.setattr(imports_mod, "fetch_series_extended", lambda tvdb_id: fetch_calls.append(tvdb_id))

    found, details, tvdb_fallback = imports_mod._match_show("200", "Some Show")

    assert found == {"id": 501, "name": "TMDB Name"}
    assert tvdb_fallback is None
    assert fetch_calls == []  # TVDB never consulted once TMDB resolves


def test_match_show_returns_none_when_extended_record_has_no_name(monkeypatch):
    """A malformed/empty extended record shouldn't be treated as a match."""
    _no_tmdb_match(monkeypatch)
    monkeypatch.setattr(imports_mod, "fetch_series_extended", lambda tvdb_id: {"id": 200})

    found, details, tvdb_fallback = imports_mod._match_show("200", "Whatever")
    assert tvdb_fallback is None
