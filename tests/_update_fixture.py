#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/10 13:40:09.511339
Revised: 2026/11/10 13:53:25.492745

Throwaway projects for the self-update tests, laid out like this one
(pyproject.toml, uv.lock, alembic/, src/renar_backend/), for both sources:
a bare ``origin`` + clone pair for git mode, and for tarball mode a
``renar_backend-<version>.tar.gz`` built like the release sdist with its
``.b3`` sum and a fake release feed served through httpx's MockTransport.
Also a fake ``uv`` executable and a fake reloading server for the helper.
git and files work for real; only the network and uv are faked.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import blake3
import httpx

FEED_URL = "https://forge.test/api/repos/renar-backend/releases/latest"


def write_project(root: Path, version: str, *, modules: tuple[str, ...] = ()) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "renar-backend"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text(f"# lock for {version}\n", encoding="utf-8")
    (root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (root / "alembic").mkdir(exist_ok=True)
    (root / "alembic" / "env.py").write_text(f"# env {version}\n", encoding="utf-8")
    pkg = root / "src" / "renar_backend"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for name in modules:
        (pkg / f"{name}.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")


def make_project(tmp_path: Path, version: str = "0.1.0") -> Path:
    """An installed server at ``version``, with the runtime files a release never ships."""
    project = tmp_path / "server"
    write_project(project, version, modules=("old_only",))
    (project / "logs").mkdir()
    (project / "media").mkdir()
    (project / "media" / "poster.jpg").write_bytes(b"jpg")
    (project / ".env").write_text("SECRET=1\n", encoding="utf-8")
    return project


def build_tarball(tmp_path: Path, version: str, *, extra: dict[str, bytes] | None = None) -> bytes:
    """``renar_backend-<version>.tar.gz`` as ``uv build --sdist`` lays it out."""
    tree = tmp_path / f"build-{version}"
    write_project(tree, version, modules=("new_feature",))
    (tree / "alembic" / "versions").mkdir(exist_ok=True)
    (tree / "alembic" / "versions" / "rev_new.py").write_text("# migration\n", encoding="utf-8")
    (tree / "PKG-INFO").write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(tree, arcname=f"renar_backend-{version}")
        for name, data in (extra or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def b3_line(data: bytes, name: str) -> str:
    return f"{blake3.blake3(data).hexdigest()}  {name}\n"


class FakeForge:
    """The release feed and its asset downloads (the tarball via a redirect,
    like GitHub's CDN). Edit the attributes to break things."""

    def __init__(self, tmp_path: Path, version: str = "0.2.0"):
        self.version = version
        self.tarball = build_tarball(tmp_path, version)
        self.checksum = b3_line(self.tarball, f"renar_backend-{version}.tar.gz")
        self.feed_status = 200
        self.feed: dict | None = None  # None: the default feed for self.version
        self.requests: list[str] = []

    def release(self) -> dict:
        name = f"renar_backend-{self.version}.tar.gz"
        return {
            "tag_name": f"v{self.version}",
            "html_url": f"https://forge.test/renar-backend/releases/v{self.version}",
            "body": "### Added\n- <b>shiny</b> feature",
            "assets": [
                {"name": name, "browser_download_url": f"https://forge.test/dl/{name}"},
                {"name": f"{name}.b3", "browser_download_url": f"https://forge.test/dl/{name}.b3"},
                {"name": f"renar_backend-{self.version}-py3-none-any.whl", "browser_download_url": "https://x/w"},
            ],
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url == FEED_URL:
            if self.feed_status != 200:
                return httpx.Response(self.feed_status, text="nope")
            return httpx.Response(200, json=self.feed if self.feed is not None else self.release())
        if url.endswith(".tar.gz"):
            return httpx.Response(302, headers={"Location": "https://cdn.forge.test/blob"})
        if url == "https://cdn.forge.test/blob":
            return httpx.Response(200, content=self.tarball)
        if url.endswith(".tar.gz.b3"):
            return httpx.Response(200, text=self.checksum)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=True)


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


def make_pair(tmp_path: Path) -> tuple[Path, Path]:
    """(origin, clone) with one commit at 0.1.0 on master."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(origin), str(clone))
    _configure(clone)
    git(clone, "checkout", "-B", "master")
    write_project(clone, "0.1.0")
    (clone / ".gitignore").write_text("/logs/\n/.self-update/\n", encoding="utf-8")
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


def write_be_pid(project: Path, *, port: int = 8000, scheme: str = "http", dev_deps: bool = True) -> None:
    (project / "logs" / "be.pid").write_text(
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
once = record.with_suffix(".sync-failed")
if args[:1] == ["sync"] and "sync-once" in fail and not once.exists():
    once.write_text("1"); print("sync exploded", file=sys.stderr); sys.exit(3)
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
    project's pyproject.toml, and each answer refreshes logs/be-worker.json as
    if a worker had started when src/renar_backend/__init__.py was last
    touched (what the real reloader reacts to). ``frozen_version`` makes it
    keep reporting one version (a new worker that never comes up)."""

    def __init__(self, project: Path, frozen_version: str | None = None):
        self.project = project
        self.frozen_version = frozen_version
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 -- http.server API
                init = outer.project / "src" / "renar_backend" / "__init__.py"
                (outer.project / "logs" / "be-worker.json").write_text(
                    json.dumps({"pid": 1, "started_at": init.stat().st_mtime + 0.001}), encoding="utf-8"
                )
                text = (outer.project / "pyproject.toml").read_text(encoding="utf-8")
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
