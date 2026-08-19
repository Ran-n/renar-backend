#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:13.871671
Revised: 2026/08/18 17:25:23.882666
"""

import logging
import re
from copy import deepcopy
from pathlib import Path

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from renar_backend._devserver import ensure_port_free

# Absolute, not "src": a relative reload dir resolves against wherever `be`
# was launched from, and uvicorn watches a nonexistent path without
# complaint — hot-reload then silently never fires.
_SRC_DIR = str(Path(__file__).resolve().parents[1])
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_LOG_FILE = _BACKEND_DIR / "logs" / "renar-backend.log"

_HOST = "0.0.0.0"  # nosec B104 -- must listen on all interfaces for LAN/mobile clients
_PORT = 8000

# Frontend polls these on a timer / fetches images in bulk; logging every hit just drowns out real traffic.
# Only the console is quieted — the file handler below keeps every request, filter-free.
_QUIET_PATHS = re.compile(r"(/import/\w+/status|/auth/me|/tmdb/image/)\b")


class _QuietPollingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _QUIET_PATHS.search(record.getMessage())


def _log_config() -> dict:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    config = deepcopy(LOGGING_CONFIG)
    config["filters"] = {"quiet_polling": {"()": f"{__name__}._QuietPollingFilter"}}
    config["handlers"]["access"]["filters"] = ["quiet_polling"]
    # Plain (no ANSI) formatter shared by the file handler and the root logger's console
    # handler, matching main.py's old logging.basicConfig format. DefaultFormatter decides
    # on colour by checking sys.stderr.isatty() globally, ignoring which handler it's
    # attached to, so it can't be reused as-is for the file without leaking escape codes.
    config["formatters"]["app"] = {
        "format": "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }
    config["handlers"]["app_console"] = {
        "class": "logging.StreamHandler",
        "formatter": "app",
        "stream": "ext://sys.stderr",
    }
    config["handlers"]["file"] = {
        "formatter": "app",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(_LOG_FILE),
        "maxBytes": 10_000_000,
        "backupCount": 5,
        "encoding": "utf-8",
    }
    # uvicorn's own loggers keep their coloured console handler and gain the file handler.
    config["loggers"]["uvicorn"]["handlers"].append("file")
    config["loggers"]["uvicorn.access"]["handlers"].append("file")
    # Root logger: this is what every renar_backend.* module logger propagates to.
    # basicConfig() in main.py becomes a no-op once this runs, since it only acts when
    # the root logger has no handlers yet — so this replaces it, not duplicates it.
    config["root"] = {"handlers": ["app_console", "file"], "level": "INFO"}
    return config


def run():
    ensure_port_free(_HOST, _PORT)
    uvicorn.run(
        "renar_backend.main:asgi_app",
        host=_HOST,
        port=_PORT,
        reload=True,
        reload_dirs=[_SRC_DIR],
        server_header=False,  # don't advertise "uvicorn" + version to scanners
        log_config=_log_config(),
        # Without this, shutdown waits forever for open connections to close
        # (uvicorn's own default) — but /events (routers/events.py) holds an
        # SSE stream open indefinitely, only ending when the client
        # disconnects. A single Ctrl+C would then just hang logging "Waiting
        # for connections to close" until every connected frontend session
        # closed its stream, needing a second Ctrl+C to force-exit. This
        # caps that wait instead of relying on the user to force it.
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    run()
