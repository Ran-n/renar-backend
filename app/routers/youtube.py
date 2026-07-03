"""Resolve YouTube URLs to title/channel/thumbnail via oEmbed (no API key)."""
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/youtube", tags=["youtube"])

_http = httpx.Client(timeout=10)

YT_URL_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


@router.get("/resolve")
def resolve_youtube(
    url: str = Query(min_length=5, max_length=500),
    user: User = Depends(get_current_user),
):
    match = YT_URL_RE.search(url)
    if not match:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="That does not look like a YouTube video URL")
    video_id = match.group(1)
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    try:
        resp = _http.get("https://www.youtube.com/oembed",
                         params={"url": canonical, "format": "json"})
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Could not reach YouTube")
    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Video not found (private or deleted?)")
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"YouTube error {resp.status_code}")
    data = resp.json()
    return {
        "url": canonical,
        "title": data.get("title"),
        "channel": data.get("author_name"),
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    }
