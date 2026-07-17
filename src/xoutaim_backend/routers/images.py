#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.011640
Revised: 2026/07/16 09:54:30.961587

Serve files from the content-addressed image store.
"""

import logging
import re

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from ..media.storage import image_path

router = APIRouter(prefix="/images", tags=["images"])
_log = logging.getLogger(__name__)

HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@router.get("/{hash_}")
def get_image(hash_: str):
    if not HASH_RE.match(hash_):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    path = image_path(hash_)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # content-addressed => immutable => cache aggressively
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})
