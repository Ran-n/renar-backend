#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.707791
Revised: 2026/07/09 10:06:24.400825

Shared fixtures: isolated SQLite database, media dir, and API test client.

The environment overrides MUST be set before anything imports
xoutaim_backend.config, because Settings() is instantiated at import time.
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="xoutaim-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["MEDIA_DIR"] = str(_TMP / "media")
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ["TMDB_API_KEY"] = ""
os.environ["TVDB_API_KEY"] = ""
os.environ["ADMIN_USERNAME"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["ADMIN_PATH"] = "/admin"
# All test traffic comes from one fake IP; the guard would ban it.
# test_security.py builds its own app to exercise the middleware.
os.environ["ABUSE_GUARD_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from xoutaim_backend.config import settings  # noqa: E402
from xoutaim_backend.database import Base, engine  # noqa: E402
from xoutaim_backend.main import app  # noqa: E402

PASSWORD = "password123"
ADMIN_BASIC = ("root", "hunter2secret")


@pytest.fixture
def admin_enabled():
    """Temporarily configure admin credentials (unset by the conftest env)."""
    settings.admin_username, settings.admin_password = ADMIN_BASIC
    yield
    settings.admin_username = ""
    settings.admin_password = ""


@pytest.fixture(autouse=True)
def _fresh_db():
    """Every test starts from an empty schema."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    # No context manager on purpose: the lifespan (background episode
    # checker) must not run during tests.
    return TestClient(app)


def register(client: TestClient, username: str = "alice", password: str = PASSWORD) -> dict:
    r = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    return r.json()


def login(client: TestClient, username: str = "alice", password: str = PASSWORD) -> dict:
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def make_user(client):
    """Factory: register + login, returns (user dict, auth headers)."""

    def _make(username: str = "alice") -> tuple[dict, dict]:
        user = register(client, username)
        return user, login(client, username)

    return _make


@pytest.fixture
def alice(make_user):
    return make_user("alice")


@pytest.fixture
def bob(make_user):
    return make_user("bob")
