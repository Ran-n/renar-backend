#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/27 00:00:00.000000
Revised: 2026/07/27 00:00:00.000000

Import a Renar export (.7z) back into an account: the round trip half of
GDPR Art. 20 that users/export.py builds, exercised end-to-end through the
same download an account holder would actually get.
"""

import io
import time

import py7zr
from conftest import login, register


def _empty_7z() -> bytes:
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr("{}", "profile.json")
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
