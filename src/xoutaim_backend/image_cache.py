#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:19:17.878175
Revised: 2026/07/10 18:26:22.222090

Cached external images (TMDB posters/stills, Open Library covers).

The bytes live in the content-addressed store (storage.py) exactly like
user avatars; the external_images table maps the upstream identity
(source, key) to the stored file so each image is downloaded at most once
and identical files are shared. Callers keep their own fetch/validation
logic; this module only answers "do we have it?" and "remember it".
"""

import logging
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .image_service import image_row_for
from .models import ExternalImage
from .storage import image_path

_log = logging.getLogger(__name__)


def stored_external_image(db: Session, source: str, key: str) -> Path | None:
    """Path of the stored file for (source, key), or None if never cached."""
    row = db.query(ExternalImage).filter_by(source=source, key=key).first()
    if row is None:
        return None
    path = image_path(row.image.hash)
    if not path.is_file():  # store file lost (manual cleanup?) — refetch
        _log.warning("external image %s/%s has a row but no file %s", source, key, path)
        return None
    return path


def store_external_image(db: Session, source: str, key: str, data: bytes) -> Path:
    """Write the bytes to the store and remember the (source, key) mapping.
    Race-safe: concurrent requests for the same image converge on one row."""
    image = image_row_for(data, db)  # no-op when the identical file already exists
    existing = db.query(ExternalImage).filter_by(source=source, key=key).first()
    if existing is None:
        try:
            with db.begin_nested():
                db.add(ExternalImage(source=source, key=key, image_id=image.id))
        except IntegrityError:
            pass  # another request cached it first — same content either way
    db.commit()
    return image_path(image.hash)
