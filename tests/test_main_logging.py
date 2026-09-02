#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/20 20:52:18.198510
Revised: 2026/09/02 10:57:53.287675

Tests for __main__.py's _QUIET_PATHS: which access-log lines get dropped
from the console (the file handler always keeps every request, filter-free)
because the frontend polls them on a timer and logging every hit drowns out
real traffic.

Also covers main.py: backend_version() fallbacks and
_ShutdownCancellationSilencer's error handling.
"""

import asyncio
import logging
from importlib.metadata import PackageNotFoundError
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

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


# ---------- backend_version() fallbacks (main.py lines 63-71) ----------


def test_backend_version_fallback_to_pyproject(tmp_path):
    """When the installed package has no dist metadata, backend_version() reads
    the version from pyproject.toml (lines 63-68 in main.py)."""
    from renar_backend import main

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "9.8.7"\n')

    with (
        patch("renar_backend.main._pkg_version", side_effect=PackageNotFoundError),
        patch("renar_backend.main.Path") as mock_path,
    ):
        # Make Path(__file__).resolve().parents[2] / "pyproject.toml" → our tmp file.
        mock_parents = mock_path.return_value.resolve.return_value.parents
        mock_parents.__getitem__.return_value.__truediv__.return_value = pyproject
        result = main.backend_version()

    assert result == "9.8.7"


def test_backend_version_fallback_to_unknown(tmp_path):
    """When both the dist metadata and pyproject.toml are unavailable,
    backend_version() returns 'unknown' (lines 69-71 in main.py)."""
    from renar_backend import main

    with (
        patch("renar_backend.main._pkg_version", side_effect=PackageNotFoundError),
        patch("renar_backend.main.Path") as mock_path,
    ):
        # Make the pyproject.toml open fail with OSError.
        broken = MagicMock()
        broken.open.side_effect = OSError("not found")
        mock_path.return_value.resolve.return_value.parents.__getitem__.return_value.__truediv__.return_value = broken
        result = main.backend_version()

    assert result == "unknown"


# ---------- _ShutdownCancellationSilencer (main.py lines 195-200) ----------


@pytest.mark.anyio
async def test_shutdown_silencer_swallows_cancelled_error_for_http():
    """CancelledError raised inside an http-scope ASGI app is swallowed by
    _ShutdownCancellationSilencer (lines 197-200 in main.py)."""
    from renar_backend.main import _ShutdownCancellationSilencer

    inner = AsyncMock(side_effect=asyncio.CancelledError)
    silencer = _ShutdownCancellationSilencer(inner)
    scope = {"type": "http", "method": "GET", "path": "/events"}
    # Should NOT raise — the error is swallowed and logged.
    await silencer(scope, None, None)


@pytest.mark.anyio
async def test_shutdown_silencer_reraises_cancelled_error_for_lifespan():
    """CancelledError from a non-http scope (e.g. lifespan) is re-raised."""
    from renar_backend.main import _ShutdownCancellationSilencer

    inner = AsyncMock(side_effect=asyncio.CancelledError)
    silencer = _ShutdownCancellationSilencer(inner)
    scope = {"type": "lifespan"}
    with pytest.raises(asyncio.CancelledError):
        await silencer(scope, None, None)


@pytest.mark.anyio
async def test_shutdown_silencer_swallows_would_block_for_http():
    """anyio.WouldBlock from an http scope is also swallowed."""
    from renar_backend.main import _ShutdownCancellationSilencer

    inner = AsyncMock(side_effect=anyio.WouldBlock)
    silencer = _ShutdownCancellationSilencer(inner)
    scope = {"type": "http", "method": "GET", "path": "/events"}
    await silencer(scope, None, None)  # no raise


@pytest.mark.anyio
async def test_shutdown_silencer_passes_through_other_exceptions():
    """Regular exceptions are never swallowed."""
    from renar_backend.main import _ShutdownCancellationSilencer

    inner = AsyncMock(side_effect=ValueError("boom"))
    silencer = _ShutdownCancellationSilencer(inner)
    scope = {"type": "http", "method": "GET", "path": "/test"}
    with pytest.raises(ValueError, match="boom"):
        await silencer(scope, None, None)
