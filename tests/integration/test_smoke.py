#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:07:31.849247
Revised: 2026/08/18 17:07:31.849247

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
