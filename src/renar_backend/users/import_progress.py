#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:16:50.169212
Revised: 2026/11/14 00:22:50.131487

Upkeep of the importers' in-memory progress dicts.

Each importer keeps `{user_id: progress}` so a status poll during a run
needs no database read. An entry used to stay there for the life of the
process after its run finished. Once a run is finished its outcome is also
in the durable ImportJob row, which GET /import/status falls back to, so
the in-memory copy can go: it is kept for a short while (a client still
polling sees the same answer from memory) and then dropped.
"""

import logging
import time

_log = logging.getLogger(__name__)

# How long a finished run's entry stays in memory. Comfortably longer than
# any client's polling interval, so the poll that sees "finished" and the
# few after it are served from memory; short enough that the dict only ever
# holds runs from the last few minutes.
FINISHED_TTL_S = 600.0
_FINISHED_AT = "finished_at"


def update(progress: dict[int, dict], user_id: int, **fields) -> None:
    """Merge `fields` into `user_id`'s entry, stamping the moment a run is
    reported finished so prune_finished can age it out."""
    entry = progress.setdefault(user_id, {})
    entry.update(fields)
    if fields.get("finished"):
        entry[_FINISHED_AT] = time.monotonic()


def prune_finished(progress: dict[int, dict], *, now: float | None = None, ttl: float = FINISHED_TTL_S) -> int:
    """Drop every entry whose run finished more than `ttl` seconds ago;
    returns how many were dropped. Running entries are never touched, nor is
    a finished one with no stamp (nothing says how old it is)."""
    now = time.monotonic() if now is None else now
    stale = [
        user_id
        for user_id, entry in list(progress.items())
        if entry.get("finished") and _FINISHED_AT in entry and now - entry[_FINISHED_AT] > ttl
    ]
    for user_id in stale:
        progress.pop(user_id, None)
    if stale:
        _log.debug("pruned %d finished import progress entries", len(stale))
    return len(stale)
