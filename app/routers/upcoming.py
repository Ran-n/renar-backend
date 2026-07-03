"""Upcoming releases for tracked titles: next episodes and film premieres."""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import MediaItem, MediaType, User, WatchStatus
from .tmdb import _tmdb_get

router = APIRouter(prefix="/upcoming", tags=["upcoming"])


@router.get("")
def get_upcoming(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = (
        db.query(MediaItem)
        .filter(
            MediaItem.user_id == user.id,
            MediaItem.tmdb_id.isnot(None),
            MediaItem.status != WatchStatus.dropped,
        )
        .all()
    )
    today = date.today()
    out = []
    for item in items:
        try:
            if item.media_type == MediaType.tv_show:
                data = _tmdb_get(f"/tv/{item.tmdb_id}")
                nxt = data.get("next_episode_to_air") or {}
                air_str = nxt.get("air_date")
                if not air_str:
                    continue
                when = date.fromisoformat(air_str)
                if when < today:
                    continue
                out.append({
                    "item_id": item.id,
                    "media_type": "tv_show",
                    "title": item.title,
                    "poster_url": item.poster_url,
                    "date": air_str,
                    "days_until": (when - today).days,
                    "season": nxt.get("season_number"),
                    "episode": nxt.get("episode_number"),
                    "episode_name": nxt.get("name"),
                })
            elif item.media_type == MediaType.film:
                # only unreleased films the user still wants to watch
                if item.status != WatchStatus.want_to_watch:
                    continue
                data = _tmdb_get(f"/movie/{item.tmdb_id}")
                rel_str = data.get("release_date")
                if not rel_str:
                    continue
                when = date.fromisoformat(rel_str)
                if when <= today:
                    continue
                out.append({
                    "item_id": item.id,
                    "media_type": "film",
                    "title": item.title,
                    "poster_url": item.poster_url,
                    "date": rel_str,
                    "days_until": (when - today).days,
                    "season": None,
                    "episode": None,
                    "episode_name": None,
                })
        except Exception:
            continue  # one unreachable title must not break the whole feed
    out.sort(key=lambda e: e["date"])
    return out
