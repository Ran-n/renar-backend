#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/21 18:57:47.874960
Revised: 2026/11/22 01:52:31.715847

Pull prod's nightly backups onto this PC: ``uv run backup-pull``.

The prod VPS dumps its database every night (``scripts/backup/renar-backup``,
run by ``renar-backup.timer``) into ``/var/backups/renar``. This command,
run daily by a scheduled task on the build PC, copies over SSH every dump it
doesn't have yet (checked against the BLAKE3 ``.b3`` written next to it) and
mirrors the uploaded images (``/opt/renar-backend/media``), so a lost VPS
loses at most a day. Images deleted on prod are moved to
``media-deleted/<date>/`` here and kept as long as the dumps, so a dump
restored from that window still finds its files.

The SSH host is an alias from ``~/.ssh/config`` (``--host``, default
``$RENAR_BACKUP_HOST`` or ``renar-prod``), so no address lives in the repo.
Any failure is logged and exits non-zero; nothing is retried silently.
"""

import argparse
import datetime as dt
import logging
import os
import re
import shutil
import tarfile
from pathlib import Path, PurePosixPath

import blake3

from .backup_remote import DUMP_NAME, REMOTE_DUMP_DIR, BackupError, Remote, RemoteFile, SshRemote

_log = logging.getLogger(__name__)

DEFAULT_HOST = "renar-prod"
DEFAULT_DEST = Path.home() / "backups" / "renar-prod"
KEEP_DAYS = 14


def blake3_of(path: Path) -> str:
    digest = blake3.blake3()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pull_dump(remote: Remote, name: str, dumps: Path) -> None:
    """Copy one dump, refuse it unless its BLAKE3 matches prod's ``.b3``."""
    expected = remote.read_text(f"{REMOTE_DUMP_DIR}/{name}.b3").split()[0]
    part = dumps / f"{name}.part"
    remote.copy(f"{REMOTE_DUMP_DIR}/{name}", part)
    actual = blake3_of(part)
    if actual != expected:
        part.unlink()
        raise BackupError(f"{name}: BLAKE3 {actual} doesn't match prod's {expected}")
    part.replace(dumps / name)
    (dumps / f"{name}.b3").write_text(f"{expected}  {name}\n", encoding="utf-8")


def pull_dumps(remote: Remote, dumps: Path) -> list[str]:
    """Every dump on prod that isn't here yet; returns their names."""
    dumps.mkdir(parents=True, exist_ok=True)
    new = [n for n in sorted(remote.list_dumps()) if not (dumps / n).exists()]
    for name in new:
        pull_dump(remote, name, dumps)
        _log.info("pulled %s", name)
    return new


def local_media(media: Path, prefix: str = "") -> dict[str, RemoteFile]:
    """Every file under ``media`` by relative path. ``os.scandir`` because on
    Windows its entries carry size and mtime from the directory listing:
    ``Path.rglob`` + ``stat()`` costs two more disk calls per file, minutes
    for a few thousand images on a slow disk."""
    files = {}
    with os.scandir(media) as entries:
        for entry in entries:
            rel = f"{prefix}{entry.name}"
            if entry.is_dir(follow_symlinks=False):
                files.update(local_media(Path(entry.path), f"{rel}/"))
            elif entry.is_file(follow_symlinks=False):
                stat = entry.stat(follow_symlinks=False)
                files[rel] = RemoteFile(rel, stat.st_size, int(stat.st_mtime))
    return files


def set_aside(media: Path, deleted: Path, rel: str) -> None:
    target = deleted / PurePosixPath(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(media / PurePosixPath(rel), target)


def sync_media(remote: Remote, media: Path, deleted: Path) -> tuple[int, int]:
    """Mirror prod's images; returns (fetched, set aside)."""
    media.mkdir(parents=True, exist_ok=True)
    wanted = {f.path: f for f in remote.list_media()}
    have = local_media(media)
    changed = [p for p, f in wanted.items() if have.get(p) != f]
    gone = [p for p in have if p not in wanted]
    if changed:
        remote.fetch_media(changed, media)
    for rel in gone:
        set_aside(media, deleted, rel)
    return len(changed), len(gone)


def _date_of(path: Path) -> dt.date | None:
    match = DUMP_NAME.match(path.name) or re.match(r"^(\d{4}-\d{2}-\d{2})$", path.name)
    return dt.date.fromisoformat(match.group(1)) if match else None


def prune(dumps: Path, deleted_root: Path, today: dt.date, keep_days: int = KEEP_DAYS) -> int:
    """Delete dumps and set-aside images older than ``keep_days``; returns how many entries went."""
    cutoff = today - dt.timedelta(days=keep_days)
    removed = 0
    for path in [*dumps.glob("renar-*.dump"), *(deleted_root.iterdir() if deleted_root.exists() else [])]:
        day = _date_of(path)
        if day is None or day > cutoff:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
            path.with_name(f"{path.name}.b3").unlink(missing_ok=True)
        removed += 1
    return removed


def pull(remote: Remote, dest: Path, today: dt.date) -> None:
    new = pull_dumps(remote, dest / "dumps")
    fetched, set_aside_count = sync_media(remote, dest / "media", dest / "media-deleted" / today.isoformat())
    pruned = prune(dest / "dumps", dest / "media-deleted", today)
    _log.info(
        "backup-pull done: %d new dump(s), %d image(s) fetched, %d set aside, %d old entr(ies) pruned",
        len(new),
        fetched,
        set_aside_count,
        pruned,
    )


def _configure_logging(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(dest / "backup-pull.log", encoding="utf-8")],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backup-pull", description="Pull prod's nightly backups onto this PC.")
    parser.add_argument("--host", default=os.environ.get("RENAR_BACKUP_HOST", DEFAULT_HOST))
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    _configure_logging(args.dest)
    try:
        pull(SshRemote(args.host), args.dest, dt.date.today())
    except (BackupError, OSError, tarfile.TarError) as exc:
        _log.error("backup-pull failed: %s", exc)
        return 1
    return 0


def run() -> None:
    raise SystemExit(main())
