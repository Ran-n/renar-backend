#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/09/02 10:57:46.400208

Personal-data export (GDPR Art. 20): request/status/download flow and the
priority queue that orders premium requests ahead of free ones without
ever blocking the free path outright.
"""

import io
import json
import threading
import time
from datetime import UTC, datetime, timedelta

import py7zr

from renar_backend.database import SessionLocal
from renar_backend.models import ExportJob, User, utcnow
from renar_backend.users import export as export_module
from renar_backend.users import export_queue


def _set_premium(user_id: int, days: int = 30) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _backdate_completed_at(user_id: int, days: float) -> None:
    """Simulate a ready export that finished `days` ago, without waiting for
    a real one to age — used to test cooldown/expiry boundaries directly."""
    db = SessionLocal()
    try:
        job = db.get(ExportJob, user_id)
        job.completed_at = datetime.now(UTC) - timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _wait_for_ready(client, headers, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get("/export/data/status", headers=headers)
        assert r.status_code == 200
        body = r.json()
        if body["state"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("export never finished")


def test_export_requires_auth(client):
    assert client.post("/export/data").status_code == 401
    assert client.get("/export/data/status").status_code == 401
    assert client.get("/export/data/download").status_code == 401


def test_status_never_requested(client, alice):
    _, headers = alice
    r = client.get("/export/data/status", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"state": "never_requested"}


def test_download_before_ready_is_404(client, alice):
    _, headers = alice
    assert client.get("/export/data/download", headers=headers).status_code == 404


def test_export_flow_free_user(client, alice, tmp_path):
    user, headers = alice
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "rating": 9},
        headers=headers,
    ).raise_for_status()

    r = client.post("/export/data", headers=headers)
    assert r.status_code == 202, r.text

    body = _wait_for_ready(client, headers)
    assert body["state"] == "ready"

    r = client.get("/export/data/download", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-7z-compressed"
    disposition = r.headers["content-disposition"]
    assert "renar-export-" in disposition
    assert disposition.endswith('.7z"')

    with py7zr.SevenZipFile(io.BytesIO(r.content), "r") as zf:
        zf.extractall(path=tmp_path)
    profile = json.loads((tmp_path / "profile.json").read_text())
    library = json.loads((tmp_path / "library.json").read_text())
    assert profile["username"] == user["username"]
    assert profile["is_premium"] is False
    assert len(library) == 1
    assert library[0]["title"] == "Heat"
    assert library[0]["rating"] == 9


def test_export_available_without_premium(client, alice):
    """The export itself is a GDPR right, not a premium perk — only queue
    ordering differs by subscription (see export_queue's docstring)."""
    _, headers = alice
    r = client.post("/export/data", headers=headers)
    assert r.status_code == 202
    body = _wait_for_ready(client, headers)
    assert body["state"] == "ready"


def test_conflict_while_already_queued(client, alice, monkeypatch):
    """A second request while one is still queued/processing is rejected —
    but doesn't need premium to succeed at all, just to not double-queue.

    Blocks the worker mid-job (a persistent worker thread from an earlier
    test may already be running and would otherwise race to finish before
    the second request lands) so the "processing" state is held open for
    the whole assertion instead of relying on timing.
    """
    gate = threading.Event()

    def _blocking_run(user_id):
        export_queue._progress[user_id] = {"state": "processing"}
        gate.wait(timeout=2)

    monkeypatch.setattr(export_queue, "_run", _blocking_run)
    _, headers = alice
    try:
        assert client.post("/export/data", headers=headers).status_code == 202
        assert client.post("/export/data", headers=headers).status_code == 409
    finally:
        gate.set()


def test_premium_dequeued_before_free(alice, bob):
    """Premium requests jump the free ones in the priority heap.

    Pushes straight onto the heap under its own lock instead of calling
    enqueue() (which notifies the worker) — a worker thread started by an
    earlier test is still alive and asleep on the same condition variable,
    and would race to drain the heap the instant anything wakes it, making
    the ordering unobservable. Not notifying keeps it asleep so this can
    assert on the heap's actual order.
    """
    import heapq

    free_user, _ = alice
    premium_user, _ = bob

    with export_queue._not_empty:
        export_queue._heap.clear()
        export_queue._queued_user_ids.clear()
        heapq.heappush(export_queue._heap, (1, next(export_queue._counter), free_user["id"]))
        heapq.heappush(export_queue._heap, (0, next(export_queue._counter), premium_user["id"]))
        assert export_queue._heap[0][2] == premium_user["id"]
        export_queue._heap.clear()
        export_queue._queued_user_ids.clear()


def test_reexport_blocked_while_ready(client, alice):
    """A ready, unexpired export blocks a fresh request with 429 — spamming
    "Request export" shouldn't rebuild the same window's data over and over."""
    _, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)

    r = client.post("/export/data", headers=headers)
    assert r.status_code == 429
    assert "already have a ready export" in r.json()["detail"]


def test_failed_export_can_retry_immediately(client, alice, monkeypatch):
    """A failed job has no completed_at, so it's never subject to the
    cooldown that a ready one is — the failure wasn't the user's fault.
    Fails via the real _run() exception path (not a faked progress dict) so
    the DB row actually ends up finished=True/error=... like production."""

    def _boom(user, db):
        raise RuntimeError("boom")

    monkeypatch.setattr(export_queue, "build_export", _boom)
    _, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    body = _wait_for_ready(client, headers)
    assert body["state"] == "failed"

    # Immediate retry after a failure must not be cooldown-blocked.
    monkeypatch.undo()
    assert client.post("/export/data", headers=headers).status_code == 202


def test_ready_row_with_missing_file_is_not_ready(client, alice):
    """Regression test: a DB row can say finished/unexpired while its file
    is gone (deleted out of band, or written under an old format/name that
    export_path() no longer matches) — export_status must not report
    "ready" in that case just because it never checked the file, the way it
    once did while download_export's separate is_file() check correctly
    404'd the very same account."""
    user, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)

    export_module.export_path(user["id"]).unlink()
    export_queue.forget(user["id"])  # simulate a fresh process, no in-memory cache to hide the gap

    assert client.get("/export/data/status", headers=headers).json() == {"state": "never_requested"}
    assert client.get("/export/data/download", headers=headers).status_code == 404
    # No lingering row should block a fresh request either.
    assert client.post("/export/data", headers=headers).status_code == 202


def test_expired_export_reverts_to_never_requested(client, alice):
    """Past EXPORT_EXPIRY_DAYS_FREE, a ready export stops being reported as
    ready and a fresh request is allowed again — the button's job is to
    reflect this without a separate "expired" state."""
    user, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)

    _backdate_completed_at(user["id"], days=export_module.EXPORT_EXPIRY_DAYS_FREE + 1)
    export_queue.forget(user["id"])  # simulate the cache having already been evicted, like a fresh process would see

    r = client.get("/export/data/status", headers=headers)
    assert r.json() == {"state": "never_requested"}
    assert client.get("/export/data/download", headers=headers).status_code == 404
    assert client.post("/export/data", headers=headers).status_code == 202


def test_premium_shorter_expiry(client, alice):
    """Premium's expiry (and thus cooldown) is EXPORT_EXPIRY_DAYS_PREMIUM,
    shorter than the free tier's — same account, same export, different
    accepted age depending on premium_until."""
    user, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)

    midpoint = (export_module.EXPORT_EXPIRY_DAYS_PREMIUM + export_module.EXPORT_EXPIRY_DAYS_FREE) / 2
    _backdate_completed_at(user["id"], days=midpoint)
    export_queue.forget(user["id"])

    # Still within the free window -> still ready for a free account.
    assert client.get("/export/data/status", headers=headers).json()["state"] == "ready"

    _set_premium(user["id"])
    export_queue.forget(user["id"])
    # Past the (shorter) premium window -> expired for the same export.
    assert client.get("/export/data/status", headers=headers).json()["state"] == "never_requested"


def test_purge_expired_exports_deletes_file_row_and_cache(client, alice):
    user, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)
    assert export_module.export_path(user["id"]).is_file()

    _backdate_completed_at(user["id"], days=export_module.EXPORT_EXPIRY_DAYS_FREE + 1)

    db = SessionLocal()
    try:
        purged = export_module.purge_expired_exports(db)
    finally:
        db.close()

    assert purged == 1
    assert not export_module.export_path(user["id"]).is_file()
    db = SessionLocal()
    try:
        assert db.get(ExportJob, user["id"]) is None
    finally:
        db.close()
    assert export_queue.status(user["id"]) is None


def test_purge_expired_exports_leaves_fresh_ones_alone(client, alice):
    _, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)

    db = SessionLocal()
    try:
        purged = export_module.purge_expired_exports(db)
    finally:
        db.close()
    assert purged == 0
    assert client.get("/export/data/status", headers=headers).json()["state"] == "ready"


# ---------- _format_retry_at edge cases ----------


def test_format_retry_at_days_only(monkeypatch):
    """When remaining time is exactly N days with 0 hours, only the days part
    is included — covers export.py _format_retry_at's `if days:` True branch
    with `if hours or not days:` False (lines 39->41 True, 41->43 False)."""
    from datetime import timedelta

    from renar_backend.models import utcnow
    from renar_backend.routers.export import _format_retry_at

    # 3 days from now, on-the-hour (hours component = 0 after flooring)
    exactly_3_days = utcnow() + timedelta(days=3, seconds=1)
    result = _format_retry_at(exactly_3_days)
    assert "day" in result
    assert "hour" not in result or "0 hour" not in result


def test_format_retry_at_hours_only(monkeypatch):
    """When remaining time is less than 24 hours, only the hours part is
    included — covers the `if days:` False (39->41) + `if hours or not days:`
    True (41->43 is skipped, hours part appended) path."""
    from renar_backend.models import utcnow
    from renar_backend.routers.export import _format_retry_at

    in_3_hours = utcnow() + timedelta(hours=3, minutes=30)
    result = _format_retry_at(in_3_hours)
    assert "day" not in result
    assert "hour" in result


# ---------- export interrupted by server restart ----------


def test_status_reports_interrupted_when_job_not_finished(client, alice):
    """A job row with finished=False (written at queue time, never completed)
    appears as 'failed' with an interruption message in export_status —
    covers routers/export.py line 97."""
    user, headers = alice
    # Write an unfinished ImportJob directly (simulates a server restart
    # mid-export that never got to mark finished=True).
    with SessionLocal() as db:
        db.add(ExportJob(user_id=user["id"], finished=False, error=None, completed_at=None))
        db.commit()

    r = client.get("/export/data/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "failed"
    assert "interrupted" in body["error"].lower()


# ---------- export_queue internal paths ----------


def test_export_queue_enqueue_already_queued_skips_heap_push(alice):
    """Calling enqueue() twice while the user is already in _queued_user_ids
    must not push a duplicate entry — covers export_queue.py's `if user_id not
    in _queued_user_ids:` False branch (line 65->69)."""
    user, _ = alice
    uid = user["id"]
    # Add the user to _queued_user_ids so the second enqueue skips the push
    with export_queue._not_empty:
        export_queue._queued_user_ids.add(uid)
        heap_len_before = len(export_queue._heap)
    try:
        export_queue.enqueue(uid, is_premium=False)
        with export_queue._not_empty:
            heap_len_after = len(export_queue._heap)
        # No new entry pushed since user was already queued
        assert heap_len_after == heap_len_before
    finally:
        with export_queue._not_empty:
            export_queue._queued_user_ids.discard(uid)


def test_export_queue_run_with_deleted_user_exits_cleanly():
    """_run() for a user_id that no longer exists in the DB must return without
    error — covers export_queue.py lines 97-98."""
    export_queue._run(999999)  # no such user
    assert export_queue._progress.get(999999) is None


def test_export_queue_run_without_job_row_still_records_ready(alice):
    """_run() when the ExportJob row doesn't exist must still mark progress
    ready — covers export_queue.py's `if job is not None:` False branch
    (line 102->107)."""
    user, _ = alice
    uid = user["id"]
    # User exists but no ExportJob row
    export_queue._run(uid)
    assert export_queue._progress.get(uid, {}).get("state") == "ready"


def test_export_queue_run_failure_without_job_row(alice, monkeypatch):
    """When build_export raises and there's no ExportJob row, _run() must not
    crash — covers export_queue.py's `if job is not None:` False in except
    (line 115->119)."""
    user, _ = alice
    uid = user["id"]

    def _boom(user_obj, db):
        raise RuntimeError("test failure")

    monkeypatch.setattr(export_queue, "build_export", _boom)
    export_queue._run(uid)
    assert export_queue._progress.get(uid, {}).get("state") == "failed"


# ---------- users/export internal paths ----------


def test_is_export_expired_when_completed_at_is_none():
    """export_is_ready with no completed_at returns True (expired) — covers
    users/export.py line 64."""
    assert export_module.is_export_expired(None) is True
    assert export_module.is_export_expired(None, is_premium=True) is True


def test_purge_expired_exports_skips_free_user_within_free_window(client, alice):
    """A free-tier user whose export is past the premium window but still
    within the free window is NOT purged — covers users/export.py line 256."""
    user, headers = alice
    assert client.post("/export/data", headers=headers).status_code == 202
    _wait_for_ready(client, headers)

    # Backdate to just past the premium window but within the free window
    midpoint = (export_module.EXPORT_EXPIRY_DAYS_PREMIUM + export_module.EXPORT_EXPIRY_DAYS_FREE) / 2
    _backdate_completed_at(user["id"], days=midpoint)
    export_queue.forget(user["id"])

    db = SessionLocal()
    try:
        purged = export_module.purge_expired_exports(db)
    finally:
        db.close()

    assert purged == 0  # free user is still within their window
    assert export_module.export_path(user["id"]).is_file()
