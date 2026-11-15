#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:43.482192
Revised: 2026/11/14 22:43:28.405501

Diary: the caller's watch log, newest first — every watched episode and
every watched film, each with the date it was watched and its rating.

One row per watched episode (`episode_watches`) and one per watched film
(`media_items.last_watched_at`), so a rewatch moves an entry to its latest
date instead of adding a second one. A show as a whole has no entry of its
own: finishing it is already the entry of its last episode.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import Integer, String, cast, literal, null, select, tuple_, union_all
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Episode, EpisodeWatch, LibraryEntry, MediaType, Title, User, WatchStatus
from ..schemas import DiaryEntryOut
from ..tmdb.tmdb_store import localized_titles, warm_title_translations
from ..users.auth import get_current_user

router = APIRouter(prefix="/diary", tags=["diary"])
_log = logging.getLogger(__name__)

EPISODE = "episode"
FILM = "film"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
# how many not-yet-translated titles one request may queue for background
# translation: enough for a page, bounded so one call can't fan out widely
_MAX_WARMUP_PER_REQUEST = 15


# the widest offsets in use are UTC-12:00 and UTC+14:00
MAX_UTC_OFFSET_MINUTES = 14 * 60


def _day_start(day: date, utc_offset_minutes: int = 0) -> datetime:
    """Midnight opening `day` for a caller `utc_offset_minutes` east of UTC."""
    return datetime.combine(day, time.min, tzinfo=timezone(timedelta(minutes=utc_offset_minutes)))


def _watch_rows(
    user_id: int,
    kind: str | None,
    since: date | None,
    until: date | None,
    utc_offset_minutes: int = 0,
    end_utc_offset_minutes: int | None = None,
):
    """One SELECT over both sources, as (kind, item_id, season, episode,
    watched_at, rating, row_id) rows. `since`/`until` are calendar days at
    `utc_offset_minutes` east of UTC (UTC days by default), both included.
    `end_utc_offset_minutes` is the offset in force at the end of `until`
    when it differs from the start's (a range crossing a clock change)."""
    if end_utc_offset_minutes is None:
        end_utc_offset_minutes = utc_offset_minutes
    episodes = (
        select(
            literal(EPISODE, String).label("kind"),
            EpisodeWatch.media_item_id.label("item_id"),
            EpisodeWatch.season.label("season"),
            EpisodeWatch.episode.label("episode"),
            EpisodeWatch.watched_at.label("watched_at"),
            EpisodeWatch.rating.label("rating"),
            EpisodeWatch.id.label("row_id"),
        )
        .join(LibraryEntry, LibraryEntry.id == EpisodeWatch.media_item_id)
        .where(LibraryEntry.user_id == user_id)
    )
    films = (
        select(
            literal(FILM, String).label("kind"),
            LibraryEntry.id.label("item_id"),
            cast(null(), Integer).label("season"),
            cast(null(), Integer).label("episode"),
            LibraryEntry.last_watched_at.label("watched_at"),
            LibraryEntry.rating.label("rating"),
            LibraryEntry.id.label("row_id"),
        )
        .join(Title, Title.id == LibraryEntry.title_id)
        .where(
            LibraryEntry.user_id == user_id,
            Title.media_type == MediaType.film,
            # last_watched_at is also stamped when a film is merely started
            # ("watching"); only a completed film counts as watched
            LibraryEntry.status == WatchStatus.completed,
            LibraryEntry.last_watched_at.is_not(None),
        )
    )
    sources = {EPISODE: episodes, FILM: films}
    rows = union_all(*([sources[kind]] if kind else sources.values())).subquery("watches")
    query = select(rows)
    if since is not None:
        query = query.where(rows.c.watched_at >= _day_start(since, utc_offset_minutes))
    if until is not None:
        query = query.where(rows.c.watched_at < _day_start(until + timedelta(days=1), end_utc_offset_minutes))
    # kind and row_id only break ties between watches stamped in the same
    # instant (a bulk "mark season watched"), so paging never skips or
    # repeats a row; episodes of one bulk mark then read last episode first
    return query.order_by(
        rows.c.watched_at.desc(), rows.c.kind, rows.c.season.desc(), rows.c.episode.desc(), rows.c.row_id.desc()
    )


@router.get("", response_model=list[DiaryEntryOut])
def list_diary(
    background_tasks: BackgroundTasks,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    kind: Literal["film", "episode"] | None = Query(default=None, alias="type"),
    since: date | None = Query(default=None, alias="from"),
    until: date | None = Query(default=None, alias="to"),
    utc_offset: int = Query(default=0, ge=-MAX_UTC_OFFSET_MINUTES, le=MAX_UTC_OFFSET_MINUTES),
    utc_offset_to: int | None = Query(default=None, ge=-MAX_UTC_OFFSET_MINUTES, le=MAX_UTC_OFFSET_MINUTES),
    lang: str | None = Query(default=None, max_length=10),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The caller's watched episodes and films, newest first.

    `type` keeps only films or only episodes; `from`/`to` keep only watches
    on those days (both included). The days are UTC days unless `utc_offset`
    (minutes east of UTC) says where the caller's midnight falls: a client
    that groups entries by its local day sends its own offset, so the range
    it asks for is the range it shows. `utc_offset` is the offset at the
    midnight that opens `from`; `utc_offset_to` is the one at the midnight
    that closes `to`, sent when a clock change falls inside the range
    (it defaults to `utc_offset`). A page shorter than `page_size` is
    the last one. `lang` localizes titles the same way GET /media does.
    """
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="`from` must not be after `to`")
    rows = db.execute(
        _watch_rows(user.id, kind, since, until, utc_offset, utc_offset_to)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    if not rows:
        return []
    entries = {
        e.id: e
        for e in db.query(LibraryEntry)
        .options(
            joinedload(LibraryEntry.title_ref),
            joinedload(LibraryEntry.custom_poster_image),
            joinedload(LibraryEntry.owner),
        )
        .filter(LibraryEntry.id.in_({r.item_id for r in rows}))
    }
    episode_keys = {(entries[r.item_id].title_id, r.season, r.episode) for r in rows if r.kind == EPISODE}
    episode_names = {}
    if episode_keys:
        episode_names = {
            (title_id, season, number): name
            for title_id, season, number, name in db.query(
                Episode.title_id, Episode.season, Episode.episode_number, Episode.name
            ).filter(tuple_(Episode.title_id, Episode.season, Episode.episode_number).in_(episode_keys))
        }
    title_ids = sorted({e.title_id for e in entries.values()})
    translations: dict[int, str] = {}
    if lang and lang != "en":
        translations = localized_titles(db, title_ids, lang)
        missing = [tid for tid in title_ids if tid not in translations]
        if missing:
            background_tasks.add_task(warm_title_translations, missing[:_MAX_WARMUP_PER_REQUEST], lang)

    out = []
    for row in rows:
        entry = entries[row.item_id]
        title = entry.title_ref
        out.append({
            "type": row.kind,
            "item_id": entry.id,
            "title_id": title.id,
            "tmdb_id": title.tmdb_id,
            "media_type": title.media_type,
            "title": translations.get(title.id) or title.title,
            "poster_url": entry.poster_url,
            "watched_at": row.watched_at,
            "rating": row.rating,
            "season": row.season,
            "episode": row.episode,
            "episode_name": episode_names.get((title.id, row.season, row.episode)),
        })
    return out
