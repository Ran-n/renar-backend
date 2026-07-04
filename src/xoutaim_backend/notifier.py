"""Background checker: creates notifications when tracked shows air new episodes."""
import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import EpisodeWatch, MediaItem, MediaType, Notification, WatchStatus
from .routers.tmdb import _tmdb_get

log = logging.getLogger("xoutaim.notifier")

RECENT_DAYS = 7  # notify about episodes that aired in the last week


def fetch_show(tmdb_id: int) -> dict:
    return _tmdb_get(f"/tv/{tmdb_id}")


def check_new_episodes(db: Session, fetch=fetch_show) -> int:
    """Scan all tracked TV shows once; returns number of notifications created."""
    items = (
        db.query(MediaItem)
        .filter(
            MediaItem.media_type == MediaType.tv_show,
            MediaItem.tmdb_id.isnot(None),
            MediaItem.status != WatchStatus.dropped,
        )
        .all()
    )
    by_tmdb: dict[int, list[MediaItem]] = {}
    for item in items:
        by_tmdb.setdefault(item.tmdb_id, []).append(item)

    created = 0
    today = date.today()
    for tmdb_id, group in by_tmdb.items():
        try:
            data = fetch(tmdb_id)
        except Exception as exc:
            log.warning("TMDB fetch failed for show %s: %s", tmdb_id, exc)
            continue
        last = data.get("last_episode_to_air") or {}
        air_str = last.get("air_date")
        season = last.get("season_number")
        episode = last.get("episode_number")
        if not air_str or season is None or episode is None:
            continue
        try:
            air = date.fromisoformat(air_str)
        except ValueError:
            continue
        if air > today or air < today - timedelta(days=RECENT_DAYS):
            continue

        show_name = data.get("name") or group[0].title
        ep_name = last.get("name") or f"Episode {episode}"
        for item in group:
            already_watched = (
                db.query(EpisodeWatch)
                .filter_by(media_item_id=item.id, season=season, episode=episode)
                .first()
            )
            if already_watched:
                continue
            already_notified = (
                db.query(Notification)
                .filter_by(
                    user_id=item.user_id, media_item_id=item.id,
                    season=season, episode=episode, kind="new_episode",
                )
                .first()
            )
            if already_notified:
                continue
            db.add(
                Notification(
                    user_id=item.user_id,
                    media_item_id=item.id,
                    kind="new_episode",
                    title=f"New episode: {show_name}",
                    body=f"S{season:02d}E{episode:02d} · {ep_name} · aired {air_str}",
                    season=season,
                    episode=episode,
                )
            )
            created += 1
    db.commit()
    return created


def check_once() -> int:
    db = SessionLocal()
    try:
        return check_new_episodes(db)
    finally:
        db.close()


async def run_periodic() -> None:
    await asyncio.sleep(15)  # let the app finish booting
    while True:
        try:
            n = await asyncio.to_thread(check_once)
            log.info("episode check done: %d new notifications", n)
        except Exception:
            log.exception("episode check failed")
        await asyncio.sleep(settings.episode_check_minutes * 60)
