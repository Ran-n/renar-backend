#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/21 18:57:56.261688
Revised: 2026/11/22 01:52:31.999033

``backup-pull``: copying prod's nightly dumps (BLAKE3-verified) and
mirroring its images onto the PC, pruning old copies, and the SSH transport's
commands and failures, against a local fake of the VPS.
"""

import datetime as dt
import io
import logging
import os
import subprocess
import tarfile
from pathlib import Path

import blake3
import pytest

from renar_backend import backup_pull, backup_remote
from renar_backend.backup_remote import BackupError, RemoteFile, SshRemote, parse_listing_line

TODAY = dt.date(2026, 11, 21)


class FakeRemote:
    """The VPS as two local folders: ``dumps/`` and ``media/``."""

    def __init__(self, root: Path):
        self.dumps = root / "dumps"
        self.media = root / "media"
        self.dumps.mkdir(parents=True)
        self.media.mkdir(parents=True)
        self.fetched: list[list[str]] = []

    def add_dump(self, name: str, data: bytes, checksum: str | None = None) -> None:
        (self.dumps / name).write_bytes(data)
        digest = checksum or blake3.blake3(data).hexdigest()
        (self.dumps / f"{name}.b3").write_text(f"{digest}  {name}\n")

    def add_image(self, rel: str, data: bytes, mtime: int = 1_700_000_000) -> None:
        path = self.media / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (mtime, mtime))

    def list_dumps(self) -> list[str]:
        return [p.name for p in self.dumps.iterdir() if p.suffix == ".dump"]

    def read_text(self, path: str) -> str:
        return (self.dumps / Path(path).name).read_text()

    def copy(self, path: str, local: Path) -> None:
        local.write_bytes((self.dumps / Path(path).name).read_bytes())

    def list_media(self) -> list[RemoteFile]:
        return list(backup_pull.local_media(self.media).values())

    def fetch_media(self, paths: list[str], dest: Path) -> None:
        self.fetched.append(sorted(paths))
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for rel in paths:
                archive.add(self.media / rel, arcname=rel)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            archive.extractall(dest, filter="data")


@pytest.fixture
def remote(tmp_path):
    return FakeRemote(tmp_path / "vps")


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "pc"


def test_pulls_only_new_dumps_and_keeps_their_checksum(remote, dest):
    remote.add_dump("renar-2026-11-20.dump", b"night 20")
    assert backup_pull.pull_dumps(remote, dest / "dumps") == ["renar-2026-11-20.dump"]
    remote.add_dump("renar-2026-11-21.dump", b"night 21")
    assert backup_pull.pull_dumps(remote, dest / "dumps") == ["renar-2026-11-21.dump"]
    assert (dest / "dumps" / "renar-2026-11-21.dump").read_bytes() == b"night 21"
    digest = (dest / "dumps" / "renar-2026-11-21.dump.b3").read_text()
    assert digest.startswith(blake3.blake3(b"night 21").hexdigest())
    assert not list((dest / "dumps").glob("*.part"))


def test_dump_with_wrong_checksum_is_refused_and_not_kept(remote, dest):
    remote.add_dump("renar-2026-11-21.dump", b"truncated", checksum="0" * 64)
    with pytest.raises(BackupError, match="doesn't match"):
        backup_pull.pull_dumps(remote, dest / "dumps")
    assert list((dest / "dumps").iterdir()) == []


def test_media_mirror_fetches_new_and_changed_files_only(remote, dest):
    remote.add_image("posters/a.webp", b"a")
    remote.add_image("avatars/b.webp", b"b")
    assert backup_pull.sync_media(remote, dest / "media", dest / "gone") == (2, 0)
    assert backup_pull.sync_media(remote, dest / "media", dest / "gone") == (0, 0)
    remote.add_image("posters/a.webp", b"a, re-uploaded", mtime=1_800_000_000)
    assert backup_pull.sync_media(remote, dest / "media", dest / "gone") == (1, 0)
    assert remote.fetched[-1] == ["posters/a.webp"]
    assert (dest / "media" / "posters" / "a.webp").read_bytes() == b"a, re-uploaded"


def test_image_deleted_on_prod_is_set_aside_not_lost(remote, dest):
    remote.add_image("avatars/b.webp", b"b")
    backup_pull.sync_media(remote, dest / "media", dest / "gone")
    (remote.media / "avatars" / "b.webp").unlink()
    assert backup_pull.sync_media(remote, dest / "media", dest / "gone") == (0, 1)
    assert not (dest / "media" / "avatars" / "b.webp").exists()
    assert (dest / "gone" / "avatars" / "b.webp").read_bytes() == b"b"


def test_prune_drops_dumps_and_set_aside_days_past_retention(dest):
    dumps, deleted = dest / "dumps", dest / "media-deleted"
    dumps.mkdir(parents=True)
    for day in ("2026-11-07", "2026-11-08", "2026-11-21"):
        (dumps / f"renar-{day}.dump").write_bytes(b"x")
        (dumps / f"renar-{day}.dump.b3").write_text("x")
        (deleted / day).mkdir(parents=True)
    (dumps / "notes.txt").write_text("not a dump")
    assert backup_pull.prune(dumps, deleted, TODAY) == 2  # 11-07: the dump and its set-aside day
    assert sorted(p.name for p in dumps.iterdir()) == [
        "notes.txt",
        "renar-2026-11-08.dump",
        "renar-2026-11-08.dump.b3",
        "renar-2026-11-21.dump",
        "renar-2026-11-21.dump.b3",
    ]
    assert sorted(p.name for p in deleted.iterdir()) == ["2026-11-08", "2026-11-21"]


def test_prune_without_set_aside_folder(dest):
    (dest / "dumps").mkdir(parents=True)
    assert backup_pull.prune(dest / "dumps", dest / "media-deleted", TODAY) == 0


def test_full_pull_lays_out_dumps_media_and_deleted(remote, dest, caplog):
    remote.add_dump("renar-2026-11-21.dump", b"db")
    remote.add_image("p/x.webp", b"x")
    with caplog.at_level(logging.INFO, logger="renar_backend.backup_pull"):
        backup_pull.pull(remote, dest, TODAY)
    assert (dest / "dumps" / "renar-2026-11-21.dump").exists()
    assert (dest / "media" / "p" / "x.webp").exists()
    assert "1 new dump(s), 1 image(s) fetched" in caplog.text


def test_main_logs_failure_and_exits_1(dest, monkeypatch, caplog):
    def broken(_self):
        raise BackupError("ssh renar-prod failed (255): host unreachable")

    monkeypatch.setattr(SshRemote, "list_dumps", broken)
    assert backup_pull.main(["--host", "renar-prod", "--dest", str(dest)]) == 1
    assert "host unreachable" in caplog.text
    assert (dest / "backup-pull.log").exists()
    logging.getLogger().handlers[-1].close()


def test_parse_listing_line():
    assert parse_listing_line("posters/a.webp\t123\t1700000000.75") == RemoteFile("posters/a.webp", 123, 1700000000)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_ssh_remote_lists_only_dump_files(monkeypatch):
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        return _completed(stdout="renar-2026-11-21.dump\nrenar-2026-11-21.dump.b3\nx.dump.part\n")

    monkeypatch.setattr(backup_remote.subprocess, "run", fake_run)
    assert SshRemote("renar-prod").list_dumps() == ["renar-2026-11-21.dump"]
    assert calls[0][0] == "ssh" and "BatchMode=yes" in calls[0] and "renar-prod" in calls[0]


def test_ssh_remote_failure_names_the_command(monkeypatch):
    monkeypatch.setattr(backup_remote.subprocess, "run", lambda *_a, **_k: _completed(255, stderr="refused"))
    with pytest.raises(BackupError, match="refused"):
        SshRemote("renar-prod").read_text("/var/backups/renar/x.b3")
    with pytest.raises(BackupError, match="scp"):
        SshRemote("renar-prod").copy("/var/backups/renar/x.dump", Path("x"))


def test_ssh_remote_media_listing_parses_find_output(monkeypatch):
    out = "a/b.webp\t5\t1700000000.0\n"
    monkeypatch.setattr(backup_remote.subprocess, "run", lambda *_a, **_k: _completed(stdout=out))
    assert SshRemote("h").list_media() == [RemoteFile("a/b.webp", 5, 1700000000)]


def test_ssh_remote_copy_succeeds_quietly(monkeypatch):
    calls = []
    monkeypatch.setattr(backup_remote.subprocess, "run", lambda cmd, **_k: calls.append(cmd) or _completed())
    SshRemote("h").copy("/var/backups/renar/x.dump", Path("local.part"))
    assert calls[0][0] == "scp" and calls[0][-2:] == ["h:/var/backups/renar/x.dump", "local.part"]


class FakePopen:
    """``ssh … tar -cf -``: hands back a tar of ``files`` and the exit code."""

    def __init__(self, files: dict[str, bytes], returncode: int = 0, stderr: bytes = b""):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        self.stdout = io.BytesIO(buffer.getvalue())
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.cmd = None

    def __call__(self, cmd, **_kw):
        self.cmd = cmd
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_ssh_remote_fetch_media_unpacks_the_tar_stream(monkeypatch, tmp_path):
    popen = FakePopen({"p/x.webp": b"x"})
    monkeypatch.setattr(backup_remote.subprocess, "Popen", popen)
    SshRemote("h").fetch_media(["p/x.webp"], tmp_path)
    assert (tmp_path / "p" / "x.webp").read_bytes() == b"x"
    assert popen.stdin.getvalue() == b"p/x.webp\0"
    assert "tar -C /opt/renar-backend/media" in popen.cmd[-1]


def test_ssh_remote_fetch_media_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_remote.subprocess, "Popen", FakePopen({}, returncode=2, stderr=b"tar: p/x: Cannot stat"))
    with pytest.raises(BackupError, match="Cannot stat"):
        SshRemote("h").fetch_media(["p/x"], tmp_path)


def test_main_success_and_run_exit_code(remote, dest, monkeypatch):
    monkeypatch.setattr(backup_pull, "SshRemote", lambda _host: remote)
    assert backup_pull.main(["--dest", str(dest)]) == 0
    logging.getLogger().handlers[-1].close()
    monkeypatch.setattr(backup_pull, "main", lambda: 0)
    with pytest.raises(SystemExit) as stop:
        backup_pull.run()
    assert stop.value.code == 0


def test_local_media_skips_entries_that_are_neither_file_nor_folder(tmp_path, monkeypatch):
    class Link:
        name = "link"
        path = str(tmp_path / "link")

        def is_dir(self, follow_symlinks):
            return False

        def is_file(self, follow_symlinks):
            return False

    class Listing(list):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(backup_pull.os, "scandir", lambda _path: Listing([Link()]))
    assert backup_pull.local_media(tmp_path) == {}
