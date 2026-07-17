#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/13 10:35:00.000000
Revised: 2026/07/13 10:35:00.000000

YouTube video_info endpoint: URL parsing, ISO 8601 duration decoding, and
the 404/422 paths — the pieces that don't depend on real Data API access.
"""

import pytest

from renar_backend.config import settings
from renar_backend.routers import youtube as youtube_router

VIDEO_ITEM = {
    "snippet": {
        "title": "Test Video",
        "channelTitle": "Test Channel",
        "description": "A" * 2000,  # long enough to exercise the 1000-char truncation
        "thumbnails": {"medium": {"url": "https://img.example/medium.jpg"}},
        "publishedAt": "2024-03-15T12:00:00Z",
    },
    "contentDetails": {"duration": "PT1H2M3S"},
    "statistics": {"viewCount": "12345"},
}


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", "test-key")
    youtube_router._video_info_cache._data.clear()


def test_video_info_parses_url_and_returns_fields(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(
        youtube_router._http, "get", lambda url, params=None: FakeResponse(200, {"items": [VIDEO_ITEM]})
    )

    r = client.get(
        "/youtube/video_info",
        params={"url": "https://www.youtube.com/watch?v=abcdefghijk"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["video_id"] == "abcdefghijk"
    assert body["title"] == "Test Video"
    assert body["channel"] == "Test Channel"
    assert body["overview"] == "A" * 1000
    assert body["thumbnail_url"] == "https://img.example/medium.jpg"
    assert body["year"] == 2024
    assert body["duration_seconds"] == 3723
    assert body["view_count"] == 12345
    assert body["url"] == "https://www.youtube.com/watch?v=abcdefghijk"


def test_video_info_rejects_non_youtube_url(client, alice):
    _, headers = alice
    r = client.get("/youtube/video_info", params={"url": "https://example.com/not-a-video"}, headers=headers)
    assert r.status_code == 422


def test_video_info_404_when_video_missing(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(youtube_router._http, "get", lambda url, params=None: FakeResponse(200, {"items": []}))

    r = client.get(
        "/youtube/video_info",
        params={"url": "https://youtu.be/abcdefghijk"},
        headers=headers,
    )
    assert r.status_code == 404


def test_video_info_missing_duration_or_views_are_none(client, alice, monkeypatch):
    _, headers = alice
    sparse_item = {
        "snippet": {"title": "No Stats", "channelTitle": "C", "publishedAt": "2024-01-01T00:00:00Z"},
        "contentDetails": {},
        "statistics": {},
    }
    monkeypatch.setattr(
        youtube_router._http, "get", lambda url, params=None: FakeResponse(200, {"items": [sparse_item]})
    )

    r = client.get(
        "/youtube/video_info",
        params={"url": "https://www.youtube.com/watch?v=abcdefghijk"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["duration_seconds"] is None
    assert body["view_count"] is None
