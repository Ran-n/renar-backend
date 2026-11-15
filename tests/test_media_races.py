#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:10.542093
Revised: 2026/11/13 15:35:10.542093

Image store and APK store fallbacks: concurrent inserts of the same image
row or external-image mapping, a failed commit after an APK was moved into
place, and shard-directory pruning that has to stop at a non-empty folder.
"""

import io

import pytest
from _race_helpers import commit_elsewhere, hide_selects
from sqlalchemy.exc import IntegrityError

from renar_backend import app_releases
from renar_backend.database import SessionLocal
from renar_backend.media import storage
from renar_backend.media.image_cache import store_external_image
from renar_backend.media.image_service import image_row_for
from renar_backend.models import AppRelease, ExternalImage, Image


@pytest.fixture
def db(client):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _stored(data: bytes) -> str:
    return storage.store_image(data)


# ---------------------------------------------------------------------------
# image_row_for
# ---------------------------------------------------------------------------


def test_image_row_for_adopts_a_concurrently_created_row(db):
    data = b"\xff\xd8 raced image"
    hash_ = _stored(data)
    (winner_id,) = commit_elsewhere(Image(hash=hash_, size_bytes=len(data)))
    hide_selects(db, Image, times=1)

    image = image_row_for(data, db, source_url="https://img.test/a.jpg")

    assert image.id == winner_id
    assert image.source_url == "https://img.test/a.jpg"


def test_image_row_for_keeps_the_winners_source_url(db):
    data = b"\xff\xd8 raced image with url"
    hash_ = _stored(data)
    commit_elsewhere(Image(hash=hash_, size_bytes=len(data), source_url="https://img.test/first.jpg"))
    hide_selects(db, Image, times=1)

    image = image_row_for(data, db, source_url="https://img.test/second.jpg")

    assert image.source_url == "https://img.test/first.jpg"


def test_image_row_for_reraises_when_the_raced_row_cannot_be_found(db):
    data = b"\xff\xd8 vanished image"
    hash_ = _stored(data)
    commit_elsewhere(Image(hash=hash_, size_bytes=len(data)))
    hide_selects(db, Image, times=None)

    with pytest.raises(IntegrityError):
        image_row_for(data, db)


# ---------------------------------------------------------------------------
# store_external_image
# ---------------------------------------------------------------------------


def test_store_external_image_tolerates_a_concurrent_mapping(db):
    data = b"\xff\xd8 tmdb poster"
    other = SessionLocal()
    try:
        image = image_row_for(data, other)
        other.commit()
        commit_elsewhere(ExternalImage(source="tmdb", key="w500/x.jpg", image_id=image.id))
    finally:
        other.close()
    hide_selects(db, ExternalImage, times=1)

    path = store_external_image(db, "tmdb", "w500/x.jpg", data)

    assert path.is_file()
    assert db.query(ExternalImage).filter_by(source="tmdb", key="w500/x.jpg").count() == 1


# ---------------------------------------------------------------------------
# delete_image shard pruning
# ---------------------------------------------------------------------------


def test_delete_image_stops_pruning_at_a_non_empty_shard(db):
    # two hashes sharing a top-level shard directory, so the first delete
    # empties the inner dir but must leave the shared outer one alone
    first = b"shard-a"
    hash_a = _stored(first)
    sibling = storage.image_path(hash_a).parent.parent / "zz" / "keep.jpg"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_bytes(b"x")
    try:
        storage.delete_image(hash_a)

        assert not storage.image_path(hash_a).exists()
        assert not storage.image_path(hash_a).parent.exists()
        assert sibling.parent.parent.is_dir()
    finally:
        sibling.unlink()
        sibling.parent.rmdir()
        sibling.parent.parent.rmdir()


# ---------------------------------------------------------------------------
# app_releases.store_upload
# ---------------------------------------------------------------------------


def test_store_upload_removes_the_file_when_the_commit_fails(db, monkeypatch):
    data = b"PK\x03\x04" + b"commit fails" * 8

    def _fail():
        raise RuntimeError("database went away")

    monkeypatch.setattr(db, "commit", _fail)

    with pytest.raises(RuntimeError, match="database went away"):
        app_releases.store_upload(db, io.BytesIO(data), "android-arm64-v8a", "9.9.9", None)

    assert db.query(AppRelease).count() == 0
    assert list(app_releases.releases_root().glob("*.apk")) == []
    assert list(app_releases.releases_root().glob(".upload-*.part")) == []
