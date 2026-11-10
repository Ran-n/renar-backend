#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.387223
Revised: 2026/11/09 23:36:44.312171

The server's side of the admin panel's one-click update: whether an update
is available or blocked (``check``), starting the detached helper
(``launch``, see self_update.py), and reading its last outcome
(``last_result``).

Only fast-forwards of a clean ``master`` checkout are allowed: the rollback
is a ``git reset --hard`` to the old commit, which must never throw away
uncommitted work (a second editor often has some in this checkout), and an
update must never create a merge commit.

The server must be running under ``uv run be`` (uvicorn's reloader), which
writes logs/be.pid: the update restarts the worker by changing files, never
by stopping the process, so it works the same under systemd or a console,
on any OS. Each worker writes logs/be-worker.json on startup so the helper
can tell a fresh worker from the old one.
"""

import importlib.util
import json
import logging
import os
import shutil
import subprocess  # nosec B404 -- fixed git argv lists only, never a shell
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import self_update

_log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
BRANCH = "master"
REMOTE = "origin"
GIT_TIMEOUT_SECONDS = 30
MAX_LISTED_COMMITS = 50
STALE_LOCK_SECONDS = 15 * 60
SERVER_PID_FILE = "be.pid"


def _repo(repo: Path | None) -> Path:
    # Resolved per call (not as a default argument) so tests can point REPO elsewhere.
    return REPO if repo is None else repo


def logs_dir(repo: Path | None = None) -> Path:
    return _repo(repo) / "logs"


@dataclass
class UpdateStatus:
    branch: str = ""
    head_sha: str = ""
    remote_sha: str = ""
    remote_version: str | None = None
    behind: list[str] = field(default_factory=list)  # "<short sha> <subject>", newest first
    behind_count: int = 0
    dirty_paths: list[str] = field(default_factory=list)
    blocked_reason: str | None = None
    retryable: bool = False  # a fetch failure: offer "Retry"

    @property
    def available(self) -> bool:
        return self.blocked_reason is None and self.behind_count > 0


class GitError(Exception):
    pass


def _git_exe() -> str:
    git = shutil.which("git")
    if git is None:
        raise GitError("git is not installed or not on PATH")
    return git


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(  # nosec B603 -- fixed argv, no shell
            [_git_exe(), *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS} s") from exc
    except OSError as exc:
        raise GitError(f"could not run git: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


# ---- server / worker markers -------------------------------------------------


def write_server_pid(port: int, scheme: str, repo: Path | None = None) -> Path:
    """Called by ``be`` (the reloader process) before serving."""
    path = logs_dir(repo) / SERVER_PID_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "pid": os.getpid(),
        "port": port,
        "scheme": scheme,
        "reload": True,
        "dev_deps": importlib.util.find_spec("pytest") is not None,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def remove_server_pid(repo: Path | None = None) -> None:
    try:
        (logs_dir(repo) / SERVER_PID_FILE).unlink()
    except FileNotFoundError:
        _log.warning("%s already removed", SERVER_PID_FILE)


def read_server_pid(repo: Path | None = None) -> dict | None:
    try:
        return json.loads((logs_dir(repo) / SERVER_PID_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        _log.error("unreadable %s: %s", SERVER_PID_FILE, exc)
        return None


def write_worker_marker(repo: Path | None = None) -> None:
    """Called from the app's lifespan in each worker; failure is logged, not fatal."""
    path = logs_dir(repo) / self_update.WORKER_MARKER
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": os.getpid(), "started_at": time.time()}), encoding="utf-8")
    except OSError:
        _log.exception("could not write %s; a self-update can't confirm this worker", path)


# ---- lock -------------------------------------------------------------------


def _lock_path(repo: Path | None) -> Path:
    return logs_dir(repo) / self_update.LOCK_FILE


def lock_active(repo: Path | None = None) -> bool:
    """A lock younger than 15 min means an update is running; an older one
    is stale (a helper that died) and is removed, logged at WARNING."""
    path = _lock_path(repo)
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    if age < STALE_LOCK_SECONDS:
        return True
    _log.warning("removing stale self-update lock (%d min old)", age // 60)
    path.unlink(missing_ok=True)  # a concurrent check may have removed it already
    return False


def take_lock(repo: Path | None = None) -> bool:
    """Exclusive create; False when another update holds it."""
    if lock_active(repo):
        return False
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "taken_at": time.time()}))
    return True


def release_lock(repo: Path | None = None) -> None:
    try:
        _lock_path(repo).unlink()
    except FileNotFoundError:
        _log.warning("self-update lock already released")


# ---- check ------------------------------------------------------------------


def check(repo: Path | None = None, *, fetch: bool = True) -> UpdateStatus:
    """The update state of ``repo`` against origin/master. Every problem
    becomes ``blocked_reason``; a failed check is never "Up to date"."""
    repo = _repo(repo)
    status = UpdateStatus()
    try:
        _git(repo, "rev-parse", "--show-toplevel")
    except GitError as exc:
        status.blocked_reason = f"Not a git checkout, so it can't update itself ({exc})."
        return status
    try:
        status.branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        status.head_sha = _git(repo, "rev-parse", "HEAD").strip()
    except GitError as exc:
        status.blocked_reason = str(exc)
        return status
    if lock_active(repo):
        status.blocked_reason = "An update is already in progress."
        return status
    server = read_server_pid(repo)
    if server is None or not server.get("reload"):
        status.blocked_reason = (
            "The server wasn't started with `uv run be` (no logs/be.pid), so it can't reload itself; update by hand."
        )
        return status
    if status.branch != BRANCH:
        status.blocked_reason = f"Checked out on {status.branch}; switch to {BRANCH} to update."
        return status
    try:
        porcelain = _git(repo, "status", "--porcelain")
    except GitError as exc:
        status.blocked_reason = str(exc)
        return status
    status.dirty_paths = [line[3:] for line in porcelain.splitlines() if line.strip()]
    if status.dirty_paths:
        status.blocked_reason = "The working tree has uncommitted changes; commit or discard them first."
        return status
    if fetch:
        try:
            _git(repo, "fetch", REMOTE, BRANCH)
        except GitError as exc:
            status.blocked_reason = f"Couldn't check for updates: {exc}"
            status.retryable = True
            return status
    ref = f"{REMOTE}/{BRANCH}"
    try:
        status.remote_sha = _git(repo, "rev-parse", ref).strip()
        if _git(repo, "rev-list", f"{ref}..HEAD").strip():
            status.blocked_reason = "Local commits not pushed; an update would need a merge."
            return status
        status.behind_count = int(_git(repo, "rev-list", "--count", f"HEAD..{ref}").strip() or 0)
        if status.behind_count:
            log = _git(repo, "log", f"--max-count={MAX_LISTED_COMMITS}", "--format=%h %s", f"HEAD..{ref}")
            status.behind = log.splitlines()
            status.remote_version = _version_at(repo, ref)
    except GitError as exc:
        status.blocked_reason = str(exc)
    return status


def _version_at(repo: Path, ref: str) -> str | None:
    try:
        return tomllib.loads(_git(repo, "show", f"{ref}:pyproject.toml"))["project"]["version"]
    except (GitError, tomllib.TOMLDecodeError, KeyError) as exc:
        _log.error("can't read the version at %s: %s", ref, exc)
        return None


# ---- launch -----------------------------------------------------------------


def _uv_exe() -> str | None:
    # `uv run` exports UV (its own path) to what it runs; fall back to PATH.
    return os.environ.get("UV") or shutil.which("uv")


def launch(status: UpdateStatus, from_version: str, repo: Path | None = None) -> Path:
    """Start the detached helper; the caller holds the lock (take_lock),
    which the helper releases when done. Returns the helper's log path."""
    repo = _repo(repo)
    server = read_server_pid(repo) or {}
    uv = _uv_exe()
    if uv is None:
        raise RuntimeError("uv not found (no UV variable, not on PATH)")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = logs_dir(repo) / f"self-update-{stamp}.log"
    scheme = server.get("scheme", "http")
    port = server.get("port", 8000)
    cmd = [
        # The base interpreter in isolated mode: outside the venv (its
        # packages can be replaced by `uv sync`), no user site, no cwd on
        # sys.path. self_update.py imports only the standard library.
        getattr(sys, "_base_executable", sys.executable),
        "-I",
        str(Path(self_update.__file__).resolve()),
        "--repo",
        str(repo),
        "--uv",
        uv,
        "--git",
        _git_exe(),
        "--from-sha",
        status.head_sha,
        "--to-sha",
        status.remote_sha,
        "--from-version",
        from_version,
        "--to-version",
        status.remote_version or from_version,
        "--base-url",
        f"{scheme}://127.0.0.1:{port}",
        "--log-path",
        str(log_path),
    ]
    if not server.get("dev_deps", True):
        cmd.append("--no-dev")
    kwargs: dict = {
        "cwd": repo,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        # Own process group, no console: survives the worker being replaced
        # and never receives the console's Ctrl+C.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)  # nosec B603 -- fixed argv, no shell
    _log.warning("self-update started: %s -> %s, log %s", status.head_sha[:8], status.remote_sha[:8], log_path)
    return log_path


# ---- last result ------------------------------------------------------------


@dataclass
class LastResult:
    status: str  # ok / rolled_back / failed / running / corrupt
    from_version: str = ""
    to_version: str = ""
    failed_step: str | None = None
    error: str | None = None
    log_path: str = ""
    finished_at: str | None = None


def last_result(repo: Path | None = None) -> LastResult | None:
    path = logs_dir(repo) / self_update.STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LastResult(
            status=str(data["status"]),
            from_version=str(data.get("from_version") or ""),
            to_version=str(data.get("to_version") or ""),
            failed_step=data.get("failed_step"),
            error=data.get("error"),
            log_path=str(data.get("log_path") or ""),
            finished_at=data.get("finished_at"),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log.error("corrupt %s: %s", path, exc)
        return LastResult(status="corrupt", error=str(exc), log_path=str(path))
