#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/07/21 09:51:08.045732

Priority queue for building personal-data exports (see users/export.py).

Building an export is cheap today (a handful of DB reads plus a small JSON
zip), so a single worker thread processing one job at a time is plenty —
the queue isn't about throughput, it's about ordering: premium requests are
dequeued ahead of free ones because premium pays for compute priority, same
as any other resource-priority perk. It is NOT a way to slow down or
discourage the free path — data portability is a GDPR right (Art. 20) and
must stay free and available to every account regardless of subscription;
see the "Your rights" section of docs/privacy-policy.md. Ties (both
premium, or both free) resolve FIFO by request order.
"""

import heapq
import itertools
import logging
import threading

from ..database import SessionLocal
from ..models import ExportJob, User
from .export import build_export, write_export

_log = logging.getLogger(__name__)

_lock = threading.Lock()
_not_empty = threading.Condition(_lock)
_heap: list[tuple[int, int, int]] = []  # (priority, seq, user_id) — 0=premium, 1=free
_counter = itertools.count()
_queued_user_ids: set[int] = set()
_worker_started = False

# Live progress, mirrored to the durable ExportJob row at start/finish. A
# server restart wipes this dict; ExportJob.finished lets a status poll
# after that tell "was queued, got dropped by the restart" apart from
# "never requested" — same pattern as routers/imports.py's ImportJob.
_progress: dict[int, dict] = {}


def status(user_id: int) -> dict | None:
    return _progress.get(user_id)


def enqueue(user_id: int, *, is_premium: bool) -> None:
    """Queue (or re-queue) this user's export. A repeat request while one is
    already queued just leaves it queued once — no point building the same
    export twice back to back."""
    priority = 0 if is_premium else 1
    with _not_empty:
        _progress[user_id] = {"state": "queued"}
        if user_id not in _queued_user_ids:
            _queued_user_ids.add(user_id)
            heapq.heappush(_heap, (priority, next(_counter), user_id))
            _not_empty.notify()
    _ensure_worker()


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    threading.Thread(target=_worker_loop, daemon=True, name="export-worker").start()


def _worker_loop() -> None:
    while True:
        with _not_empty:
            while not _heap:
                _not_empty.wait()
            _, _, user_id = heapq.heappop(_heap)
            _queued_user_ids.discard(user_id)
        _run(user_id)


def _run(user_id: int) -> None:
    _progress[user_id] = {"state": "processing"}
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            _progress.pop(user_id, None)
            return  # account deleted while queued
        content = build_export(user, db)
        write_export(user_id, content)
        job = db.get(ExportJob, user_id)
        if job is not None:
            job.finished = True
            job.error = None
            db.commit()
        _progress[user_id] = {"state": "ready"}
    except Exception:
        _log.warning("export failed for user_id=%s", user_id, exc_info=True)
        db.rollback()
        # The real exception goes to the log above only — callers only ever
        # see a generic message via GET /export/data/status.
        generic_error = "Export failed due to an internal error. Please try again or contact support."
        job = db.get(ExportJob, user_id)
        if job is not None:
            job.finished = True
            job.error = generic_error
            db.commit()
        _progress[user_id] = {"state": "failed", "error": generic_error}
    finally:
        db.close()
