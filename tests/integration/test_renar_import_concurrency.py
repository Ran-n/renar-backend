#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/25 00:00:00.000000
Revised: 2026/08/25 21:52:59.411474

Stresses the `users/renar_import.py` reconcile-lock fix (`with_for_update` +
per-row commit — see docs/design-decisions.md's "Renar-export reconcile
locks the row and commits per entry") against a real server on a real
socket, with a real thread pool firing real HTTP requests — no
`monkeypatch`-gated single-row race like tests/test_renar_import.py's
unit-level coverage of the same fix. That version proves the lock exists at
one deterministic point; this one proves the fix holds up under many rows
and many concurrent writers hitting it at once, which is the actual shape
of the bug report ("concurrent reconciles of the same entry are
last-write-wins").
"""

import io
import json
import threading
import time
import uuid

import httpx
import py7zr
import pytest

from .conftest import register_and_login

pytestmark = [pytest.mark.integration, pytest.mark.load]

_SHOW_COUNT = 8
_PATCH_ATTEMPTS_PER_SHOW = 3


def _library_7z(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr("{}", "profile.json")
        zf.writestr(json.dumps(rows), "library.json")
    return buf.getvalue()


def _wait_for_ready(client: httpx.Client, headers: dict, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = client.get("/import/status", headers=headers)
            r.raise_for_status()
        except httpx.HTTPError:
            # The server is under heavy concurrent load from the PATCH
            # threads below; a single poll timing out isn't the failure
            # this test is checking for, just retry.
            time.sleep(0.2)
            continue
        body = r.json()
        if body["finished"]:
            return body
        time.sleep(0.05)
    raise AssertionError("renar-export import never finished")


def test_many_concurrent_edits_survive_a_real_reconcile_run(live_server):
    """`_SHOW_COUNT` already-tracked shows get reconciled by one import run
    while a pool of real threads independently PATCHes each of them
    (unsynchronized with the import — no gating, no shared event) for as
    long as the import takes. Every show must end up with both the import's
    rating (proving the reconcile itself wasn't skipped/lost) and the last
    PATCH's favorite flag (proving the concurrent edit wasn't clobbered by
    the reconcile's own commit) — a lost update on either side would show
    up as a wrong final value here, and a missing/weakened lock would show
    up as sporadic failures across the many concurrent write attempts this
    fires (`_SHOW_COUNT * _PATCH_ATTEMPTS_PER_SHOW`)."""
    with httpx.Client(base_url=live_server, timeout=30) as client:
        headers = register_and_login(client, live_server, username=f"itest_reconcile_{uuid.uuid4().hex[:8]}")

        tmdb_ids = list(range(90_000, 90_000 + _SHOW_COUNT))
        entry_ids: dict[int, int] = {}
        for tmdb_id in tmdb_ids:
            r = client.post(
                "/media",
                json={"media_type": "tv_show", "title": f"Show {tmdb_id}", "tmdb_id": tmdb_id, "status": "watching"},
                headers=headers,
            )
            r.raise_for_status()
            entry_ids[tmdb_id] = r.json()["id"]

        archive = _library_7z([
            {
                "media_type": "tv_show",
                "tmdb_id": tmdb_id,
                "title": f"Show {tmdb_id}",
                "status": "watching",
                "rating": (tmdb_id % 100) + 1,
            }
            for tmdb_id in tmdb_ids
        ])
        r = client.post(
            "/import",
            files={"file": ("renar-export.7z", archive, "application/x-7z-compressed")},
            headers=headers,
        )
        assert r.status_code == 202, r.text

        errors: list[str] = []
        stop = threading.Event()

        def hammer(tmdb_id: int, entry_id: int) -> None:
            with httpx.Client(base_url=live_server, timeout=30) as patch_client:
                attempts = 0
                while not stop.is_set() and attempts < _PATCH_ATTEMPTS_PER_SHOW:
                    try:
                        resp = patch_client.patch(f"/media/{entry_id}", json={"is_favorite": True}, headers=headers)
                        if resp.status_code != 200:
                            errors.append(
                                f"tmdb_id={tmdb_id} entry_id={entry_id} status={resp.status_code}: {resp.text}"
                            )
                    except httpx.HTTPError as exc:
                        errors.append(f"tmdb_id={tmdb_id} entry_id={entry_id} transport error: {exc}")
                    attempts += 1

        threads = [threading.Thread(target=hammer, args=(tmdb_id, entry_ids[tmdb_id])) for tmdb_id in tmdb_ids]
        for t in threads:
            t.start()

        status_body = _wait_for_ready(client, headers)
        assert status_body["error"] is None, status_body

        stop.set()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive(), "a concurrent PATCH thread never finished"

        assert errors == [], f"{len(errors)} concurrent write(s) failed:\n" + "\n".join(errors[:10])

        for tmdb_id in tmdb_ids:
            entry = client.get(f"/media/{entry_ids[tmdb_id]}", headers=headers).json()
            assert entry["rating"] == (tmdb_id % 100) + 1, f"reconcile lost/never applied for tmdb_id={tmdb_id}"
            assert entry["is_favorite"] is True, f"concurrent PATCH lost for tmdb_id={tmdb_id}"
