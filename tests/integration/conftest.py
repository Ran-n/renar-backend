#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 16:49:30.615616
Revised: 2026/08/18 16:49:46.134243

Fixtures for tests that need the real app reachable over real HTTP, not
TestClient's in-process ASGI transport — the main motivating case is
routers/events.py's SSE stream: tests/test_events.py explicitly can't open
it end-to-end because the sync TestClient can't hold a stream open and
issue a second concurrent request without deadlocking (see that file's
docstring). A real server on a real socket, hit from a second real
connection, has no such limitation.

Needs a reachable local Postgres (see the `reska` scratch account docs) —
live_server skips rather than silently no-op'ing if the venv/DB isn't set
up right.
"""

import contextlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import TextIO

import httpx
import pytest

TEST_PASSWORD = "IntegrationTest123!"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn_logged(args: list[str]) -> tuple[subprocess.Popen, Path, TextIO]:
    """subprocess.Popen with output going to a real file, not stdout=PIPE.

    Not load-bearing here the way it was for renar-frontend's Playwright
    fixture (nothing here spawns a browser), but kept as the default:
    a PIPE handle for a long-lived child is inheritable on Windows and
    was observed elsewhere to cause hard-to-diagnose failures in whatever
    else the parent process spawns later — see
    renar-frontend/tests/integration/conftest.py's `_spawn_logged`."""
    log_path = Path(tempfile.mkstemp(prefix="renar-itest-", suffix=".log")[1])
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        args,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )
    return proc, log_path, log_file


def _wait_ready(proc: subprocess.Popen, url: str, log_path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early (code {proc.returncode}):\n{log_path.read_text()}")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    proc.kill()
    raise RuntimeError(f"{url} never became ready within {timeout}s:\n{log_path.read_text()}")


def _stop_gracefully(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.CTRL_BREAK_EVENT)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def live_server():
    """Base URL of the real app on a real socket, isolated Postgres schema,
    torn down (schema dropped) at the end of the session."""
    port = _free_port()
    proc, log_path, log_file = _spawn_logged([sys.executable, "-m", "renar_backend._test_server", "--port", str(port)])
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(proc, f"{base_url}/health", log_path)
    except RuntimeError as exc:
        pytest.fail(f"live test server failed to start:\n{exc}")
    yield base_url
    # Drop the schema through the still-running server rather than relying
    # on its own atexit-on-CTRL_BREAK path — see renar-frontend's identical
    # fixture for why that path isn't trusted (observed to skip on Windows).
    with contextlib.suppress(httpx.TransportError):
        httpx.post(f"{base_url}/_itest/drop_schema", timeout=10)
    _stop_gracefully(proc)
    log_file.close()
    with contextlib.suppress(PermissionError):
        log_path.unlink(missing_ok=True)


@pytest.fixture
def http_client(live_server):
    """Fresh httpx.Client per test, pointed at the live server."""
    with httpx.Client(base_url=live_server, timeout=10) as client:
        yield client


def register_and_login(client: httpx.Client, live_server: str, username: str | None = None) -> dict:
    """Register a fresh account, bypass real email confirmation via the
    live test server's `_itest` endpoint, log in, and return auth headers.
    Each call uses a unique username — the schema is shared for the whole
    session, not reset per test."""
    username = username or f"itest_{uuid.uuid4().hex[:10]}"
    r = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": TEST_PASSWORD},
    )
    r.raise_for_status()
    r = client.post(f"{live_server}/_itest/confirm_email/{username}")
    r.raise_for_status()
    assert r.json()["ok"] is True
    r = client.post("/auth/login", data={"username": username, "password": TEST_PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_headers(http_client, live_server):
    return register_and_login(http_client, live_server)
