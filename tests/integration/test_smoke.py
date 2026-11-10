#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:07:31.849247
Revised: 2026/11/09 23:36:41.622337

Post-boot sanity check: the smallest possible set of requests that prove a
freshly started server is actually serviceable — not full feature coverage
(that's tests/test_*.py and tests/integration/test_*_live.py), just "did the
deploy come up alive." Meant to run in seconds against a live_server and
gate a deploy/release before the real suite runs.
"""

import pytest

from .conftest import register_and_login

pytestmark = [pytest.mark.integration, pytest.mark.smoke]


def test_health_reports_ok(http_client):
    r = http_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_public_registration_status_is_served(http_client):
    r = http_client.get("/auth/registration-status")
    assert r.status_code == 200


def test_can_register_login_and_hit_an_authed_route(http_client, live_server):
    headers = register_and_login(http_client, live_server)
    r = http_client.get("/auth/me", headers=headers)
    assert r.status_code == 200


def test_unauthenticated_request_to_a_protected_route_is_rejected(http_client):
    r = http_client.get("/auth/me")
    assert r.status_code == 401


def test_app_release_upload_latest_download_delete_round_trip(http_client):
    from .conftest import ITEST_ADMIN_HEADERS

    data = b"PK\x03\x04" + b"smoke-apk" * 100
    r = http_client.post(
        "/admin/app-releases",
        data={"platform": "android-x86_64", "version": "0.0.1", "notes": "smoke"},
        files={"file": ("smoke.apk", data)},
        headers=ITEST_ADMIN_HEADERS,
    )
    assert r.status_code == 201, r.text
    release = r.json()
    try:
        latest = http_client.get("/app-releases/latest", params={"platform": "android-x86_64"})
        assert latest.status_code == 200
        assert latest.json()["id"] == release["id"]
        download = http_client.get(release["download_url"])
        assert download.status_code == 200
        assert download.content == data
    finally:
        r = http_client.post(f"/admin/app-releases/{release['id']}/delete", headers=ITEST_ADMIN_HEADERS)
        assert r.status_code == 303
    assert http_client.get("/app-releases/latest", params={"platform": "android-x86_64"}).status_code == 404
