#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:43.374283
Revised: 2026/11/14 00:22:43.374283

Console log formatting: lines a person can skim.

The log files keep the full, plain, greppable line (date, padded level,
full logger name). The console is read live by someone looking for the few
lines that matter among the routine ones, so its lines are built for that:

    20:49:57 INFO  social.notifier       cleanup removed 3 expired rows
    20:49:58 WARN  tmdb.tmdb_store       TMDB lookup failed, using cache

- time of day only (the date is in the file, and a console session rarely
  spans one);
- a short fixed-width level, so messages start in the same column;
- the logger name without the package prefix, in a fixed-width column;
- on a terminal, the level is colored and a WARNING or worse colors its
  whole message, so those lines stand out without reading anything.

Colors are used only when the stream is a terminal and NO_COLOR is not set,
so piping the console to a file or a service manager stays plain text.
"""

import logging
import os
import sys

_PACKAGE_PREFIX = "renar_backend."
_NAME_WIDTH = 21
_LEVEL_LABELS = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRIT",
}
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_LEVEL_COLORS = {
    logging.DEBUG: "\x1b[36m",  # cyan
    logging.INFO: "\x1b[32m",  # green
    logging.WARNING: "\x1b[33m",  # yellow
    logging.ERROR: "\x1b[31m",  # red
    logging.CRITICAL: "\x1b[1;31m",  # bold red
}


def short_name(name: str, width: int = _NAME_WIDTH) -> str:
    """`name` without the package prefix, fitted to exactly `width` columns:
    padded when shorter, and when longer cut on the left (keeping the
    module, the informative end) behind an ellipsis."""
    name = name.removeprefix(_PACKAGE_PREFIX)
    if len(name) > width:
        name = "…" + name[-(width - 1) :]
    return name.ljust(width)


def _level_floor(levelno: int) -> int:
    """The standard level a (possibly custom) numeric level counts as."""
    return max((known for known in _LEVEL_LABELS if known <= levelno), default=logging.DEBUG)


def stream_supports_color(stream) -> bool:
    return bool(getattr(stream, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ


class ConsoleFormatter(logging.Formatter):
    """See the module docstring. `use_color=None` decides from stderr (the
    stream the console handler writes to) when the formatter is created."""

    def __init__(self, use_color: bool | None = None):
        super().__init__(datefmt="%H:%M:%S")
        self.use_color = stream_supports_color(sys.stderr) if use_color is None else use_color

    def format(self, record: logging.LogRecord) -> str:
        floor = _level_floor(record.levelno)
        when = self.formatTime(record, self.datefmt)
        level = _LEVEL_LABELS[floor].ljust(5)
        name = short_name(record.name)
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"
        if not self.use_color:
            return f"{when} {level} {name} {message}"
        color = _LEVEL_COLORS[floor]
        if floor >= logging.WARNING:
            message = f"{color}{message}{_RESET}"
        return f"{_DIM}{when}{_RESET} {color}{level}{_RESET} {_DIM}{name}{_RESET} {message}"
