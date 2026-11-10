#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 15:59:25.836736
Revised: 2026/11/09 15:59:25.836736

Watch-status rules shared by every path that recomputes a library entry's
progress: per-episode toggles, imports, and a show's production status
changing on a TMDB refresh.

A still-airing show the user is up to date on stays "watching" (In
progress), never "completed" — "completed" means there's nothing left to
watch, which isn't true while new episodes keep coming. Only a show that
has ended (or a film) can be completed.
"""

import logging
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import ENDED_STATUSES
from ..models import Episode, LibraryEntry, MediaType, Title, WatchStatus

_log = logging.getLogger(__name__)


def show_is_airing(title: Title | None) -> bool:
    """True for a tv_show whose TMDB production status is known and not
    ended. An unknown status (unmatched title, not fetched yet) counts as
    not airing, so completion keeps working for shows with no TMDB data."""
    return bool(
        title is not None
        and title.media_type == MediaType.tv_show
        and title.show_status
        and title.show_status not in ENDED_STATUSES
    )


def caught_up_status(item: LibraryEntry) -> WatchStatus:
    """The status for an entry whose every aired episode is watched."""
    return WatchStatus.watching if show_is_airing(item.title_ref) else WatchStatus.completed


def aired_episode_total(title_id: int, db: Session) -> int | None:
    """How many episodes have actually aired, per the synced Episode
    catalog — None when nothing's synced yet for this title (callers fall
    back to the flat Title.total_episodes count).

    Title.total_episodes comes straight from TMDB's number_of_episodes,
    which can already include an announced episode that hasn't aired."""
    known = db.query(func.count(Episode.id)).filter(Episode.title_id == title_id).scalar()
    if not known:
        return None
    return (
        db.query(func.count(Episode.id))
        .filter(Episode.title_id == title_id, Episode.air_date.isnot(None), Episode.air_date <= date.today())
        .scalar()
    )


def resolve_status(item: LibraryEntry, db: Session) -> None:
    """Recompute `item.status` from `item.episodes_watched` (the caller keeps
    that counter current). No commit."""
    total = aired_episode_total(item.title_id, db)
    if total is None:
        total = item.total_episodes
    if total and item.episodes_watched >= total:
        if show_is_airing(item.title_ref):
            # up to date on an airing show: in progress, not finished
            if item.status in (WatchStatus.completed, WatchStatus.want_to_watch):
                item.status = WatchStatus.watching
        else:
            item.status = WatchStatus.completed
    elif total and item.status == WatchStatus.completed:
        # no longer every episode is watched — undo the auto-promotion.
        # Guarded on `total`: a film has no episode concept (`total` None),
        # so a completed film is never demoted here.
        item.status = WatchStatus.watching if item.episodes_watched > 0 else WatchStatus.want_to_watch
    elif item.episodes_watched > 0 and item.status == WatchStatus.want_to_watch:
        item.status = WatchStatus.watching


def refresh_title_entries(db: Session, title: Title) -> None:
    """Re-resolve every in-progress/completed entry of `title` after its
    show_status changed: an ended show the user is caught up on becomes
    completed, a revived one goes back to watching. No commit."""
    entries = (
        db.query(LibraryEntry)
        .filter(
            LibraryEntry.title_id == title.id,
            LibraryEntry.status.in_((WatchStatus.watching, WatchStatus.completed)),
        )
        .all()
    )
    for entry in entries:
        before = entry.status
        resolve_status(entry, db)
        if entry.status != before:
            _log.info(
                "entry %s of title %s: %s -> %s after show_status changed to %r",
                entry.id,
                title.id,
                before.value,
                entry.status.value,
                title.show_status,
            )
