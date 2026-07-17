#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.286403
Revised: 2026/07/17 20:11:30.431373
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..catalog.titles import WITH_TITLE_GENRES, find_or_create_title, find_title
from ..database import get_db
from ..media.image_service import gc_image, image_row_for
from ..media.image_utils import decode_b64_image, normalize_jpeg
from ..models import (
    Episode,
    EpisodeCustomStill,
    EpisodeWatch,
    LibraryEntry,
    MediaType,
    Title,
    TmdbCache,
    User,
    WatchEvent,
    WatchStatus,
    prefetch_episode_cache,
)
from ..schemas import (
    CustomPosterSet,
    EpisodeBulk,
    EpisodeSet,
    LibraryEntryCreate,
    LibraryEntryOut,
    LibraryEntryUpdate,
    RewatchCreate,
)
from ..tmdb.tmdb_store import localized_titles, refresh_title_details, warm_title_translations
from ..users.auth import get_current_user, require_premium
from .tmdb import fetch_poster_bytes

router = APIRouter(prefix="/media", tags=["media"])
_log = logging.getLogger(__name__)

# cap on how many titles get a background translation fetch per list_media
# call — bounds worst-case TMDB load for a user with a huge library switching
# language for the first time; the rest warm up over subsequent requests.
_MAX_WARMUP_PER_REQUEST = 15

# default page size when the caller omits `limit` — previously an omitted
# limit meant "return the entire library", which scaled linearly with
# library size on every call. Matches the frontend's own page size
# (library_view.py's _PAGE_SIZE), so callers that already paginate see no
# behavior change.
_DEFAULT_LIST_LIMIT = 60


def _get_owned_item(item_id: int, user: User, db: Session) -> LibraryEntry:
    item = db.get(LibraryEntry, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return item


@router.get("", response_model=list[LibraryEntryOut])
def list_media(
    background_tasks: BackgroundTasks,
    media_type: MediaType | None = None,
    status_filter: WatchStatus | None = None,
    search: str | None = None,
    lang: str | None = None,
    favorites_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit = _DEFAULT_LIST_LIMIT if limit is None else limit
    query = db.query(LibraryEntry).join(Title).options(*WITH_TITLE_GENRES).filter(LibraryEntry.user_id == user.id)
    if media_type is not None:
        query = query.filter(Title.media_type == media_type)
    if status_filter is not None:
        query = query.filter(LibraryEntry.status == status_filter)
    if favorites_only:
        query = query.filter(LibraryEntry.is_favorite.is_(True))
    if search:
        # matches the title's creation-time text, its language-independent
        # original name, or any language's title we've already cached from
        # TMDB (e.g. a Spanish title cached because some user viewed it in
        # Spanish) — so a search in the user's own language finds it too.
        cached_match = db.query(TmdbCache.title_id).filter(
            TmdbCache.kind == "details",
            or_(
                TmdbCache.payload["title"].astext.ilike(f"%{search}%"),
                TmdbCache.payload["name"].astext.ilike(f"%{search}%"),
            ),
        )
        query = query.filter(
            or_(
                Title.title.ilike(f"%{search}%"),
                Title.original_title.ilike(f"%{search}%"),
                Title.id.in_(cached_match),
            )
        )
    query = query.order_by(LibraryEntry.updated_at.desc()).offset(offset).limit(limit)
    entries = query.all()
    prefetch_episode_cache(db, (e.title_id for e in entries))

    if lang and lang != "en" and entries:
        translations = localized_titles(db, [e.title_id for e in entries], lang)
        missing_ids = []
        for entry in entries:
            found = translations.get(entry.title_id)
            if found:
                entry._display_title = found
            elif entry.title_id not in missing_ids:
                missing_ids.append(entry.title_id)
        if missing_ids:
            background_tasks.add_task(warm_title_translations, missing_ids[:_MAX_WARMUP_PER_REQUEST], lang)

    return entries


@router.get("/keys")
def list_media_keys(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Lightweight identifiers for every entry in the user's library — just
    enough (media_type, tmdb_id, url, title, author) to build the "already in
    my library" membership check Explore needs. Deliberately unbounded (no
    `limit`/`offset`, unlike list_media): that check needs the whole library
    in one shot, but skips the WITH_TITLE_GENRES joins and full LibraryEntryOut
    shape list_media carries per row, so it stays cheap even for a large
    library."""
    rows = (
        db.query(Title.media_type, Title.tmdb_id, Title.title, Title.author, LibraryEntry.url)
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(LibraryEntry.user_id == user.id)
        .all()
    )
    return [
        {"media_type": media_type.value, "tmdb_id": tmdb_id, "title": title, "author": author, "url": url}
        for media_type, tmdb_id, title, author, url in rows
    ]


@router.get("/by_tmdb", response_model=LibraryEntryOut)
def get_media_by_tmdb(
    media_type: MediaType,
    tmdb_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single-item lookup by (media_type, tmdb_id) in the caller's own
    library — for callers (e.g. the title detail page) that only need one
    entry and shouldn't have to page through list_media to find it."""
    title_row = find_title(db, media_type, tmdb_id, None)
    item = (
        db.query(LibraryEntry).filter(LibraryEntry.user_id == user.id, LibraryEntry.title_id == title_row.id).first()
        if title_row is not None
        else None
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return item


@router.post("", response_model=LibraryEntryOut, status_code=status.HTTP_201_CREATED)
def create_media(
    data: LibraryEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    title = find_or_create_title(
        db,
        data.media_type,
        data.tmdb_id,
        data.title,
        year=data.year,
        poster_url=data.poster_url,
        runtime_minutes=data.runtime_minutes,
        total_episodes=data.total_episodes,
        genres=data.genres,
        author=data.author,
        page_count=data.page_count,
    )
    # populate overview/status/etc. now that the title exists; best-effort
    # (usually served from the in-memory TMDB cache — the client was just
    # on the detail page) and never blocks the add
    refresh_title_details(db, title)
    duplicate = (
        db.query(LibraryEntry).filter(LibraryEntry.user_id == user.id, LibraryEntry.title_id == title.id).first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already saved this title",
        )
    item = LibraryEntry(
        user_id=user.id,
        title_id=title.id,
        url=data.url,
        status=data.status,
        rating=data.rating,
        notes=data.notes,
        current_season=data.current_season,
        current_episode=data.current_episode,
        episodes_watched=data.episodes_watched,
        is_favorite=data.is_favorite,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/ratings")
def title_ratings(
    media_type: MediaType,
    tmdb_id: int | None = None,
    title: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )
    title_row = find_title(db, media_type, tmdb_id, title)
    if title_row is None:
        return {"average": None, "count": 0}
    ratings = [
        r
        for (r,) in db.query(LibraryEntry.rating)
        .filter(LibraryEntry.title_id == title_row.id, LibraryEntry.rating.isnot(None))
        .all()
    ]
    average = round(sum(ratings) / len(ratings), 1) if ratings else None
    return {"average": average, "count": len(ratings)}


@router.get("/{item_id}", response_model=LibraryEntryOut)
def get_media(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_owned_item(item_id, user, db)


def _derive_season_episode(item: LibraryEntry, db: Session) -> None:
    """Best-effort fill-in for current_season/current_episode from the
    title's Episode catalog (ordered by season, episode_number), so the
    season-relative display (e.g. "3x05") also works for the coarse
    "+1 episodes_watched" flow, not just per-episode tracking. Never
    overrides a season/episode the caller set explicitly in this same
    request — see update_media."""
    if not item.episodes_watched:
        return
    episodes = (
        db.query(Episode)
        .filter(Episode.title_id == item.title_id)
        .order_by(Episode.season, Episode.episode_number)
        .all()
    )
    if not episodes:
        return
    ep = episodes[min(item.episodes_watched, len(episodes)) - 1]
    item.current_season, item.current_episode = ep.season, ep.episode_number


@router.patch("/{item_id}", response_model=LibraryEntryOut)
def update_media(
    item_id: int,
    data: LibraryEntryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    changed = data.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(item, field, value)
    if "episodes_watched" in changed and "current_season" not in changed and "current_episode" not in changed:
        _derive_season_episode(item, db)
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
    old_poster_image_id = item.custom_poster_image_id
    old_backdrop_image_id = item.custom_backdrop_image_id
    db.delete(item)
    db.flush()
    gc_image(old_poster_image_id, db)
    gc_image(old_backdrop_image_id, db)
    db.commit()


# ---------- custom posters and backdrops (premium) ----------

POSTER_MAX = (800, 1200)  # w500-class 2:3 poster, generous headroom
BACKDROP_MAX = (1280, 720)  # w780-class 16:9 backdrop, generous headroom


def _resolve_raw_image(data: CustomPosterSet) -> bytes:
    """Return raw image bytes from either a base64 upload or a TMDB URL."""
    return decode_b64_image(data.image_b64) if data.image_b64 else fetch_poster_bytes(data.tmdb_url)


def _swap_image(item: LibraryEntry, attr: str, new_image_id: int, db: Session) -> None:
    """Replace the image FK on `attr`, GC the old one after flushing."""
    old_image_id = getattr(item, attr)
    setattr(item, attr, new_image_id)
    if old_image_id != new_image_id:
        db.flush()  # GC must see the new reference
        gc_image(old_image_id, db)


@router.put("/{item_id}/poster", response_model=LibraryEntryOut)
def set_custom_poster(
    item_id: int,
    data: CustomPosterSet,
    db: Session = Depends(get_db),
    user: User = Depends(require_premium),
):
    """Premium: override this entry's poster with an upload or a TMDB
    alternate (downloaded server-side). Only touches the user's own entry —
    the shared Title poster is never modified."""
    item = _get_owned_item(item_id, user, db)
    raw = _resolve_raw_image(data)
    new_id = image_row_for(normalize_jpeg(raw, POSTER_MAX), db).id
    _swap_image(item, "custom_poster_image_id", new_id, db)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}/poster", response_model=LibraryEntryOut)
def clear_custom_poster(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clearing works without premium: a lapsed subscriber can always go
    back to the default poster."""
    item = _get_owned_item(item_id, user, db)
    old_image_id = item.custom_poster_image_id
    item.custom_poster_image_id = None
    if old_image_id is not None:
        db.flush()
        gc_image(old_image_id, db)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}/backdrop", response_model=LibraryEntryOut)
def set_custom_backdrop(
    item_id: int,
    data: CustomPosterSet,
    db: Session = Depends(get_db),
    user: User = Depends(require_premium),
):
    """Premium: override this entry's backdrop with an upload or a TMDB
    alternate (downloaded server-side). Only touches the user's own entry —
    the shared Title backdrop is never modified."""
    item = _get_owned_item(item_id, user, db)
    raw = _resolve_raw_image(data)
    new_id = image_row_for(normalize_jpeg(raw, BACKDROP_MAX), db).id
    _swap_image(item, "custom_backdrop_image_id", new_id, db)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}/backdrop", response_model=LibraryEntryOut)
def clear_custom_backdrop(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clearing works without premium: a lapsed subscriber can always go
    back to the default backdrop."""
    item = _get_owned_item(item_id, user, db)
    old_image_id = item.custom_backdrop_image_id
    item.custom_backdrop_image_id = None
    if old_image_id is not None:
        db.flush()
        gc_image(old_image_id, db)
    db.commit()
    db.refresh(item)
    return item


# ---------- custom episode stills (premium) ----------


def _get_custom_still(item: LibraryEntry, season: int, episode: int, db: Session) -> EpisodeCustomStill | None:
    return (
        db.query(EpisodeCustomStill)
        .filter(
            EpisodeCustomStill.media_item_id == item.id,
            EpisodeCustomStill.season == season,
            EpisodeCustomStill.episode == episode,
        )
        .first()
    )


@router.put("/{item_id}/episodes/{season}/{episode}/still")
def set_custom_episode_still(
    item_id: int,
    season: int,
    episode: int,
    data: CustomPosterSet,
    db: Session = Depends(get_db),
    user: User = Depends(require_premium),
):
    """Premium: override this episode's still with an upload or a TMDB
    alternate, same rules/shape as the item-level poster/backdrop overrides.
    Kept on its own table rather than EpisodeWatch — a still may be set on an
    episode the user hasn't watched yet, and a watch row's mere existence
    already means "watched" elsewhere in this file."""
    item = _get_owned_item(item_id, user, db)
    raw = _resolve_raw_image(data)
    still = _get_custom_still(item, season, episode, db)
    img = image_row_for(normalize_jpeg(raw, BACKDROP_MAX), db)
    old_image_id = still.still_image_id if still else None
    if still is None:
        still = EpisodeCustomStill(media_item_id=item.id, season=season, episode=episode, still_image_id=img.id)
        db.add(still)
    else:
        still.still_image_id = img.id
    if old_image_id != img.id:
        db.flush()  # GC must see the new reference
        gc_image(old_image_id, db)
    db.commit()
    return {"still_url": f"/images/{img.hash}"}


@router.delete("/{item_id}/episodes/{season}/{episode}/still")
def clear_custom_episode_still(
    item_id: int,
    season: int,
    episode: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clearing works without premium: a lapsed subscriber can always go
    back to the default still."""
    item = _get_owned_item(item_id, user, db)
    still = _get_custom_still(item, season, episode, db)
    if still is not None:
        old_image_id = still.still_image_id
        db.delete(still)
        db.flush()
        gc_image(old_image_id, db)
    db.commit()
    return {"still_url": None}


# ---------- per-episode tracking ----------


def _sync_progress(item: LibraryEntry, db: Session) -> None:
    """Recompute counters/status from the episode_watches rows."""
    watches = db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item.id).all()
    item.episodes_watched = len(watches)
    if watches:
        last = max(watches, key=lambda w: (w.season, w.episode))
        item.current_season, item.current_episode = last.season, last.episode
    if item.total_episodes and item.episodes_watched >= item.total_episodes:
        item.status = WatchStatus.completed
    elif item.episodes_watched > 0 and item.status == WatchStatus.want_to_watch:
        item.status = WatchStatus.watching
    db.commit()


def _ratings_summary(item: LibraryEntry, db: Session) -> dict:
    ep_ratings = [
        w.rating
        for w in db.query(EpisodeWatch)
        .filter(EpisodeWatch.media_item_id == item.id, EpisodeWatch.rating.isnot(None))
        .all()
    ]
    episode_avg = round(sum(ep_ratings) / len(ep_ratings), 1) if ep_ratings else None
    all_episodes_rated = bool(item.total_episodes) and len(ep_ratings) >= item.total_episodes
    combined = round((item.rating + episode_avg) / 2, 1) if item.rating and episode_avg and all_episodes_rated else None
    rewatch_count = (
        db.query(WatchEvent).filter(WatchEvent.media_item_id == item.id, WatchEvent.season.is_(None)).count()
    )
    return {
        "overall_rating": item.rating,
        "episode_avg": episode_avg,
        "combined_score": combined,
        "rated_episodes": len(ep_ratings),
        "rewatch_count": rewatch_count,
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
    rewatch_counts = {
        (s, e): c
        for s, e, c in db.query(WatchEvent.season, WatchEvent.episode, func.count(WatchEvent.id))
        .filter(WatchEvent.media_item_id == item.id, WatchEvent.season.isnot(None))
        .group_by(WatchEvent.season, WatchEvent.episode)
        .all()
    }
    # custom stills exist independently of watch status, so they're listed
    # separately rather than folded into `watched`; only served while the
    # owner is premium (kept but not served once premium lapses, same rule
    # as the item-level poster/backdrop overrides)
    custom_stills = (
        [
            {"season": s.season, "episode": s.episode, "still_url": f"/images/{s.still_image.hash}"}
            for s in db.query(EpisodeCustomStill).filter(EpisodeCustomStill.media_item_id == item.id).all()
        ]
        if item.owner.is_premium
        else []
    )
    return {
        "watched": [
            {
                "season": w.season,
                "episode": w.episode,
                "rating": w.rating,
                "rewatch_count": rewatch_counts.get((w.season, w.episode), 0),
            }
            for w in watches
        ],
        "custom_stills": custom_stills,
        **_ratings_summary(item, db),
    }


@router.post("/{item_id}/rewatch")
def rewatch(
    item_id: int,
    data: RewatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    if (data.season is None) != (data.episode is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="season and episode must be given together",
        )
    if data.season is not None:
        watch = (
            db.query(EpisodeWatch)
            .filter(
                EpisodeWatch.media_item_id == item.id,
                EpisodeWatch.season == data.season,
                EpisodeWatch.episode == data.episode,
            )
            .first()
        )
        if watch is None:
            db.add(EpisodeWatch(media_item_id=item.id, season=data.season, episode=data.episode))
    db.add(WatchEvent(media_item_id=item.id, season=data.season, episode=data.episode))
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)


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
