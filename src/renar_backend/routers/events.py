#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/28 15:40:00.000000

Server-Sent Events stream: pushes account-level events (currently just
`settings_changed`) to every open session of the caller's account, so a
language/theme/etc. change on one device is picked up by others without
waiting on their next navigation or app-resume. See events.py for the
in-process pub/sub this reads from, and docs/design-decisions.md for why
SSE over plain httpx rather than a WebSocket (the `websockets` package has
no prebuilt wheels for the frontend's Android/iOS build targets).
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, status
from starlette.responses import StreamingResponse

from ..database import SessionLocal
from ..events import subscribe, unsubscribe
from ..users.auth import get_current_user

router = APIRouter(prefix="/events", tags=["events"])
_log = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 25.0


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return token


@router.get("")
async def stream(request: Request):
    # Resolve identity with a short-lived DB session rather than the usual
    # Depends(get_current_user) — that would hold a pooled connection open
    # for as long as this SSE connection stays open (could be hours), and
    # this stream doesn't otherwise touch the database.
    with SessionLocal() as db:
        user_id = get_current_user(token=_bearer_token(request), db=db).id

    queue = subscribe(user_id)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event_type = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except TimeoutError:
                    # SSE comment line — keeps proxies/idle timeouts from closing the connection
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: {event_type}\ndata: {{}}\n\n"
        finally:
            unsubscribe(user_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")
