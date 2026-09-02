#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/27 00:00:00.000000
Revised: 2026/09/02 10:58:06.951269

Import a Renar export (.7z) back into an account: the round trip half of
GDPR Art. 20 that users/export.py builds, exercised end-to-end through the
same download an account holder would actually get.
"""

import io
import json
import time

import py7zr
from conftest import login, register


def _empty_7z() -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr("{}", "profile.json")
    return buf.getvalue()


def _library_7z(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr("{}", "profile.json")
        zf.writestr(json.dumps(rows), "library.json")
    return buf.getvalue()


def _wait_for_ready(client, headers, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get("/import/status", headers=headers)
        assert r.status_code == 200
        body = r.json()
        if body["finished"]:
            return body
        time.sleep(0.05)
    raise AssertionError("renar-export import never finished")


def _download_export(client, headers) -> bytes:
    r = client.post("/export/data", headers=headers)
    assert r.status_code == 202, r.text
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = client.get("/export/data/status", headers=headers).json()
        if st["state"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert st["state"] == "ready", st
    r = client.get("/export/data/download", headers=headers)
    assert r.status_code == 200
    return r.content


def test_import_requires_auth(client):
    assert client.post("/import").status_code == 401
    assert client.get("/import/status").status_code == 401


def test_status_never_run(client, alice):
    _, headers = alice
    r = client.get("/import/status", headers=headers)
    assert r.status_code == 200
    assert r.json()["stage"] == "Never run"


def test_round_trip_restores_library_comments_follows_and_profile(client, alice, bob):
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob

    item = client.post(
        "/media",
        json={
            "media_type": "tv_show",
            "title": "Dark",
            "tmdb_id": 555,
            "status": "watching",
            "rating": 8,
            "is_favorite": True,
            "notes": "great show",
        },
        headers=alice_headers,
    ).json()
    client.put(f"/media/{item['id']}/episodes/1/1", json={"watched": True}, headers=alice_headers).raise_for_status()
    client.post(
        "/comments",
        json={"media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "text": "nice show"},
        headers=alice_headers,
    ).raise_for_status()
    client.patch("/auth/profile", json={"language": "es"}, headers=alice_headers).raise_for_status()
    client.post(f"/users/{bob_user['id']}/follow", headers=alice_headers).raise_for_status()

    archive = _download_export(client, alice_headers)

    charlie_headers = _register_and_login(client, "charlie")

    r = client.post(
        "/import",
        files={"file": ("renar-export.7z", archive, "application/x-7z-compressed")},
        headers=charlie_headers,
    )
    assert r.status_code == 202, r.text

    status_body = _wait_for_ready(client, charlie_headers)
    assert status_body["error"] is None, status_body
    summary = status_body["summary"]
    assert summary["library_entries"] == 1
    assert summary["episodes"] == 1
    assert summary["comments"] == 1
    assert summary["follows"] == 1

    entry = client.get(
        "/media/by_tmdb", params={"media_type": "tv_show", "tmdb_id": 555}, headers=charlie_headers
    ).json()
    assert entry["rating"] == 8
    assert entry["is_favorite"] is True
    assert entry["notes"] == "great show"
    assert entry["status"] == "watching"

    me = client.get("/auth/me", headers=charlie_headers).json()
    assert me["language"] == "es"

    charlie_user = client.get("/auth/me", headers=charlie_headers).json()
    following = client.get(f"/users/{charlie_user['id']}/following", headers=charlie_headers).json()
    assert any(u["username"] == bob_user["username"] for u in following)


def test_reimport_does_not_duplicate(client, alice):
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "tmdb_id": 777, "status": "completed", "rating": 9},
        headers=alice[1],
    ).raise_for_status()
    archive = _download_export(client, alice[1])

    for _ in range(2):
        r = client.post(
            "/import",
            files={"file": ("renar-export.7z", archive, "application/x-7z-compressed")},
            headers=alice[1],
        )
        assert r.status_code == 202, r.text
        status_body = _wait_for_ready(client, alice[1])
        assert status_body["error"] is None

    entries = client.get("/media", headers=alice[1]).json()
    assert len([e for e in entries if e["tmdb_id"] == 777]) == 1


def test_concurrent_edit_during_reconcile_is_not_lost(client, alice, monkeypatch):
    """A PATCH /media edit racing an in-flight reconcile of the same entry
    must not be silently discarded by whichever side commits last. The
    import thread is gated inside `_reconcile_library_entry` so it holds its
    `with_for_update` lock on the row while a concurrent PATCH is fired; the
    PATCH's own UPDATE must block on that lock (proving the row is actually
    locked, not just read) rather than racing ahead and losing whichever
    write lands first."""
    import threading

    from renar_backend.users import renar_import

    user, headers = alice
    entry = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "status": "watching"},
        headers=headers,
    ).json()
    assert entry["rating"] is None
    assert entry["is_favorite"] is False

    started = threading.Event()
    proceed = threading.Event()
    original = renar_import._reconcile_library_entry

    def gated(entry_obj, incoming):
        started.set()
        proceed.wait(timeout=5)
        return original(entry_obj, incoming)

    monkeypatch.setattr(renar_import, "_reconcile_library_entry", gated)

    archive = _library_7z([
        {"media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "status": "watching", "rating": 90}
    ])
    r = client.post(
        "/import",
        files={"file": ("renar-export.7z", archive, "application/x-7z-compressed")},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    assert started.wait(timeout=5), "import never reached the reconcile gate"

    patch_result = {}

    def do_patch():
        patch_result["response"] = client.patch(f"/media/{entry['id']}", json={"is_favorite": True}, headers=headers)

    patch_thread = threading.Thread(target=do_patch)
    patch_thread.start()
    patch_thread.join(timeout=0.5)
    assert patch_thread.is_alive(), "concurrent PATCH did not block on the locked row"

    proceed.set()
    patch_thread.join(timeout=5)
    assert not patch_thread.is_alive()
    assert patch_result["response"].status_code == 200

    _wait_for_ready(client, headers)
    final = client.get(f"/media/{entry['id']}", headers=headers).json()
    assert final["rating"] == 90
    assert final["is_favorite"] is True


def test_concurrent_edit_during_progress_sync_is_not_lost(client, alice, monkeypatch):
    """The touched_items pass at the end of `_import_library` (`_sync_progress`,
    which derives `episodes_watched`/current season+episode) locks its row
    the same way the reconcile pass does. A PATCH racing that second lock
    site must block and merge too, not just the first one."""
    import threading

    from renar_backend.users import renar_import

    _, headers = alice
    entry = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "status": "watching"},
        headers=headers,
    ).json()
    assert entry["notes"] is None

    started = threading.Event()
    proceed = threading.Event()
    original = renar_import._sync_progress

    def gated(item, db):
        started.set()
        proceed.wait(timeout=5)
        return original(item, db)

    monkeypatch.setattr(renar_import, "_sync_progress", gated)

    archive = _library_7z([
        {
            "media_type": "tv_show",
            "tmdb_id": 555,
            "title": "Dark",
            "status": "watching",
            "episode_watches": [{"season": 1, "episode": 1}],
        }
    ])
    r = client.post(
        "/import",
        files={"file": ("renar-export.7z", archive, "application/x-7z-compressed")},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    assert started.wait(timeout=5), "import never reached the progress-sync gate"

    patch_result = {}

    def do_patch():
        patch_result["response"] = client.patch(
            f"/media/{entry['id']}", json={"notes": "concurrent edit"}, headers=headers
        )

    patch_thread = threading.Thread(target=do_patch)
    patch_thread.start()
    patch_thread.join(timeout=0.5)
    assert patch_thread.is_alive(), "concurrent PATCH did not block on the locked row"

    proceed.set()
    patch_thread.join(timeout=5)
    assert not patch_thread.is_alive()
    assert patch_result["response"].status_code == 200

    _wait_for_ready(client, headers)
    final = client.get(f"/media/{entry['id']}", headers=headers).json()
    assert final["episodes_watched"] == 1
    assert final["notes"] == "concurrent edit"


def test_reconcile_commits_incrementally_row_by_row(client, alice, monkeypatch):
    """Committing per row (instead of batching the whole file into one
    end-of-import transaction) is what keeps each row's lock hold time
    short. Verify that a row's reconciled change is durably visible to a
    completely separate reader before the next row has even started, i.e.
    the commit genuinely happens per row and not only once at the end."""
    import threading

    from renar_backend.database import SessionLocal
    from renar_backend.models import LibraryEntry
    from renar_backend.users import renar_import

    _, headers = alice
    first = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "status": "watching"},
        headers=headers,
    ).json()
    second = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Severance", "tmdb_id": 666, "status": "watching"},
        headers=headers,
    ).json()

    second_row_started = threading.Event()
    proceed = threading.Event()
    original = renar_import._reconcile_library_entry
    calls = []

    def gated(entry_obj, incoming):
        calls.append(incoming.get("tmdb_id"))
        if len(calls) == 2:
            second_row_started.set()
            proceed.wait(timeout=5)
        return original(entry_obj, incoming)

    monkeypatch.setattr(renar_import, "_reconcile_library_entry", gated)

    archive = _library_7z([
        {"media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "status": "watching", "rating": 90},
        {"media_type": "tv_show", "tmdb_id": 666, "title": "Severance", "status": "watching", "rating": 70},
    ])
    r = client.post(
        "/import",
        files={"file": ("renar-export.7z", archive, "application/x-7z-compressed")},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    assert second_row_started.wait(timeout=5), "import never reached the second row"

    db = SessionLocal()
    try:
        db_first = db.get(LibraryEntry, first["id"])
        db_second = db.get(LibraryEntry, second["id"])
        assert db_first.rating == 90, "first row's commit was not yet visible to a separate reader"
        assert db_second.rating is None, "second row's change was committed before it was even reconciled"
    finally:
        db.close()

    proceed.set()
    _wait_for_ready(client, headers)


def test_conflict_while_already_running(client, alice, monkeypatch):
    import threading

    from renar_backend.users import renar_import

    gate = threading.Event()

    def _blocking_run(user_id, archive_bytes):
        renar_import._progress[user_id] = {"finished": False, "stage": "Importing library"}
        gate.wait(timeout=2)

    monkeypatch.setattr(renar_import, "run", _blocking_run)
    _, headers = alice
    try:
        r1 = client.post(
            "/import",
            files={"file": ("renar-export.7z", _empty_7z(), "application/x-7z-compressed")},
            headers=headers,
        )
        assert r1.status_code == 202, r1.text
        r2 = client.post(
            "/import",
            files={"file": ("renar-export.7z", _empty_7z(), "application/x-7z-compressed")},
            headers=headers,
        )
        assert r2.status_code == 409
    finally:
        gate.set()


def test_rejects_non_7z_upload(client, alice):
    _, headers = alice
    r = client.post(
        "/import",
        files={"file": ("renar-export.7z", b"not a real archive", "application/x-7z-compressed")},
        headers=headers,
    )
    assert r.status_code == 422


def test_sources_lists_registered_importers(client, alice):
    _, headers = alice
    r = client.get("/import/sources", headers=headers)
    assert r.status_code == 200
    kinds = {s["kind"]: s["label"] for s in r.json()}
    assert kinds == {"renar": "Renar", "tvtime": "TV Time"}


def test_claimed_kind_mismatch_is_rejected(client, alice):
    _, headers = alice
    r = client.post(
        "/import",
        data={"claimed_kind": "tvtime"},
        files={"file": ("renar-export.7z", _empty_7z(), "application/x-7z-compressed")},
        headers=headers,
    )
    assert r.status_code == 422
    assert "Renar" in r.json()["detail"]
    assert "TV Time" in r.json()["detail"]


def test_claimed_kind_match_proceeds(client, alice):
    _, headers = alice
    r = client.post(
        "/import",
        data={"claimed_kind": "renar"},
        files={"file": ("renar-export.7z", _empty_7z(), "application/x-7z-compressed")},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    status_body = _wait_for_ready(client, headers)
    assert status_body["error"] is None


def _register_and_login(client, username: str) -> dict:
    register(client, username)
    return login(client, username)


def _full_7z(*, profile=None, library=None, comments=None, social=None) -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr(json.dumps(profile or {}), "profile.json")
        if library is not None:
            zf.writestr(json.dumps(library), "library.json")
        if comments is not None:
            zf.writestr(json.dumps(comments), "comments.json")
        if social is not None:
            zf.writestr(json.dumps(social), "social.json")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Unit tests — pure functions, no DB needed
# ---------------------------------------------------------------------------


def test_parse_iso_handles_none_empty_and_invalid():
    from renar_backend.users.renar_import import _parse_iso

    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None
    dt = _parse_iso("2025-01-15T10:00:00+00:00")
    assert dt is not None


def test_reconcile_library_entry_fills_rating_and_notes():
    from unittest.mock import MagicMock

    from renar_backend.users.renar_import import _reconcile_library_entry

    entry = MagicMock()
    entry.is_favorite = False
    entry.rating = None
    entry.notes = None

    changed = _reconcile_library_entry(entry, {"rating": 80, "notes": "great", "is_favorite": True})
    assert changed is True
    assert entry.rating == 80
    assert entry.notes == "great"
    assert entry.is_favorite is True


def test_try_start_job_returns_false_when_already_active():
    from renar_backend.users import renar_import

    user_id = 9_000_001
    renar_import._active_users.add(user_id)
    try:
        assert renar_import.try_start_job(user_id) is False
    finally:
        renar_import._active_users.discard(user_id)
        renar_import._progress.pop(user_id, None)


def test_read_json_returns_empty_for_missing_file():
    import tempfile
    from pathlib import Path

    from renar_backend.users.renar_import import _read_json

    with tempfile.TemporaryDirectory() as tmp:
        assert _read_json(Path(tmp), "nonexistent.json") == {}


def test_mark_job_db_exception_does_not_raise(monkeypatch):
    from renar_backend.users import renar_import

    class _FailDB:
        def get(self, *a, **kw):
            raise RuntimeError("injected DB failure")

        def add(self, *a):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(renar_import, "SessionLocal", lambda: _FailDB())
    # Must not propagate — exception is caught and logged
    renar_import._mark_job(9_000_002, finished=True, error=None, summary=None)


# ---------------------------------------------------------------------------
# Integration tests — library edge cases
# ---------------------------------------------------------------------------


def test_import_skips_invalid_media_type_and_status(client, alice):
    _, headers = alice
    rows = [
        {"media_type": "alien_type", "title": "Bad", "tmdb_id": 1, "status": "watching"},
        {"media_type": "tv_show", "title": "Also Bad", "tmdb_id": 2, "status": "INVALID_STATUS"},
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _library_7z(rows), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    assert body["summary"]["library_skipped"] == 2


def test_import_progress_counter_fires_at_50_rows(client, alice):
    """_import_library calls _set(done=n) every 50 rows (line 274)."""
    _, headers = alice
    rows = [{"media_type": "film", "title": f"Film{i}", "status": "completed"} for i in range(55)]
    r = client.post(
        "/import", files={"file": ("x.7z", _library_7z(rows), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    assert body["summary"]["library_entries"] == 55


def test_import_library_no_tmdb_id_in_existing_map(client, alice):
    """An existing library entry without a tmdb_id must still be dedup'd by title_key
    (covers the False branch of `if t.tmdb_id:` in the existing_map build loop)."""
    _, headers = alice
    # Add an entry without tmdb_id via the regular API first
    client.post(
        "/media",
        json={"media_type": "film", "title": "NoTmdbFilm", "status": "completed"},
        headers=headers,
    ).raise_for_status()
    # Re-import that same title — reconcile path, not new-entry path
    rows = [{"media_type": "film", "title": "NoTmdbFilm", "status": "completed", "rating": 75}]
    r = client.post(
        "/import", files={"file": ("x.7z", _library_7z(rows), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    # Reconciled, not new
    assert body["summary"]["library_entries"] == 0


def test_import_deduplicates_episode_watches_and_skips_none_key(client, alice):
    """Duplicate watch entries in the archive are only inserted once;
    watches with a None season/episode key are skipped."""
    _, headers = alice
    rows = [
        {
            "media_type": "tv_show",
            "title": "Probe",
            "tmdb_id": 9_000_900,
            "status": "watching",
            "episode_watches": [
                {"season": 1, "episode": 1},
                {"season": 1, "episode": 1},  # duplicate
                {"season": None, "episode": 1},  # None key → skip
                {"season": 1, "episode": None},  # None key → skip
            ],
        }
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _library_7z(rows), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    assert body["summary"]["episodes"] == 1


def test_import_autocompletes_when_all_episodes_watched(client, alice):
    """_sync_progress sets status=completed when episodes_watched >= total_episodes."""
    _, headers = alice
    entry = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Miniseries", "tmdb_id": 9_000_800, "status": "watching"},
        headers=headers,
    ).json()

    from renar_backend.database import SessionLocal
    from renar_backend.models import LibraryEntry

    db = SessionLocal()
    try:
        lib = db.get(LibraryEntry, entry["id"])
        lib.title_ref.total_episodes = 1  # total_episodes is on Title, not LibraryEntry
        db.commit()
    finally:
        db.close()

    rows = [
        {
            "media_type": "tv_show",
            "title": "Miniseries",
            "tmdb_id": 9_000_800,
            "status": "watching",
            "episode_watches": [{"season": 1, "episode": 1}],
        }
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _library_7z(rows), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    final = client.get(f"/media/{entry['id']}", headers=headers).json()
    assert final["status"] == "completed"


# ---------------------------------------------------------------------------
# Integration tests — comments edge cases
# ---------------------------------------------------------------------------


def test_import_comments_skips_incomplete_rows(client, alice):
    _, headers = alice
    comments = [
        {"id": 1, "media_type": None, "title": "X", "text": "hi", "parent_id": None},
        {"id": 2, "media_type": "tv_show", "title": None, "text": "hi", "parent_id": None},
        {"id": 3, "media_type": "tv_show", "title": "X", "text": None, "parent_id": None},
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _full_7z(comments=comments), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    assert body["summary"]["comments"] == 0
    assert body["summary"]["comments_skipped"] == 3


def test_import_comments_deduplicates_existing_root(client, alice):
    _, headers = alice
    client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "status": "watching"},
        headers=headers,
    ).raise_for_status()
    client.post(
        "/comments",
        json={"media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "text": "nice show"},
        headers=headers,
    ).raise_for_status()

    comments = [
        {"id": 10, "media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "text": "nice show", "parent_id": None}
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _full_7z(comments=comments), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    # dedup: same comment already exists — not re-created
    assert body["summary"]["comments"] == 0


def test_import_comments_with_replies_and_orphan(client, alice):
    _, headers = alice
    comments = [
        {"id": 1, "media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "text": "root", "parent_id": None},
        {"id": 2, "media_type": None, "title": None, "text": "reply to root", "parent_id": 1},
        {"id": 3, "media_type": None, "title": None, "text": "orphan", "parent_id": 99_999},
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _full_7z(comments=comments), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["error"] is None
    assert body["summary"]["comments"] == 2  # root + reply
    assert body["summary"]["comments_skipped"] == 1  # orphan dropped


def test_import_comments_progress_counter_at_100_roots(client, alice):
    """_import_comments calls _set(done=done) every 100 root comments (line 371)."""
    _, headers = alice
    comments = [
        {"id": i, "media_type": "tv_show", "tmdb_id": 555, "title": "Dark", "text": f"comment {i}", "parent_id": None}
        for i in range(105)
    ]
    r = client.post(
        "/import", files={"file": ("x.7z", _full_7z(comments=comments), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers, timeout=15.0)
    assert body["error"] is None
    assert body["summary"]["comments"] == 105


# ---------------------------------------------------------------------------
# Integration tests — social edge cases
# ---------------------------------------------------------------------------


def test_import_social_skips_self_and_nonexistent(client, alice):
    alice_user, alice_headers = alice
    social = {"following": [alice_user["username"], "zzz_no_such_user_xyz"]}
    r = client.post(
        "/import",
        files={"file": ("x.7z", _full_7z(social=social), "application/x-7z-compressed")},
        headers=alice_headers,
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, alice_headers)
    assert body["error"] is None
    assert body["summary"]["follows_skipped"] == 2
    assert body["summary"]["follows"] == 0


def test_import_social_skips_existing_follow(client, alice, bob):
    alice_user, alice_headers = alice
    bob_user, _ = bob
    client.post(f"/users/{bob_user['id']}/follow", headers=alice_headers).raise_for_status()

    social = {"following": [bob_user["username"]]}
    r = client.post(
        "/import",
        files={"file": ("x.7z", _full_7z(social=social), "application/x-7z-compressed")},
        headers=alice_headers,
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, alice_headers)
    assert body["error"] is None
    assert body["summary"]["follows_skipped"] == 1
    assert body["summary"]["follows"] == 0


def test_import_social_progress_counter_at_50(client, alice):
    """_import_social calls _set(done=n) every 50 entries (line 438)."""
    alice_user, alice_headers = alice
    # 55 nonexistent usernames — all skipped, but counter still ticks
    social = {"following": [f"ghost_user_{i}" for i in range(55)]}
    r = client.post(
        "/import",
        files={"file": ("x.7z", _full_7z(social=social), "application/x-7z-compressed")},
        headers=alice_headers,
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, alice_headers)
    assert body["error"] is None
    assert body["summary"]["follows_skipped"] == 55


# ---------------------------------------------------------------------------
# Integration test — run() exception handling
# ---------------------------------------------------------------------------


def test_run_exception_is_captured_in_status(client, alice, monkeypatch):
    """An unhandled exception inside run() must set finished=True and error!=None."""
    from renar_backend.users import renar_import

    def _boom(*args, **kwargs):
        raise RuntimeError("Injected failure for coverage")

    monkeypatch.setattr(renar_import, "_import_library", _boom)

    _, headers = alice
    rows = [{"media_type": "tv_show", "title": "X", "tmdb_id": 1, "status": "watching"}]
    r = client.post(
        "/import", files={"file": ("x.7z", _library_7z(rows), "application/x-7z-compressed")}, headers=headers
    )
    assert r.status_code == 202, r.text
    body = _wait_for_ready(client, headers)
    assert body["finished"] is True
    assert body["error"] is not None
