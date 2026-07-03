"""Proxy search against TMDB so the API key never reaches clients."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import get_current_user
from ..config import settings
from ..models import User

router = APIRouter(prefix="/tmdb", tags=["tmdb"])

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w342"

SEARCH_PATHS = {"film": "/search/movie", "tv_show": "/search/tv"}


@router.get("/search")
def search_tmdb(
    query: str = Query(min_length=1, max_length=200),
    media_type: str = Query(pattern="^(film|tv_show)$"),
    user: User = Depends(get_current_user),
):
    if not settings.tmdb_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TMDB is not configured — set TMDB_API_KEY in the backend .env",
        )

    params: dict = {"query": query, "include_adult": "false"}
    headers = {}
    # v4 read access tokens are JWTs sent as Bearer; v3 keys go in the query string
    if settings.tmdb_api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.tmdb_api_key}"
    else:
        params["api_key"] = settings.tmdb_api_key

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"{TMDB_BASE}{SEARCH_PATHS[media_type]}", params=params, headers=headers
            )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB"
        )
    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB rejected the API key"
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TMDB error {resp.status_code}",
        )

    results = []
    for r in resp.json().get("results", [])[:10]:
        # movies use title/release_date, tv uses name/first_air_date
        title = r.get("title") or r.get("name")
        date = r.get("release_date") or r.get("first_air_date") or ""
        if not title:
            continue
        results.append(
            {
                "tmdb_id": r["id"],
                "title": title,
                "year": int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None,
                "poster_url": f"{POSTER_BASE}{r['poster_path']}" if r.get("poster_path") else None,
                "overview": (r.get("overview") or "")[:300],
            }
        )
    return results
