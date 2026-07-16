#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:25:42.200759
Revised: 2026/07/16 09:54:30.478211

DB-side helpers for the content-addressed image store.

Six columns reference images rows: users.avatar_id, users.background_id,
media_items.custom_poster_image_id, media_items.custom_backdrop_image_id,
episode_custom_stills.still_image_id and external_images.image_id.
Everything that attaches or garbage-collects an image must go through here
so the reference counting stays in one place — a GC that only checked
avatars would delete a file still used as somebody's custom poster or as a
cached external image.
"""

import logging

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import EpisodeCustomStill, ExternalImage, Image, LibraryEntry, User
from .storage import delete_image, store_image

_log = logging.getLogger(__name__)


def image_row_for(raw: bytes, db: Session) -> Image:
    """Find-or-create the (deduplicated) image row for these bytes; the file
    is written to the store when missing. Race-safe: concurrent requests
    for the same bytes converge on one row."""
    hash_ = store_image(raw)  # no-op when the identical file already exists
    image = db.query(Image).filter_by(hash=hash_).first()
    if image is not None:
        return image
    try:
        with db.begin_nested():
            image = Image(hash=hash_, size_bytes=len(raw))
            db.add(image)
        db.flush()
        return image
    except IntegrityError:
        image = db.query(Image).filter_by(hash=hash_).first()
        if image is None:
            raise
        return image


def gc_image(image_id: int | None, db: Session) -> None:
    """Delete an image row + file once nothing references it anymore.

    Callers must flush/delete the dropped reference first so this sees the
    post-change state.
    """
    if image_id is None:
        return
    # Four LIMIT-1 checks (short-circuiting) instead of six COUNT queries —
    # each uses LIMIT 1 and Python's `or` stops as soon as a reference is found.
    # Same-table checks are combined with OR so they hit each table at most once.
    still_used = (
        db.query(User).filter(or_(User.avatar_id == image_id, User.background_id == image_id)).first() is not None
        or db.query(LibraryEntry)
        .filter(
            or_(
                LibraryEntry.custom_poster_image_id == image_id,
                LibraryEntry.custom_backdrop_image_id == image_id,
            )
        )
        .first()
        is not None
        or db.query(EpisodeCustomStill).filter(EpisodeCustomStill.still_image_id == image_id).first() is not None
        or db.query(ExternalImage).filter(ExternalImage.image_id == image_id).first() is not None
    )
    if still_used:
        return
    image = db.get(Image, image_id)
    if image:
        _log.debug("gc_image: deleting image id=%s hash=%s", image_id, image.hash[:12])
        delete_image(image.hash)
        db.delete(image)
