#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:11.948966
Revised: 2026/11/13 15:35:11.948966

update_check.py's failure handling: git commands that fail, time out, can't
start or aren't installed; a check without fetching; a remote pyproject the
version can't be read from; a bare-hash .b3 file; a release whose
pyproject.toml has no version; unreadable or missing pid files, an
unwritable worker marker, a lost lock race, and the POSIX launch flags.
"""

import io
import logging
import subprocess
import tarfile
from pathlib import Path

import httpx
import pytest
from _update_fixture import make_pair, push_update, write_be_pid, write_project

from renar_backend import self_update, update_check
from renar_backend.update_check import GitError, UpdateError, UpdateStatus

# ---------------------------------------------------------------------------
# status / client
# ---------------------------------------------------------------------------


def test_a_release_check_with_no_latest_version_is_not_available():
    status = UpdateStatus(mode=update_check.MODE_TARBALL, current_version="0.1.0")

    assert status.available is False


def test_http_client_follows_cdn_redirects():
    with update_check._http() as client:
        assert client.follow_redirects is True
        assert client.headers["User-Agent"] == update_check._USER_AGENT


# ---------------------------------------------------------------------------
# _git
# ---------------------------------------------------------------------------


def test_git_missing_from_path(monkeypatch):
    monkeypatch.setattr(update_check.shutil, "which", lambda name: None)

    with pytest.raises(GitError, match="not installed"):
        update_check._git(Path("."), "status")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (subprocess.TimeoutExpired("git", 30), "timed out"),
        (PermissionError(13, "Access is denied"), "could not run git"),
    ],
)
def test_git_that_cannot_finish(monkeypatch, error, message):
    def _boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(update_check.subprocess, "run", _boom)

    with pytest.raises(GitError, match=message):
        update_check._git(Path("."), "fetch", "origin")


# ---------------------------------------------------------------------------
# _check_git
# ---------------------------------------------------------------------------


@pytest.fixture
def pair(tmp_path, monkeypatch):
    origin, clone = make_pair(tmp_path)
    write_be_pid(clone)
    return tmp_path, origin, clone


def _status() -> UpdateStatus:
    return UpdateStatus(mode=update_check.MODE_GIT, current_version="0.1.0", branch=update_check.BRANCH)


def _failing_git(real, *failing: str):
    def _git(repo, *args):
        if args[0] in failing:
            raise GitError(f"git {args[0]} failed: boom")
        return real(repo, *args)

    return _git


def test_check_git_blocks_when_git_status_fails(pair, monkeypatch):
    _, _, clone = pair
    monkeypatch.setattr(update_check, "_git", _failing_git(update_check._git, "status"))
    status = _status()

    update_check._check_git(clone, status, fetch=True)

    assert status.blocked_reason == "git status failed: boom"


def test_check_git_blocks_when_the_remote_ref_cannot_be_read(pair, monkeypatch):
    _, _, clone = pair
    monkeypatch.setattr(update_check, "_git", _failing_git(update_check._git, "rev-parse"))
    status = _status()

    update_check._check_git(clone, status, fetch=False)

    assert status.blocked_reason == "git rev-parse failed: boom"


def test_check_git_without_fetch_uses_the_last_fetched_state(pair, monkeypatch):
    tmp_path, origin, clone = pair
    push_update(tmp_path, origin, "0.2.0", ["feat: new"])  # pushed, but never fetched here
    calls = []
    real = update_check._git
    monkeypatch.setattr(update_check, "_git", lambda repo, *args: calls.append(args[0]) or real(repo, *args))
    status = _status()

    update_check._check_git(clone, status, fetch=False)

    assert "fetch" not in calls
    assert status.behind_count == 0


def test_version_at_logs_an_unreadable_pyproject(pair, monkeypatch, caplog):
    _, _, clone = pair
    monkeypatch.setattr(update_check, "_git", lambda repo, *args: "this is = not [toml")

    with caplog.at_level(logging.ERROR, logger=update_check.__name__):
        assert update_check._version_at(clone, "origin/master") is None

    assert "can't read the version at origin/master" in caplog.text


# ---------------------------------------------------------------------------
# release download / unpack
# ---------------------------------------------------------------------------


def test_expected_sum_accepts_a_bare_hash_file():
    digest = "ab" * 32

    def _serve(request):
        return httpx.Response(200, text=f"{digest.upper()}\n")

    with httpx.Client(transport=httpx.MockTransport(_serve)) as client:
        assert update_check._expected_sum(client, "https://forge.test/x.b3", "x.tar.gz") == digest


def test_unpack_rejects_a_release_without_a_version(tmp_path):
    tree = tmp_path / "tree"
    write_project(tree, "0.2.0")
    (tree / "pyproject.toml").write_text('[project]\nname = "renar-backend"\n', encoding="utf-8")
    tarball = tmp_path / "renar_backend-0.2.0.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(tree, arcname="renar_backend-0.2.0")
    tarball.write_bytes(buf.getvalue())
    stage = tmp_path / "work" / self_update.STAGE_DIR
    stage.parent.mkdir()

    with pytest.raises(UpdateError, match="pyproject.toml has no version"):
        update_check._unpack(tarball, stage, "0.2.0")


# ---------------------------------------------------------------------------
# pid file / worker marker / lock
# ---------------------------------------------------------------------------


def test_remove_server_pid_tolerates_a_missing_file(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=update_check.__name__):
        update_check.remove_server_pid(tmp_path)

    assert "already removed" in caplog.text


def test_read_server_pid_logs_an_unreadable_file(tmp_path, caplog):
    logs = update_check.logs_dir(tmp_path)
    logs.mkdir()
    (logs / update_check.SERVER_PID_FILE).write_text("{not json", encoding="utf-8")

    assert update_check.read_server_pid(tmp_path) is None
    assert "unreadable" in caplog.text


def test_write_worker_marker_failure_is_logged_not_raised(tmp_path, caplog):
    (tmp_path / "logs").write_text("a file where the logs folder should be", encoding="utf-8")

    update_check.write_worker_marker(tmp_path)

    assert "could not write" in caplog.text


def test_take_lock_loses_a_race_to_another_check(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "lock_active", lambda repo: False)  # checked before the other one took it
    path = update_check._lock_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    assert update_check.take_lock(tmp_path) is False


def test_release_lock_tolerates_a_missing_lock(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=update_check.__name__):
        update_check.release_lock(tmp_path)

    assert "already released" in caplog.text


# ---------------------------------------------------------------------------
# launch flags per platform
# ---------------------------------------------------------------------------


def test_helper_detaches_with_a_new_session_on_posix():
    assert update_check._detach_kwargs(windows=False) == {"start_new_session": True}


@pytest.mark.skipif(not hasattr(subprocess, "DETACHED_PROCESS"), reason="Windows-only flags")
def test_helper_detaches_into_its_own_group_on_windows():
    flags = update_check._detach_kwargs(windows=True)["creationflags"]

    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert flags & subprocess.DETACHED_PROCESS
