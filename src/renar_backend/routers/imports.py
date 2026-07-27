#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:15.146587
Revised: 2026/07/27 10:44:15.615104

One upload endpoint, many import origins: POST /import takes whatever file
the user picked, auto-detects which registered importer it belongs to (by
content, not filename — see each importer's own `detect`), and dispatches
to it. GET /import/status reports on whichever importer last ran (or is
still running) for the caller. Adding a new origin — e.g. Letterboxd's own
export, or a future non-file/OAuth-based source — is a matter of adding one
entry to IMPORTERS below; nothing here needs to change per-origin.

Each entry in IMPORTERS is a self-contained importer module (users/
renar_import.py, users/tvtime_import.py, ...) exposing a common shape:
  KIND: str                         stable id ("renar", "tvtime", ...)
  LABEL: str                        display name, for the source picker and
                                     the mismatch error below
  detect(bytes) -> bool             does this file belong to this importer?
  run(user_id, bytes) -> None       blocking; runs the whole import
  progress(user_id) -> dict | None  live in-memory status, or None if idle
  is_running(user_id) -> bool
  start_job(user_id) -> None        records job start (memory + ImportJob)
  acquire_slot() -> bool            non-blocking; this importer's own
  release_slot() -> None            concurrency budget (independent of the
                                     others' — a slow origin can't starve a
                                     fast one, or vice versa)

GET /import/sources lists (kind, label) for every registered importer, so
the frontend can offer a "which are you importing from?" picker before the
file dialog: the user's pick travels back as `claimed_kind` on the upload,
and is cross-checked against what `detect()` actually finds — agreement
proceeds as normal, disagreement is rejected with a clear "this looks like
X, not Y" instead of either trusting the user's claim blindly or silently
overriding it. Passing no `claimed_kind` (or omitting the picker) still
works exactly as before: detection alone decides.

A connection-based origin with no file at all (an OAuth pull, say) doesn't
fit the "detect from bytes" half of this — it would get its own endpoint
(e.g. "connect account") that calls straight into that importer's run()
after auth, skipping detection. It still shares this same ImportJob table
and status shape, so the frontend's polling/progress code needs no origin-
specific branches either way.
"""

import logging
import threading

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import ImportJob, User
from ..users import renar_import, tvtime_import
from ..users.auth import get_current_user

router = APIRouter(prefix="/import", tags=["import"])
_log = logging.getLogger(__name__)

# Every registered importer, tried in order — first (and only) match wins.
# Order matters only in that a file must never satisfy two detectors at
# once; if that ever becomes possible, put the more specific one first.
IMPORTERS = [renar_import, tvtime_import]

# Bounds how many uploads can be held in memory (up to MAX_UPLOAD_BYTES each)
# at once across ALL origins, during the read-and-detect step only — each
# importer's own acquire_slot()/release_slot() separately bounds how many of
# ITS runs can be in flight for the (much longer) processing step.
MAX_CONCURRENT_UPLOADS = 5
_upload_slots = threading.Semaphore(MAX_CONCURRENT_UPLOADS)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _detect(data: bytes):
    for importer in IMPORTERS:
        if importer.detect(data):
            return importer
    return None


@router.get("/sources")
def import_sources():
    return [{"kind": importer.KIND, "label": importer.LABEL} for importer in IMPORTERS]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def import_data(
    file: UploadFile,
    claimed_kind: str | None = Form(None),
    user: User = Depends(get_current_user),
):
    if any(importer.is_running(user.id) for importer in IMPORTERS):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An import is already running")
    if not _upload_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many imports running right now. Please try again shortly.",
        )
    try:
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="File too large")
        importer = _detect(data)
        if importer is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Unrecognized export file",
            )
        if claimed_kind and claimed_kind != importer.KIND:
            claimed_label = next((i.LABEL for i in IMPORTERS if claimed_kind == i.KIND), claimed_kind)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"This looks like a {importer.LABEL} export, not {claimed_label}.",
            )
    finally:
        _upload_slots.release()

    if not importer.acquire_slot():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many imports running right now. Please try again shortly.",
        )
    importer.start_job(user.id)

    def _run():
        try:
            importer.run(user.id, data)
        finally:
            importer.release_slot()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "kind": importer.KIND}


@router.get("/status")
def import_status(user: User = Depends(get_current_user)):
    for importer in IMPORTERS:
        live = importer.progress(user.id)
        if live is not None:
            return {**live, "kind": importer.KIND}

    # Nothing in memory for this user on any registered importer — either
    # none ever ran on this process, or one did and the process (and its
    # in-memory progress dict) was lost mid-import, e.g. a server restart.
    # ImportJob (written at job start and at completion/failure) tells the
    # two apart: a row stuck at finished=False means the job never got to
    # report back. Picking the most recently updated row across every kind
    # this account has ever run is the right generalization of "my last
    # import" once there can be more than one origin in play.
    db: Session = SessionLocal()
    try:
        job = db.query(ImportJob).filter(ImportJob.user_id == user.id).order_by(ImportJob.updated_at.desc()).first()
    finally:
        db.close()
    if job is None:
        return {
            "stage": "Never run",
            "finished": True,
            "error": None,
            "summary": None,
            "done": 0,
            "total": 0,
            "kind": None,
        }
    if not job.finished:
        return {
            "stage": "Failed",
            "finished": True,
            "error": "Import was interrupted by a server restart. Please re-run it.",
            "summary": None,
            "done": 0,
            "total": 0,
            "kind": job.kind,
        }
    return {
        "stage": "Failed" if job.error else "Done",
        "finished": True,
        "error": job.error,
        "summary": job.summary,
        "done": 0,
        "total": 0,
        "kind": job.kind,
    }
