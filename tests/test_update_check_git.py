#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/10 13:53:25.009536
Revised: 2026/11/10 13:53:25.009536

update_check in git mode (a project with .git): every state the Server
Update page can show on a real git repo pair (bare origin + clone), and how
launch() hands the commits to the helper. Tarball mode, the lock, the
markers and the last-result file are in test_update_check.py.
"""

import os
import subprocess
import sys

import pytest
from _update_fixture import GIT, git, make_pair, push_update, write_be_pid

from renar_backend import self_update, update_check


@pytest.fixture
def pair(tmp_path, monkeypatch):
    origin, clone = make_pair(tmp_path)
    write_be_pid(clone)
    monkeypatch.setattr(update_check, "REPO", clone)

    def no_feed():
        raise AssertionError("git mode must never read the release feed")

    monkeypatch.setattr(update_check, "_http", no_feed)
    return tmp_path, origin, clone


def test_up_to_date(pair):
    _, _, clone = pair
    st = update_check.check("0.1.0")
    assert st.mode == update_check.MODE_GIT
    assert st.blocked_reason is None
    assert st.behind_count == 0 and st.behind == []
    assert not st.available
    assert st.branch == "master"
    assert st.head_sha == git(clone, "rev-parse", "HEAD")


def test_behind_lists_commits_and_remote_version(pair):
    tmp, origin, _ = pair
    to_sha = push_update(tmp, origin, "0.2.0", ["first change", "second change", "bump"])
    st = update_check.check("0.1.0")
    assert st.available
    assert st.behind_count == 3
    assert [c.split(" ", 1)[1] for c in st.behind] == ["bump", "second change", "first change"]
    assert st.latest_version == "0.2.0"
    assert st.remote_sha == to_sha


def test_new_commits_without_a_version_bump_are_still_an_update(pair):
    tmp, origin, _ = pair
    push_update(tmp, origin, "0.1.0", ["fix only"])
    st = update_check.check("0.1.0")
    assert st.available
    assert st.latest_version == "0.1.0"


def test_behind_list_capped(pair, monkeypatch):
    tmp, origin, _ = pair
    monkeypatch.setattr(update_check, "MAX_LISTED_COMMITS", 2)
    push_update(tmp, origin, "0.2.0", ["a", "b", "c"])
    st = update_check.check("0.1.0")
    assert st.behind_count == 3
    assert len(st.behind) == 2


def test_dirty_tree_blocks_with_paths(pair):
    tmp, origin, clone = pair
    push_update(tmp, origin, "0.2.0", ["x"])
    (clone / "src" / "renar_backend" / "wip.py").write_text("# wip\n", encoding="utf-8")
    (clone / "uv.lock").write_text("edited\n", encoding="utf-8")
    st = update_check.check("0.1.0")
    assert "uncommitted changes" in st.blocked_reason
    assert sorted(st.dirty_paths) == ["src/renar_backend/wip.py", "uv.lock"]
    assert not st.available


def test_ignored_files_do_not_block(pair):
    _, _, clone = pair
    (clone / "logs" / "renar-backend.log").write_text("log\n", encoding="utf-8")
    (clone / self_update.WORK_DIR).mkdir()
    assert update_check.check("0.1.0").blocked_reason is None


def test_wrong_branch_blocks(pair):
    _, _, clone = pair
    git(clone, "checkout", "-b", "feature")
    st = update_check.check("0.1.0")
    assert st.blocked_reason == "Checked out on feature; switch to master to update."


def test_local_commits_block(pair):
    tmp, origin, clone = pair
    push_update(tmp, origin, "0.2.0", ["remote"])
    (clone / "local.txt").write_text("x\n", encoding="utf-8")
    git(clone, "add", "local.txt")
    git(clone, "commit", "-m", "local only")
    st = update_check.check("0.1.0")
    assert st.blocked_reason == "Local commits not pushed; an update would need a merge."


def test_fetch_failure_blocks_not_up_to_date(pair, caplog):
    tmp, _, clone = pair
    git(clone, "remote", "set-url", "origin", str(tmp / "gone.git"))
    st = update_check.check("0.1.0")
    assert st.blocked_reason.startswith("Couldn't check for updates:")
    assert st.retryable
    assert not st.available
    assert "git fetch failed" in caplog.text


def test_lock_blocks(pair):
    assert update_check.take_lock()
    assert update_check.check("0.1.0").blocked_reason == "An update is already in progress."


def test_missing_server_pid_blocks(pair):
    _, _, clone = pair
    (clone / "logs" / "be.pid").unlink()
    assert "wasn't started with `uv run be`" in update_check.check("0.1.0").blocked_reason


def test_prepare_has_nothing_to_stage(pair):
    tmp, origin, clone = pair
    push_update(tmp, origin, "0.2.0", ["x"])
    assert update_check.prepare(update_check.check("0.1.0")) is None
    assert not (clone / self_update.WORK_DIR).exists()


def test_prepare_refuses_when_nothing_is_newer(pair):
    with pytest.raises(update_check.UpdateError, match="Nothing newer"):
        update_check.prepare(update_check.check("0.1.0"))


@pytest.mark.parametrize("dev_deps", [True, False])
def test_launch_hands_the_commits_to_the_helper(pair, monkeypatch, dev_deps):
    tmp, origin, clone = pair
    write_be_pid(clone, port=8123, scheme="https", dev_deps=dev_deps)
    push_update(tmp, origin, "0.2.0", ["x"])
    st = update_check.check("0.1.0")
    started = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: started.update(cmd=cmd, kwargs=kw))
    monkeypatch.setenv("UV", "/opt/uv")
    log_path = update_check.launch(st, None)
    cmd, kwargs = started["cmd"], started["kwargs"]
    assert cmd[:3] == [getattr(sys, "_base_executable", sys.executable), "-I", self_update.__file__]
    args = dict(zip(cmd[3::2], cmd[4::2], strict=False))
    assert args["--mode"] == "git"
    assert os.path.samefile(args["--git"], GIT)
    assert args["--from-sha"] == st.head_sha and args["--to-sha"] == st.remote_sha
    assert "--stage" not in args
    assert args["--to-version"] == "0.2.0" and args["--from-version"] == "0.1.0"
    assert args["--base-url"] == "https://127.0.0.1:8123"
    assert args["--log-path"] == str(log_path)
    assert ("--no-dev" in cmd) is (not dev_deps)
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_tarball_launch_without_a_stage_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    monkeypatch.setenv("UV", "/opt/uv")
    st = update_check.UpdateStatus(mode=update_check.MODE_TARBALL, current_version="0.1.0", latest_version="0.2.0")
    with pytest.raises(RuntimeError, match="needs the unpacked stage"):
        update_check.launch(st, None)
