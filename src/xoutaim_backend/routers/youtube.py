#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.124960
Revised: 2026/07/16 09:54:31.525197

Resolve YouTube URLs to title/channel/thumbnail via oEmbed (no API key), and
channel search / video listing via the YouTube Data API v3 (needs a key) for
the Explore YouTube tab.
"""

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import get_current_user
from ..config import settings
from ..http_cache import TTLCache
from ..models import User

router = APIRouter(prefix="/youtube", tags=["youtube"])
_log = logging.getLogger(__name__)

_http = httpx.Client(timeout=10)

DATA_API_BASE = "https://www.googleapis.com/youtube/v3"

YT_URL_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")
ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

# both channel and video search cost 100 quota units of the 10k/day default.
# channels rarely change, so cache those generously; video listings get a
# shorter TTL that still smooths repeat clicks while staying fresh for
# newly uploaded videos. videos.list (single-video details) costs only 1
# unit, so it can afford a shorter TTL that keeps view counts reasonably fresh.
_search_cache = TTLCache(ttl_seconds=12 * 3600, max_entries=512)
_videos_cache = TTLCache(ttl_seconds=15 * 60, max_entries=512)
_trending_cache = TTLCache(ttl_seconds=6 * 3600, max_entries=16)
_video_info_cache = TTLCache(ttl_seconds=3 * 3600, max_entries=512)


def _parse_duration_seconds(duration: str) -> int | None:
    match = ISO8601_DURATION_RE.fullmatch(duration)
    if not match:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _thumbnail_url(snippet: dict) -> str | None:
    thumbnails = snippet.get("thumbnails", {})
    return (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")


def _data_api_get(path: str, params: dict, cache: TTLCache | None = None) -> dict:
    if not settings.youtube_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="YouTube search is not configured — set YOUTUBE_API_KEY in the backend .env",
        )
    cache_key = (path, tuple(sorted(params.items())))
    if cache is not None:
        hit = cache.get(cache_key)
        if hit is not None:
            return hit
    try:
        resp = _http.get(f"{DATA_API_BASE}{path}", params={**params, "key": settings.youtube_api_key})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach YouTube") from exc
    if resp.status_code == 403:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="YouTube rejected the API key (or quota exceeded)"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"YouTube error {resp.status_code}")
    data = resp.json()
    if cache is not None:
        cache.put(cache_key, data)
    return data


@router.get("/resolve")
def resolve_youtube(
    url: str = Query(min_length=5, max_length=500),
    user: User = Depends(get_current_user),
):
    match = YT_URL_RE.search(url)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="That does not look like a YouTube video URL"
        )
    video_id = match.group(1)
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    try:
        resp = _http.get("https://www.youtube.com/oembed", params={"url": canonical, "format": "json"})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach YouTube") from exc
    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found (private or deleted?)")
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"YouTube error {resp.status_code}")
    data = resp.json()
    return {
        "url": canonical,
        "title": data.get("title"),
        "channel": data.get("author_name"),
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    }


@router.get("/search_channels")
def search_channels(
    query: str = Query(min_length=1, max_length=200),
    user: User = Depends(get_current_user),
):
    data = _data_api_get(
        "/search",
        {"part": "snippet", "type": "channel", "q": query, "maxResults": 10},
        cache=_search_cache,
    )
    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        channel_id = item.get("id", {}).get("channelId")
        if not channel_id:
            continue
        results.append({
            "channel_id": channel_id,
            "title": snippet.get("title"),
            "thumbnail_url": _thumbnail_url(snippet),
        })
    return results


@router.get("/trending_channels")
def trending_channels(
    region_code: str = Query(default="US", min_length=2, max_length=2),
    user: User = Depends(get_current_user),
):
    # there's no "trending channels" chart in the Data API, so this derives
    # one: pull the trending-videos chart (1 unit) and resolve the unique
    # channels behind those videos via a single batched channels.list call
    # (1 unit) — far cheaper than a search.list per channel (100 units each).
    videos_data = _data_api_get(
        "/videos",
        {"part": "snippet", "chart": "mostPopular", "regionCode": region_code, "maxResults": 50},
        cache=_trending_cache,
    )
    channel_ids = list(
        dict.fromkeys(
            item.get("snippet", {}).get("channelId")
            for item in videos_data.get("items", [])
            if item.get("snippet", {}).get("channelId")
        )
    )[:25]
    if not channel_ids:
        return []
    channels_data = _data_api_get(
        "/channels",
        {"part": "snippet", "id": ",".join(channel_ids)},
        cache=_trending_cache,
    )
    by_id = {item["id"]: item for item in channels_data.get("items", [])}
    results = []
    for channel_id in channel_ids:  # keep the chart's order (most-viewed video's channel first)
        item = by_id.get(channel_id)
        if not item:
            continue
        snippet = item.get("snippet", {})
        results.append({
            "channel_id": channel_id,
            "title": snippet.get("title"),
            "thumbnail_url": _thumbnail_url(snippet),
        })
    return results


@router.get("/channel_videos")
def channel_videos(
    channel_id: str = Query(min_length=1, max_length=64),
    page_token: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
):
    # playlistItems.list on the uploads playlist (1 quota unit) returns items
    # oldest-added-first with no way to reverse it, so browsing a channel
    # would open on its 2010s videos instead of anything recent. search.list
    # with order=date (100 units) gives newest-first directly.
    if not channel_id.startswith("UC"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Not a channel id")
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "type": "video",
        "order": "date",
        "maxResults": 20,
    }
    if page_token:
        params["pageToken"] = page_token
    data = _data_api_get("/search", params, cache=_videos_cache)
    videos = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId")
        if not video_id:
            continue
        videos.append({
            "video_id": video_id,
            "title": snippet.get("title"),
            "channel": snippet.get("channelTitle"),
            "thumbnail_url": _thumbnail_url(snippet),
            "published_at": snippet.get("publishedAt"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return {"videos": videos, "next_page_token": data.get("nextPageToken")}


@router.get("/video_info")
def video_info(
    url: str = Query(min_length=5, max_length=500),
    user: User = Depends(get_current_user),
):
    # single-video detail for the title page: description, duration, view
    # count — none of which channel_videos/search.list carries, since that's
    # a search result snippet rather than the video resource itself.
    match = YT_URL_RE.search(url)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="That does not look like a YouTube video URL"
        )
    video_id = match.group(1)
    data = _data_api_get(
        "/videos",
        {"part": "snippet,contentDetails,statistics", "id": video_id},
        cache=_video_info_cache,
    )
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found (private or deleted?)")
    item = items[0]
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    statistics = item.get("statistics", {})
    published_at = snippet.get("publishedAt")
    view_count = statistics.get("viewCount")
    return {
        "video_id": video_id,
        "title": snippet.get("title"),
        "channel": snippet.get("channelTitle"),
        "overview": (snippet.get("description") or "")[:1000] or None,
        "thumbnail_url": _thumbnail_url(snippet),
        "published_at": published_at,
        "year": int(published_at[:4]) if published_at else None,
        "duration_seconds": _parse_duration_seconds(content_details.get("duration") or ""),
        "view_count": int(view_count) if view_count is not None else None,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }
