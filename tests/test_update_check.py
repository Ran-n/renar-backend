#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:19.074462
Revised: 2026/11/09 23:36:45.799981

update_check: every state the Server Update page can show, on a real git
repo pair (bare origin + clone), plus the lock, the server/worker markers,
the last-result file and how launch() starts the helper.
"""

import json
import os
import subprocess
import sys
import time

import pytest
from _git_fixture import git, make_pair, push_update, write_be_pid

from renar_backend import self_update, update_check


@pytest.fixture
def pair(tmp_path, monkeypatch):
    origin, clone = make_pair(tmp_path)
    write_be_pid(clone)
    monkeypatch.setattr(update_check, "REPO", clone)
    return tmp_path, origin, clone


def test_up_to_date(pair):
    _, _, clone = pair
    st = update_check.check()
    assert st.blocked_reason is None
    assert st.behind_count == 0 and st.behind == []
    assert not st.available
    assert st.branch == "master"
    assert st.head_sha == git(clone, "rev-parse", "HEAD")


def test_behind_lists_commits_and_remote_version(pair):
    tmp, origin, _ = pair
    to_sha = push_update(tmp, origin, "0.2.0", ["first change", "second change", "bump"])
    st = update_check.check()
    assert st.available
    assert st.behind_count == 3
    assert [c.split(" ", 1)[1] for c in st.behind] == ["bump", "second change", "first change"]
    assert st.remote_version == "0.2.0"
    assert st.remote_sha == to_sha


def test_behind_list_capped(pair, monkeypatch):
    tmp, origin, _ = pair
    monkeypatch.setattr(update_check, "MAX_LISTED_COMMITS", 2)
    push_update(tmp, origin, "0.2.0", ["a", "b", "c"])
    st = update_check.check()
    assert st.behind_count == 3
    assert len(st.behind) == 2


def test_dirty_tree_blocks_with_paths(pair):
    tmp, origin, clone = pair
    push_update(tmp, origin, "0.2.0", ["x"])
    (clone / "src" / "renar_backend" / "wip.py").write_text("# wip\n", encoding="utf-8")
    (clone / "uv.lock").write_text("edited\n", encoding="utf-8")
    st = update_check.check()
    assert "uncommitted changes" in st.blocked_reason
    assert sorted(st.dirty_paths) == ["src/renar_backend/wip.py", "uv.lock"]
    assert not st.available


def test_ignored_files_do_not_block(pair):
    _, _, clone = pair
    (clone / "logs" / "renar-backend.log").write_text("log\n", encoding="utf-8")
    assert update_check.check().blocked_reason is None


def test_wrong_branch_blocks(pair):
    _, _, clone = pair
    git(clone, "checkout", "-b", "feature")
    st = update_check.check()
    assert st.blocked_reason == "Checked out on feature; switch to master to update."


def test_local_commits_block(pair):
    tmp, origin, clone = pair
    push_update(tmp, origin, "0.2.0", ["remote"])
    (clone / "local.txt").write_text("x\n", encoding="utf-8")
    git(clone, "add", "local.txt")
    git(clone, "commit", "-m", "local only")
    st = update_check.check()
    assert st.blocked_reason == "Local commits not pushed; an update would need a merge."


def test_fetch_failure_blocks_not_up_to_date(pair):
    tmp, origin, clone = pair
    git(clone, "remote", "set-url", "origin", str(tmp / "gone.git"))
    st = update_check.check()
    assert st.blocked_reason.startswith("Couldn't check for updates:")
    assert st.retryable
    assert not st.available


def test_lock_blocks_second_update(pair):
    assert update_check.take_lock()
    assert not update_check.take_lock()
    assert update_check.check().blocked_reason == "An update is already in progress."
    update_check.release_lock()
    assert update_check.take_lock()


def test_stale_lock_is_replaced(pair, caplog):
    _, _, clone = pair
    lock = clone / "logs" / self_update.LOCK_FILE
    lock.write_text("{}", encoding="utf-8")
    old = time.time() - update_check.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    assert update_check.take_lock()
    assert "removing stale self-update lock" in caplog.text


def test_missing_server_pid_blocks(pair):
    _, _, clone = pair
    (clone / "logs" / "be.pid").unlink()
    assert "wasn't started with `uv run be`" in update_check.check().blocked_reason


def test_not_a_git_checkout_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    assert update_check.check().blocked_reason.startswith("Not a git checkout")


def test_server_pid_written_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    path = update_check.write_server_pid(8443, "https")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record == {"pid": os.getpid(), "port": 8443, "scheme": "https", "reload": True, "dev_deps": True}
    update_check.remove_server_pid()
    assert not path.exists()


def test_worker_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    before = time.time()
    update_check.write_worker_marker()
    record = json.loads((tmp_path / "logs" / self_update.WORKER_MARKER).read_text(encoding="utf-8"))
    assert record["pid"] == os.getpid() and record["started_at"] >= before


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, None),
        ('{"status": "ok", "from_version": "0.1.0", "to_version": "0.2.0", "log_path": "x.log"}', "ok"),
        ('{"status": "rolled_back", "failed_step": "migrate"}', "rolled_back"),
        ("{not json", "corrupt"),
        ('{"no_status": 1}', "corrupt"),
    ],
)
def test_last_result(tmp_path, monkeypatch, content, expected):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    if content is not None:
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / self_update.STATUS_FILE).write_text(content, encoding="utf-8")
    result = update_check.last_result()
    assert (result.status if result else None) == expected


@pytest.mark.parametrize("dev_deps", [True, False])
def test_launch_starts_isolated_detached_helper(pair, monkeypatch, dev_deps):
    tmp, origin, clone = pair
    write_be_pid(clone, port=8123, scheme="https", dev_deps=dev_deps)
    push_update(tmp, origin, "0.2.0", ["x"])
    st = update_check.check()
    started = {}

    def fake_popen(cmd, **kwargs):
        started["cmd"], started["kwargs"] = cmd, kwargs

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("UV", "/opt/uv")
    log_path = update_check.launch(st, "0.1.0")
    cmd, kwargs = started["cmd"], started["kwargs"]
    assert cmd[0] == getattr(sys, "_base_executable", sys.executable)
    assert cmd[1] == "-I"
    assert cmd[2] == self_update.__file__
    args = dict(zip(cmd[3::2], cmd[4::2], strict=False))
    assert args["--uv"] == "/opt/uv"
    assert args["--from-sha"] == st.head_sha and args["--to-sha"] == st.remote_sha
    assert args["--to-version"] == "0.2.0" and args["--from-version"] == "0.1.0"
    assert args["--base-url"] == "https://127.0.0.1:8123"
    assert args["--log-path"] == str(log_path)
    assert ("--no-dev" in cmd) is (not dev_deps)
    if os.name == "nt":
        assert kwargs["creationflags"] & subprocess.DETACHED_PROCESS
        assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_launch_without_uv_raises(pair, monkeypatch):
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(update_check.shutil, "which", lambda name: None if name == "uv" else "git")
    with pytest.raises(RuntimeError, match="uv not found"):
        update_check.launch(update_check.UpdateStatus(head_sha="a", remote_sha="b"), "0.1.0")
