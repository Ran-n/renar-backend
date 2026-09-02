#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/28 21:20:00.000000

Covers events.py's in-process pub/sub directly, and routers/events.py's
`GET /events` auth gate through the test client. The stream itself is an
infinite generator (heartbeats every 25s until disconnect), so it isn't
opened here — the sync TestClient can't hold it open and issue a second
concurrent request without deadlocking; the pub/sub tests below exercise
the same subscribe/publish/queue path the live generator reads from.
"""

import asyncio

from renar_backend import events


def test_subscribe_unsubscribe_registers_and_cleans_up():
    queue = events.subscribe(1)
    assert 1 in events._subscribers
    assert queue in events._subscribers[1]
    events.unsubscribe(1, queue)
    assert 1 not in events._subscribers


def test_unsubscribe_unknown_user_is_a_noop():
    events.unsubscribe(999, asyncio.Queue())


def test_publish_delivers_to_subscribed_queue():
    queue = events.subscribe(1)
    events.publish(1, "settings_changed")
    assert queue.get_nowait() == "settings_changed"


def test_publish_noop_for_user_with_no_subscribers():
    events.publish(42, "settings_changed")  # must not raise


def test_publish_drops_when_queue_full():
    queue = events.subscribe(1)
    for _ in range(queue.maxsize):
        queue.put_nowait("settings_changed")
    events.publish(1, "settings_changed")  # must not raise despite QueueFull
    assert queue.qsize() == queue.maxsize


def test_publish_only_reaches_subscribers_of_that_user():
    queue_a = events.subscribe(1)
    queue_b = events.subscribe(2)
    events.publish(1, "settings_changed")
    assert queue_a.get_nowait() == "settings_changed"
    assert queue_b.qsize() == 0


def test_stream_requires_auth(client):
    r = client.get("/events")
    assert r.status_code == 401


def test_stream_rejects_bad_token(client):
    r = client.get("/events", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_stream_publish_reaches_subscriber_queue(client, alice):
    """Exercises the same subscribe -> publish -> queue path the live SSE
    generator reads from, without needing a second concurrent request on
    the single-threaded TestClient (which would deadlock against the
    still-open stream)."""
    user, _ = alice
    queue = events.subscribe(user["id"])
    events.publish(user["id"], "settings_changed")
    assert queue.get_nowait() == "settings_changed"


# ---------- gen() body coverage via asyncio.run() ----------
# The gen() closure inside stream() is an async generator that loops
# forever; TestClient can't hold it open and fire concurrent requests
# without deadlocking. Instead we call stream() directly in asyncio.run()
# with a fake request that controls is_disconnected(), exercising every
# branch in gen() without the single-threaded TestClient limitation.


def _make_fake_request(token: str, disconnect_on_first: bool = False):
    """Build a minimal fake ASGI request for the stream() handler."""
    call_count = [0]

    class _FakeRequest:
        headers = {"authorization": f"Bearer {token}"}

        async def is_disconnected(self):
            if disconnect_on_first:
                return True
            call_count[0] += 1
            # Never reports disconnect — caller drives termination via break/aclose()
            return False

    return _FakeRequest()


def test_stream_gen_event_and_heartbeat_paths(client, alice, monkeypatch):
    """
    Covers lines 50-63 + 65:
    - heartbeat path (TimeoutError → yield ": heartbeat")
    - event-yield path (queue item → yield "event: ...")
    - finally cleanup (unsubscribe called via aclose() on break)
    """
    import asyncio

    import renar_backend.routers.events as events_router

    # Shorten heartbeat so the TimeoutError fires in milliseconds
    monkeypatch.setattr(events_router, "_HEARTBEAT_SECONDS", 0.02)

    user, headers = alice
    token = headers["Authorization"].split(" ", 1)[1]
    fake_req = _make_fake_request(token)

    async def run():
        resp = await events_router.stream(fake_req)

        # Schedule an event after one heartbeat has had time to fire
        async def publish_later():
            await asyncio.sleep(0.06)
            events.publish(user["id"], "settings_changed")

        asyncio.create_task(publish_later())

        chunks = []
        async for chunk in resp.body_iterator:
            if isinstance(chunk, bytes):
                chunk = chunk.decode()
            chunks.append(chunk)
            if any("settings_changed" in c for c in chunks):
                break  # aclose() triggers the finally block

        return chunks

    chunks = asyncio.run(run())
    assert any(": heartbeat" in c for c in chunks), f"no heartbeat in {chunks}"
    assert any("settings_changed" in c for c in chunks), f"no event in {chunks}"


def test_stream_gen_disconnect_path(client, alice):
    """
    Covers line 54 (return when is_disconnected() → True on first poll).
    gen() must yield nothing and clean up immediately.
    """
    import asyncio

    import renar_backend.routers.events as events_router

    user, headers = alice
    token = headers["Authorization"].split(" ", 1)[1]
    fake_req = _make_fake_request(token, disconnect_on_first=True)

    async def run():
        resp = await events_router.stream(fake_req)
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    assert chunks == []
