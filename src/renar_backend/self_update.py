#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.223079
Revised: 2026/11/09 23:36:44.145270

The admin panel's one-click server update, as a detached helper process.

Started by update_check.launch() with the base interpreter in isolated mode
(``python -I``), outside the project venv: it imports only the standard
library, so ``uv sync`` can replace any installed package while it runs.

The server is never stopped. It runs under uvicorn's reloader (``uv run
be``), so the helper only changes files on disk and the reloader swaps the
worker; whatever supervises the reloader (systemd on prod, a console on a
dev PC) is untouched, which keeps this the same on every OS. To keep the
running code consistent at each moment, the order is:

1. stage   ``git checkout <to> -- pyproject.toml uv.lock alembic.ini alembic``
           (paths the reloader doesn't watch, so nothing restarts yet)
2. sync    ``uv sync --locked`` (``--no-dev`` when the server runs without dev deps)
3. migrate ``uv run --no-sync alembic upgrade head`` (one transaction:
           a failure leaves the schema as it was)
4. swap    ``git merge --ff-only <to>``, then touch the package's __init__.py
           so the reloader restarts even when no .py changed
5. verify  the new worker writes logs/be-worker.json on startup; wait for a
           marker newer than the swap, then for ``GET /`` to report the new
           version (120 s)

Any failure rolls back: ``alembic downgrade <from revision>`` if step 3 ran,
``git reset --hard <from sha>`` (safe: the tree was clean, a precondition),
``uv sync`` again, touch, and wait for the old version. The outcome lands in
logs/self-update-last.json (``ok`` / ``rolled_back`` / ``failed``), every
command's output in logs/self-update-<timestamp>.log, and the lock
logs/self-update.lock is removed at the end either way.
"""

import argparse
import json
import logging
import os
import ssl
import subprocess  # nosec B404 -- fixed argv lists only, never a shell
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger("renar_backend.self_update")

STAGED_PATHS = ("pyproject.toml", "uv.lock", "alembic.ini", "alembic")
STATUS_FILE = "self-update-last.json"
LOCK_FILE = "self-update.lock"
WORKER_MARKER = "be-worker.json"
STEP_TIMEOUT_SECONDS = 600
HEALTH_TIMEOUT_SECONDS = 120
_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"


class StepFailed(Exception):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Updater:
    def __init__(self, args: argparse.Namespace, log_path: Path):
        self.repo = Path(args.repo).resolve()
        self.logs = self.repo / "logs"
        self.uv = args.uv
        self.git = args.git
        self.from_sha = args.from_sha
        self.to_sha = args.to_sha
        self.from_version = args.from_version
        self.to_version = args.to_version
        self.base_url = args.base_url.rstrip("/")
        self.no_dev = args.no_dev
        self.health_timeout = args.health_timeout
        self.log_path = log_path
        self.started_at = _now_iso()
        self.from_revision: str | None = None
        self.migrated = False
        self.swapped = False

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
            "from_sha": self.from_sha,
            "to_sha": self.to_sha,
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

    def touch_reload(self) -> float:
        """Make the reloader restart the worker; returns the time of the touch."""
        marker = self.repo / "src" / "renar_backend" / "__init__.py"
        stamp = time.time()
        os.utime(marker, (stamp, stamp))
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

    def stage(self) -> None:
        listed = self.run([self.git, "ls-tree", "--name-only", self.to_sha, "--", *STAGED_PATHS], "stage")
        present = [p for p in listed.split() if p]
        if present:
            self.run([self.git, "checkout", self.to_sha, "--", *present], "stage")

    def sync(self) -> None:
        self.run(self.sync_cmd(), "sync")

    def migrate(self) -> None:
        self.run([self.uv, "run", "--no-sync", "alembic", "upgrade", "head"], "migrate")
        self.migrated = True

    def swap(self) -> float:
        self.run([self.git, "merge", "--ff-only", self.to_sha], "swap")
        self.swapped = True
        return self.touch_reload()

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
            self.from_revision = self.current_revision()
            self.stage()
            self.sync()
            self.migrate()
            since = self.swap()
            self.wait_healthy(self.to_version, since, "verify")
        except StepFailed as failure:
            _log.error("update failed at %s; rolling back to %s", failure.step, self.from_sha)
            try:
                self.rollback()
            except StepFailed as rollback_failure:
                _log.error("rollback failed at %s; the server may be down", rollback_failure.step)
                self.write_status("failed", failure.step, f"{failure}; rollback: {rollback_failure}")
                return "failed"
            self.write_status("rolled_back", failure.step, str(failure))
            return "rolled_back"
        self.write_status("ok")
        _log.info("updated %s -> %s", self.from_version, self.to_version)
        return "ok"

    def rollback(self) -> None:
        if self.migrated and self.from_revision:
            # The downgrade scripts are the staged (new) ones, still on disk.
            self.run([self.uv, "run", "--no-sync", "alembic", "downgrade", self.from_revision], "rollback-migrate")
        self.run([self.git, "reset", "--hard", self.from_sha], "rollback-reset")
        self.run(self.sync_cmd(), "rollback-sync")
        since = self.touch_reload()
        self.wait_healthy(self.from_version, since, "rollback-verify")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="self_update", description="One-click server update helper.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--uv", required=True)
    parser.add_argument("--git", required=True)
    parser.add_argument("--from-sha", required=True)
    parser.add_argument("--to-sha", required=True)
    parser.add_argument("--from-version", required=True)
    parser.add_argument("--to-version", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--no-dev", action="store_true")
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--health-timeout", type=float, default=HEALTH_TIMEOUT_SECONDS)
    return parser.parse_args(argv)


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
