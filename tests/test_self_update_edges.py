#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:11.786086
Revised: 2026/11/13 15:35:11.786086

self_update.py's failure handling, piece by piece on throwaway trees: file
moves and restores that fail half way, a release adding a file the old one
didn't have, steps whose command can't even start, a lost lock file, an
unwritable reload marker, health probes that never see the new worker, and
a crash outside any step still ending in a status file.
"""

import json
import logging
import os
import shutil
import subprocess
import urllib.error
from pathlib import Path

import pytest

from renar_backend import self_update
from renar_backend.self_update import GitSource, StepFailed, TarballSource, Updater


def _release(stage: Path) -> Path:
    pkg = stage / self_update.CODE_DIR / "renar_backend"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    return stage


def _tarball(tmp_path: Path) -> TarballSource:
    repo = tmp_path / "repo"
    repo.mkdir()
    return TarballSource(repo, _release(tmp_path / "stage"))


def _deny(monkeypatch, name: str, fail_on):
    real = getattr(shutil if name == "rmtree" else os, name)

    def _maybe(*args, **kwargs):
        if fail_on(*args):
            raise PermissionError(13, "Access is denied")
        return real(*args, **kwargs)

    monkeypatch.setattr(shutil if name == "rmtree" else os, name, _maybe)


# ---------------------------------------------------------------------------
# _remove / GitSource
# ---------------------------------------------------------------------------


def test_remove_ignores_a_path_that_is_already_gone(tmp_path):
    self_update._remove(tmp_path / "never-existed")


def test_git_stage_with_nothing_to_check_out(tmp_path):
    calls = []

    def _run(cmd, step):
        calls.append(cmd)
        return "\n"  # ls-tree listed none of the staged paths

    GitSource(tmp_path, _run, "git", "a" * 40, "b" * 40).stage()

    assert len(calls) == 1 and calls[0][1] == "ls-tree"


# ---------------------------------------------------------------------------
# TarballSource
# ---------------------------------------------------------------------------


def test_begin_fails_when_the_old_backup_cannot_be_cleared(tmp_path, monkeypatch):
    source = _tarball(tmp_path)
    source.previous.mkdir(parents=True)
    _deny(monkeypatch, "rmtree", lambda path, *a: Path(path) == source.previous)

    with pytest.raises(StepFailed) as exc:
        source.begin()

    assert exc.value.step == "begin"
    assert "can't reset" in exc.value.detail


def test_a_file_new_in_this_release_is_installed_then_removed_on_rollback(tmp_path):
    source = _tarball(tmp_path)
    (source.stage_dir / "NEW_FILE.txt").write_text("new", encoding="utf-8")
    source.begin()

    source.move_in("NEW_FILE.txt", "stage")
    assert (source.repo / "NEW_FILE.txt").read_text(encoding="utf-8") == "new"
    assert source.moved == [("NEW_FILE.txt", False)]

    source.restore()
    assert not (source.repo / "NEW_FILE.txt").exists()
    assert source.moved == []


def test_move_in_failure_is_a_failed_step(tmp_path, monkeypatch, caplog):
    source = _tarball(tmp_path)
    (source.stage_dir / "uv.lock").write_text("lock", encoding="utf-8")
    source.begin()
    _deny(monkeypatch, "replace", lambda src, dst: Path(dst) == source.repo / "uv.lock")

    with pytest.raises(StepFailed) as exc:
        source.move_in("uv.lock", "stage")

    assert exc.value.step == "stage"
    assert "could not move uv.lock into place" in caplog.text


def test_restore_failure_is_a_failed_rollback(tmp_path, monkeypatch, caplog):
    source = _tarball(tmp_path)
    (source.repo / "uv.lock").write_text("old", encoding="utf-8")
    (source.stage_dir / "uv.lock").write_text("new", encoding="utf-8")
    source.begin()
    source.move_in("uv.lock", "stage")
    _deny(monkeypatch, "replace", lambda src, dst: Path(src) == source.previous / "uv.lock")

    with pytest.raises(StepFailed) as exc:
        source.restore()

    assert exc.value.step == "rollback-restore"
    assert "could not restore uv.lock" in caplog.text


def test_finish_logs_when_the_stage_cannot_be_removed(tmp_path, monkeypatch, caplog):
    source = _tarball(tmp_path)
    _deny(monkeypatch, "rmtree", lambda path, *a: Path(path) == source.stage_dir)

    source.finish()

    assert "could not remove" in caplog.text
    assert source.stage_dir.exists()


# ---------------------------------------------------------------------------
# Updater plumbing
# ---------------------------------------------------------------------------


@pytest.fixture
def updater(tmp_path) -> Updater:
    repo = tmp_path / "repo"
    (repo / "logs").mkdir(parents=True)
    (repo / self_update.CODE_DIR / "renar_backend").mkdir(parents=True)
    (repo / self_update.CODE_DIR / "renar_backend" / "__init__.py").write_text("", encoding="utf-8")
    stage = _release(tmp_path / "stage")
    args = self_update.parse_args([
        "--repo", str(repo), "--uv", "uv", "--mode", "tarball", "--stage", str(stage),
        "--from-version", "0.1.0", "--to-version", "0.2.0",
        "--base-url", "http://127.0.0.1:1", "--log-path", str(repo / "logs" / "u.log"),
        "--health-timeout", "0.5",
    ])  # fmt: skip
    return Updater(args, repo / "logs" / "u.log")


@pytest.mark.parametrize("error", [FileNotFoundError("uv"), subprocess.TimeoutExpired("uv", 600)])
def test_a_command_that_cannot_run_is_a_failed_step(updater, monkeypatch, error):
    def _boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(self_update.subprocess, "run", _boom)

    with pytest.raises(StepFailed) as exc:
        updater.run(["uv", "sync"], "sync")

    assert exc.value.step == "sync"


def test_release_lock_tolerates_a_missing_lock(updater, caplog):
    with caplog.at_level(logging.WARNING, logger=self_update.__name__):
        updater.release_lock()

    assert "lock file already gone" in caplog.text


def test_touch_reload_failure_is_a_failed_step(updater, monkeypatch):
    def _denied(path, times):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(self_update.os, "utime", _denied)

    with pytest.raises(StepFailed) as exc:
        updater.touch_reload("swap")

    assert exc.value.step == "swap"


def test_current_revision_none_on_an_unstamped_database(updater, monkeypatch):
    monkeypatch.setattr(updater, "run", lambda cmd, step: "INFO  [alembic.runtime] Context impl.\n")

    assert updater.current_revision() is None


def test_wait_healthy_reports_an_unreachable_server(updater, monkeypatch):
    def _refused(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(self_update.urllib.request, "urlopen", _refused)
    monkeypatch.setattr(self_update.time, "sleep", lambda s: None)

    with pytest.raises(StepFailed) as exc:
        updater.wait_healthy("0.2.0", 0.0, "verify")

    assert exc.value.detail.startswith("GET / failed")


class _Response:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_wait_healthy_ignores_the_old_worker_answering(updater, monkeypatch):
    monkeypatch.setattr(self_update.urllib.request, "urlopen", lambda *a, **kw: _Response({"version": "0.2.0"}))
    monkeypatch.setattr(self_update.time, "sleep", lambda s: None)
    # no worker marker written: nothing has restarted since the swap

    with pytest.raises(StepFailed) as exc:
        updater.wait_healthy("0.2.0", 0.0, "verify")

    assert exc.value.detail == "no new worker started"


@pytest.mark.parametrize("content", ["not json", '{"other": 1}', '{"started_at": null}'])
def test_unreadable_worker_marker_counts_as_no_new_worker(updater, content):
    (updater.logs / self_update.WORKER_MARKER).write_text(content, encoding="utf-8")

    assert updater._worker_started_at() is None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_records_a_crash_outside_any_step(updater, monkeypatch):
    (updater.logs / self_update.LOCK_FILE).write_text("{}", encoding="utf-8")

    def _crash(self):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(Updater, "update", _crash)
    argv = [
        "--repo", str(updater.repo), "--uv", "uv", "--mode", "tarball", "--stage", str(updater.source.stage_dir),
        "--from-version", "0.1.0", "--to-version", "0.2.0", "--base-url", "http://127.0.0.1:1",
        "--log-path", str(updater.log_path),
    ]  # fmt: skip
    handlers_before = list(self_update._log.handlers)

    assert self_update.main(argv) == 1

    record = json.loads((updater.logs / self_update.STATUS_FILE).read_text(encoding="utf-8"))
    assert (record["status"], record["failed_step"]) == ("failed", "helper")
    assert "RuntimeError('unexpected')" in record["error"]
    assert not (updater.logs / self_update.LOCK_FILE).exists()
    assert "self-update crashed" in updater.log_path.read_text(encoding="utf-8")
    assert self_update._log.handlers == handlers_before  # its log handler is detached again
