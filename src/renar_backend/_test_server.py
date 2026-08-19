#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 14:33:20.294880
Revised: 2026/08/18 20:15:32.518260

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
    os.environ["TURNSTILE_SITE_KEY"] = ""
    os.environ["TURNSTILE_SECRET_KEY"] = ""  # nosec B105 -- empty, disables Turnstile for the test run
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
    from renar_backend.models import User

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
