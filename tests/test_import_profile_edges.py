#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:11.265832
Revised: 2026/11/13 15:35:11.265832

Renar-export import corners (an airing show exported as completed, an entry
deleted mid-import, long reply threads, re-imported and empty replies),
profile edits that change nothing, and a custom-poster URL httpx can't parse.
"""

import io
import json
import time

import httpx
import py7zr
import pytest
from _race_helpers import commit_elsewhere
from fastapi import HTTPException
from sqlalchemy import event, false

from renar_backend.database import SessionLocal
from renar_backend.models import LibraryEntry, MediaType, Title, User
from renar_backend.routers import tmdb as tmdb_router
from renar_backend.users import renar_import


def _export(*, library=None, comments=None) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr(json.dumps({}), "profile.json")
        if library is not None:
            zf.writestr(json.dumps(library), "library.json")
        if comments is not None:
            zf.writestr(json.dumps(comments), "comments.json")
    return buf.getvalue()


def _import(client, headers, data: bytes, timeout: float = 15.0) -> dict:
    r = client.post("/import", files={"file": ("x.7z", data, "application/x-7z-compressed")}, headers=headers)
    assert r.status_code == 202, r.text
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/import/status", headers=headers).json()
        if body["finished"]:
            assert body["error"] is None, body
            return body
        time.sleep(0.05)
    pytest.fail("import did not finish")


_SHOW = {"media_type": "tv_show", "title": "Severance", "tmdb_id": 95396}


# ---------------------------------------------------------------------------
# library progress sync
# ---------------------------------------------------------------------------


def test_import_reopens_an_airing_show_exported_as_completed(client, alice):
    """An export from before airing shows stopped auto-completing can list a
    still-airing show as completed; it's imported as in progress."""
    _, headers = alice
    commit_elsewhere(
        Title(media_type=MediaType.tv_show, tmdb_id=_SHOW["tmdb_id"], title="Severance", show_status="Returning Series")
    )
    row = {**_SHOW, "status": "completed", "episode_watches": [{"season": 1, "episode": 1}]}

    body = _import(client, headers, _export(library=[row]))

    assert body["summary"]["library_entries"] == 1
    (entry,) = client.get("/media", headers=headers).json()
    assert entry["status"] == "watching"


def _delete_during_import(monkeypatch, *, after_locked_reads: int) -> None:
    """Make the importer's locked re-reads of a LibraryEntry find nothing once
    `after_locked_reads` of them have run: the user deleted the entry then."""
    real_session = renar_import.SessionLocal
    seen = [0]

    def _session():
        session = real_session()

        @event.listens_for(session, "do_orm_execute")
        def _vanish(state):
            if not (state.is_select and state.statement._for_update_arg is not None):
                return
            if state.statement.column_descriptions[0].get("entity") is not LibraryEntry:
                return
            seen[0] += 1
            if seen[0] > after_locked_reads:
                state.statement = state.statement.where(false())

        return session

    monkeypatch.setattr(renar_import, "SessionLocal", _session)


def test_import_skips_a_row_whose_entry_was_deleted_before_reconcile(client, alice, monkeypatch):
    _, headers = alice
    client.post("/media", json={**_SHOW, "status": "watching"}, headers=headers).raise_for_status()
    _delete_during_import(monkeypatch, after_locked_reads=0)
    row = {**_SHOW, "status": "watching", "rating": 80, "episode_watches": [{"season": 1, "episode": 1}]}

    body = _import(client, headers, _export(library=[row]))

    assert body["summary"]["library_skipped"] == 1
    assert body["summary"]["episodes"] == 0


def test_import_skips_progress_sync_for_an_entry_deleted_after_its_watches(client, alice, monkeypatch):
    _, headers = alice
    client.post("/media", json={**_SHOW, "status": "watching"}, headers=headers).raise_for_status()
    synced = []
    monkeypatch.setattr(renar_import, "_sync_progress", lambda item, db: synced.append(item.id))
    _delete_during_import(monkeypatch, after_locked_reads=1)
    row = {**_SHOW, "status": "watching", "episode_watches": [{"season": 1, "episode": 1}]}

    body = _import(client, headers, _export(library=[row]))

    assert body["summary"]["episodes"] == 1
    assert synced == []


# ---------------------------------------------------------------------------
# comment replies
# ---------------------------------------------------------------------------


def _thread(replies: int, *, empty_reply: bool = False) -> list[dict]:
    rows = [{"id": 1, **_SHOW, "text": "root", "parent_id": None}]
    rows += [{"id": 1 + n, "text": f"reply {n}", "parent_id": 1} for n in range(1, replies + 1)]
    if empty_reply:
        rows.append({"id": 10_000, "text": "", "parent_id": 1})
    return rows


def test_import_long_reply_thread_reports_progress(client, alice, monkeypatch):
    _, headers = alice
    progress = []
    real_set = renar_import._set
    monkeypatch.setattr(renar_import, "_set", lambda user_id, **kw: progress.append(kw) or real_set(user_id, **kw))

    body = _import(client, headers, _export(comments=_thread(120)))

    assert body["summary"]["comments"] == 121
    assert {"done": 100} in progress  # reached inside the reply loop (1 root + 99 replies)


def test_reimported_replies_are_matched_and_empty_ones_skipped(client, alice):
    _, headers = alice
    data = _export(comments=_thread(2, empty_reply=True))

    first = _import(client, headers, data)
    second = _import(client, headers, data)

    assert first["summary"]["comments"] == 3  # root + 2 replies; the empty reply is dropped
    assert second["summary"]["comments"] == 0  # everything matched the first import


# ---------------------------------------------------------------------------
# PATCH /auth/profile no-ops
# ---------------------------------------------------------------------------


def test_profile_patch_with_the_current_email_starts_no_change(client, alice):
    user, headers = alice

    r = client.patch("/auth/profile", json={"email": user["email"].upper()}, headers=headers)

    assert r.status_code == 200, r.text
    assert r.json()["email"] == user["email"]
    db = SessionLocal()
    try:
        row = db.get(User, user["id"])
        assert (row.pending_email, row.email_confirmed) == (None, True)
    finally:
        db.close()


def test_profile_patch_clearing_images_that_were_never_set(client, alice, monkeypatch):
    _, headers = alice
    from renar_backend.routers import auth

    monkeypatch.setattr(auth, "gc_image", lambda image_id, db: pytest.fail("nothing to collect"))

    r = client.patch("/auth/profile", json={"avatar_b64": "", "background_b64": ""}, headers=headers)

    assert r.status_code == 200, r.text
    assert r.json()["avatar"] is None


# ---------------------------------------------------------------------------
# custom poster download
# ---------------------------------------------------------------------------


def test_fetch_poster_bytes_rejects_a_url_httpx_cannot_parse(monkeypatch):
    def _invalid(url):
        raise httpx.InvalidURL("Invalid non-printable ASCII character in URL")

    monkeypatch.setattr(tmdb_router.http_client, "get", _invalid)

    with pytest.raises(HTTPException) as exc:
        tmdb_router.fetch_poster_bytes("https://image.tmdb.org/t/p/original/\x01.jpg")

    assert exc.value.status_code == 422
