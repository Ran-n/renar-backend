#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/07/17 18:08:57.390257

Periodic-task tracking: each background task (see TASKS) is independently
enabled, independently scheduled, and reports its own run status — one
upserted row per task_key in the periodic_task_runs table. Nothing is
grouped under a shared toggle or a shared interval: episode_check and
episode_history_sync used to ride one flag and one poll interval, which
meant you couldn't pause or reschedule the episode-history backfill without
also affecting notifications.

Public surface:
- `is_enabled(task_key)` / `get_interval_minutes(task_key)` — short-TTL
  cached reads; used in the task loop and in AbuseGuardMiddleware's
  per-request strike-cleanup gate (same pattern as site_settings.current()).
- `set_enabled(task_key, enabled)` / `set_interval_minutes(task_key, minutes)`
  — admin writes; invalidate the cache.
- `record_run(task_key, started_at, status, detail)` — upsert the outcome of
  a run. Never raises — a tracking failure must not take down the task loop.
- `list_runs()` — every task's current row, for the admin page.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from .database import SessionLocal
from .models import PeriodicTaskRun, utcnow

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskSpec:
    key: str
    label: str
    desc: str
    group: str  # visual grouping on the admin page, e.g. "TV Shows"
    interval_minutes: int  # default poll interval; overridable per task in the DB


# Order here is the order the admin page lists them in (grouped by `group`,
# in first-seen order).
TASKS: list[TaskSpec] = [
    TaskSpec(
        "episode_check",
        "Episode check",
        "Poll TMDB for new episodes on tracked shows and create notifications.",
        "TV Shows",
        360,
    ),
    TaskSpec(
        "episode_history_sync",
        "Episode history sync",
        "Backfill the episodes table for tracked, non-dropped shows.",
        "TV Shows",
        360,
    ),
    TaskSpec(
        "film_check",
        "Film release check",
        "Poll TMDB for upcoming release dates on tracked want-to-watch films.",
        "Films",
        360,
    ),
    TaskSpec(
        "strike_cleanup",
        "Strike cleanup",
        "Drop abuse-strike rows nobody has touched in 30 days.",
        "Security",
        60,
    ),
]

_TASKS_BY_KEY = {t.key: t for t in TASKS}


@dataclass(frozen=True)
class _TaskState:
    enabled: bool
    interval_minutes: int


_CACHE_TTL = 5.0
_state_cache: dict[str, _TaskState] | None = None
_state_cache_ts = 0.0


def _defaults() -> dict[str, _TaskState]:
    return {t.key: _TaskState(True, t.interval_minutes) for t in TASKS}


def _load_state() -> dict[str, _TaskState]:
    state = _defaults()
    with SessionLocal() as db:
        rows = db.query(PeriodicTaskRun.task_key, PeriodicTaskRun.enabled, PeriodicTaskRun.interval_minutes).all()
    for key, enabled, interval in rows:
        spec = _TASKS_BY_KEY.get(key)
        default_interval = spec.interval_minutes if spec else 60
        state[key] = _TaskState(enabled, interval if interval is not None else default_interval)
    return state


def _state(task_key: str) -> _TaskState:
    global _state_cache, _state_cache_ts
    now = time.time()
    if _state_cache is None or now - _state_cache_ts >= _CACHE_TTL:
        try:
            _state_cache = _load_state()
            _state_cache_ts = now
        except Exception:
            _log.exception("could not load periodic task state; using defaults")
            if _state_cache is None:
                _state_cache = _defaults()
    spec = _TASKS_BY_KEY.get(task_key)
    return _state_cache.get(task_key) or _TaskState(True, spec.interval_minutes if spec else 60)


def is_enabled(task_key: str) -> bool:
    """Whether `task_key` should run, refreshed from the DB at most every 5s.

    Defaults to True (unknown/new task, or table unreachable) so a task never
    silently stops running just because tracking failed to load.
    """
    return _state(task_key).enabled


def get_interval_minutes(task_key: str) -> int:
    """Minutes between runs of `task_key`, refreshed at most every 5s."""
    return _state(task_key).interval_minutes


def _invalidate() -> None:
    global _state_cache_ts
    _state_cache_ts = 0.0


def set_enabled(task_key: str, enabled: bool) -> None:
    with SessionLocal() as db:
        row = db.get(PeriodicTaskRun, task_key)
        if row is None:
            row = PeriodicTaskRun(task_key=task_key, enabled=enabled)
            db.add(row)
        else:
            row.enabled = enabled
        db.commit()
    _invalidate()


def set_interval_minutes(task_key: str, minutes: int) -> None:
    with SessionLocal() as db:
        row = db.get(PeriodicTaskRun, task_key)
        if row is None:
            row = PeriodicTaskRun(task_key=task_key, interval_minutes=minutes)
            db.add(row)
        else:
            row.interval_minutes = minutes
        db.commit()
    _invalidate()


def record_run(task_key: str, started_at: datetime, status: str, detail: str) -> None:
    """Upsert the latest outcome for `task_key`. Never raises — a tracking
    failure must not take down the task loop that called it."""
    try:
        with SessionLocal() as db:
            row = db.get(PeriodicTaskRun, task_key)
            if row is None:
                row = PeriodicTaskRun(task_key=task_key)
                db.add(row)
            row.last_started_at = started_at
            row.last_finished_at = utcnow()
            row.last_status = status
            row.last_detail = detail
            db.commit()
    except Exception:
        _log.exception("could not record periodic task run for %s", task_key)


def list_runs() -> dict[str, PeriodicTaskRun]:
    """All recorded task rows, keyed by task_key. A missing key means the
    task has never been toggled or run — treat it as enabled with defaults."""
    try:
        with SessionLocal() as db:
            rows = db.query(PeriodicTaskRun).all()
            db.expunge_all()
            return {r.task_key: r for r in rows}
    except Exception:
        _log.exception("could not load periodic task runs")
        return {}
