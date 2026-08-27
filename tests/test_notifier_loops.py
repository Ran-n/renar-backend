#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/27 11:17:50.226741

Covers social/notifier.py's eight periodic-task loops (`_episode_check_loop`,
`_episode_history_sync_loop`, ...) — previously untested, per docs/backlog.md's
Testing entry ("mostly the periodic-task loop bodies rather than the testable
`*_once()` functions the suite already exercises"). All eight share one shape
(sleep, check task_runs.is_enabled, run the `*_once` function via
asyncio.to_thread, record success/failure via task_runs.record_run, sleep
again) so one parametrized harness drives all of them: run one real
iteration, then break out via a CancelledError raised from the loop's own
second `asyncio.sleep` call rather than a hard timeout, and assert the
skip/success/failure branches all behave and — most importantly — that an
exception from the `*_once()` function never escapes the loop (a periodic
task that dies once must not stop running forever).
"""

import asyncio

import pytest

from renar_backend import task_runs
from renar_backend.social import notifier

_LOOPS = [
    (notifier._episode_check_loop, "episode_check", "check_once"),
    (notifier._episode_history_sync_loop, "episode_history_sync", "sync_episode_history_once"),
    (notifier._film_check_loop, "film_check", "check_films_once"),
    (notifier._tmdb_metadata_resync_loop, "tmdb_metadata_resync", "resync_tmdb_metadata_once"),
    (notifier._unmatched_title_retry_loop, "unmatched_title_retry", "retry_unmatched_titles_once"),
    (notifier._email_confirmation_cleanup_loop, "email_confirmation_cleanup", "cleanup_unconfirmed_accounts_once"),
    (notifier._export_cleanup_loop, "export_cleanup", "purge_expired_exports_once"),
    (notifier._account_purge_loop, "account_purge", "purge_expired_deletions_once"),
]


class _StopAfterOneIteration(Exception):
    pass


def _run_one_iteration(monkeypatch, loop_fn):
    """Drives `loop_fn()` through its initial sleep + exactly one loop body,
    then breaks out via the loop's own second `asyncio.sleep(...)` call
    (the per-task reschedule sleep) instead of a hard timeout — a real
    `while True` never returns on its own."""
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise _StopAfterOneIteration
        return None

    monkeypatch.setattr(notifier.asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopAfterOneIteration):
        asyncio.run(loop_fn())
    return sleeps


@pytest.mark.parametrize("loop_fn,task_key,once_name", _LOOPS)
def test_loop_runs_once_and_records_success(monkeypatch, loop_fn, task_key, once_name):
    monkeypatch.setattr(task_runs, "is_enabled", lambda key: True)
    monkeypatch.setattr(task_runs, "get_interval_minutes", lambda key: 5)
    recorded = []
    monkeypatch.setattr(task_runs, "record_run", lambda key, started, status, detail: recorded.append((key, status)))
    monkeypatch.setattr(notifier, once_name, lambda: 3)

    _run_one_iteration(monkeypatch, loop_fn)

    assert recorded == [(task_key, "ok")]


@pytest.mark.parametrize("loop_fn,task_key,once_name", _LOOPS)
def test_loop_records_failure_and_does_not_crash(monkeypatch, loop_fn, task_key, once_name):
    """The `*_once()` call raising must not escape the loop — a periodic
    task that dies on one bad run would otherwise never run again."""
    monkeypatch.setattr(task_runs, "is_enabled", lambda key: True)
    monkeypatch.setattr(task_runs, "get_interval_minutes", lambda key: 5)
    recorded = []
    monkeypatch.setattr(task_runs, "record_run", lambda key, started, status, detail: recorded.append((key, status)))

    def boom():
        raise RuntimeError("transient failure")

    monkeypatch.setattr(notifier, once_name, boom)

    _run_one_iteration(monkeypatch, loop_fn)

    assert recorded == [(task_key, "error")]


@pytest.mark.parametrize("loop_fn,task_key,once_name", _LOOPS)
def test_loop_skips_once_call_when_disabled(monkeypatch, loop_fn, task_key, once_name):
    monkeypatch.setattr(task_runs, "is_enabled", lambda key: False)
    monkeypatch.setattr(task_runs, "get_interval_minutes", lambda key: 5)
    calls = []
    monkeypatch.setattr(notifier, once_name, lambda: calls.append(1) or 0)
    recorded = []
    monkeypatch.setattr(task_runs, "record_run", lambda key, started, status, detail: recorded.append((key, status)))

    _run_one_iteration(monkeypatch, loop_fn)

    assert calls == []
    assert recorded == []


def test_start_periodic_tasks_launches_all_eight_loops(monkeypatch):
    async def _drive():
        tasks = notifier.start_periodic_tasks()
        try:
            assert len(tasks) == 8
            assert all(isinstance(t, asyncio.Task) for t in tasks)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    asyncio.run(_drive())
