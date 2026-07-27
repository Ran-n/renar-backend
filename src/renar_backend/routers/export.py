#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/07/21 09:51:07.650622

Personal-data export (GDPR Art. 20): request a build, poll its status,
download the result once ready. Available to every authenticated user
regardless of premium status — see users/export_queue.py's docstring for
why premium only affects queue order, never whether the export exists.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import ExportJob, User
from ..users import export_queue
from ..users.auth import get_current_user
from ..users.export import export_path

router = APIRouter(prefix="/export", tags=["export"])
_log = logging.getLogger(__name__)


@router.post("/data", status_code=status.HTTP_202_ACCEPTED)
def request_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    live = export_queue.status(user.id)
    if live and live["state"] in ("queued", "processing"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An export is already in progress")
    job = db.get(ExportJob, user.id)
    if job is None:
        job = ExportJob(user_id=user.id)
        db.add(job)
    job.finished = False
    job.error = None
    db.commit()
    export_queue.enqueue(user.id, is_premium=user.is_premium)
    return {"status": "queued"}


@router.get("/data/status")
def export_status(user: User = Depends(get_current_user)):
    live = export_queue.status(user.id)
    if live is not None:
        return live

    # Nothing in memory for this user — either no export ever ran on this
    # process, or one did and the process (and its in-memory progress dict)
    # was lost mid-build, e.g. a server restart. ExportJob (written at job
    # start and at completion/failure) tells the two apart: a row stuck at
    # finished=False means the job never got to report back.
    db = SessionLocal()
    try:
        job = db.get(ExportJob, user.id)
    finally:
        db.close()
    if job is None:
        return {"state": "never_requested"}
    if not job.finished:
        return {"state": "failed", "error": "Export was interrupted by a server restart. Please request it again."}
    if job.error:
        return {"state": "failed", "error": job.error}
    return {"state": "ready"}


@router.get("/data/download")
def download_export(user: User = Depends(get_current_user)):
    path = export_path(user.id)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No export ready for this account")
    # mtime is when build_export finished writing this file — the export's
    # own timestamp, not the moment it happens to be downloaded.
    built_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"renar-export-{built_at}.7z"
    return FileResponse(path, media_type="application/x-7z-compressed", filename=filename)
