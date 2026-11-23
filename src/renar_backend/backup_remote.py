#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/21 18:57:56.162516
Revised: 2026/11/23 16:29:11.046664

The prod VPS as seen by ``backup-pull``: what it offers (``Remote``) and the
real thing reached with the system ``ssh``/``scp`` (``SshRemote``). Kept apart
from the pull logic so tests drive that logic with a local fake.
"""

import re
import subprocess  # nosec B404 -- argv lists only, never a local shell
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REMOTE_DUMP_DIR = "/var/backups/renar"
REMOTE_MEDIA_DIR = "/opt/renar-backend/media"
DUMP_NAME = re.compile(r"^renar-(\d{4}-\d{2}-\d{2})\.dump$")
_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]


class BackupError(RuntimeError):
    """A step of the pull failed; the message says which and why."""


@dataclass(frozen=True)
class RemoteFile:
    path: str  # relative, POSIX separators
    size: int
    mtime: int  # whole seconds


class Remote(Protocol):
    def list_dumps(self) -> list[str]: ...
    def read_text(self, path: str) -> str: ...
    def copy(self, path: str, local: Path) -> None: ...
    def list_media(self) -> list[RemoteFile]: ...
    def fetch_media(self, paths: list[str], dest: Path) -> None: ...


class SshRemote:
    """The prod VPS, reached with the system ``ssh``/``scp`` and the user's key."""

    def __init__(self, host: str):
        self.host = host

    def _ssh(self, command: str) -> str:
        done = subprocess.run(  # nosec B603 B607 -- argv list, no shell; the system's own ssh
            ["ssh", *_SSH_OPTS, self.host, command], capture_output=True, text=True, encoding="utf-8", check=False
        )
        if done.returncode != 0:
            raise BackupError(f"ssh {self.host} {command!r} failed ({done.returncode}): {done.stderr.strip()}")
        return done.stdout

    def list_dumps(self) -> list[str]:
        return [n for n in self._ssh(f"ls -1 {REMOTE_DUMP_DIR}").split() if DUMP_NAME.match(n)]

    def read_text(self, path: str) -> str:
        return self._ssh(f"cat {path}")

    def copy(self, path: str, local: Path) -> None:
        done = subprocess.run(  # nosec B603 B607 -- argv list, no shell; the system's own ssh
            ["scp", "-q", *_SSH_OPTS, f"{self.host}:{path}", str(local)], capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise BackupError(f"scp {path} failed ({done.returncode}): {done.stderr.strip()}")

    def list_media(self) -> list[RemoteFile]:
        out = self._ssh(f"cd {REMOTE_MEDIA_DIR} && find . -type f -printf '%P\\t%s\\t%T@\\n'")
        return [parse_listing_line(line) for line in out.splitlines() if line]

    def fetch_media(self, paths: list[str], dest: Path) -> None:
        """Stream the files as one tar over SSH and unpack them under ``dest``."""
        command = f"tar -C {REMOTE_MEDIA_DIR} -cf - --null -T -"
        with subprocess.Popen(  # nosec B603 B607 -- argv list, no shell; the system's own ssh
            ["ssh", *_SSH_OPTS, self.host, command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as proc:
            proc.stdin.write(b"".join(p.encode() + b"\0" for p in paths))
            proc.stdin.close()
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                archive.extractall(dest, filter="data")
            stderr = proc.stderr.read().decode(errors="replace").strip()
        if proc.returncode != 0:
            raise BackupError(f"fetching {len(paths)} image(s) failed ({proc.returncode}): {stderr}")


def parse_listing_line(line: str) -> RemoteFile:
    path, size, mtime = line.split("\t")
    return RemoteFile(path, int(size), int(float(mtime)))
