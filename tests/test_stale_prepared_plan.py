#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/27 09:52:03.254888

Covers main.py's `_handle_stale_prepared_plan` — the self-healing fix for
psycopg3's "cached plan must not change result type" error (see
TODO.md's psycopg3 entry): a migration's DDL invalidates prepared
plans already cached on this app's own pooled connections, and this handler
disposes the pool instead of requiring a manual app restart.
"""

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy.exc import DBAPIError

from renar_backend.main import _STALE_PLAN_MARKER, _handle_stale_prepared_plan


def _dbapi_error(message: str) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, Exception(message))


def test_stale_plan_error_disposes_pool_and_returns_503():
    exc = _dbapi_error(_STALE_PLAN_MARKER)
    with patch("renar_backend.main.engine") as mock_engine:
        response = asyncio.run(_handle_stale_prepared_plan(None, exc))
    mock_engine.dispose.assert_called_once()
    assert response.status_code == 503


def test_unrelated_dbapi_error_reraises_unchanged():
    exc = _dbapi_error("connection refused")
    with patch("renar_backend.main.engine") as mock_engine, pytest.raises(DBAPIError):
        asyncio.run(_handle_stale_prepared_plan(None, exc))
    mock_engine.dispose.assert_not_called()
