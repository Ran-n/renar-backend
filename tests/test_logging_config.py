#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/20 17:00:00.000000
Revised: 2026/08/20 17:00:00.000000
"""

import logging
import logging.config

import pytest

from renar_backend.__main__ import _ERROR_LOG_FILE, _log_config


@pytest.fixture
def configured_logging(tmp_path, monkeypatch):
    """Points both log files at a tmp dir and applies the real dictConfig,
    restoring the previous logging state afterward so this doesn't leak
    handlers into other tests."""
    log_file = tmp_path / "renar-backend.log"
    error_log_file = tmp_path / "renar-backend-errors.log"
    monkeypatch.setattr("renar_backend.__main__._LOG_FILE", log_file)
    monkeypatch.setattr("renar_backend.__main__._ERROR_LOG_FILE", error_log_file)

    previous_handlers = list(logging.getLogger().handlers)
    logging.config.dictConfig(_log_config())
    yield log_file, error_log_file
    logging.getLogger().handlers = previous_handlers


def test_log_config_declares_error_only_file_handler():
    config = _log_config()
    assert config["handlers"]["errors_file"]["level"] == "WARNING"
    assert config["handlers"]["errors_file"]["filename"] == str(_ERROR_LOG_FILE)
    assert "errors_file" in config["root"]["handlers"]
    assert "errors_file" in config["loggers"]["uvicorn"]["handlers"]


def test_info_only_reaches_full_log_not_error_log(configured_logging):
    log_file, error_log_file = configured_logging
    logging.getLogger("renar_backend.test").info("routine info line")

    assert "routine info line" in log_file.read_text(encoding="utf-8")
    assert not error_log_file.exists() or "routine info line" not in error_log_file.read_text(encoding="utf-8")


def test_warning_and_exception_reach_both_logs(configured_logging):
    log_file, error_log_file = configured_logging
    log = logging.getLogger("renar_backend.test")
    log.warning("something worth noticing")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("unhandled failure")

    full = log_file.read_text(encoding="utf-8")
    errors = error_log_file.read_text(encoding="utf-8")
    for text in (full, errors):
        assert "something worth noticing" in text
        assert "unhandled failure" in text
        assert "ValueError: boom" in text


def test_uncaught_exception_propagated_via_uvicorn_error_reaches_error_log(configured_logging):
    """Mirrors how a real 500 gets logged: Starlette's ServerErrorMiddleware
    re-raises after responding, and uvicorn's protocol layer logs it via the
    "uvicorn.error" logger, which propagates up into "uvicorn"."""
    _log_file, error_log_file = configured_logging
    log = logging.getLogger("uvicorn.error")
    try:
        raise RuntimeError("simulated unhandled request exception")
    except RuntimeError:
        log.error("Exception in ASGI application", exc_info=True)

    errors = error_log_file.read_text(encoding="utf-8")
    assert "Exception in ASGI application" in errors
    assert "RuntimeError: simulated unhandled request exception" in errors
