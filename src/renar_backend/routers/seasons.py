#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:43.610711
Revised: 2026/11/14 00:43:56.451334

Season ratings: the caller's own 1-100 grade for one whole season of a show
in their library, separate from the show's overall rating and from each
episode's rating.

A season can be rated only once every aired episode of it is watched (see
catalog/progress.py's season_is_complete): the same "only after actually
watching it" rule the title-level rating implies. The grade is never
derived from or pre-filled with any episode's rating. It is one editable
fact per (library entry, season): rewatching a season does not add another.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog.progress import season_is_complete
from ..database import get_db
from ..events import publish as publish_event
from ..models import MediaType, SeasonRating, User
from ..schemas import PG_INT32_MAX, SeasonRatingOut, SeasonRatingSet
from ..tmdb.tmdb_store import ensure_seasons_synced
from ..users.auth import get_current_user
from .media import _get_owned_item

router = APIRouter(prefix="/media", tags=["seasons"])
_log = logging.getLogger(__name__)

_SEASON = Path(ge=0, le=PG_INT32_MAX)


def _get_rating(db: Session, item_id: int, season: int) -> SeasonRating | None:
    return db.query(SeasonRating).filter(SeasonRating.media_item_id == item_id, SeasonRating.season == season).first()


@router.put("/{item_id}/seasons/{season}/rating", response_model=SeasonRatingOut)
def set_season_rating(
    item_id: int,
    data: SeasonRatingSet,
    season: int = _SEASON,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rate (or re-rate) a season the caller has fully watched."""
    item = _get_owned_item(item_id, user, db)
    if item.media_type != MediaType.tv_show:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Only a TV show has seasons")
    ensure_seasons_synced(db, item.title_ref, {season})
    if not season_is_complete(db, item, season):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Watch every aired episode of this season before rating it",
        )
    row = _get_rating(db, item.id, season)
    if row is None:
        row = SeasonRating(media_item_id=item.id, season=season, rating=data.rating)
        db.add(row)
    else:
        row.rating = data.rating
    try:
        db.commit()
    except IntegrityError:
        # the caller's own concurrent request inserted the row first: apply
        # this request's grade to that row instead of failing
        db.rollback()
        _log.info("concurrent season rating for item %s season %s: updating the existing row", item.id, season)
        row = _get_rating(db, item.id, season)
        if row is None:  # and it was deleted again in between: nothing to update
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Try again") from None
        row.rating = data.rating
        db.commit()
    publish_event(user.id, "library_changed")
    return {"season": season, "rating": row.rating}


@router.delete("/{item_id}/seasons/{season}/rating", status_code=status.HTTP_204_NO_CONTENT)
def clear_season_rating(
    item_id: int,
    season: int = _SEASON,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove the caller's rating for a season; a no-op when there is none.
    Allowed whether or not the season is still fully watched."""
    item = _get_owned_item(item_id, user, db)
    row = _get_rating(db, item.id, season)
    if row is None:
        return
    db.delete(row)
    db.commit()
    publish_event(user.id, "library_changed")
