#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/07/21 09:51:08.424181

Personal-data export (GDPR Art. 20): request/status/download flow and the
priority queue that orders premium requests ahead of free ones without
ever blocking the free path outright.
"""

import io
import json
import threading
import time
import zipfile
from datetime import timedelta

from renar_backend.database import SessionLocal
from renar_backend.models import User, utcnow
from renar_backend.users import export_queue


def _set_premium(user_id: int, days: int = 30) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=days)
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


def test_export_flow_free_user(client, alice):
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
    assert r.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        data = json.loads(zf.read("data.json"))
    assert data["profile"]["username"] == user["username"]
    assert data["profile"]["is_premium"] is False
    assert len(data["library"]) == 1
    assert data["library"][0]["title"] == "Heat"
    assert data["library"][0]["rating"] == 9


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
