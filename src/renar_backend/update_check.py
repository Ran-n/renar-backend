#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.387223
Revised: 2026/11/10 16:17:27.444492

The server's side of the admin panel's one-click update: whether an update
is available or blocked (``check``), getting it ready (``prepare``),
starting the detached helper (``launch``, see self_update.py), and reading
its last outcome (``last_result``).

Two sources, picked by what the project directory is:

* a **git checkout** (``.git`` present) fast-forwards to ``origin/master``.
  Only a clean ``master`` with no unpushed commits is allowed: the rollback
  is a ``git reset --hard`` to the old commit, which must never throw away
  uncommitted work (a second editor often has some in a checkout), and an
  update must never create a merge commit.
* anything else (a tarball deploy, like prod) installs the latest release's
  ``renar_backend-<version>.tar.gz``, refused unless it matches the
  ``.tar.gz.b3`` BLAKE3 sum published with it. ``prepare`` downloads,
  checks and unpacks it before the helper starts.

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
import subprocess  # nosec B404 -- fixed argv lists only, never a shell
import sys
import tarfile
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import blake3
import httpx

from . import self_update
from .config import settings

_log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
PACKAGE = "renar_backend"
HTTP_TIMEOUT_SECONDS = 20
MAX_TARBALL_BYTES = 100 * 1024 * 1024
MAX_NOTES_CHARS = 4000
STALE_LOCK_SECONDS = 15 * 60
SERVER_PID_FILE = "be.pid"
MODE_GIT = self_update.MODE_GIT
MODE_TARBALL = self_update.MODE_TARBALL
BRANCH = "master"
REMOTE = "origin"
GIT_TIMEOUT_SECONDS = 30
MAX_LISTED_COMMITS = 50
_USER_AGENT = "renar-backend-self-update"


def _repo(repo: Path | None) -> Path:
    # Resolved per call (not as a default argument) so tests can point REPO elsewhere.
    return REPO if repo is None else repo


def logs_dir(repo: Path | None = None) -> Path:
    return _repo(repo) / "logs"


def work_dir(repo: Path | None = None) -> Path:
    """Where the unpacked release and the previous files live during an
    update; inside the project so every move is a same-filesystem rename."""
    return _repo(repo) / self_update.WORK_DIR


@dataclass
class UpdateStatus:
    mode: str = MODE_TARBALL
    current_version: str = ""
    # the newer version: the release's in tarball mode, origin/master's pyproject.toml in git mode
    latest_version: str | None = None
    blocked_reason: str | None = None
    retryable: bool = False  # a failed lookup (release feed or git fetch): the page's check button says "Retry"
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))  # when check() built this
    # tarball mode
    release_url: str = ""  # the release's web page
    release_notes: str = ""
    tarball_url: str = ""
    checksum_url: str = ""
    # git mode
    branch: str = ""
    head_sha: str = ""
    remote_sha: str = ""
    behind: list[str] = field(default_factory=list)  # "<short sha> <subject>", newest first
    behind_count: int = 0
    dirty_paths: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        if self.blocked_reason is not None:
            return False
        if self.mode == MODE_GIT:
            return self.behind_count > 0
        if self.latest_version is None:
            return False
        return parse_version(self.latest_version) > parse_version(self.current_version)


class UpdateError(Exception):
    pass


class GitError(Exception):
    pass


def mode_of(repo: Path | None = None) -> str:
    return MODE_GIT if (_repo(repo) / ".git").exists() else MODE_TARBALL


def parse_version(text: str) -> tuple[int, ...]:
    """``"v1.2.3"`` -> ``(1, 2, 3)``; anything else raises UpdateError."""
    parts = text.strip().removeprefix("v").split(".")
    if not parts or not all(p.isdigit() for p in parts):
        raise UpdateError(f"not a release version: {text!r}")
    return tuple(int(p) for p in parts)


def tarball_name(version: str) -> str:
    return f"{PACKAGE}-{version}.tar.gz"


def _http() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,  # release assets redirect to a CDN
        headers={"User-Agent": _USER_AGENT},
    )


# ---- check ------------------------------------------------------------------


def check(current_version: str, repo: Path | None = None, *, fetch: bool = True) -> UpdateStatus:
    """The update state of ``repo``: against origin/master for a git
    checkout, against the latest release otherwise. Every problem becomes
    ``blocked_reason``; a failed check is never "Up to date"."""
    repo = _repo(repo)
    status = UpdateStatus(mode=mode_of(repo), current_version=current_version)
    if status.mode == MODE_GIT:
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
    if status.mode == MODE_GIT:
        _check_git(repo, status, fetch=fetch)
    else:
        _check_release(status)
    return status


def _check_git(repo: Path, status: UpdateStatus, *, fetch: bool) -> None:
    if status.branch != BRANCH:
        status.blocked_reason = f"Checked out on {status.branch}; switch to {BRANCH} to update."
        return
    try:
        porcelain = _git(repo, "status", "--porcelain")
    except GitError as exc:
        status.blocked_reason = str(exc)
        return
    status.dirty_paths = [line[3:] for line in porcelain.splitlines() if line.strip()]
    if status.dirty_paths:
        status.blocked_reason = "The working tree has uncommitted changes; commit or discard them first."
        return
    if fetch:
        try:
            _git(repo, "fetch", REMOTE, BRANCH)
        except GitError as exc:
            _log.error("git fetch failed: %s", exc)
            status.blocked_reason = f"Couldn't check for updates: {exc}"
            status.retryable = True
            return
    ref = f"{REMOTE}/{BRANCH}"
    try:
        status.remote_sha = _git(repo, "rev-parse", ref).strip()
        if _git(repo, "rev-list", f"{ref}..HEAD").strip():
            status.blocked_reason = "Local commits not pushed; an update would need a merge."
            return
        status.behind_count = int(_git(repo, "rev-list", "--count", f"HEAD..{ref}").strip() or 0)
        if status.behind_count:
            log = _git(repo, "log", f"--max-count={MAX_LISTED_COMMITS}", "--format=%h %s", f"HEAD..{ref}")
            status.behind = log.splitlines()
            status.latest_version = _version_at(repo, ref)
    except GitError as exc:
        status.blocked_reason = str(exc)


def _version_at(repo: Path, ref: str) -> str | None:
    try:
        return tomllib.loads(_git(repo, "show", f"{ref}:pyproject.toml"))["project"]["version"]
    except (GitError, tomllib.TOMLDecodeError, KeyError) as exc:
        _log.error("can't read the version at %s: %s", ref, exc)
        return None


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


def _check_release(status: UpdateStatus) -> None:
    current_version = status.current_version
    try:
        parse_version(current_version)
    except UpdateError as exc:
        status.blocked_reason = f"The running version can't be compared: {exc}"
        return
    try:
        with _http() as client:
            response = client.get(settings.update_release_url, headers={"Accept": "application/json"})
        response.raise_for_status()
        release = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        _log.error("release lookup at %s failed: %s", settings.update_release_url, exc)
        status.blocked_reason = f"Couldn't check for updates: {exc}"
        status.retryable = True
        return
    try:
        _read_release(release, status)
    except UpdateError as exc:
        _log.error("unusable latest release at %s: %s", settings.update_release_url, exc)
        status.blocked_reason = str(exc)


def _read_release(release: object, status: UpdateStatus) -> None:
    if not isinstance(release, dict) or not isinstance(release.get("tag_name"), str):
        raise UpdateError("The release feed answered without a tag_name.")
    version = release["tag_name"].strip().removeprefix("v")
    parse_version(version)
    status.latest_version = version
    status.release_url = str(release.get("html_url") or "")
    notes = str(release.get("body") or "")
    status.release_notes = notes if len(notes) <= MAX_NOTES_CHARS else notes[:MAX_NOTES_CHARS] + "\n…"
    assets = {
        a.get("name"): a.get("browser_download_url")
        for a in release.get("assets") or []
        if isinstance(a, dict) and a.get("browser_download_url")
    }
    name = tarball_name(version)
    if name not in assets or f"{name}.b3" not in assets:
        raise UpdateError(f"Release {version} has no {name} with its {name}.b3 checksum.")
    status.tarball_url = assets[name]
    status.checksum_url = assets[f"{name}.b3"]


# ---- prepare ----------------------------------------------------------------


def prepare(status: UpdateStatus, repo: Path | None = None) -> Path | None:
    """Tarball mode: download the release tarball, check it against its
    ``.b3`` sum and unpack it into the work dir's ``stage``; returns that
    directory. Git mode has nothing to get ready (the fetch already ran):
    returns None. The caller holds the lock. Any problem raises UpdateError."""
    repo = _repo(repo)
    if not status.available:
        raise UpdateError("Nothing newer to install.")
    if status.mode == MODE_GIT:
        return None
    work = work_dir(repo)
    stage = work / self_update.STAGE_DIR
    if stage.exists():
        shutil.rmtree(stage)  # left over from an update that never launched
    work.mkdir(parents=True, exist_ok=True)
    tarball = work / tarball_name(status.latest_version)
    try:
        with _http() as client:
            expected = _expected_sum(client, status.checksum_url, tarball.name)
            actual = _download(client, status.tarball_url, tarball)
    except httpx.HTTPError as exc:
        tarball.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't download the release: {exc}") from exc
    except UpdateError:
        tarball.unlink(missing_ok=True)
        raise
    if actual != expected:
        tarball.unlink()
        raise UpdateError(f"{tarball.name} doesn't match its BLAKE3 sum (got {actual}, expected {expected}).")
    _log.info("downloaded %s, BLAKE3 %s", tarball.name, actual)
    try:
        _unpack(tarball, stage, status.latest_version)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        tarball.unlink(missing_ok=True)
    return stage


def _expected_sum(client: httpx.Client, url: str, name: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    # b3sum format: "<64 hex>  <file name>"
    for line in response.text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip("*") == name:
            return fields[0].lower()
        if len(fields) == 1:
            return fields[0].lower()
    raise UpdateError(f"{name}.b3 has no sum for {name}.")


def _download(client: httpx.Client, url: str, dest: Path) -> str:
    hasher = blake3.blake3()
    size = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_TARBALL_BYTES:
                    raise UpdateError(f"{dest.name} is over {MAX_TARBALL_BYTES // (1024 * 1024)} MB.")
                hasher.update(chunk)
                f.write(chunk)
    return hasher.hexdigest()


def _unpack(tarball: Path, stage: Path, version: str) -> None:
    unpacked = stage.parent / f"{self_update.STAGE_DIR}.unpack"
    shutil.rmtree(unpacked, ignore_errors=True)
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(unpacked, filter="data")  # nosec B202 -- "data" refuses links and paths outside
    except (tarfile.TarError, OSError) as exc:
        shutil.rmtree(unpacked, ignore_errors=True)
        raise UpdateError(f"Couldn't unpack {tarball.name}: {exc}") from exc
    roots = list(unpacked.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        shutil.rmtree(unpacked, ignore_errors=True)
        raise UpdateError(f"{tarball.name} should hold one top-level folder, found {len(roots)} entries.")
    os.replace(roots[0], stage)
    unpacked.rmdir()
    (stage / "PKG-INFO").unlink(missing_ok=True)  # sdist metadata, not a project file
    for required in ("pyproject.toml", "uv.lock", "alembic.ini", f"src/{PACKAGE}/__init__.py"):
        if not (stage / required).is_file():
            raise UpdateError(f"{tarball.name} has no {required}.")
    try:
        found = tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError) as exc:
        raise UpdateError(f"{tarball.name}'s pyproject.toml has no version: {exc}") from exc
    if found != version:
        raise UpdateError(f"{tarball.name} contains version {found}, not {version}.")


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


# ---- launch -----------------------------------------------------------------


def _uv_exe() -> str | None:
    # `uv run` exports UV (its own path) to what it runs; fall back to PATH.
    return os.environ.get("UV") or shutil.which("uv")


def launch(status: UpdateStatus, stage: Path | None, repo: Path | None = None) -> Path:
    """Start the detached helper (on the unpacked ``stage`` in tarball
    mode); the caller holds the lock (take_lock), which the helper releases
    when done. Returns the helper's log path."""
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
        "--mode",
        status.mode,
        *_source_args(status, stage),
        "--from-version",
        status.current_version,
        "--to-version",
        status.latest_version or status.current_version,
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
    target = status.remote_sha[:8] if status.mode == MODE_GIT else status.latest_version
    _log.warning("self-update (%s) started: %s -> %s, log %s", status.mode, status.current_version, target, log_path)
    return log_path


def _source_args(status: UpdateStatus, stage: Path | None) -> list[str]:
    if status.mode == MODE_GIT:
        return ["--git", _git_exe(), "--from-sha", status.head_sha, "--to-sha", status.remote_sha]
    if stage is None:
        raise RuntimeError("a tarball update needs the unpacked stage from prepare()")
    return ["--stage", str(stage)]


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
