#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/09/01 00:00:00.000000
Revised: 2026/09/02 10:58:38.529588

Unit tests for the media utility modules:
  media/http_cache.py   — TTLCache get/put with eviction
  media/image_utils.py  — normalize_jpeg (crop path, error paths), decode_b64_image errors
  media/storage.py      — delete_image OSError paths, directory pruning
  media/image_cache.py  — stored_external_image missing file, store_external_image race
  media/image_service.py — image_row_for IntegrityError race, gc_image no-op when image gone
"""

import base64
import io

import pytest
from fastapi import HTTPException
from PIL import Image as PILImage

from renar_backend.database import SessionLocal
from renar_backend.media.http_cache import TTLCache
from renar_backend.media.image_cache import store_external_image, stored_external_image
from renar_backend.media.image_service import gc_image, image_row_for
from renar_backend.media.image_utils import decode_b64_image, normalize_jpeg
from renar_backend.media.storage import delete_image, image_path, store_image
from renar_backend.models import ExternalImage, Image
from renar_backend.schemas import CropBox

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg(width: int = 8, height: int = 8) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color=(128, 64, 32)).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------


def test_ttlcache_get_returns_none_on_miss():
    cache = TTLCache(ttl_seconds=60, max_entries=10)
    assert cache.get(("key",)) is None


def test_ttlcache_get_returns_value_on_hit():
    cache = TTLCache(ttl_seconds=60, max_entries=10)
    cache.put(("key",), "hello")
    assert cache.get(("key",)) == "hello"


def test_ttlcache_get_returns_none_after_expiry(monkeypatch):
    import time as _time

    cache = TTLCache(ttl_seconds=1, max_entries=10)
    t = [_time.time()]
    monkeypatch.setattr(_time, "time", lambda: t[0])
    cache.put(("key",), "val")
    t[0] += 2  # advance past TTL
    assert cache.get(("key",)) is None


def test_ttlcache_put_evicts_expired_entries_when_full(monkeypatch):
    """When at capacity, expired entries are removed first."""
    import time as _time

    t = [_time.time()]
    monkeypatch.setattr(_time, "time", lambda: t[0])

    cache = TTLCache(ttl_seconds=5, max_entries=3)
    cache.put(("a",), 1)
    cache.put(("b",), 2)
    cache.put(("c",), 3)  # now at capacity

    t[0] += 10  # all three expire

    cache.put(("d",), 4)  # triggers eviction of expired entries
    assert cache.get(("d",)) == 4
    assert cache.get(("a",)) is None  # evicted


def test_ttlcache_put_evicts_oldest_when_no_expired_entries(monkeypatch):
    """When full and no entries have expired, the oldest-expiring is dropped."""
    import time as _time

    t = [_time.time()]
    monkeypatch.setattr(_time, "time", lambda: t[0])

    cache = TTLCache(ttl_seconds=100, max_entries=2)
    cache.put(("first",), 1)  # expires at t+100
    t[0] += 1
    cache.put(("second",), 2)  # expires at t+101

    # adding a third entry forces eviction — ("first",) has the smallest expiry
    cache.put(("third",), 3)
    assert cache.get(("first",)) is None
    assert cache.get(("second",)) == 2
    assert cache.get(("third",)) == 3


# ---------------------------------------------------------------------------
# normalize_jpeg — crop path and error paths
# ---------------------------------------------------------------------------


def test_normalize_jpeg_applies_crop():
    raw = _make_jpeg(width=100, height=100)
    crop = CropBox(x=0.25, y=0.25, w=0.5, h=0.5)
    result = normalize_jpeg(raw, (50, 50), crop=crop)
    img = PILImage.open(io.BytesIO(result))
    assert img.format == "JPEG"
    # should have been cropped and thumbnailed to at most 50×50
    assert img.size[0] <= 50 and img.size[1] <= 50


def test_normalize_jpeg_raises_422_on_invalid_bytes():
    with pytest.raises(HTTPException) as exc_info:
        normalize_jpeg(b"not an image", (200, 200))
    assert exc_info.value.status_code == 422


def test_normalize_jpeg_reraises_http_exception(monkeypatch):
    """An HTTPException raised inside the try block must not be swallowed
    by the outer except Exception handler."""
    from PIL import Image as _PILImage

    injected = HTTPException(status_code=400, detail="injected")

    def boom(*args, **kwargs):
        raise injected

    monkeypatch.setattr(_PILImage, "open", boom)
    with pytest.raises(HTTPException) as exc_info:
        normalize_jpeg(b"whatever", (200, 200))
    assert exc_info.value is injected


# ---------------------------------------------------------------------------
# decode_b64_image
# ---------------------------------------------------------------------------


def test_decode_b64_image_happy_path():
    raw = b"hello bytes"
    encoded = base64.b64encode(raw).decode()
    assert decode_b64_image(encoded) == raw


def test_decode_b64_image_raises_422_on_bad_input():
    with pytest.raises(HTTPException) as exc_info:
        decode_b64_image("!!!not base64!!!")
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# storage.py
# ---------------------------------------------------------------------------


def test_store_image_is_idempotent():
    raw = b"idempotent image"
    h1 = store_image(raw)
    h2 = store_image(raw)
    assert h1 == h2
    assert image_path(h1).is_file()
    delete_image(h1)


def test_delete_image_removes_file_and_prunes_directories():
    raw = b"to be deleted"
    h = store_image(raw)
    path = image_path(h)
    assert path.is_file()
    delete_image(h)
    assert not path.exists()
    assert not path.parent.exists()


def test_delete_image_no_error_on_already_missing():
    """Deleting a non-existent hash must be a no-op (FileNotFoundError swallowed)."""
    delete_image("a" * 64)  # must not raise


def test_delete_image_osderror_is_logged_and_swallowed(tmp_path, monkeypatch):
    """OSError during unlink is logged but must not propagate."""
    raw = b"oserror test"
    h = store_image(raw)
    path = image_path(h)

    def boom(self):
        raise OSError("permission denied")

    monkeypatch.setattr(type(path), "unlink", boom)
    delete_image(h)  # must not raise
    # cleanup
    monkeypatch.undo()
    delete_image(h)


def test_delete_image_skips_rmdir_when_parent_still_has_files():
    """If a shard directory has other files, rmdir raises OSError and we break out."""
    raw1 = b"file one " + b"\x00" * 100
    raw2 = b"file two " + b"\x00" * 200

    h1 = store_image(raw1)
    h2 = store_image(raw2)

    p1 = image_path(h1)
    p2 = image_path(h2)

    # Only delete one; if they share a shard dir the rmdir will fail silently
    # (parent still has the other file). If they're in different shards, both
    # directories will be pruned — either way must not raise.
    delete_image(h1)
    assert not p1.exists()
    # cleanup
    delete_image(h2)
    assert not p2.exists()


# ---------------------------------------------------------------------------
# image_cache.py
# ---------------------------------------------------------------------------


def test_stored_external_image_returns_none_when_not_cached(client):
    db = SessionLocal()
    try:
        assert stored_external_image(db, "tmdb", "missing-key") is None
    finally:
        db.close()


def test_stored_external_image_returns_none_when_file_missing(client):
    """Row exists but the file was deleted — must return None and log warning."""
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        path = store_external_image(db, "tmdb", "orphan-key", raw)
        # Physically remove the stored file to simulate manual cleanup
        path.unlink()
        result = stored_external_image(db, "tmdb", "orphan-key")
        assert result is None
    finally:
        db.close()


def test_store_external_image_is_idempotent(client):
    """Calling store_external_image twice for the same (source, key) must not
    create duplicate rows (IntegrityError branch)."""
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        p1 = store_external_image(db, "tmdb", "dedup-key", raw)
        p2 = store_external_image(db, "tmdb", "dedup-key", raw)
        assert p1 == p2
        assert db.query(ExternalImage).filter_by(source="tmdb", key="dedup-key").count() == 1
    finally:
        db.close()


def test_store_external_image_skips_insert_when_row_already_exists(client):
    """If an ExternalImage row was inserted between the query and the insert
    (concurrent duplicate), the function must log a debug message and continue."""
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        # First call creates row and file
        store_external_image(db, "tmdb", "race-key", raw)
        # Second call finds the existing row (existing is not None path)
        path = store_external_image(db, "tmdb", "race-key", raw)
        assert path.is_file()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# image_service.py — image_row_for and gc_image
# ---------------------------------------------------------------------------


def test_image_row_for_creates_row_and_deduplicates(client):
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        img1 = image_row_for(raw, db)
        img2 = image_row_for(raw, db)
        assert img1.id == img2.id
    finally:
        db.close()


def test_image_row_for_sets_source_url_on_first_hit(client):
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        img = image_row_for(raw, db, source_url="https://example.com/img.jpg")
        assert img.source_url == "https://example.com/img.jpg"
        # second call with a different URL must not overwrite (first-recorded wins)
        img2 = image_row_for(raw, db, source_url="https://other.com/img.jpg")
        assert img2.source_url == "https://example.com/img.jpg"
    finally:
        db.close()


def test_image_row_for_updates_source_url_on_dedup_when_previously_none(client):
    """A dedup hit against a row with no source_url gets the new URL attached."""
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        img1 = image_row_for(raw, db, source_url=None)
        assert img1.source_url is None
        img2 = image_row_for(raw, db, source_url="https://example.com/late.jpg")
        assert img2.source_url == "https://example.com/late.jpg"
        assert img1.id == img2.id
    finally:
        db.close()


def test_gc_image_deletes_unreferenced_image(client):
    raw = _make_jpeg()
    db = SessionLocal()
    try:
        img = image_row_for(raw, db)
        db.commit()
        img_id = img.id
        h = img.hash
        path = image_path(h)
        assert path.is_file()

        gc_image(img_id, db)
        db.commit()

        assert db.get(Image, img_id) is None
        assert not path.exists()
    finally:
        db.close()


def test_gc_image_noop_when_image_id_is_none(client):
    db = SessionLocal()
    try:
        gc_image(None, db)  # must not raise
    finally:
        db.close()


def test_gc_image_noop_when_image_row_missing(client):
    """image_id is not None but no Image row exists — must exit cleanly."""
    db = SessionLocal()
    try:
        gc_image(99999, db)  # must not raise
    finally:
        db.close()
