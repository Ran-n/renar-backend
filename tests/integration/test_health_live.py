#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 16:50:51.878439
Revised: 2026/08/18 16:50:51.878439
"""

import pytest

pytestmark = pytest.mark.integration


def test_health(http_client):
    r = http_client.get("/health")
    assert r.json() == {"status": "ok"}


def test_auth_headers_work(http_client, auth_headers):
    r = http_client.get("/auth/me", headers=auth_headers)
    assert r.status_code == 200
