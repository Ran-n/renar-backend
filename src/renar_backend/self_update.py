#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.223079
Revised: 2026/11/10 13:53:25.298678

The admin panel's one-click server update, as a detached helper process.

Started by update_check.launch() with the base interpreter in isolated mode
(``python -I``), outside the project venv: it imports only the standard
library, so ``uv sync`` can replace any installed package while it runs.

The server is never stopped. It runs under uvicorn's reloader (``uv run
be``), so the helper only changes files on disk and the reloader swaps the
worker; whatever supervises the reloader (systemd on prod, a console on a
dev PC) is untouched, which keeps this the same on every OS. To keep the
running code consistent at each moment, the order is:

1. stage   put the new pyproject.toml, uv.lock, alembic/ and other
           non-code files in place; the reloader only watches src/, so
           nothing restarts yet
2. sync    ``uv sync --locked`` (``--no-dev`` when the server runs without dev deps)
3. migrate ``uv run --no-sync alembic upgrade head`` (one transaction:
           a failure leaves the schema as it was)
4. swap    put the new src/ in place, then touch the package's __init__.py
           so the reloader restarts
5. verify  the new worker writes logs/be-worker.json on startup; wait for a
           marker newer than the swap, then for ``GET /`` to report the new
           version (120 s)

Steps 1 and 4 depend on the source (``--mode``):

* ``git``: stage is ``git checkout <to> -- pyproject.toml uv.lock
  alembic.ini alembic``, swap is ``git merge --ff-only <to>``, and the
  rollback is ``git reset --hard <from>`` (safe: the tree was clean, a
  precondition update_check enforces).
* ``tarball``: update_check.prepare() has unpacked the release into
  ``.self-update/stage``. Every change is a rename between the stage, the
  project and ``.self-update/previous`` (one filesystem, so nothing is
  half-written): stage moves each top-level entry except ``src``, swap each
  entry of ``src/`` (the package directory, never ``src/`` itself, so the
  reloader's watch on it survives). The rollback moves everything back in
  reverse order and deletes entries the old release didn't have. After a
  success ``previous`` keeps the old files until the next update.

Any failure rolls back: ``alembic downgrade <from revision>`` if step 3 ran
(with the new scripts, still in place), the source's restore, ``uv sync``
again, touch, and wait for the old version. The outcome lands in
logs/self-update-last.json (``ok`` / ``rolled_back`` / ``failed``), every
command's output in logs/self-update-<timestamp>.log, and the lock
logs/self-update.lock is removed at the end either way.
"""

import argparse
import json
import logging
import os
import shutil
import ssl
import subprocess  # nosec B404 -- fixed argv lists only, never a shell
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger("renar_backend.self_update")

MODE_GIT = "git"
MODE_TARBALL = "tarball"
GIT_STAGED_PATHS = ("pyproject.toml", "uv.lock", "alembic.ini", "alembic")
WORK_DIR = ".self-update"
STAGE_DIR = "stage"
PREVIOUS_DIR = "previous"
CODE_DIR = "src"
STATUS_FILE = "self-update-last.json"
LOCK_FILE = "self-update.lock"
WORKER_MARKER = "be-worker.json"
STEP_TIMEOUT_SECONDS = 600
HEALTH_TIMEOUT_SECONDS = 120
_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"

Runner = Callable[[list[str], str], str]


class StepFailed(Exception):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


# ---- sources: where the new files come from ---------------------------------


class GitSource:
    """Fast-forward of a clean checkout to ``to_sha``."""

    def __init__(self, repo: Path, run: Runner, git: str, from_sha: str, to_sha: str):
        self.repo, self.run, self.git = repo, run, git
        self.from_sha, self.to_sha = from_sha, to_sha

    def record(self) -> dict:
        return {"from_sha": self.from_sha, "to_sha": self.to_sha}

    def begin(self) -> None:
        pass

    def stage(self) -> None:
        listed = self.run([self.git, "ls-tree", "--name-only", self.to_sha, "--", *GIT_STAGED_PATHS], "stage")
        present = [p for p in listed.split() if p]
        if present:
            self.run([self.git, "checkout", self.to_sha, "--", *present], "stage")

    def swap(self) -> None:
        self.run([self.git, "merge", "--ff-only", self.to_sha], "swap")

    def restore(self) -> None:
        self.run([self.git, "reset", "--hard", self.from_sha], "rollback-reset")

    def finish(self) -> None:
        pass


class TarballSource:
    """A release unpacked in ``stage``, swapped in by renames."""

    def __init__(self, repo: Path, stage: Path):
        self.repo = repo
        self.stage_dir = stage
        self.previous = repo / WORK_DIR / PREVIOUS_DIR
        # (path relative to the project, whether the old release had it), in move order
        self.moved: list[tuple[str, bool]] = []

    def record(self) -> dict:
        return {}

    def begin(self) -> None:
        if not (self.stage_dir / CODE_DIR / "renar_backend" / "__init__.py").is_file():
            raise StepFailed("begin", f"{self.stage_dir} holds no unpacked release")
        try:
            if self.previous.exists():
                shutil.rmtree(self.previous)  # the update before last's files
            self.previous.mkdir(parents=True)
        except OSError as exc:
            raise StepFailed("begin", f"can't reset {self.previous}: {exc}") from exc

    def move_in(self, rel: str, step: str) -> None:
        """The release's ``rel`` replaces the project's, whose old copy
        goes to ``previous``: two renames, recorded for the rollback."""
        target = self.repo / rel
        existed = target.exists() or target.is_symlink()
        try:
            if existed:
                (self.previous / rel).parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, self.previous / rel)
            self.moved.append((rel, existed))
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self.stage_dir / rel, target)
        except OSError as exc:
            _log.error("[%s] could not move %s into place: %s", step, rel, exc)
            raise StepFailed(step, f"{rel}: {exc}") from exc
        _log.info("[%s] installed %s%s", step, rel, "" if existed else " (new)")

    def stage(self) -> None:
        for entry in sorted(self.stage_dir.iterdir()):
            if entry.name != CODE_DIR:
                self.move_in(entry.name, "stage")

    def swap(self) -> None:
        for entry in sorted((self.stage_dir / CODE_DIR).iterdir()):
            self.move_in(f"{CODE_DIR}/{entry.name}", "swap")

    def restore(self) -> None:
        for rel, existed in reversed(self.moved):
            try:
                _remove(self.repo / rel)
                if existed:
                    os.replace(self.previous / rel, self.repo / rel)
            except OSError as exc:
                _log.error("[rollback-restore] could not restore %s: %s", rel, exc)
                raise StepFailed("rollback-restore", f"{rel}: {exc}") from exc
            _log.info("[rollback-restore] %s %s", "restored" if existed else "removed", rel)
        self.moved.clear()

    def finish(self) -> None:
        try:
            shutil.rmtree(self.stage_dir)
        except FileNotFoundError:
            pass
        except OSError:
            _log.exception("could not remove %s", self.stage_dir)


# ---- the update -------------------------------------------------------------


class Updater:
    def __init__(self, args: argparse.Namespace, log_path: Path):
        self.repo = Path(args.repo).resolve()
        self.logs = self.repo / "logs"
        self.uv = args.uv
        self.from_version = args.from_version
        self.to_version = args.to_version
        self.base_url = args.base_url.rstrip("/")
        self.no_dev = args.no_dev
        self.health_timeout = args.health_timeout
        self.log_path = log_path
        self.started_at = _now_iso()
        self.from_revision: str | None = None
        self.migrated = False
        if args.mode == MODE_GIT:
            self.source = GitSource(self.repo, self.run, args.git, args.from_sha, args.to_sha)
        else:
            self.source = TarballSource(self.repo, Path(args.stage).resolve())

    # ---- plumbing ---------------------------------------------------------

    def run(self, cmd: list[str], step: str) -> str:
        """Run one command in the repo, its output teed to the log; a
        non-zero exit or a timeout raises StepFailed, so no step fails silently."""
        _log.info("[%s] $ %s", step, " ".join(cmd))
        try:
            proc = subprocess.run(  # nosec B603 -- fixed argv, no shell
                cmd,
                cwd=self.repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=STEP_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log.error("[%s] could not run: %s", step, exc)
            raise StepFailed(step, str(exc)) from exc
        for stream in (proc.stdout, proc.stderr):
            if stream.strip():
                _log.info("[%s] %s", step, stream.rstrip())
        if proc.returncode != 0:
            _log.error("[%s] exited with %d", step, proc.returncode)
            raise StepFailed(step, f"exit code {proc.returncode}")
        return proc.stdout

    def write_status(self, status: str, failed_step: str | None = None, error: str | None = None) -> None:
        record = {
            "status": status,
            "started_at": self.started_at,
            "finished_at": None if status == "running" else _now_iso(),
            "mode": MODE_GIT if isinstance(self.source, GitSource) else MODE_TARBALL,
            **self.source.record(),
            "from_version": self.from_version,
            "to_version": self.to_version,
            "failed_step": failed_step,
            "error": error,
            "log_path": str(self.log_path),
        }
        tmp = self.logs / f"{STATUS_FILE}.tmp"
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, self.logs / STATUS_FILE)

    def release_lock(self) -> None:
        try:
            (self.logs / LOCK_FILE).unlink()
        except FileNotFoundError:
            _log.warning("lock file already gone")

    def sync_cmd(self) -> list[str]:
        cmd = [self.uv, "sync", "--locked"]
        if self.no_dev:
            cmd.append("--no-dev")
        return cmd

    def touch_reload(self, step: str) -> float:
        """Make the reloader restart the worker; returns the time of the touch."""
        marker = self.repo / CODE_DIR / "renar_backend" / "__init__.py"
        stamp = time.time()
        try:
            os.utime(marker, (stamp, stamp))
        except OSError as exc:
            raise StepFailed(step, f"touch {marker}: {exc}") from exc
        _log.info("touched %s to trigger the reload", marker)
        return stamp

    # ---- steps ------------------------------------------------------------

    def current_revision(self) -> str | None:
        out = self.run([self.uv, "run", "--no-sync", "alembic", "current"], "alembic-current")
        for line in out.splitlines():
            token = line.strip().split(" ")[0]
            if token and all(c in "0123456789abcdef" for c in token):
                return token
        return None

    def sync(self) -> None:
        self.run(self.sync_cmd(), "sync")

    def migrate(self) -> None:
        self.run([self.uv, "run", "--no-sync", "alembic", "upgrade", "head"], "migrate")
        self.migrated = True

    def swap(self) -> float:
        self.source.swap()
        return self.touch_reload("swap")

    def wait_healthy(self, expected_version: str, since: float, step: str) -> None:
        """A worker started after ``since`` answers ``GET /`` with ``expected_version``."""
        deadline = time.monotonic() + self.health_timeout
        # Loopback liveness check only: the cert (if any) is for the public
        # hostname, never 127.0.0.1, so hostname/chain checks can't apply.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # nosec B501 -- loopback health probe, see above
        last_problem = "no new worker started"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.base_url}/", timeout=5, context=context) as response:  # nosec B310 -- fixed loopback URL
                    version = json.loads(response.read().decode("utf-8")).get("version")
            except (OSError, ValueError, urllib.error.URLError) as exc:
                last_problem = f"GET / failed: {exc}"
            else:
                started = self._worker_started_at()
                if started is None or started < since:
                    last_problem = "no new worker started"  # the old worker answered
                elif version != expected_version:
                    last_problem = f"server reports version {version!r}, expected {expected_version!r}"
                else:
                    _log.info("[%s] server is back on %s", step, version)
                    return
            time.sleep(1)
        _log.error("[%s] %s after %d s", step, last_problem, self.health_timeout)
        raise StepFailed(step, last_problem)

    def _worker_started_at(self) -> float | None:
        try:
            data = json.loads((self.logs / WORKER_MARKER).read_text(encoding="utf-8"))
            return float(data["started_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # ---- orchestration ----------------------------------------------------

    def update(self) -> str:
        self.write_status("running")
        try:
            self.source.begin()
            self.from_revision = self.current_revision()
            self.source.stage()
            self.sync()
            self.migrate()
            since = self.swap()
            self.wait_healthy(self.to_version, since, "verify")
        except StepFailed as failure:
            _log.error("update failed at %s; rolling back to %s", failure.step, self.from_version)
            try:
                self.rollback()
            except StepFailed as rollback_failure:
                _log.error("rollback failed at %s; the server may be down", rollback_failure.step)
                self.write_status("failed", failure.step, f"{failure}; rollback: {rollback_failure}")
                return "failed"
            finally:
                self.source.finish()
            self.write_status("rolled_back", failure.step, str(failure))
            return "rolled_back"
        self.source.finish()
        self.write_status("ok")
        _log.info("updated %s -> %s", self.from_version, self.to_version)
        return "ok"

    def rollback(self) -> None:
        if self.migrated and self.from_revision:
            # The downgrade scripts are the new ones, still in place.
            self.run([self.uv, "run", "--no-sync", "alembic", "downgrade", self.from_revision], "rollback-migrate")
        self.source.restore()
        self.run(self.sync_cmd(), "rollback-sync")
        since = self.touch_reload("rollback-restore")
        self.wait_healthy(self.from_version, since, "rollback-verify")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="self_update", description="One-click server update helper.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--uv", required=True)
    parser.add_argument("--mode", choices=(MODE_GIT, MODE_TARBALL), required=True)
    parser.add_argument("--git", help="git mode: the git executable")
    parser.add_argument("--from-sha", help="git mode: the commit to roll back to")
    parser.add_argument("--to-sha", help="git mode: the commit to fast-forward to")
    parser.add_argument("--stage", help="tarball mode: the unpacked release")
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--to-version", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--no-dev", action="store_true")
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--health-timeout", type=float, default=HEALTH_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    if args.mode == MODE_GIT and not (args.git and args.from_sha and args.to_sha):
        parser.error("--mode git needs --git, --from-sha and --to-sha")
    if args.mode == MODE_TARBALL and not args.stage:
        parser.error("--mode tarball needs --stage")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log_path = Path(args.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, "%Y-%m-%d %H:%M:%S"))
    _log.addHandler(handler)
    _log.setLevel(logging.INFO)
    updater = Updater(args, log_path)
    try:
        result = updater.update()
    except Exception as exc:  # anything unforeseen still ends in a status and no lock
        _log.exception("self-update crashed")
        updater.write_status("failed", "helper", repr(exc))
        result = "failed"
    finally:
        updater.release_lock()
        handler.close()
    return 0 if result == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
