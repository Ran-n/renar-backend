#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 16:20:14.448518
Revised: 2026/11/09 16:20:40.658772

Public app-release routes: installed sideloaded apps ask for the newest APK
for their ABI and download it. No auth: the phone may not be signed in yet,
and the files are the same ones every user installs.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import app_releases
from ..constants import APP_RELEASE_PLATFORMS
from ..database import get_db
from ..models import AppRelease
from ..schemas import AppReleaseOut

router = APIRouter(prefix="/app-releases", tags=["app-releases"])
_log = logging.getLogger(__name__)

# A Literal (not a plain str) so a typo'd platform is a 422, never a silent 404.
AppReleasePlatform = Literal[APP_RELEASE_PLATFORMS]


@router.get("/latest", response_model=AppReleaseOut)
def latest_release(platform: AppReleasePlatform = Query(...), db: Session = Depends(get_db)):
    release = app_releases.latest(db, platform)
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No release for this platform")
    return app_releases.to_out(release)


@router.get("/{release_id}/download")
def download_release(release_id: int, db: Session = Depends(get_db)):
    release = db.get(AppRelease, release_id)
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such release")
    path = app_releases.file_path(release)
    if not path.is_file():
        _log.error("app release %d (%s %s) has no file at %s", release.id, release.platform, release.version, path)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Release file is missing on the server")
    abi = release.platform.removeprefix("android-")
    return FileResponse(
        path,
        media_type="application/vnd.android.package-archive",
        filename=f"renar-{release.version}-{abi}.apk",
    )
