"""Proxy against TMDB so the API key never reaches clients.

Read-only TMDB responses are cached in memory (30 min TTL) to keep the
Explore feeds and season lists fast and to stay well inside rate limits.
"""
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from ..auth import get_current_user
from ..config import settings
from ..models import User

router = APIRouter(prefix="/tmdb", tags=["tmdb"])

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_BASE = f"{IMAGE_BASE}/w342"

# our media_type -> TMDB path segment
TMDB_KIND = {"film": "movie", "tv_show": "tv"}

CACHE_TTL_SECONDS = 30 * 60
_cache: dict[tuple, tuple[float, dict]] = {}

# one pooled client: reusing connections to TMDB saves a TLS handshake per call
_http = httpx.Client(
    timeout=15,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)


def _tmdb_get(path: str, params: dict | None = None, cache: bool = True) -> dict:
    if not settings.tmdb_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TMDB is not configured — set TMDB_API_KEY in the backend .env",
        )
    params = dict(params or {})

    cache_key = (path, tuple(sorted(params.items())))
    if cache:
        hit = _cache.get(cache_key)
        if hit and hit[0] > time.time():
            return hit[1]

    headers = {}
    # v4 read access tokens are JWTs sent as Bearer; v3 keys go in the query string
    if settings.tmdb_api_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.tmdb_api_key}"
    else:
        params["api_key"] = settings.tmdb_api_key

    try:
        resp = _http.get(f"{TMDB_BASE}{path}", params=params, headers=headers)
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach TMDB"
        )
    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="TMDB rejected the API key"
        )
    if resp.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found on TMDB")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TMDB error {resp.status_code}",
        )

    data = resp.json()
    if cache:
        _cache[cache_key] = (time.time() + CACHE_TTL_SECONDS, data)
    return data


def _map_results(raw: list[dict], limit: int = 20) -> list[dict]:
    results = []
    for r in raw[:limit]:
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
                "vote_average": round(r.get("vote_average") or 0, 1),
            }
        )
    return results


@router.get("/search")
def search_tmdb(
    query: str = Query(min_length=1, max_length=200),
    media_type: str = Query(pattern="^(film|tv_show)$"),
    user: User = Depends(get_current_user),
):
    data = _tmdb_get(
        f"/search/{TMDB_KIND[media_type]}",
        {"query": query, "include_adult": "false"},
    )
    return _map_results(data.get("results", []), limit=10)


@router.get("/trending")
def trending_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    user: User = Depends(get_current_user),
):
    data = _tmdb_get(f"/trending/{TMDB_KIND[media_type]}/week")
    return _map_results(data.get("results", []))


@router.get("/popular")
def popular_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    user: User = Depends(get_current_user),
):
    data = _tmdb_get(f"/{TMDB_KIND[media_type]}/popular")
    return _map_results(data.get("results", []))


@router.get("/details")
def details_tmdb(
    media_type: str = Query(pattern="^(film|tv_show)$"),
    tmdb_id: int = Query(ge=1),
    user: User = Depends(get_current_user),
):
    data = _tmdb_get(f"/{TMDB_KIND[media_type]}/{tmdb_id}")

    seasons = None
    if media_type == "film":
        runtime = data.get("runtime") or None
        total_episodes = None
        total_seasons = None
    else:
        run_times = data.get("episode_run_time") or []
        runtime = round(sum(run_times) / len(run_times)) if run_times else None
        if runtime is None:
            last_ep = data.get("last_episode_to_air") or {}
            runtime = last_ep.get("runtime") or None
        total_episodes = data.get("number_of_episodes")
        total_seasons = data.get("number_of_seasons")
        seasons = [
            {
                "season": s["season_number"],
                "name": s.get("name") or f"Season {s['season_number']}",
                "episode_count": s.get("episode_count") or 0,
            }
            for s in data.get("seasons", [])
            if s.get("season_number", 0) > 0  # skip "Specials"
        ]

    return {
        "tmdb_id": tmdb_id,
        "runtime_minutes": runtime,
        "total_episodes": total_episodes,
        "total_seasons": total_seasons,
        "genres": ", ".join(g["name"] for g in data.get("genres", []))[:300] or None,
        "seasons": seasons,
    }


ALLOWED_IMAGE_SIZES = {"w92", "w154", "w185", "w342", "w500", "w780", "original"}
IMAGE_TTL_SECONDS = 24 * 3600
_image_cache: dict[str, tuple[float, bytes, str]] = {}


@router.get("/image/{size}/{filename}")
def image_proxy(size: str, filename: str):
    """Serve TMDB posters from our origin.

    Browsers sometimes cannot load image.tmdb.org directly (ISP blocks,
    filtering extensions), and <img> tags cannot send auth headers — so this
    endpoint is public but restricted to TMDB poster files only.
    """
    if (
        size not in ALLOWED_IMAGE_SIZES
        or "/" in filename or "\\" in filename or ".." in filename
        or not filename.endswith((".jpg", ".jpeg", ".png", ".webp"))
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    key = f"{size}/{filename}"
    now = time.time()
    hit = _image_cache.get(key)
    if hit and hit[0] > now:
        return Response(hit[1], media_type=hit[2],
                        headers={"Cache-Control": "public, max-age=86400"})

    try:
        resp = _http.get(f"{IMAGE_BASE}/{size}/{filename}")
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Could not reach TMDB images")
    if resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    ctype = resp.headers.get("content-type", "image/jpeg")
    if len(_image_cache) > 1000:  # crude but sufficient eviction
        _image_cache.clear()
    _image_cache[key] = (now + IMAGE_TTL_SECONDS, resp.content, ctype)
    return Response(resp.content, media_type=ctype,
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/season")
def season_tmdb(
    tmdb_id: int = Query(ge=1),
    season_number: int = Query(ge=0),
    user: User = Depends(get_current_user),
):
    data = _tmdb_get(f"/tv/{tmdb_id}/season/{season_number}")
    return [
        {
            "season": season_number,
            "episode": e["episode_number"],
            "name": e.get("name") or f"Episode {e['episode_number']}",
            "air_date": e.get("air_date"),
            "runtime": e.get("runtime"),
        }
        for e in data.get("episodes", [])
    ]
