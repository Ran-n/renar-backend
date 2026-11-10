#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 16:20:15.571378
Revised: 2026/11/10 11:04:47.880009

App-release hosting for in-app updates: admin upload rules (idempotency,
conflicts, validation, size cap), the public latest/download routes, the
admin page and delete, and that the "no release yet" 404 every installed
app hits on launch is never an abuse strike.
"""

import hashlib
import logging

import blake3
import pytest
from conftest import admin_headers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from renar_backend import app_releases, constants
from renar_backend.config import settings
from renar_backend.database import SessionLocal
from renar_backend.models import AppRelease
from renar_backend.routers import app_releases as public_router
from renar_backend.users import security
from renar_backend.users.security import AbuseGuardMiddleware

ARM = "android-arm64-v8a"


def apk(tag: str = "a", size: int = 64) -> bytes:
    body = (tag.encode() * size)[:size]
    return b"PK\x03\x04" + body


def upload(client, data: bytes, version: str = "0.23.0", platform: str = ARM, notes: str | None = None, headers=None):
    form = {"platform": platform, "version": version}
    if notes is not None:
        form["notes"] = notes
    return client.post(
        "/admin/app-releases",
        data=form,
        files={"file": ("x.apk", data)},
        headers=admin_headers() if headers is None else headers,
    )


def stored_files() -> list:
    root = app_releases.releases_root()
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


@pytest.fixture(autouse=True)
def _empty_release_dir():
    root = app_releases.releases_root()
    if root.exists():
        for p in root.iterdir():
            p.unlink()
    yield


def test_upload_stores_file_and_row(client, admin_enabled):
    data = apk()
    r = upload(client, data, notes="fixed the crash")
    assert r.status_code == 201, r.text
    body = r.json()
    digest = blake3.blake3(data).hexdigest()
    assert body["blake3"] == digest
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert body["size_bytes"] == len(data)
    assert body["notes"] == "fixed the crash"
    assert body["download_url"] == f"/app-releases/{body['id']}/download"
    assert stored_files() == [f"{digest}.apk"]


def test_upload_same_content_is_idempotent(client, admin_enabled):
    data = apk()
    first = upload(client, data)
    second = upload(client, data)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    with SessionLocal() as db:
        assert db.query(AppRelease).count() == 1
    assert len(stored_files()) == 1


def test_upload_same_version_different_content_conflicts(client, admin_enabled):
    original = apk("a")
    upload(client, original)
    r = upload(client, apk("b"))
    assert r.status_code == 409
    assert "bump the version" in r.json()["detail"]
    assert stored_files() == [f"{blake3.blake3(original).hexdigest()}.apk"]


def test_upload_same_bytes_under_another_version_conflicts(client, admin_enabled):
    data = apk()
    upload(client, data, version="0.23.0")
    r = upload(client, data, version="0.24.0")
    assert r.status_code == 409
    assert len(stored_files()) == 1


def test_upload_rejects_non_zip(client, admin_enabled):
    r = upload(client, b"not a zip at all")
    assert r.status_code == 422
    assert r.json()["detail"] == "Not an APK"
    assert stored_files() == []


def test_upload_rejects_empty_file(client, admin_enabled):
    assert upload(client, b"").status_code == 422
    assert stored_files() == []


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "1.2.3-beta", "", ".".join("1234")])  # 4 parts
def test_upload_rejects_bad_version(client, admin_enabled, version):
    assert upload(client, apk(), version=version).status_code == 422
    assert stored_files() == []


def test_upload_rejects_unknown_platform(client, admin_enabled):
    assert upload(client, apk(), platform="android-mips").status_code == 422
    assert stored_files() == []


def test_upload_rejects_long_or_nul_notes(client, admin_enabled):
    assert upload(client, apk(), notes="x" * 2001).status_code == 422
    assert upload(client, apk(), notes="bad\x00note").status_code == 422
    assert stored_files() == []


def test_upload_too_large_is_413_and_cleans_part_file(client, admin_enabled, monkeypatch):
    monkeypatch.setattr(constants, "APP_RELEASE_MAX_BYTES", 1024)
    r = upload(client, apk(size=4096))
    assert r.status_code == 413
    assert stored_files() == []


def test_upload_requires_admin(client, admin_enabled):
    assert client.post("/admin/app-releases", data={"platform": ARM, "version": "1.0.0"}).status_code == 401
    assert upload(client, apk(), headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert stored_files() == []


def test_latest_compares_versions_numerically(client, admin_enabled):
    upload(client, apk("a"), version="0.9.9")
    upload(client, apk("b"), version="0.10.0")
    r = client.get("/app-releases/latest", params={"platform": ARM})
    assert r.status_code == 200
    assert r.json()["version"] == "0.10.0"


def test_latest_404_when_none(client):
    r = client.get("/app-releases/latest", params={"platform": ARM})
    assert r.status_code == 404
    assert r.json()["detail"] == "No release for this platform"


def test_latest_rejects_unknown_platform(client):
    assert client.get("/app-releases/latest", params={"platform": "ios"}).status_code == 422


def test_latest_is_per_platform(client, admin_enabled):
    upload(client, apk("a"), version="0.30.0", platform="android-x86_64")
    upload(client, apk("b"), version="0.20.0", platform=ARM)
    assert client.get("/app-releases/latest", params={"platform": ARM}).json()["version"] == "0.20.0"
    assert client.get("/app-releases/latest", params={"platform": "android-armeabi-v7a"}).status_code == 404


def test_download_streams_with_versioned_filename(client, admin_enabled):
    data = apk(size=5000)
    release = upload(client, data).json()
    r = client.get(release["download_url"])
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    assert r.headers["content-length"] == str(len(data))
    assert 'filename="renar-0.23.0-arm64-v8a.apk"' in r.headers["content-disposition"]


def test_download_unknown_id_is_404(client):
    assert client.get("/app-releases/999/download").status_code == 404


def test_download_missing_file_is_500_and_logged(client, admin_enabled, caplog):
    release = upload(client, apk()).json()
    (app_releases.releases_root() / f"{release['blake3']}.apk").unlink()
    with caplog.at_level(logging.ERROR, logger="renar_backend.routers.app_releases"):
        r = client.get(release["download_url"])
    assert r.status_code == 500
    assert any("has no file" in rec.getMessage() for rec in caplog.records)


def test_delete_removes_row_and_file(client, admin_enabled):
    release = upload(client, apk()).json()
    r = client.post(f"/admin/app-releases/{release['id']}/delete", headers=admin_enabled, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/app-releases"
    assert stored_files() == []
    assert client.get("/app-releases/latest", params={"platform": ARM}).status_code == 404


def test_delete_promotes_next_latest(client, admin_enabled):
    upload(client, apk("a"), version="0.9.0")
    newest = upload(client, apk("b"), version="0.10.0").json()
    client.post(f"/admin/app-releases/{newest['id']}/delete", headers=admin_enabled)
    assert client.get("/app-releases/latest", params={"platform": ARM}).json()["version"] == "0.9.0"


def test_delete_with_file_already_missing_still_deletes_row(client, admin_enabled, caplog):
    release = upload(client, apk()).json()
    (app_releases.releases_root() / f"{release['blake3']}.apk").unlink()
    with caplog.at_level(logging.WARNING, logger="renar_backend.app_releases"):
        r = client.post(f"/admin/app-releases/{release['id']}/delete", headers=admin_enabled, follow_redirects=False)
    assert r.status_code == 303
    assert any("had no file" in rec.getMessage() for rec in caplog.records)
    with SessionLocal() as db:
        assert db.query(AppRelease).count() == 0


def test_delete_unknown_id_is_404(client, admin_enabled):
    assert client.post("/admin/app-releases/999/delete", headers=admin_enabled).status_code == 404


def test_admin_page_lists_releases_and_empty_state(client, admin_enabled):
    empty = client.get("/admin/app-releases", headers=admin_enabled)
    assert empty.status_code == 200
    assert "No releases uploaded yet" in empty.text
    upload(client, apk("a"), version="0.9.0", notes="<b>notes</b>")
    upload(client, apk("b"), version="0.10.0")
    page = client.get("/admin/app-releases", headers=admin_enabled).text
    assert ARM in page
    assert page.index("0.10.0") < page.index("0.9.0")  # newest first
    assert page.count('pill-latest">Latest') == 1
    assert "&lt;b&gt;notes&lt;/b&gt;" in page  # notes are escaped


def test_admin_page_requires_admin(client, admin_enabled):
    assert client.get("/admin/app-releases", follow_redirects=False).status_code == 303  # to the login page


def test_dashboard_has_app_releases_tile(client, admin_enabled):
    page = client.get("/admin/", headers=admin_enabled).text
    assert 'href="/admin/app-releases"' in page
    assert "Android builds served to in-app updates" in page


def test_latest_404_is_not_an_abuse_strike(monkeypatch):
    monkeypatch.setattr(settings, "abuse_guard_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1000)
    monkeypatch.setattr(settings, "flood_ban_per_minute", 2000)
    monkeypatch.setattr(settings, "probe_ban_threshold", 3)
    security._permabanned.clear()
    security._permabans_loaded = False
    app = FastAPI()
    app.add_middleware(AbuseGuardMiddleware)
    app.include_router(public_router.router)
    guarded = TestClient(app)
    codes = [guarded.get("/app-releases/latest", params={"platform": ARM}).status_code for _ in range(10)]
    assert codes == [404] * 10
