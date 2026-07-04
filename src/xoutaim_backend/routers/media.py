from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import EpisodeWatch, MediaItem, MediaType, User, WatchStatus
from ..schemas import (
    EpisodeBulk, EpisodeSet, MediaItemCreate, MediaItemOut, MediaItemUpdate,
)

router = APIRouter(prefix="/media", tags=["media"])


def _get_owned_item(item_id: int, user: User, db: Session) -> MediaItem:
    item = db.get(MediaItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return item


@router.get("", response_model=list[MediaItemOut])
def list_media(
    media_type: MediaType | None = None,
    status_filter: WatchStatus | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(MediaItem).filter(MediaItem.user_id == user.id)
    if media_type is not None:
        query = query.filter(MediaItem.media_type == media_type)
    if status_filter is not None:
        query = query.filter(MediaItem.status == status_filter)
    if search:
        query = query.filter(MediaItem.title.ilike(f"%{search}%"))
    return query.order_by(MediaItem.updated_at.desc()).all()


@router.post("", response_model=MediaItemOut, status_code=status.HTTP_201_CREATED)
def create_media(
    data: MediaItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    duplicate = db.query(MediaItem).filter(
        MediaItem.user_id == user.id,
        MediaItem.media_type == data.media_type,
        MediaItem.title == data.title,
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already saved this title",
        )
    item = MediaItem(user_id=user.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=MediaItemOut)
def get_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_owned_item(item_id, user, db)


@router.patch("/{item_id}", response_model=MediaItemOut)
def update_media(
    item_id: int,
    data: MediaItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    db.delete(item)
    db.commit()


# ---------- per-episode tracking ----------

def _sync_progress(item: MediaItem, db: Session) -> None:
    """Recompute counters/status from the episode_watches rows."""
    watches = (
        db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item.id).all()
    )
    item.episodes_watched = len(watches)
    if watches:
        last = max(watches, key=lambda w: (w.season, w.episode))
        item.current_season, item.current_episode = last.season, last.episode
    if item.total_episodes and item.episodes_watched >= item.total_episodes:
        item.status = WatchStatus.completed
    elif item.episodes_watched > 0 and item.status == WatchStatus.want_to_watch:
        item.status = WatchStatus.watching
    db.commit()


def _ratings_summary(item: MediaItem, db: Session) -> dict:
    ep_ratings = [
        w.rating
        for w in db.query(EpisodeWatch)
        .filter(EpisodeWatch.media_item_id == item.id, EpisodeWatch.rating.isnot(None))
        .all()
    ]
    episode_avg = round(sum(ep_ratings) / len(ep_ratings), 1) if ep_ratings else None
    all_episodes_rated = bool(item.total_episodes) and len(ep_ratings) >= item.total_episodes
    combined = (
        round((item.rating + episode_avg) / 2, 1)
        if item.rating and episode_avg and all_episodes_rated
        else None
    )
    return {
        "overall_rating": item.rating,
        "episode_avg": episode_avg,
        "combined_score": combined,
        "rated_episodes": len(ep_ratings),
    }


@router.get("/{item_id}/episodes")
def list_episodes(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    watches = (
        db.query(EpisodeWatch)
        .filter(EpisodeWatch.media_item_id == item.id)
        .order_by(EpisodeWatch.season, EpisodeWatch.episode)
        .all()
    )
    return {
        "watched": [
            {"season": w.season, "episode": w.episode, "rating": w.rating}
            for w in watches
        ],
        **_ratings_summary(item, db),
    }


@router.put("/{item_id}/episodes/{season}/{episode}")
def set_episode(
    item_id: int,
    season: int,
    episode: int,
    data: EpisodeSet,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    watch = (
        db.query(EpisodeWatch)
        .filter(
            EpisodeWatch.media_item_id == item.id,
            EpisodeWatch.season == season,
            EpisodeWatch.episode == episode,
        )
        .first()
    )
    if data.watched:
        if watch is None:
            watch = EpisodeWatch(media_item_id=item.id, season=season, episode=episode)
            db.add(watch)
        watch.rating = data.rating
    elif watch is not None:
        db.delete(watch)
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)


@router.post("/{item_id}/episodes/bulk")
def bulk_episodes(
    item_id: int,
    data: EpisodeBulk,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    existing = {
        w.episode: w
        for w in db.query(EpisodeWatch).filter(
            EpisodeWatch.media_item_id == item.id, EpisodeWatch.season == data.season
        )
    }
    for ep in data.episodes:
        if data.watched and ep not in existing:
            db.add(EpisodeWatch(media_item_id=item.id, season=data.season, episode=ep))
        elif not data.watched and ep in existing:
            db.delete(existing[ep])
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)
