#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.286403
Revised: 2026/08/18 11:05:47.076244
"""

import logging
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import Date, and_, cast, exists, func, or_
from sqlalchemy.orm import Session

from ..catalog.titles import WITH_TITLE_GENRES, find_or_create_title, find_title
from ..database import get_db
from ..media.image_service import gc_image, image_row_for
from ..media.image_utils import decode_b64_image, normalize_jpeg
from ..models import (
    Episode,
    EpisodeCustomStill,
    EpisodeRatingAggregate,
    EpisodeWatch,
    LibraryEntry,
    MediaType,
    Title,
    TmdbCache,
    User,
    WatchEvent,
    WatchStatus,
    prefetch_episode_cache,
    utcnow,
)
from ..schemas import (
    CustomPosterSet,
    EpisodeBulk,
    EpisodeSet,
    LibraryEntryCreate,
    LibraryEntryOut,
    LibraryEntryUpdate,
    RatingsBatchRequest,
    RewatchCreate,
)
from ..tmdb.tmdb_store import localized_titles, refresh_title_details, sync_show_episodes, warm_title_translations
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


def _unwatched_aired_episode_clause(*, newer_than_last_watched: bool = False):
    """EXISTS(...) clause, correlated to whatever `LibraryEntry` row it's
    filtered/selected alongside: does this show have an aired episode
    (`air_date <= today`) with no matching `EpisodeWatch` row?

    Live, not cached: `LibraryEntry.status`/`episodes_watched` only get
    recomputed by `_sync_progress()` on a write to that item (toggling an
    episode, a rewatch, ...) — a show sitting untouched while a new episode
    airs never re-runs that, so `status` alone can't answer "is this show
    *currently* fully caught up" reliably. This clause re-evaluates fresh
    against the `episodes`/`episode_watches` tables on every call instead,
    which `list_media`'s "last_watched" ordering (Home's Watch Next list) is
    small enough — one user, one status — to afford doing live.

    `newer_than_last_watched=True` narrows this to episodes that aired more
    recently than the show's own `last_watched_at` — i.e. genuinely new
    content that arrived since the user last watched anything on it, not
    just an old backlog episode they haven't gotten around to yet. Used for
    the "bubble a fresh episode to position #2" ranking rule, a stricter
    condition than the plain "still has something aired left to watch" one
    used for excluding fully caught-up shows.
    """
    conditions = [
        Episode.title_id == LibraryEntry.title_id,
        Episode.air_date.isnot(None),
        Episode.air_date <= date.today(),
        ~exists().where(
            EpisodeWatch.media_item_id == LibraryEntry.id,
            EpisodeWatch.season == Episode.season,
            EpisodeWatch.episode == Episode.episode_number,
        ),
    ]
    if newer_than_last_watched:
        conditions.append(
            or_(LibraryEntry.last_watched_at.is_(None), Episode.air_date > cast(LibraryEntry.last_watched_at, Date))
        )
    return exists().where(and_(*conditions))


def _known_aired_episode_clause():
    """EXISTS(...): has at least one Episode row synced for this show with
    `air_date <= today`. Guards `_unwatched_aired_episode_clause` from a
    vacuous-truth trap: a show with *no* synced episode data at all (never
    opened its season list, or a brand new addition) has zero aired-and-
    unwatched rows for the exact same reason a genuinely caught-up show
    does — there's nothing to find either way. Without this guard, both
    look identical to the exclusion filter and a show with simply no data
    yet would vanish from Watch Next instead of a caught-up one."""
    return exists().where(
        Episode.title_id == LibraryEntry.title_id, Episode.air_date.isnot(None), Episode.air_date <= date.today()
    )


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
    order_by: str | None = None,
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
    # "last_watched" is opt-in (Home's in-progress preview) rather than the
    # default: it orders by genuine watch activity only (see
    # LibraryEntry.last_watched_at), while Library's own browsing/filtering
    # keeps the existing "most recently touched at all" order everyone
    # already expects.
    if order_by == "last_watched":
        # A tv_show fully caught up on everything aired so far has nothing
        # left to prompt "continue watching" for until a new episode
        # actually airs — see _unwatched_aired_episode_clause's docstring
        # for why this can't just filter on the (possibly stale) status
        # field. Films have no episode concept, so media_type != tv_show
        # short-circuits the OR before the correlated EXISTS runs for them.
        # A show with no synced episode data at all is kept too (see
        # _known_aired_episode_clause's docstring) — there's no evidence
        # it's caught up, just no data yet.
        query = query.filter(
            or_(
                Title.media_type != MediaType.tv_show,
                ~_known_aired_episode_clause(),
                _unwatched_aired_episode_clause(),
            )
        )
        has_new_episode = _unwatched_aired_episode_clause(newer_than_last_watched=True)
        query = query.add_columns(has_new_episode.label("has_new_episode")).order_by(
            LibraryEntry.last_watched_at.desc().nullslast()
        )
        # Re-ranked in Python, not SQL: position #1 always stays the single
        # most-recently-watched item (last_watched_at's own top row) — a show
        # with a fresh unwatched episode bubbles to #2, ahead of older
        # last_watched_at rows without one, but never displaces #1 itself.
        # Expressing "row 1 is exempt from the boost" as one ORDER BY key
        # isn't possible without a self-referencing window function; doing it
        # here, over a per-user "watching" list that's never large, is
        # simpler and just as correct. Runs over the un-limited result (only
        # `offset` applied at the SQL level) so a boosted show further down
        # the last_watched order can still surface within `limit`.
        rows = query.offset(offset).all()
        if rows:
            head, *rest = rows
            rest.sort(key=lambda pair: not pair.has_new_episode)  # stable: new-episode rows first
            rows = [head, *rest]
        entries = [entry for entry, _has_new in rows[:limit]]
    else:
        query = query.order_by(LibraryEntry.updated_at.desc())
        entries = query.offset(offset).limit(limit).all()
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
    enough (media_type, tmdb_id, url, title) to build the "already in my
    library" membership check Explore needs. Deliberately unbounded (no
    `limit`/`offset`, unlike list_media): that check needs the whole library
    in one shot, but skips the WITH_TITLE_GENRES joins and full LibraryEntryOut
    shape list_media carries per row, so it stays cheap even for a large
    library."""
    rows = (
        db.query(Title.media_type, Title.tmdb_id, Title.title, LibraryEntry.url)
        .join(LibraryEntry, LibraryEntry.title_id == Title.id)
        .filter(LibraryEntry.user_id == user.id)
        .all()
    )
    return [
        {"media_type": media_type.value, "tmdb_id": tmdb_id, "title": title, "url": url}
        for media_type, tmdb_id, title, url in rows
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
        # same rule as update_media: adding straight into "watching" (or
        # "completed", the no-episodes film case) is itself a watch signal
        last_watched_at=utcnow() if data.status in (WatchStatus.watching, WatchStatus.completed) else None,
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
    """Renar average+count for one title, read straight off
    Title.rating_sum/rating_count — a running total a database trigger keeps
    in sync on every media_items rating write (see db_triggers.py), not a
    live aggregate over every LibraryEntry row recomputed on every call."""
    if tmdb_id is None and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide tmdb_id or title",
        )
    title_row = find_title(db, media_type, tmdb_id, title)
    if title_row is None or title_row.rating_count == 0:
        return {"average": None, "count": 0}
    return {"average": round(title_row.rating_sum / title_row.rating_count), "count": title_row.rating_count}


@router.post("/ratings/batch")
def title_ratings_batch(
    data: RatingsBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Renar average+count for many tmdb_ids at once — explore grids need one
    rating per card without firing a request per card, and a request-per-card
    approach doesn't scale to a page of 20-40 results. Same trigger-maintained
    columns as `title_ratings`, just selected for a whole batch of titles at
    once instead of one."""
    rows = (
        db.query(Title.tmdb_id, Title.rating_sum, Title.rating_count)
        .filter(
            Title.media_type == data.media_type,
            Title.tmdb_id.in_(data.tmdb_ids),
            Title.rating_count > 0,
        )
        .all()
    )
    return {
        str(tmdb_id): {"average": round(rating_sum / rating_count), "count": rating_count}
        for tmdb_id, rating_sum, rating_count in rows
    }


@router.get("/episode-ratings")
def episode_ratings(
    tmdb_id: int = Query(ge=1),
    season: int = Query(ge=0),
    episode: int = Query(ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Renar average+count for one episode, across every user's own
    EpisodeWatch.rating for it — the per-episode counterpart to
    `title_ratings`. Reads EpisodeRatingAggregate, a trigger-maintained
    running total (see db_triggers.py) keyed by (title_id, season, episode),
    instead of live-joining/aggregating every EpisodeWatch row for it."""
    title_id = db.query(Title.id).filter(Title.media_type == MediaType.tv_show, Title.tmdb_id == tmdb_id).scalar()
    if title_id is None:
        return {"average": None, "count": 0}
    agg = (
        db.query(EpisodeRatingAggregate)
        .filter(
            EpisodeRatingAggregate.title_id == title_id,
            EpisodeRatingAggregate.season == season,
            EpisodeRatingAggregate.episode == episode,
        )
        .first()
    )
    if agg is None or agg.rating_count == 0:
        return {"average": None, "count": 0}
    return {"average": round(agg.rating_sum / agg.rating_count), "count": agg.rating_count}


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


def _mark_all_aired_watched(item: LibraryEntry, db: Session) -> None:
    """Fill in EpisodeWatch rows for every already-aired episode the user
    hasn't marked yet — used when a show is set straight to "completed"
    without per-episode tracking. Only episodes with a known air_date in the
    past are touched, so a still-airing show never gets future/unannounced
    episodes marked watched out from under it. _sync_progress (called at the
    end) uses the same aired-only count as its completion threshold, so it
    won't demote the "completed" status the caller just set."""
    if item.title_ref is None:
        return
    sync_show_episodes(db, item.title_ref)
    aired = (
        db.query(Episode)
        .filter(Episode.title_id == item.title_id, Episode.air_date.isnot(None), Episode.air_date <= date.today())
        .all()
    )
    if not aired:
        return
    existing = {(w.season, w.episode) for w in db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item.id)}
    for ep in aired:
        if (ep.season, ep.episode_number) not in existing:
            db.add(EpisodeWatch(media_item_id=item.id, season=ep.season, episode=ep.episode_number))
    # sessions here are autoflush=False (see database.py) — _sync_progress
    # re-queries EpisodeWatch, so the inserts above must be committed first
    # or it won't see them, same as every other call site of _sync_progress.
    db.commit()
    _sync_progress(item, db)


@router.patch("/{item_id}", response_model=LibraryEntryOut)
def update_media(
    item_id: int,
    data: LibraryEntryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_owned_item(item_id, user, db)
    changed = data.model_dump(exclude_unset=True)
    if item.media_type == MediaType.film:
        tv_only = {"episodes_watched", "current_season", "current_episode"} & changed.keys()
        if tv_only:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{', '.join(sorted(tv_only))} not applicable to a film",
            )
    for field, value in changed.items():
        setattr(item, field, value)
    if "episodes_watched" in changed and "current_season" not in changed and "current_episode" not in changed:
        _derive_season_episode(item, db)
    # Setting status -> completed directly (not via per-episode toggles)
    # otherwise leaves zero EpisodeWatch rows behind: episodes_watched stays
    # untouched, so per-episode ratings/rewatch have no data for a show the
    # user just told us they're done with. Backfill every already-aired
    # episode as watched — unless the caller also gave an explicit
    # episodes_watched count of their own, which wins instead.
    if (
        changed.get("status") == WatchStatus.completed
        and item.media_type == MediaType.tv_show
        and "episodes_watched" not in changed
    ):
        _mark_all_aired_watched(item, db)
    # Coarse progress (no per-episode rows) is still the user asserting a
    # watch happened, so it has to move last_watched_at the same as the
    # per-episode path does — everything else this endpoint can touch
    # (favorite, rating, notes, url, status on its own) must NOT.
    #
    # status -> watching is included too: a show manually flipped to
    # "watching" (no episodes marked yet) is exactly the case where the user
    # most wants it to surface on Home right away, instead of sitting at the
    # bottom of the list until they separately go mark an episode watched.
    # status -> completed also counts — a film has no episode rows at all,
    # so "mark this watched" for one IS this status change and nothing else.
    if {"episodes_watched", "current_season", "current_episode"} & changed.keys() or changed.get("status") in (
        WatchStatus.watching,
        WatchStatus.completed,
    ):
        item.last_watched_at = utcnow()
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
    new_id = image_row_for(normalize_jpeg(raw, POSTER_MAX), db, source_url=data.tmdb_url).id
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
    new_id = image_row_for(normalize_jpeg(raw, BACKDROP_MAX), db, source_url=data.tmdb_url).id
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
    img = image_row_for(normalize_jpeg(raw, BACKDROP_MAX), db, source_url=data.tmdb_url)
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
    return {"still_url": f"/images/{img.hash}", "still_source_url": img.source_url}


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
    return {"still_url": None, "still_source_url": None}


# ---------- per-episode tracking ----------


def _aired_episode_total(item: LibraryEntry, db: Session) -> int | None:
    """How many episodes have actually aired, per the synced Episode
    catalog — None when nothing's synced yet for this title (caller falls
    back to the flat Title.total_episodes count).

    Title.total_episodes comes straight from TMDB's number_of_episodes,
    which can already include an episode announced with a future air_date
    that hasn't aired. Without this, a still-airing show the user has fully
    caught up on would never cross that flat threshold, and so would never
    promote to "completed" (shown as "Caught up" for a non-ended show) until
    the show itself wrapped."""
    known = db.query(func.count(Episode.id)).filter(Episode.title_id == item.title_id).scalar()
    if not known:
        return None
    return (
        db.query(func.count(Episode.id))
        .filter(Episode.title_id == item.title_id, Episode.air_date.isnot(None), Episode.air_date <= date.today())
        .scalar()
    )


def _sync_progress(item: LibraryEntry, db: Session) -> None:
    """Recompute counters/status from the episode_watches rows."""
    watches = db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item.id).all()
    item.episodes_watched = len(watches)
    if watches:
        last = max(watches, key=lambda w: (w.season, w.episode))
        item.current_season, item.current_episode = last.season, last.episode
        item.last_watched_at = utcnow()
    total = _aired_episode_total(item, db)
    if total is None:
        total = item.total_episodes
    if total and item.episodes_watched >= total:
        item.status = WatchStatus.completed
    elif total and item.status == WatchStatus.completed:
        # no longer every episode is watched — completed doesn't hold up
        # anymore, so this undoes the auto-promotion above the same way an
        # unwatch undoes want_to_watch -> watching below. Without this, an
        # unwatch after finishing a show left the status stuck on
        # "completed" forever, since nothing ever demoted it back down.
        # Guarded on `total`: a film has no episode concept, so `total` is
        # always None and `episodes_watched` always 0 — without this guard,
        # every rewatch of a completed film fell into this branch and got
        # wrongly demoted all the way to want_to_watch.
        item.status = WatchStatus.watching if item.episodes_watched > 0 else WatchStatus.want_to_watch
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
    episode_avg = round(sum(ep_ratings) / len(ep_ratings)) if ep_ratings else None
    all_episodes_rated = bool(item.total_episodes) and len(ep_ratings) >= item.total_episodes
    combined = round((item.rating + episode_avg) / 2) if item.rating and episode_avg and all_episodes_rated else None
    rewatch_count = (
        db.query(WatchEvent).filter(WatchEvent.media_item_id == item.id, WatchEvent.season.is_(None)).count()
    )
    return {
        "overall_rating": item.rating,
        "episode_avg": episode_avg,
        "combined_score": combined,
        "rated_episodes": len(ep_ratings),
        "rewatch_count": rewatch_count,
        # item fields _sync_progress may have just changed (status can
        # auto-promote/demote on an episode toggle) — carried here so a
        # caller can update its own copy of the item without a follow-up
        # GET just to pick up the new status/progress
        "item_status": item.status,
        "item_episodes_watched": item.episodes_watched,
        "item_current_season": item.current_season,
        "item_current_episode": item.current_episode,
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
            {
                "season": s.season,
                "episode": s.episode,
                "still_url": f"/images/{s.still_image.hash}",
                "still_source_url": s.still_image.source_url,
            }
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
    # _sync_progress only stamps last_watched_at off episode_watches rows, so
    # a rewatch of an episode already in that table (or a whole-film rewatch,
    # which has no episode_watches row at all) wouldn't otherwise move it —
    # this is itself a watch event, so it must count.
    item.last_watched_at = utcnow()
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)


@router.delete("/{item_id}/rewatch")
def undo_rewatch(
    item_id: int,
    data: RewatchCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove the single most recent rewatch for this item/episode — the
    inverse of POST .../rewatch, one event at a time. Lets the frontend step
    an already-rewatched episode down by one instead of jumping straight to
    fully unwatched when the user "unmarks" it. The underlying watched
    status (EpisodeWatch row) is left in place, but its rating IS cleared:
    this endpoint's only caller is that same "unmark" tap on the checkmark
    (never a standalone "undo my last rewatch" action elsewhere — see
    rewatch_widget.py, which uses the separate per-event delete-rewatch-
    event endpoint instead), so from the user's perspective tapping unmark
    should always drop the rating too, not just leave it stranded on a row
    that no longer looks freshly watched."""
    item = _get_owned_item(item_id, user, db)
    if (data.season is None) != (data.episode is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="season and episode must be given together",
        )
    latest = (
        db.query(WatchEvent)
        .filter(
            WatchEvent.media_item_id == item.id,
            WatchEvent.season == data.season,
            WatchEvent.episode == data.episode,
        )
        .order_by(WatchEvent.watched_at.desc(), WatchEvent.id.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rewatch to undo")
    db.delete(latest)
    rating_cleared = False
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
        if watch is not None and watch.rating is not None:
            watch.rating = None
            rating_cleared = True
    db.commit()
    _sync_progress(item, db)
    return {**_ratings_summary(item, db), "rating_cleared": rating_cleared}


@router.get("/{item_id}/rewatch-events")
def list_rewatch_events(
    item_id: int,
    season: int | None = Query(default=None, ge=0),
    episode: int | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-event detail behind the aggregate rewatch_count — newest first —
    so the frontend can show a removable history instead of only
    undo-the-latest."""
    item = _get_owned_item(item_id, user, db)
    if (season is None) != (episode is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="season and episode must be given together",
        )
    events = (
        db.query(WatchEvent)
        .filter(WatchEvent.media_item_id == item.id, WatchEvent.season == season, WatchEvent.episode == episode)
        .order_by(WatchEvent.watched_at.desc(), WatchEvent.id.desc())
        .all()
    )
    return [{"id": e.id, "watched_at": e.watched_at} for e in events]


@router.delete("/{item_id}/rewatch-events/{event_id}")
def delete_rewatch_event(
    item_id: int,
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove one specific rewatch event by id, not just the most recent —
    lets the user drop a particular entry out of their rewatch history."""
    item = _get_owned_item(item_id, user, db)
    event = db.query(WatchEvent).filter(WatchEvent.id == event_id, WatchEvent.media_item_id == item.id).first()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rewatch event not found")
    db.delete(event)
    db.commit()
    _sync_progress(item, db)
    return _ratings_summary(item, db)


def _assert_not_future_episode(item: LibraryEntry, season: int, episode_number: int, db: Session) -> None:
    """Raise 422 if the episode's air_date is a future date.

    Only fires when the episode exists in our catalog AND has a known air_date
    that hasn't arrived yet.  Missing catalog row or NULL air_date → allowed
    (treat as possibly aired or untracked). Unset on the unwatch path — only
    called when marking an episode as watched.
    """
    if item.title_id is None:
        return
    ep = (
        db.query(Episode)
        .filter(Episode.title_id == item.title_id, Episode.season == season, Episode.episode_number == episode_number)
        .first()
    )
    if ep is not None and ep.air_date is not None and ep.air_date > date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"S{season:02d}E{episode_number:02d} has not aired yet (air date: {ep.air_date})",
        )


def _assert_no_future_episodes(item: LibraryEntry, season: int, episode_numbers: list[int], db: Session) -> None:
    """Batch form of `_assert_not_future_episode` for marking a whole season
    at once — one query for every episode in the batch instead of one query
    per episode (up to ~24 for a full season)."""
    if item.title_id is None or not episode_numbers:
        return
    future = (
        db.query(Episode)
        .filter(
            Episode.title_id == item.title_id,
            Episode.season == season,
            Episode.episode_number.in_(episode_numbers),
            Episode.air_date.isnot(None),
            Episode.air_date > date.today(),
        )
        .order_by(Episode.episode_number)
        .first()
    )
    if future is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"S{season:02d}E{future.episode_number:02d} has not aired yet (air date: {future.air_date})",
        )


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
        _assert_not_future_episode(item, season, episode, db)
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
    if data.watched:
        _assert_no_future_episodes(item, data.season, data.episodes, db)
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
