#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 16:50:51.784964
Revised: 2026/08/18 16:51:07.009266

Opens GET /events for real and reads the live stream — the one path
tests/test_events.py explicitly can't reach: TestClient is sync and
single-threaded, so holding a stream open and firing a second concurrent
request would deadlock it (see that file's docstring). Two real
connections over a real socket have no such limitation.
"""

import queue
import threading
import time

import httpx
import pytest

from .conftest import register_and_login

pytestmark = pytest.mark.integration


def _read_events(client: httpx.Client, headers: dict, out: queue.Queue, stop: threading.Event) -> None:
    try:
        with client.stream("GET", "/events", headers=headers, timeout=30) as resp:
            for line in resp.iter_lines():
                if stop.is_set():
                    return
                if line.startswith("event:"):
                    out.put(line.removeprefix("event:").strip())
    except httpx.ReadError:
        pass  # connection closed out from under us at teardown — expected


def test_stream_requires_auth(http_client):
    r = http_client.get("/events")
    assert r.status_code == 401


def test_stream_delivers_settings_changed_from_a_concurrent_request(live_server):
    with httpx.Client(base_url=live_server, timeout=10) as setup_client:
        headers = register_and_login(setup_client, live_server)

    received: queue.Queue = queue.Queue()
    stop = threading.Event()
    stream_client = httpx.Client(base_url=live_server)
    reader = threading.Thread(target=_read_events, args=(stream_client, headers, received, stop), daemon=True)
    reader.start()
    try:
        # No signal for "subscribed yet" from the server — the stream's
        # first action after auth is queue.get() with no announcement back.
        # A short, generous wait is the simplest correct option here.
        time.sleep(1.0)

        with httpx.Client(base_url=live_server, timeout=10) as trigger_client:
            r = trigger_client.patch("/auth/profile", json={"language": "gl"}, headers=headers)
            assert r.status_code == 200

        event_type = received.get(timeout=10)
        assert event_type == "settings_changed"
    finally:
        stop.set()
        stream_client.close()
        reader.join(timeout=5)
