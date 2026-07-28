#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/28 15:40:00.000000

In-process pub/sub for pushing account-level events (e.g. a settings change)
to every open session of a user, over the `/events` SSE stream in
routers/events.py.

Single-worker only, like the anti-abuse rate-limit state (see
docs/design-decisions.md) — a registry keyed by user_id living in this
process's memory doesn't see connections held by other workers. Move to
Redis pub/sub if the backend ever runs with more than one.
"""

import asyncio
import contextlib
import threading

_lock = threading.Lock()
_subscribers: dict[int, set[asyncio.Queue]] = {}


def subscribe(user_id: int) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    with _lock:
        _subscribers.setdefault(user_id, set()).add(queue)
    return queue


def unsubscribe(user_id: int, queue: asyncio.Queue) -> None:
    with _lock:
        queues = _subscribers.get(user_id)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                del _subscribers[user_id]


def publish(user_id: int, event_type: str) -> None:
    """Fire-and-forget: drop the event for any session whose queue is full
    rather than block the caller (a profile PATCH request) on a slow reader."""
    with _lock:
        queues = list(_subscribers.get(user_id, ()))
    for queue in queues:
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event_type)
