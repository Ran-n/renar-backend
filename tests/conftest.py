#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.707791
Revised: 2026/08/20 10:49:47.970772

Shared fixtures: isolated Postgres schema, media dir, and API test client.

The environment overrides MUST be set before anything imports
renar_backend.config, because Settings() is instantiated at import time.

Tests run against the local Postgres server (see docs on the `reska`
scratch account), in a schema unique to this test run so concurrent runs
and dev data never collide; the schema is dropped at process exit.
"""

import atexit
import os
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="renar-tests-"))
_PG_BASE_URL = "postgresql+psycopg://reska:reska@127.0.0.1:5432/reska"
_SCHEMA = f"renar_test_{uuid.uuid4().hex[:8]}"
os.environ["DATABASE_URL"] = f"{_PG_BASE_URL}?options=-csearch_path%3D{_SCHEMA}"
os.environ["MEDIA_DIR"] = str(_TMP / "media")
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"
os.environ["TMDB_API_KEY"] = ""
os.environ["TVDB_API_KEY"] = ""
# Real keys in .env (for live/manual testing) must never leak into the suite —
# test_turnstile.py configures them per-test via monkeypatch instead, and
# every other register() call in the suite expects the check to no-op.
os.environ["TURNSTILE_SITE_KEY"] = ""
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["ADMIN_USERNAME"] = ""
os.environ["ADMIN_PASSWORD"] = ""
os.environ["ADMIN_PATH"] = "/admin"
# All test traffic comes from one fake IP; the guard would ban it.
# test_security.py builds its own app to exercise the middleware.
os.environ["ABUSE_GUARD_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from renar_backend.config import settings  # noqa: E402
from renar_backend.database import Base, SessionLocal, engine  # noqa: E402
from renar_backend.main import app  # noqa: E402
from renar_backend.models import User  # noqa: E402

with create_engine(_PG_BASE_URL).begin() as _conn:
    _conn.execute(text(f'CREATE SCHEMA "{_SCHEMA}"'))


def _drop_schema() -> None:
    with create_engine(_PG_BASE_URL).begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{_SCHEMA}" CASCADE'))


atexit.register(_drop_schema)

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
    """Every test starts from an empty schema.

    The pool must be disposed after the drop/create: psycopg3 auto-prepares
    hot statements per connection, and a pooled connection's prepared plans
    reference the OLD table OIDs after recreation ("cached plan must not
    change result type" errors in whatever test runs next).
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    from renar_backend import site_settings, task_runs
    from renar_backend.routers import svc
    from renar_backend.users import export_queue, renar_import, tvtime_import

    task_runs._enabled_cache = None  # each test gets a fresh schema; don't leak a prior test's cache
    site_settings._cache_ts = 0.0  # same: don't serve a cached row from the just-dropped schema
    # Every importer/exporter keeps LIVE progress in a process-global dict,
    # keyed by user_id, that survives independently of the DB (a server
    # restart shouldn't lose in-flight status just because a request happens
    # to land mid-drop_all). But the schema above just reset — and since ids
    # restart at 1 each test, the next test's alice reuses the same user_id a
    # PREVIOUS test's entry is still keyed under. Without this, a status
    # check the very next test would see a stale "still running"/"done" from
    # a completely unrelated earlier test.
    export_queue._progress.clear()
    renar_import._progress.clear()
    tvtime_import._progress.clear()
    svc._auth_failures.clear()
    yield


@pytest.fixture
def client():
    # No context manager on purpose: the lifespan (background episode
    # checker) must not run during tests.
    return TestClient(app)


def _confirm_email(user_id: int) -> None:
    """Most tests aren't about the confirmation flow itself and expect a
    normal, ranking-eligible account — see test_email_confirmation.py for
    the unconfirmed/pending-confirmation paths, which register through the
    API directly instead of calling this."""
    db = SessionLocal()
    try:
        db.get(User, user_id).email_confirmed = True
        db.commit()
    finally:
        db.close()


def register(client: TestClient, username: str = "alice", password: str = PASSWORD) -> dict:
    r = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    user = r.json()
    _confirm_email(user["id"])
    user["email_confirmed"] = True
    return user


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
