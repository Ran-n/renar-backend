#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:13.871671
Revised: 2026/07/21 09:51:02.396011
"""

import logging
import re
from pathlib import Path

import uvicorn

from renar_backend._devserver import ensure_port_free

# Absolute, not "src": a relative reload dir resolves against wherever `be`
# was launched from, and uvicorn watches a nonexistent path without
# complaint — hot-reload then silently never fires.
_SRC_DIR = str(Path(__file__).resolve().parents[1])

_HOST = "0.0.0.0"
_PORT = 8000

# Frontend polls these on a timer; logging every hit just drowns out real traffic.
_QUIET_PATHS = re.compile(r"(/import/\w+/status|/auth/me)\b")


class _QuietPollingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _QUIET_PATHS.search(record.getMessage())


def run():
    ensure_port_free(_HOST, _PORT)
    logging.getLogger("uvicorn.access").addFilter(_QuietPollingFilter())
    uvicorn.run(
        "renar_backend.main:app",
        host=_HOST,
        port=_PORT,
        reload=True,
        reload_dirs=[_SRC_DIR],
        server_header=False,  # don't advertise "uvicorn" + version to scanners
    )


if __name__ == "__main__":
    run()
