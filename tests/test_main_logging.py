#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/20 20:52:18.198510
Revised: 2026/08/20 20:52:18.198510

Tests for __main__.py's _QUIET_PATHS: which access-log lines get dropped
from the console (the file handler always keeps every request, filter-free)
because the frontend polls them on a timer and logging every hit drowns out
real traffic.
"""

import logging

from renar_backend.__main__ import _QuietPollingFilter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, message, (), None)


def test_turnstile_token_polling_is_quieted():
    msg = '127.0.0.1:1234 - "GET /auth/turnstile-token/abc123 HTTP/1.1" 200 OK'
    assert _QuietPollingFilter().filter(_record(msg)) is False


def test_turnstile_session_creation_is_not_quieted():
    """Only the repeated poll should be silenced — the one-time session
    create/callback/widget-page requests are normal traffic, not noise."""
    for path in ("/auth/turnstile-session", "/auth/turnstile-widget/abc123", "/auth/turnstile-callback/abc123"):
        msg = f'127.0.0.1:1234 - "GET {path} HTTP/1.1" 200 OK'
        assert _QuietPollingFilter().filter(_record(msg)) is True


def test_other_known_quiet_paths_still_quieted():
    for path in ("/import/tvtime/status", "/auth/me", "/tmdb/image/abc"):
        msg = f'127.0.0.1:1234 - "GET {path} HTTP/1.1" 200 OK'
        assert _QuietPollingFilter().filter(_record(msg)) is False


def test_unrelated_paths_are_not_quieted():
    msg = '127.0.0.1:1234 - "GET /titles HTTP/1.1" 200 OK'
    assert _QuietPollingFilter().filter(_record(msg)) is True
