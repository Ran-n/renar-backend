#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 14:33:20.294880
Revised: 2026/11/09 11:49:59.465340

Opt-in server for integration tests that need the real app reachable over
real HTTP, not the in-process ASGI transport TestClient uses: this repo's
own tests/integration/ (real streaming connections, real server timing —
see routers/events.py's SSE stream, which tests/test_events.py explicitly
can't open end-to-end through TestClient) and renar-frontend's cross-repo
tests/integration/. Boots the real app against an isolated Postgres schema
on a caller-chosen port, with turnstile/abuse-guard/admin disabled — same
env overrides as tests/conftest.py — plus a test-only endpoint to flag a
user's email confirmed without wiring up real email delivery.

Never imported by the production app or by this repo's own *unit* test
suite (tests/*.py, which stays on TestClient); invoked only as
`python -m renar_backend._test_server --port <port>` in a subprocess with
its own env, from either this repo's tests/integration/conftest.py or the
frontend's.

The environment overrides MUST be set before anything imports
renar_backend.config, because Settings() is instantiated at import time —
see tests/conftest.py for the same constraint.
"""

import argparse
import atexit
import datetime
import os
import tempfile
import uuid
from pathlib import Path

_PG_BASE_URL = "postgresql+psycopg://reska:reska@127.0.0.1:5432/reska"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    schema = f"renar_itest_{uuid.uuid4().hex[:8]}"
    tmp_dir = Path(tempfile.mkdtemp(prefix="renar-itest-"))

    os.environ["DATABASE_URL"] = f"{_PG_BASE_URL}?options=-csearch_path%3D{schema}"
    os.environ["MEDIA_DIR"] = str(tmp_dir / "media")
    os.environ["SECRET_KEY"] = "integration-test-secret-key-0123456789abcdef"  # nosec B105 -- test-only, not a real secret
    # setdefault, not a hard overwrite: most callers get no TMDB access (no
    # real network call from a test run), but a caller that explicitly put a
    # real key in this subprocess's env (see renar-frontend's
    # live_backend_with_tmdb fixture, for the one E2E test that drives
    # Explore's actual search-and-add UI) gets to keep it.
    os.environ.setdefault("TMDB_API_KEY", "")
    os.environ.setdefault("TVDB_API_KEY", "")
    os.environ["PROD_TURNSTILE_SITE_KEY"] = ""
    os.environ["PROD_TURNSTILE_SECRET_KEY"] = ""  # nosec B105 -- empty, disables Turnstile for the test run
    os.environ["DEV_TURNSTILE_SITE_KEY"] = ""
    os.environ["DEV_TURNSTILE_SECRET_KEY"] = ""  # nosec B105 -- empty, disables Turnstile for the test run
    os.environ["ADMIN_USERNAME"] = ""
    os.environ["ADMIN_PASSWORD"] = ""  # nosec B105 -- empty, disables the admin panel for the test run
    os.environ["ADMIN_PATH"] = "/admin"
    # Single-IP traffic from the frontend test process would otherwise trip
    # the guard partway through a run, same reasoning as tests/conftest.py.
    os.environ["ABUSE_GUARD_ENABLED"] = "false"

    from sqlalchemy import create_engine, text

    with create_engine(_PG_BASE_URL).begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    def _drop_schema() -> None:
        with create_engine(_PG_BASE_URL).begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))

    atexit.register(_drop_schema)

    from renar_backend.database import Base, SessionLocal, engine
    from renar_backend.main import app, asgi_app
    from renar_backend.models import LibraryEntry, Notification, ReviewWhitelist, User, utcnow

    Base.metadata.create_all(engine)
    engine.dispose()  # see tests/conftest.py's _fresh_db: stale prepared plans reference pre-create_all OIDs

    @app.post("/_itest/drop_schema", include_in_schema=False)
    def _drop_schema_now() -> dict:
        # The caller can't rely on this process's own atexit-on-shutdown
        # path actually running (observed: CTRL_BREAK on Windows sometimes
        # exits without it firing, leaking the schema) — calling this while
        # still up, right before the caller stops the process, is the
        # guaranteed alternative. No caller-supplied name: only ever drops
        # this instance's own schema.
        atexit.unregister(_drop_schema)
        _drop_schema()
        return {"dropped": schema}

    @app.post("/_itest/confirm_email/{username}", include_in_schema=False)
    def _confirm_email(username: str) -> dict:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                return {"ok": False}
            user.email_confirmed = True
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/_itest/seed_notification/{username}", include_in_schema=False)
    def _seed_notification(
        username: str, title: str = "New episode aired", body: str = "S01E01 is now available."
    ) -> dict:
        # Real notifications only come from the new-episode background job
        # (social/notifier.py's check_new_episodes), which needs a real TMDB
        # round-trip and a wait for the periodic task — not viable to drive
        # from a UI test. Inserting the row directly is the same shortcut
        # _confirm_email takes for email confirmation.
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                return {"ok": False}
            n = Notification(user_id=user.id, kind="new_episode", title=title, body=body, season=1, episode=1)
            db.add(n)
            db.commit()
            return {"ok": True, "id": n.id}
        finally:
            db.close()

    @app.post("/_itest/set_next_episode/{item_id}", include_in_schema=False)
    def _set_next_episode(item_id: int, days_until: int, season: int = 1, episode: int = 1) -> dict:
        # /upcoming reads next-episode/release-date data straight off Title
        # (normally synced by a background poller from TMDB) instead of
        # hitting TMDB on the request path — see renar-backend's own
        # tests/test_upcoming.py::_set_title_for_entry, which this mirrors.
        # Writing it directly here is the same TMDB-free shortcut, for E2E
        # tests driving the real UI instead of the backend test client.
        db = SessionLocal()
        try:
            entry = db.get(LibraryEntry, item_id)
            if entry is None:
                return {"ok": False}
            entry.title_ref.next_episode_air_date = datetime.date.today() + datetime.timedelta(days=days_until)
            entry.title_ref.next_episode_season = season
            entry.title_ref.next_episode_number = episode
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/_itest/set_premium/{username}", include_in_schema=False)
    def _set_premium(username: str, days: int = 30) -> dict:
        # No payment processor is wired up yet (Paddle integration is still
        # backlog — see TODO.md's Monetization section), so this is
        # the only way to get a premium account for a test run. Mirrors
        # renar-backend's own tests/test_stats.py::_set_premium.
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                return {"ok": False}
            user.premium_until = utcnow() + datetime.timedelta(days=days)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @app.post("/_itest/whitelist_reviewer/{username}", include_in_schema=False)
    def _whitelist_reviewer(username: str) -> dict:
        # POST /media/reviews is gated on a review_whitelist row (no public
        # reviewer application flow exists yet) — inserting it directly is
        # the same shortcut _set_premium takes for the payment processor.
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user is None:
                return {"ok": False}
            if db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user.id).first() is None:
                db.add(ReviewWhitelist(user_id=user.id))
                db.commit()
            return {"ok": True}
        finally:
            db.close()

    import uvicorn

    uvicorn.run(
        asgi_app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        # Same reasoning as __main__.run(): /events holds an SSE stream open
        # indefinitely, which would otherwise hang graceful shutdown.
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()
