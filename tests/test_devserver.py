#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/12 02:43:36.784037
Revised: 2026/11/13 14:25:46.213801

Dev-server guards (_devserver.py): the port-in-use probe and the
orphaned-reload-worker watchdog, plus the repo-root anchoring of
launch-directory-sensitive settings (config.py).

Background: an orphaned uvicorn reload worker once survived its killed
parent for a day, kept the inherited :8000 socket (SO_REUSEADDR lets a
second server bind the same port on Windows without an error), and
answered every request with stale code through any number of "restarts".
"""

import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from renar_backend import _devserver
from renar_backend._devserver import ensure_port_free, exit_when_orphaned
from renar_backend.config import _ROOT, Settings

# --- port-in-use probe --------------------------------------------------------


def test_port_guard_passes_on_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # socket closed above -> port free again
    ensure_port_free("127.0.0.1", port)


def test_port_guard_skips_exclusive_bind_off_windows(monkeypatch):
    """SO_EXCLUSIVEADDRUSE is Windows-only; elsewhere the probe binds plainly."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(_devserver.sys, "platform", "linux")
    ensure_port_free("127.0.0.1", port)


def test_port_guard_rejects_zombie_style_listener():
    """The occupant binds with SO_REUSEADDR, exactly like a uvicorn worker —
    the probe must still detect it instead of silently double-binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]
        with pytest.raises(SystemExit, match="already in use"):
            ensure_port_free("127.0.0.1", port)


def test_port_guard_declines_without_a_tty():
    """Non-interactive runs (CI, this test suite) must never block on input()."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]
        with pytest.raises(SystemExit, match="already in use"):
            ensure_port_free("127.0.0.1", port)


def test_port_guard_kills_occupant_when_offered_and_accepted(monkeypatch):
    """User accepts the kill offer -> occupant is killed and the retry succeeds."""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]

    killed = []

    def _fake_kill(pid):
        killed.append(pid)
        blocker.close()  # stand in for the real process releasing the socket
        return True

    monkeypatch.setattr(_devserver.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_devserver, "_find_listening_pid", lambda port: 12345)
    monkeypatch.setattr(_devserver, "_kill_pid", _fake_kill)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    ensure_port_free("127.0.0.1", port)
    assert killed == [12345]


def test_port_guard_leaves_occupant_when_declined(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        monkeypatch.setattr(_devserver.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(_devserver, "_find_listening_pid", lambda port: 12345)
        monkeypatch.setattr("builtins.input", lambda prompt: "n")

        with pytest.raises(SystemExit, match="already in use"):
            ensure_port_free("127.0.0.1", port)


# --- occupant lookup / kill helpers --------------------------------------------


@dataclass
class _Completed:
    """Stand-in for subprocess.CompletedProcess: only .stdout is read."""

    stdout: str = ""


_NETSTAT_OUT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       4
  TCP    127.0.0.1:8000         127.0.0.1:51000        ESTABLISHED     999
  TCP    0.0.0.0:18000          0.0.0.0:0              LISTENING       111
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       4242
  UDP    0.0.0.0:8000           *:*                                    77
"""


def test_find_listening_pid_parses_netstat_on_windows(monkeypatch):
    """Only a TCP LISTENING row whose local port is exactly :8000 counts — not
    an ESTABLISHED row on the same port, not :18000, not UDP."""
    calls = []
    monkeypatch.setattr(_devserver.sys, "platform", "win32")
    monkeypatch.setattr(_devserver.subprocess, "run", lambda args, **kw: calls.append(args) or _Completed(_NETSTAT_OUT))
    assert _devserver._find_listening_pid(8000) == 4242
    assert calls == [["netstat", "-ano"]]


def test_find_listening_pid_none_when_netstat_has_no_listener(monkeypatch):
    monkeypatch.setattr(_devserver.sys, "platform", "win32")
    monkeypatch.setattr(_devserver.subprocess, "run", lambda args, **kw: _Completed(_NETSTAT_OUT))
    assert _devserver._find_listening_pid(9999) is None


def test_find_listening_pid_uses_lsof_elsewhere(monkeypatch):
    calls = []
    monkeypatch.setattr(_devserver.sys, "platform", "linux")
    monkeypatch.setattr(_devserver.subprocess, "run", lambda args, **kw: calls.append(args) or _Completed("321\n654\n"))
    assert _devserver._find_listening_pid(8000) == 321
    assert calls == [["lsof", "-t", "-i", ":8000", "-sTCP:LISTEN"]]


def test_find_listening_pid_none_when_lsof_finds_nothing(monkeypatch):
    monkeypatch.setattr(_devserver.sys, "platform", "linux")
    monkeypatch.setattr(_devserver.subprocess, "run", lambda args, **kw: _Completed(""))
    assert _devserver._find_listening_pid(8000) is None


@pytest.mark.parametrize("error", [FileNotFoundError("lsof"), ValueError("bad pid")])
def test_find_listening_pid_none_when_lookup_fails(monkeypatch, error):
    """A missing tool or unparsable output degrades to "unknown occupant"
    (the caller then just fails with the manual-lookup hint)."""

    def _boom(args, **kw):
        raise error

    monkeypatch.setattr(_devserver.sys, "platform", "linux")
    monkeypatch.setattr(_devserver.subprocess, "run", _boom)
    assert _devserver._find_listening_pid(8000) is None


def test_kill_pid_uses_taskkill_on_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(_devserver.sys, "platform", "win32")
    monkeypatch.setattr(_devserver.subprocess, "run", lambda args, **kw: calls.append(args) or _Completed())
    assert _devserver._kill_pid(4242) is True
    assert calls == [["taskkill", "/F", "/PID", "4242"]]


def test_kill_pid_sends_sigkill_elsewhere(monkeypatch):
    sent = []
    monkeypatch.setattr(_devserver.sys, "platform", "linux")
    monkeypatch.setattr(_devserver.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(_devserver.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert _devserver._kill_pid(4242) is True
    assert sent == [(4242, 9)]


def test_kill_pid_false_when_kill_fails(monkeypatch):
    def _denied(pid, sig):
        raise PermissionError("not yours")

    monkeypatch.setattr(_devserver.sys, "platform", "linux")
    monkeypatch.setattr(_devserver.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(_devserver.os, "kill", _denied)
    assert _devserver._kill_pid(4242) is False


def test_port_guard_fails_when_occupant_unknown(monkeypatch):
    """Interactive, but the occupant's PID can't be found: no prompt, just the
    loud failure with the manual-lookup hint."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        monkeypatch.setattr(_devserver.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(_devserver, "_find_listening_pid", lambda port: None)
        monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("must not prompt without a PID"))

        with pytest.raises(SystemExit, match="already in use"):
            ensure_port_free("127.0.0.1", port)


def test_port_guard_offers_kill_only_once(monkeypatch):
    """Kill accepted but the port stays taken: the retry fails outright
    instead of prompting again in a loop."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]

        prompts = []
        monkeypatch.setattr(_devserver.sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(_devserver, "_find_listening_pid", lambda port: 12345)
        monkeypatch.setattr(_devserver, "_kill_pid", lambda pid: True)
        monkeypatch.setattr(_devserver.time, "sleep", lambda s: None)
        monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "y")

        with pytest.raises(SystemExit, match="already in use"):
            ensure_port_free("127.0.0.1", port)
        assert len(prompts) == 1


# --- orphan watchdog ----------------------------------------------------------


def test_no_watchdog_without_multiprocessing_parent():
    """In a plain process (tests, single-process runs) there is nothing to
    watch and no thread must be started."""
    assert exit_when_orphaned() is None


def test_watchdog_exits_process_when_parent_dies(monkeypatch):
    """In-process view of the watchdog body: once the parent's join()
    returns, it logs and hard-exits with status 1 (the subprocess test below
    proves the real end-to-end behaviour, which coverage can't see)."""

    class _DeadParent:
        pid = 4321

        def join(self):
            return None

    exits = []
    monkeypatch.setattr(_devserver.multiprocessing, "parent_process", lambda: _DeadParent())
    monkeypatch.setattr(_devserver.os, "_exit", exits.append)
    watchdog = exit_when_orphaned()
    assert watchdog is not None
    watchdog.join(timeout=5)
    assert not watchdog.is_alive()
    assert exits == [1]


_ORPHAN_PARENT_SCRIPT = """\
import multiprocessing
import os
import time


def child():
    from renar_backend._devserver import exit_when_orphaned
    exit_when_orphaned()
    time.sleep(60)  # without the watchdog this outlives the test


if __name__ == "__main__":
    p = multiprocessing.Process(target=child)
    p.start()
    print(p.pid, flush=True)
    time.sleep(2)  # let the spawn finish booting
    os._exit(0)  # die WITHOUT cleanup, orphaning the child (the zombie scenario)
"""


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return re.search(rf"\b{pid}\b", out) is not None
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_orphaned_worker_exits_with_parent(tmp_path):
    script = tmp_path / "orphan_parent.py"
    script.write_text(_ORPHAN_PARENT_SCRIPT, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    pid = int(result.stdout.strip())
    deadline = time.time() + 15
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.5)
    assert not _pid_alive(pid), f"orphaned worker {pid} survived its dead parent"


# --- launch-directory-independent settings -------------------------------------


def test_relative_media_dir_anchors_to_repo_root():
    s = Settings(media_dir="./media")
    assert Path(s.media_dir).is_absolute()
    assert Path(s.media_dir) == (_ROOT / "media").resolve()


def test_absolute_media_dir_untouched(tmp_path):
    s = Settings(media_dir=str(tmp_path))
    assert s.media_dir == str(tmp_path)


def test_env_file_locations_include_repo_root():
    files = Settings.model_config["env_file"]
    assert str(_ROOT / ".env") in files


def test_run_writes_and_removes_server_pid(tmp_path, monkeypatch):
    """`be` records the reloader's pid/port/scheme for the admin self-update
    while serving, and removes it afterwards, even when serving fails."""
    import json

    from renar_backend import __main__ as be
    from renar_backend import update_check

    monkeypatch.setattr(update_check, "REPO", tmp_path)
    monkeypatch.setattr(be, "ensure_port_free", lambda host, port: None)
    seen = {}

    def fake_serve(ssl_kwargs):
        seen["record"] = json.loads((tmp_path / "logs" / "be.pid").read_text(encoding="utf-8"))
        raise KeyboardInterrupt

    monkeypatch.setattr(be, "_serve", fake_serve)
    with pytest.raises(KeyboardInterrupt):
        be.run()
    assert seen["record"]["port"] == be._PORT
    assert seen["record"]["reload"] is True
    assert seen["record"]["scheme"] in ("http", "https")
    assert not (tmp_path / "logs" / "be.pid").exists()
