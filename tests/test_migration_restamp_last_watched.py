#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/23 08:13:13.129897
Revised: 2026/11/23 08:13:13.129897

Migration f3a9c6e2b8d1 backfills media_items.last_watched_at from each
entry's real watch history, for accounts imported before imports set it.
Its SQL runs here against the suite's normal schema, with alembic's ``op``
swapped for a plain executor, so the rows can be built with the ORM.
"""

import importlib.util
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import text

from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeWatch, LibraryEntry, WatchEvent, WatchStatus, utcnow

_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "f3a9c6e2b8d1_restamp_last_watched_from_history.py"
)


def _run_migration(direction: str) -> None:
    spec = importlib.util.spec_from_file_location("restamp_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = SessionLocal()
    try:
        module.op = SimpleNamespace(execute=lambda sql: db.execute(text(sql)))
        getattr(module, direction)()
        db.commit()
    finally:
        db.close()


def _entry(client, headers, title: str, status: str = "watching") -> int:
    r = client.post("/media", json={"media_type": "tv_show", "title": title, "status": status}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _set_up(item_id: int, *, stamp, episode_at=None, event_at=None) -> None:
    """Replace the entry's history with exactly what the test describes."""
    db = SessionLocal()
    try:
        db.query(WatchEvent).filter(WatchEvent.media_item_id == item_id).delete()
        db.get(LibraryEntry, item_id).last_watched_at = stamp
        if episode_at is not None:
            db.add(EpisodeWatch(media_item_id=item_id, season=1, episode=1, watched_at=episode_at))
        if event_at is not None:
            db.add(WatchEvent(media_item_id=item_id, watched_at=event_at, is_initial=True))
        db.commit()
    finally:
        db.close()


def _stamp(item_id: int):
    db = SessionLocal()
    try:
        return db.get(LibraryEntry, item_id).last_watched_at
    finally:
        db.close()


def test_upgrade_restamps_from_history_and_never_backwards(client, alice):
    _, headers = alice
    now = utcnow()
    imported = _entry(client, headers, "Imported")
    _set_up(imported, stamp=None, episode_at=now - timedelta(days=400), event_at=now - timedelta(days=300))
    stale = _entry(client, headers, "Stale Stamp")
    _set_up(stale, stamp=now - timedelta(days=500), episode_at=now - timedelta(days=20))
    fresh = _entry(client, headers, "Fresh Stamp")
    _set_up(fresh, stamp=now, episode_at=now - timedelta(days=20))
    no_history = _entry(client, headers, "No History")
    _set_up(no_history, stamp=None)
    planned = _entry(client, headers, "Planned", status=WatchStatus.want_to_watch.value)
    _set_up(planned, stamp=None, episode_at=now - timedelta(days=5))

    _run_migration("upgrade")

    assert _stamp(imported) == now - timedelta(days=300)
    assert _stamp(stale) == now - timedelta(days=20)
    assert _stamp(fresh) == now
    assert _stamp(no_history) is None
    assert _stamp(planned) is None


def test_downgrade_changes_nothing(client, alice):
    _, headers = alice
    item = _entry(client, headers, "Imported")
    stamp = utcnow() - timedelta(days=3)
    _set_up(item, stamp=stamp)

    _run_migration("downgrade")

    assert _stamp(item) == stamp
