#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 02:43:36.690692
Revised: 2026/08/24 08:04:25.714566

Guards against the two failure modes of running uvicorn with reload=True
on Windows, both learned the hard way (an orphaned worker from a previous
day answered every request on :8000 with stale code, through any number
of "restarts"):

- uvicorn binds its listen socket with SO_REUSEADDR, which on Windows
  lets a second server bind the same port without an error. Whichever
  process the kernel favors answers the requests — usually the OLD one.
  `ensure_port_free` turns that silent race into a loud startup failure.

- The reload worker is a multiprocessing spawn child. If the reloader
  parent is killed forcefully (closed terminal, Stop-Process), the worker
  survives, keeps the inherited socket, and becomes exactly such a
  zombie. `exit_when_orphaned` makes the worker die with its parent.

This module must stay import-light (stdlib only, no settings/database):
it is imported by the worker before the app config is even loaded, and
tests exercise it in bare subprocesses.
"""

import logging
import multiprocessing
import os
import signal
import socket
import subprocess
import sys
import threading
import time

_log = logging.getLogger(__name__)


def _find_listening_pid(port: int) -> int | None:
    """Best-effort PID of whatever is LISTENING on `port`, or None if it can't be found."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=False, timeout=5).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "TCP" and parts[-2] == "LISTENING" and parts[1].endswith(f":{port}"):
                    return int(parts[-1])
        else:
            out = subprocess.run(
                ["lsof", "-t", "-i", f":{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            ).stdout
            pids = [int(p) for p in out.split()]
            return pids[0] if pids else None
    except (OSError, ValueError):
        return None
    return None


def _kill_pid(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False, timeout=5)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    return True


def ensure_port_free(host: str, port: int) -> None:
    """Fail loudly at startup when something already listens on the port.

    Binds a throwaway probe socket (with SO_EXCLUSIVEADDRUSE on Windows,
    so even a SO_REUSEADDR listener is detected) and closes it again.
    There is a small window between the probe and uvicorn's own bind;
    that's fine for a dev server — the point is catching zombies, not
    winning races.

    When stdin is a real terminal and the occupant PID can be identified,
    offers to kill it and retry once instead of failing outright — the
    occupant is almost always yesterday's orphaned reload worker, not
    something the manual "netstat, then taskkill, then rerun" dance
    protects against.
    """
    offered_kill = False
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((host, port))
            return
        except OSError as exc:
            if not offered_kill and sys.stdin.isatty():
                offered_kill = True
                pid = _find_listening_pid(port)
                if pid is not None:
                    answer = input(f"port {port} is already in use by PID {pid} — kill it and continue? [y/N] ")
                    if answer.strip().lower() == "y" and _kill_pid(pid):
                        time.sleep(0.5)
                        continue
            find_cmd = f"netstat -ano | findstr :{port}" if sys.platform == "win32" else f"lsof -i :{port}"
            raise SystemExit(
                f"port {port} is already in use — another backend instance or an orphaned "
                f"reload worker is running. Find it with: {find_cmd}"
            ) from exc
        finally:
            probe.close()


def exit_when_orphaned() -> threading.Thread | None:
    """When running as a reload worker, exit if the reloader parent dies.

    Returns the started watchdog thread, or None when there is no
    multiprocessing parent (plain single-process run, tests).
    """
    parent = multiprocessing.parent_process()
    if parent is None:
        return None

    def _watch() -> None:
        parent.join()  # returns only when the reloader process is gone
        _log.error(
            "reloader parent (pid %s) died; exiting so the listen socket is released",
            parent.pid,
        )
        os._exit(1)

    watchdog = threading.Thread(target=_watch, daemon=True, name="orphan-watchdog")
    watchdog.start()
    return watchdog
