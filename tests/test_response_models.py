#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 14:25:45.422229
Revised: 2026/11/13 14:25:45.422229

Response-schema guard: every documented endpoint that answers with a JSON
body declares a response_model, so app.openapi() describes the real shape
and renar-frontend's contract test (tests/integration/test_contract.py) can
validate live responses against it. A new endpoint without one fails here,
not silently in the frontend.

The exceptions are listed explicitly: 204 No Content routes (no body at
all) and the non-JSON bodies below. The admin panel's server-rendered pages
are include_in_schema=False and never reach app.openapi().

Plus drift checks for the handlers that assemble their dict by hand
(routers/stats.py): FastAPI's response_model filters out undeclared keys, so
a field added to the handler but not to the schema would vanish from the
response without any error.
"""

import pytest

from renar_backend.database import SessionLocal
from renar_backend.main import app
from renar_backend.models import User
from renar_backend.routers import stats
from renar_backend.schemas import RankingOut, StatsOut

pytestmark = pytest.mark.contract

# (METHOD, path) of documented routes whose 2xx body isn't JSON.
_NON_JSON_BODIES = {
    ("GET", "/events"),  # Server-Sent Events stream
    ("GET", "/images/{hash_}"),  # image bytes
    ("GET", "/tmdb/image/{size}/{filename}"),  # proxied image bytes
    ("GET", "/export/data/download"),  # zip archive
    ("GET", "/app-releases/{release_id}/download"),  # APK bytes
}


def _operations() -> dict[tuple[str, str], dict]:
    spec = app.openapi()
    return {(method.upper(), path): op for path, methods in spec["paths"].items() for method, op in methods.items()}


def _success(op: dict) -> tuple[str, dict]:
    code = next(c for c in op["responses"] if c.startswith("2"))
    return code, op["responses"][code]


def test_every_json_endpoint_declares_a_response_schema():
    missing = []
    for key, op in sorted(_operations().items()):
        code, response = _success(op)
        if code == "204" or key in _NON_JSON_BODIES:
            continue
        if not response.get("content", {}).get("application/json", {}).get("schema"):
            missing.append(f"{key[0]} {key[1]}")
    assert not missing, "endpoints returning JSON without a response_model:\n" + "\n".join(missing)


def test_no_content_routes_really_have_no_body():
    """A 204 route that started returning a payload would need a schema."""
    for key, op in _operations().items():
        code, response = _success(op)
        if code == "204":
            assert not response.get("content"), f"{key} is 204 but documents a body"


def test_non_json_allowlist_has_no_stale_entries():
    operations = _operations()
    stale = sorted(key for key in _NON_JSON_BODIES if key not in operations)
    assert not stale, f"allowlisted routes no longer exist: {stale}"
    for key in _NON_JSON_BODIES:
        assert not _success(operations[key])[1].get("content", {}).get("application/json", {}).get("schema"), (
            f"{key} now has a JSON schema; drop it from _NON_JSON_BODIES"
        )


# ---------------------------------------------------------------------------
# hand-assembled handlers vs. their declared schema
# ---------------------------------------------------------------------------


def _user(user_id: int) -> tuple:
    db = SessionLocal()
    return db, db.get(User, user_id)


def test_stats_handler_keys_match_stats_out(client, alice):
    (user, headers) = alice
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170, "rating": 90},
        headers=headers,
    )
    db, row = _user(user["id"])
    try:
        raw = stats.get_stats(db=db, user=row)
    finally:
        db.close()
    assert set(raw) == set(StatsOut.model_fields)
    assert set(raw["most_watched_shows"][0] if raw["most_watched_shows"] else {}) <= {
        "title",
        "episodes",
        "minutes",
        "poster_url",
    }
    assert client.get("/stats", headers=headers).json() == StatsOut.model_validate(raw).model_dump(mode="json")


def test_ranking_keys_match_ranking_out(client, alice):
    (user, _) = alice
    db, row = _user(user["id"])
    try:
        ranking = stats._compute_ranking(db, row, stats.RANKING_METRICS["watch_time"])
    finally:
        db.close()
    assert set(ranking) | {"metrics"} == set(RankingOut.model_fields)
