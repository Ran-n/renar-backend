#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 16:20:14.056305
Revised: 2026/11/09 16:20:40.172000

Android APK hosting for in-app updates.

renar-frontend's ``uv run build apk --split --publish`` uploads one APK per
ABI here; installed sideloaded apps ask ``GET /app-releases/latest`` for
their ABI and download the file. Files are content-addressed under
``<media_dir>/app-releases/<blake3>.apk``. SHA-256 is stored next to BLAKE3
because the phone verifies with Python's stdlib ``hashlib`` (no native
blake3 wheel on Android); BLAKE3 stays the project's canonical hash.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import BinaryIO

import blake3
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import constants
from .config import settings
from .models import AppRelease
from .schemas import AppReleaseOut

_log = logging.getLogger(__name__)

_CHUNK = 1024 * 1024
_ZIP_MAGIC = b"PK\x03\x04"


def releases_root() -> Path:
    return Path(settings.media_dir) / "app-releases"


def file_path(release: AppRelease) -> Path:
    return releases_root() / f"{release.blake3}.apk"


def version_key(version: str) -> tuple[int, ...]:
    """Integer tuple, so ``0.10.0`` sorts above ``0.9.9``."""
    return tuple(int(part) for part in version.split("."))


def to_out(release: AppRelease) -> AppReleaseOut:
    return AppReleaseOut(
        id=release.id,
        platform=release.platform,
        version=release.version,
        size_bytes=release.size_bytes,
        sha256=release.sha256,
        blake3=release.blake3,
        notes=release.changelog,
        uploaded_at=release.uploaded_at,
        download_url=f"/app-releases/{release.id}/download",
    )


def _stream_to_part(source: BinaryIO, part: Path) -> tuple[str, str, int]:
    """Copy ``source`` into ``part`` while hashing; returns (blake3, sha256, size).

    Raises 413 past the size cap and 422 when the bytes aren't a ZIP (an APK
    is one). The caller deletes ``part`` on any exception.
    """
    b3, sha, size = blake3.blake3(), hashlib.sha256(), 0
    limit = constants.APP_RELEASE_MAX_BYTES
    with part.open("wb") as out:
        while chunk := source.read(_CHUNK):
            if size == 0 and not chunk.startswith(_ZIP_MAGIC):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Not an APK")
            size += len(chunk)
            if size > limit:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE, detail=f"APK larger than {limit // (1024 * 1024)} MiB"
                )
            b3.update(chunk)
            sha.update(chunk)
            out.write(chunk)
    if size == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Not an APK")
    return b3.hexdigest(), sha.hexdigest(), size


def store_upload(
    db: Session, source: BinaryIO, platform: str, version: str, notes: str | None
) -> tuple[AppRelease, bool]:
    """Store an uploaded APK; returns (release, created).

    Re-uploading identical bytes for the same (platform, version) returns the
    existing row with ``created=False``; different bytes for a stored version
    is a 409, because installed apps compare versions and would never fetch
    the replacement.
    """
    root = releases_root()
    root.mkdir(parents=True, exist_ok=True)
    part = root / f".upload-{os.getpid()}-{id(source)}.part"
    try:
        digest, sha, size = _stream_to_part(source, part)
        existing = db.query(AppRelease).filter_by(platform=platform, version=version).first()
        if existing is not None:
            if existing.blake3 == digest:
                _log.info("app release %s %s re-uploaded with the same content", platform, version)
                return existing, False
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Version already published with different content; bump the version",
            )
        same_bytes = db.query(AppRelease).filter_by(blake3=digest).first()
        if same_bytes is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"This file is already published as {same_bytes.platform} {same_bytes.version}",
            )
        release = AppRelease(
            platform=platform, version=version, blake3=digest, sha256=sha, size_bytes=size, changelog=notes
        )
        os.replace(part, file_path(release))
        db.add(release)
        try:
            db.commit()
        except Exception:
            db.rollback()
            file_path(release).unlink(missing_ok=True)
            raise
        db.refresh(release)
        _log.info("stored app release %s %s (%d bytes, blake3 %s)", platform, version, size, digest[:12])
        return release, True
    finally:
        part.unlink(missing_ok=True)


def latest(db: Session, platform: str) -> AppRelease | None:
    rows = db.query(AppRelease).filter_by(platform=platform).all()
    return max(rows, key=lambda r: version_key(r.version), default=None)


def all_by_platform(db: Session) -> dict[str, list[AppRelease]]:
    """Every release grouped by platform, newest version first."""
    grouped: dict[str, list[AppRelease]] = {}
    for row in db.query(AppRelease).all():
        grouped.setdefault(row.platform, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: version_key(r.version), reverse=True)
    return grouped


def delete(db: Session, release_id: int) -> bool:
    """Remove a release row and its file; False when the id is unknown."""
    release = db.get(AppRelease, release_id)
    if release is None:
        return False
    path = file_path(release)
    db.delete(release)
    db.commit()
    try:
        path.unlink()
    except FileNotFoundError:
        _log.warning("app release %s %s had no file at %s", release.platform, release.version, path)
    _log.info("deleted app release %s %s", release.platform, release.version)
    return True
