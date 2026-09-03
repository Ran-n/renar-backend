#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/09/03 08:54:41.314533

Personal-data export (GDPR Art. 20): request a build, poll its status,
download the result once ready. Available to every authenticated user
regardless of premium status — see users/export_queue.py's docstring for
why premium only affects queue order, never whether the export exists.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import ExportJob, User, utcnow
from ..schemas import ExportRequestedOut, ExportStatusOut
from ..users import export_queue
from ..users.auth import get_current_user
from ..users.export import export_expiry_days, export_is_ready, export_path

router = APIRouter(prefix="/export", tags=["export"])
_log = logging.getLogger(__name__)


def _format_retry_at(retry_at: datetime) -> str:
    """'in 6 days, 20 hours (2026-08-02 12:34 UTC)' — a countdown reads at a
    glance; the absolute timestamp in parentheses is there for whoever comes
    back to this after the countdown's gone stale (a screenshot, a support
    ticket, ...)."""
    remaining = max(retry_at - utcnow(), timedelta(0))
    days, rem_seconds = divmod(int(remaining.total_seconds()), 86400)
    hours = rem_seconds // 3600
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours or not days:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    return f"in {', '.join(parts)} ({retry_at:%Y-%m-%d %H:%M} UTC)"


@router.post("/data", status_code=status.HTTP_202_ACCEPTED, response_model=ExportRequestedOut)
def request_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    live = export_queue.status(user.id)
    if live and live["state"] in ("queued", "processing"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An export is already in progress")
    job = db.get(ExportJob, user.id)
    if export_is_ready(job, user.is_premium):
        # A ready, unexpired export already exists — re-requesting would
        # just rebuild the same window's data (nothing meaningfully changed
        # yet, since a fresh export is offered anyway once this one
        # expires). A failed job (or one whose file has gone missing) is
        # never "ready" per export_is_ready, so it always reaches past this
        # branch and can be retried immediately.
        retry_at = job.completed_at + timedelta(days=export_expiry_days(user.is_premium))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have a ready export. You can request a new one {_format_retry_at(retry_at)}.",
        )
    if job is None:
        job = ExportJob(user_id=user.id)
        db.add(job)
    job.finished = False
    job.error = None
    job.completed_at = None
    job.queued_at = utcnow()
    db.commit()
    export_queue.enqueue(user.id, is_premium=user.is_premium)
    return {"status": "queued"}


@router.get("/data/status", response_model=ExportStatusOut, response_model_exclude_none=True)
def export_status(user: User = Depends(get_current_user)):
    live = export_queue.status(user.id)
    if live is not None and live["state"] in ("queued", "processing"):
        return live

    # A cached "ready" entry (or nothing cached at all) both need the DB
    # row as the source of truth: completed_at — and therefore expiry —
    # isn't tracked in the in-memory dict, and a cached "ready" entry never
    # naturally clears within a running process, so trusting it here would
    # keep reporting ready long past this account's expiry window. A
    # missing/None job (never requested) or a genuine server-restart
    # interruption still need the same DB fallback as before.
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
    # Beyond finished/error, "ready" also requires the file to actually
    # exist (export_is_ready) — a bare completed_at/expiry check here would
    # let this disagree with download_export whenever the row outlives its
    # file (see export_is_ready's docstring for how that happened once).
    if not export_is_ready(job, user.is_premium):
        return {"state": "never_requested"}
    return {"state": "ready"}


@router.get("/data/download")
def download_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.get(ExportJob, user.id)
    if not export_is_ready(job, user.is_premium):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No export ready for this account")
    path = export_path(user.id)
    # mtime is when build_export finished writing this file — the export's
    # own timestamp, not the moment it happens to be downloaded.
    built_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"renar-export-{built_at}.7z"
    return FileResponse(path, media_type="application/x-7z-compressed", filename=filename)
