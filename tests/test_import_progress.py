#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:44.039976
Revised: 2026/11/14 00:22:44.039976

The importers' in-memory progress dicts no longer grow for the life of the
process: a finished run's entry is dropped once it is older than the TTL,
the next time any import starts, and GET /import/status then answers from
the durable ImportJob row with the same outcome.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from renar_backend.users import import_progress, renar_import, tvtime_import
from renar_backend.users.import_progress import FINISHED_TTL_S, prune_finished, update


def test_update_merges_and_stamps_only_a_finished_run():
    progress: dict[int, dict] = {}
    update(progress, 1, stage="Importing", done=3)
    assert progress == {1: {"stage": "Importing", "done": 3}}
    update(progress, 1, stage="Done", finished=True)
    assert progress[1]["stage"] == "Done"
    assert progress[1]["done"] == 3
    assert "finished_at" in progress[1]


def test_prune_drops_only_finished_entries_past_the_ttl():
    progress = {
        1: {"finished": True, "finished_at": 0.0},  # old: goes
        2: {"finished": True, "finished_at": 950.0},  # recent: stays
        3: {"finished": False},  # running: stays, however old
        4: {"finished": True},  # no stamp: age unknown, stays
    }
    assert prune_finished(progress, now=1000.0, ttl=100.0) == 1
    assert sorted(progress) == [2, 3, 4]


def test_prune_boundary_is_exclusive():
    """Exactly `ttl` old is still kept; anything older goes."""
    progress = {1: {"finished": True, "finished_at": 0.0}}
    assert prune_finished(progress, now=100.0, ttl=100.0) == 0
    assert prune_finished(progress, now=100.001, ttl=100.0) == 1


def test_prune_empty_dict():
    assert prune_finished({}, now=1.0) == 0


@pytest.mark.property
@given(
    entries=st.dictionaries(
        st.integers(1, 50),
        st.tuples(st.booleans(), st.one_of(st.none(), st.floats(0, 2000, allow_nan=False))),
        max_size=30,
    ),
    now=st.floats(0, 4000, allow_nan=False),
)
def test_prune_never_touches_running_or_fresh_entries(entries, now):
    progress = {
        user_id: {"finished": finished} | ({} if at is None else {"finished_at": at})
        for user_id, (finished, at) in entries.items()
    }
    before = {k: dict(v) for k, v in progress.items()}
    dropped = prune_finished(progress, now=now)
    assert dropped == len(before) - len(progress)
    for user_id, entry in before.items():
        stale = entry["finished"] and "finished_at" in entry and now - entry["finished_at"] > FINISHED_TTL_S
        assert (user_id not in progress) is bool(stale)


@pytest.mark.parametrize("importer", [renar_import, tvtime_import])
def test_starting_a_job_forgets_long_finished_runs(client, alice, importer, monkeypatch):
    """Both importers prune on every job start: another account's run that
    finished long ago is gone from memory, a recent one and a running one
    are still there."""
    user, _ = alice
    monkeypatch.setattr(importer, "_progress", {})
    importer._set(9001, stage="Done", finished=True)
    importer._set(9002, stage="Done", finished=True)
    importer._set(9003, stage="Importing", finished=False)
    importer._progress[9001]["finished_at"] -= FINISHED_TTL_S + 1
    importer.start_job(user["id"])
    assert sorted(importer._progress) == sorted([9002, 9003, user["id"]])
    assert importer.is_running(user["id"]) is True


def test_status_survives_the_prune_via_the_job_row(client, alice, monkeypatch):
    """After its in-memory entry is pruned, a finished import still reports
    the same outcome: the status endpoint falls back to ImportJob."""
    user, headers = alice
    monkeypatch.setattr(renar_import, "_progress", {})
    renar_import.start_job(user["id"])
    summary = {"library_entries": 2}
    renar_import._set(user["id"], stage="Done", finished=True, summary=summary, error=None)
    renar_import._mark_job(user["id"], finished=True, error=None, summary=summary)
    live = client.get("/import/status", headers=headers).json()
    assert (live["stage"], live["finished"], live["summary"]) == ("Done", True, summary)
    assert "finished_at" not in live  # bookkeeping only, never part of the API

    renar_import._progress[user["id"]]["finished_at"] -= FINISHED_TTL_S + 1
    assert import_progress.prune_finished(renar_import._progress) == 1
    after = client.get("/import/status", headers=headers).json()
    assert (after["stage"], after["finished"], after["summary"], after["error"]) == ("Done", True, summary, None)
    assert after["kind"] == live["kind"]
