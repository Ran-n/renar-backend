#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/16 00:00:00.000000
Revised: 2026/07/17 00:00:00.000000

Shared image-normalization helpers used by routers/auth.py and routers/media.py.

Centralizes the decode → (optional crop) → thumbnail → JPEG pipeline so that
both auth image uploads and media custom-poster/backdrop uploads go through
identical, tested processing code.
"""

import base64
import io
import logging

from fastapi import HTTPException, status
from PIL import Image as PILImage

from ..schemas import CropBox

_log = logging.getLogger(__name__)


def normalize_jpeg(
    raw: bytes,
    max_size: tuple[int, int],
    crop: CropBox | None = None,
) -> bytes:
    """Open `raw` as an image, optionally crop to the fractional region `crop`,
    downscale to fit within `max_size`, and return normalized JPEG bytes.

    Raises HTTP 422 if the bytes are not a valid image.
    """
    try:
        img = PILImage.open(io.BytesIO(raw))
        img = img.convert("RGB")
        if crop is not None:
            w, h = img.size
            box = (
                round(crop.x * w),
                round(crop.y * h),
                round((crop.x + crop.w) * w),
                round((crop.y + crop.h) * h),
            )
            img = img.crop(box)
        img.thumbnail(max_size)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except HTTPException:
        raise
    except Exception as exc:
        _log.debug("normalize_jpeg: could not process image (%s)", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not read that image file",
        ) from exc


def decode_b64_image(image_b64: str) -> bytes:
    """Decode a base64-encoded image upload; raises HTTP 422 on malformed input."""
    try:
        return base64.b64decode(image_b64)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not read that image file",
        ) from exc
