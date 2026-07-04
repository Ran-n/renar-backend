"""Serve files from the content-addressed image store."""
import re

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from ..storage import image_path

router = APIRouter(prefix="/images", tags=["images"])

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@router.get("/{hash_}")
def get_image(hash_: str):
    if not HASH_RE.match(hash_):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    path = image_path(hash_)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # content-addressed => immutable => cache aggressively
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
