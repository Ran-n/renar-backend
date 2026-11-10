#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.741322
Revised: 2026/11/09 23:36:44.645983

Throwaway git repo pairs for the self-update tests: a bare ``origin`` and a
clone laid out like this project (pyproject.toml, uv.lock, alembic/,
src/renar_backend/), so git behaves for real instead of being mocked. Also
a fake ``uv`` executable and a fake reloading server for the helper.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

GIT = shutil.which("git")


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout.strip()


def _configure(repo: Path) -> None:
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "commit.gpgsign", "false")


def write_project(repo: Path, version: str) -> None:
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "renar-backend"\nversion = "{version}"\n', encoding="utf-8"
    )
    (repo / "uv.lock").write_text(f"# lock for {version}\n", encoding="utf-8")
    (repo / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (repo / "alembic").mkdir(exist_ok=True)
    (repo / "alembic" / "env.py").write_text("# env\n", encoding="utf-8")
    pkg = repo / "src" / "renar_backend"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (repo / ".gitignore").write_text("/logs/\n", encoding="utf-8")


def make_pair(tmp_path: Path) -> tuple[Path, Path]:
    """(origin, clone) with one commit at 0.1.0 on master."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(origin), str(clone))
    _configure(clone)
    git(clone, "checkout", "-B", "master")
    write_project(clone, "0.1.0")
    git(clone, "add", ".")
    git(clone, "commit", "-m", "initial")
    git(clone, "push", "origin", "master")
    (clone / "logs").mkdir()
    return origin, clone


def push_update(tmp_path: Path, origin: Path, version: str, subjects: list[str]) -> str:
    """Commit ``subjects`` (one each) from a second clone, bumping to
    ``version`` in the last one; returns the new origin/master sha."""
    other = tmp_path / f"other-{version}"
    if not other.exists():
        git(tmp_path, "clone", str(origin), str(other))
        _configure(other)
    git(other, "pull", "origin", "master")
    for i, subject in enumerate(subjects):
        (other / "src" / "renar_backend" / f"mod_{version.replace('.', '_')}_{i}.py").write_text(
            "X = 1\n", encoding="utf-8"
        )
        (other / "alembic" / f"rev_{i}.py").write_text("# migration\n", encoding="utf-8")
        if i == len(subjects) - 1:
            write_project(other, version)
        git(other, "add", ".")
        git(other, "commit", "-m", subject)
    git(other, "push", "origin", "master")
    return git(other, "rev-parse", "HEAD")


def write_be_pid(clone: Path, *, port: int = 8000, scheme: str = "http", dev_deps: bool = True) -> None:
    (clone / "logs" / "be.pid").write_text(
        json.dumps({"pid": os.getpid(), "port": port, "scheme": scheme, "reload": True, "dev_deps": dev_deps}),
        encoding="utf-8",
    )


_FAKE_UV = r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
record = Path(os.environ["FAKE_UV_RECORD"])
with record.open("a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
print("FAKE-UV " + " ".join(args))
fail = set(filter(None, os.environ.get("FAKE_UV_FAIL", "").split(",")))
if args[:1] == ["sync"] and "sync" in fail:
    print("sync exploded", file=sys.stderr); sys.exit(3)
if args[-2:] == ["upgrade", "head"] and "migrate" in fail:
    print("migration exploded", file=sys.stderr); sys.exit(4)
if "downgrade" in args and "downgrade" in fail:
    sys.exit(5)
if args[-1:] == ["current"]:
    print("abc123def456 (head)")
"""


def make_fake_uv(tmp_path: Path) -> Path:
    script = tmp_path / "fakeuv.py"
    script.write_text(_FAKE_UV, encoding="utf-8")
    if os.name == "nt":
        launcher = tmp_path / "fakeuv.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = tmp_path / "fakeuv"
        launcher.write_text(f"#!{sys.executable}\n" + _FAKE_UV, encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def uv_calls(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "uv-calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class FakeReloadingServer:
    """Stands in for ``uv run be``: GET / answers with the version in the
    clone's pyproject.toml, and each answer refreshes logs/be-worker.json as
    if a worker had started when src/renar_backend/__init__.py was last
    touched (what the real reloader reacts to). ``frozen_version`` makes it
    keep reporting one version (a new worker that never comes up)."""

    def __init__(self, clone: Path, frozen_version: str | None = None):
        self.clone = clone
        self.frozen_version = frozen_version
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 -- http.server API
                init = outer.clone / "src" / "renar_backend" / "__init__.py"
                (outer.clone / "logs" / "be-worker.json").write_text(
                    json.dumps({"pid": 1, "started_at": init.stat().st_mtime + 0.001}), encoding="utf-8"
                )
                text = (outer.clone / "pyproject.toml").read_text(encoding="utf-8")
                version = outer.frozen_version or text.split('version = "')[1].split('"')[0]
                body = json.dumps({"status": "ok", "version": version}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
