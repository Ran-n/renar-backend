#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:18:08.747952
Revised: 2026/08/18 17:18:08.747952

Snapshot tests: the derived value (API surface, a schema's field set) is
compared against a checked-in baseline in tests/snapshots/ instead of
hand-written expected data. Catches accidental shape drift — a route
renamed/removed, a field silently added or dropped from a public schema —
that no single example-based test happens to cover. An intentional change
is accepted by re-running with UPDATE_SNAPSHOTS=1, which rewrites the
baseline for review in the same diff as the change that caused it.
"""

import json
import os
from pathlib import Path

import pytest

from renar_backend.main import app
from renar_backend.schemas import LibraryEntryOut, TitleOut, UserOut

pytestmark = pytest.mark.snapshot

_SNAP_DIR = Path(__file__).parent / "snapshots"
_UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def _check(name: str, value) -> None:
    path = _SNAP_DIR / f"{name}.json"
    serialized = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if _UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"no snapshot baseline at {path} — run with UPDATE_SNAPSHOTS=1 to create it")
    expected = path.read_text(encoding="utf-8")
    assert serialized == expected, f"snapshot {name!r} changed — if intentional, re-run with UPDATE_SNAPSHOTS=1"


def test_api_surface_snapshot():
    """Every (METHOD, path) the app actually serves, HEAD excluded (FastAPI
    adds it to every GET automatically — not a route anyone declared)."""
    routes = sorted(
        f"{method} {route.path}"
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method != "HEAD"
    )
    _check("api_surface", routes)


def test_user_out_shape_snapshot():
    fields = sorted(UserOut.model_fields.keys())
    _check("user_out_shape", fields)
    # Never let a raw credential field slip into the public user schema.
    assert "password" not in fields
    assert "password_hash" not in fields


def test_library_entry_out_shape_snapshot():
    _check("library_entry_out_shape", sorted(LibraryEntryOut.model_fields.keys()))


def test_title_out_shape_snapshot():
    _check("title_out_shape", sorted(TitleOut.model_fields.keys()))
