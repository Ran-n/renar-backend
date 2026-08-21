#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:13.871671
Revised: 2026/08/21 08:33:49.466180
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
# WARNING+ only, same records as _LOG_FILE — lets a crash/error check skim
# one small file instead of grepping the full (mostly INFO/access-log) one.
_ERROR_LOG_FILE = _BACKEND_DIR / "logs" / "renar-backend-errors.log"

_HOST = "0.0.0.0"  # nosec B104 -- must listen on all interfaces for LAN/mobile clients
_PORT = 8000

# Let's Encrypt cert for api.renar.app (DNS-01 via certbot-dns-cloudflare —
# see docs/design-decisions.md's HTTPS entry for why DNS-01, not HTTP-01: an
# unrelated service already owns port 80 on this host). `certs/` is
# gitignored — nothing here ships in the repo, only exists on this
# deployment once `certbot certonly` has been run. Falls back to plain HTTP
# below when the files aren't present (a fresh checkout, or local dev before
# ever running certbot) rather than crashing — this is the only run() this
# module has, used for both the public deployment and same-machine local
# dev, and dev shouldn't be blocked on a cert existing.
#
# The cert is only valid for the literal hostname api.renar.app, not
# 127.0.0.1/localhost — connecting to this port by IP once HTTPS is active
# will fail hostname validation. For local dev over HTTPS, add a hosts-file
# entry (`127.0.0.1 api.renar.app`, needs an elevated editor on Windows —
# C:\Windows\System32\drivers\etc\hosts) and connect to
# https://api.renar.app:8000 instead: resolves straight to loopback, no
# router round-trip, and the hostname still matches the real cert — no
# separate self-signed cert or per-device CA install needed.
_CERT_LIVE_DIR = _BACKEND_DIR / "certs" / "certbot-config" / "live" / "api.renar.app"
_SSL_CERTFILE = _CERT_LIVE_DIR / "fullchain.pem"
_SSL_KEYFILE = _CERT_LIVE_DIR / "privkey.pem"

# Frontend polls these on a timer / fetches images in bulk; logging every hit just drowns out real traffic.
# Only the console is quieted — the file handler below keeps every request, filter-free.
_QUIET_PATHS = re.compile(r"(/import/\w+/status|/auth/me|/tmdb/image/|/auth/turnstile-token/)\b")


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
    config["handlers"]["errors_file"] = {
        "formatter": "app",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(_ERROR_LOG_FILE),
        "maxBytes": 10_000_000,
        "backupCount": 5,
        "encoding": "utf-8",
        "level": "WARNING",
    }
    # uvicorn's own loggers keep their coloured console handler and gain the file handlers.
    # uvicorn.error (unhandled exception tracebacks) propagates into "uvicorn" — no separate
    # entry needed for it to reach errors_file too.
    config["loggers"]["uvicorn"]["handlers"].extend(["file", "errors_file"])
    config["loggers"]["uvicorn.access"]["handlers"].append("file")
    # Root logger: this is what every renar_backend.* module logger propagates to.
    # basicConfig() in main.py becomes a no-op once this runs, since it only acts when
    # the root logger has no handlers yet — so this replaces it, not duplicates it.
    config["root"] = {"handlers": ["app_console", "file", "errors_file"], "level": "INFO"}
    return config


def run():
    ensure_port_free(_HOST, _PORT)
    ssl_kwargs = {}
    if _SSL_CERTFILE.exists() and _SSL_KEYFILE.exists():
        ssl_kwargs = {"ssl_certfile": str(_SSL_CERTFILE), "ssl_keyfile": str(_SSL_KEYFILE)}
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
        **ssl_kwargs,
    )


if __name__ == "__main__":
    run()
