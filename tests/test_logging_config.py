#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/20 17:00:00.000000
Revised: 2026/11/14 01:59:19.952068
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


# ---------- console formatter ----------


def _record(level: int, msg: str, name: str = "renar_backend.social.notifier", **kwargs) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, None, kwargs.get("exc_info"))


def test_console_line_is_time_level_short_name_message():
    """Plain console line: time of day, 5-wide level, the logger without
    the package prefix in a fixed column, then the message."""
    import re

    from renar_backend.logging_setup import ConsoleFormatter

    line = ConsoleFormatter(use_color=False).format(_record(logging.INFO, "cleanup removed 3 rows"))
    assert re.fullmatch(r"\d\d:\d\d:\d\d INFO  social\.notifier {7}cleanup removed 3 rows", line), line


def test_console_messages_start_in_the_same_column_for_every_level_and_logger():
    from renar_backend.logging_setup import ConsoleFormatter

    fmt = ConsoleFormatter(use_color=False)
    columns = {
        fmt.format(_record(level, "MARK", name)).index("MARK")
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL)
        for name in ("renar_backend.main", "renar_backend.tmdb.tmdb_store", "uvicorn", "a" * 60)
    }
    assert len(columns) == 1


def test_console_level_labels():
    from renar_backend.logging_setup import ConsoleFormatter

    fmt = ConsoleFormatter(use_color=False)
    labels = [
        fmt.format(_record(level, "x")).split()[1]
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL, 25)
    ]
    # a custom level between INFO and WARNING reads as INFO
    assert labels == ["DEBUG", "INFO", "WARN", "ERROR", "CRIT", "INFO"]


def test_short_name_strips_prefix_pads_and_keeps_the_module_end():
    from renar_backend.logging_setup import short_name

    assert short_name("renar_backend.main", 10) == "main      "
    assert short_name("uvicorn.error", 14) == "uvicorn.error "
    long = short_name("renar_backend.routers.admin.periodic_tasks", 12)
    assert long == "…iodic_tasks"
    assert len(long) == 12


def test_console_color_only_marks_warnings_and_worse():
    """On a terminal the level is colored on every line, and the message
    itself only from WARNING up; without color there are no escape codes."""
    from renar_backend.logging_setup import ConsoleFormatter

    color = ConsoleFormatter(use_color=True)
    info = color.format(_record(logging.INFO, "routine"))
    warning = color.format(_record(logging.WARNING, "look here"))
    assert "\x1b[32mINFO " in info
    assert info.endswith(" routine")
    assert warning.endswith("\x1b[33mlook here\x1b[0m")
    assert "\x1b[" not in ConsoleFormatter(use_color=False).format(_record(logging.ERROR, "plain"))


def test_console_traceback_follows_the_message():
    import sys

    from renar_backend.logging_setup import ConsoleFormatter

    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(logging.ERROR, "unhandled failure", exc_info=sys.exc_info())
    lines = ConsoleFormatter(use_color=False).format(record).splitlines()
    assert lines[0].endswith("unhandled failure")
    assert lines[-1] == "ValueError: boom"


def test_color_follows_the_terminal_and_no_color(monkeypatch):
    from renar_backend.logging_setup import stream_supports_color

    class _Tty:
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert stream_supports_color(_Tty()) is True
    assert stream_supports_color(object()) is False  # a pipe or file: no isatty
    monkeypatch.setenv("NO_COLOR", "1")
    assert stream_supports_color(_Tty()) is False


def test_console_handler_uses_the_console_formatter_and_files_stay_plain(configured_logging, capsys):
    """The real config: the console handler formats with ConsoleFormatter,
    while the log file keeps the full dated line with the whole logger name."""
    from renar_backend.logging_setup import ConsoleFormatter

    log_file, _errors = configured_logging
    console = next(h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler)
    assert isinstance(console.formatter, ConsoleFormatter)
    logging.getLogger("renar_backend.social.notifier").warning("sync skipped")
    for handler in logging.getLogger().handlers:
        handler.flush()
    written = log_file.read_text(encoding="utf-8")
    assert "[WARNING ] renar_backend.social.notifier: sync skipped" in written
    assert "\x1b[" not in written


def test_console_line_carries_stack_info():
    """`logger.warning(..., stack_info=True)` keeps its stack on the console,
    under the message."""
    from renar_backend.logging_setup import ConsoleFormatter

    record = _record(logging.WARNING, "slow sync")
    record.stack_info = "Stack (most recent call last):\n  File notifier.py, line 1"
    lines = ConsoleFormatter(use_color=False).format(record).splitlines()
    assert lines[0].endswith("slow sync")
    assert lines[1:] == ["Stack (most recent call last):", "  File notifier.py, line 1"]
