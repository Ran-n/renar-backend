"""Content-addressed file store.

Layout (git-style two-level fan-out, so no directory grows unbounded):

    media/
      images/
        3f/
          a2/
            3fa29c...e1.jpg

A file's name is the blake3 hash of its bytes; identical content is stored
exactly once and shared by every row that references it.
"""
from pathlib import Path

import blake3

from .config import settings

IMAGES_ROOT = Path(settings.media_dir) / "images"


def hash_bytes(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()


def image_path(hash_: str) -> Path:
    return IMAGES_ROOT / hash_[:2] / hash_[2:4] / f"{hash_}.jpg"


def store_image(data: bytes) -> str:
    """Write bytes to the store (no-op if already present); returns the hash."""
    hash_ = hash_bytes(data)
    path = image_path(hash_)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return hash_


def delete_image(hash_: str) -> None:
    """Remove a file from the store; prunes now-empty shard directories."""
    path = image_path(hash_)
    try:
        path.unlink()
    except OSError:
        return
    for parent in (path.parent, path.parent.parent):
        try:
            parent.rmdir()  # only succeeds when empty — exactly what we want
        except OSError:
            break
