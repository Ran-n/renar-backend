"""Book catalog via Open Library (free, no API key)."""
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/books", tags=["books"])

OL_BASE = "https://openlibrary.org"
COVER_BASE = "https://covers.openlibrary.org/b/id"

CACHE_TTL_SECONDS = 30 * 60
_cache: dict[tuple, tuple[float, dict]] = {}

_http = httpx.Client(
    timeout=15,
    follow_redirects=True,  # covers.openlibrary.org 302s to archive.org
    headers={"User-Agent": "Xoutaim/0.1 (personal media tracker)"},
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)


def _ol_get(path: str, params: dict | None = None) -> dict:
    key = (path, tuple(sorted((params or {}).items())))
    hit = _cache.get(key)
    now = time.time()
    if hit and hit[0] > now:
        return hit[1]
    try:
        resp = _http.get(f"{OL_BASE}{path}", params=params)
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Could not reach Open Library")
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Open Library error {resp.status_code}")
    data = resp.json()
    _cache[key] = (now + CACHE_TTL_SECONDS, data)
    return data


def _map_docs(docs: list[dict], limit: int = 20) -> list[dict]:
    out = []
    for d in docs[:limit]:
        title = d.get("title")
        if not title:
            continue
        cover_id = d.get("cover_i") or d.get("cover_id")
        authors = d.get("author_name") or []
        if isinstance(authors, str):
            authors = [authors]
        out.append({
            "title": title,
            "year": d.get("first_publish_year"),
            "author": ", ".join(authors[:3]) or None,
            # served via our own cover proxy: cached, redirect-safe
            "poster_url": f"/books/cover/{cover_id}" if cover_id else None,
            "pages": d.get("number_of_pages_median"),
            "overview": None,
        })
    return out


COVER_TTL_SECONDS = 24 * 3600
_cover_cache: dict[int, tuple[float, bytes]] = {}


@router.get("/cover/{cover_id}")
def book_cover(cover_id: int):
    """Proxy + cache Open Library covers (public: <img>-style fetches)."""
    from fastapi.responses import Response
    now = time.time()
    hit = _cover_cache.get(cover_id)
    if hit and hit[0] > now:
        return Response(hit[1], media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    try:
        resp = _http.get(f"{COVER_BASE}/{cover_id}-M.jpg")
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Could not reach cover server")
    # OL returns a tiny placeholder for unknown ids — treat as missing
    if resp.status_code != 200 or len(resp.content) < 500:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No cover")
    if len(_cover_cache) > 1000:
        _cover_cache.clear()
    _cover_cache[cover_id] = (now + COVER_TTL_SECONDS, resp.content)
    return Response(resp.content, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/search")
def search_books(
    query: str = Query(min_length=1, max_length=200),
    user: User = Depends(get_current_user),
):
    data = _ol_get("/search.json", {
        "q": query, "limit": 10,
        "fields": "title,first_publish_year,author_name,cover_i,number_of_pages_median",
    })
    return _map_docs(data.get("docs", []), limit=10)


@router.get("/trending")
def trending_books(user: User = Depends(get_current_user)):
    data = _ol_get("/trending/daily.json", {"limit": 20})
    docs = data.get("works", [])
    for d in docs:  # trending uses slightly different field names
        d.setdefault("author_name", d.get("author_names") or [])
    return _map_docs(docs)
