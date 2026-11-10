#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/10 13:53:25.110297
Revised: 2026/11/10 13:53:25.110297

The self-update helper (self_update.py) in git mode, end to end on a real
git repo pair, with ``uv`` replaced by a fake executable that records its
calls and a fake reloading server answering ``GET /``. Also the argument
checks that keep each mode from starting without what it needs.
"""

import json
import subprocess
import sys

import pytest
from _update_fixture import GIT, FakeReloadingServer, git, make_fake_uv, make_pair, push_update, uv_calls

from renar_backend import self_update


@pytest.fixture
def setup(tmp_path, monkeypatch):
    origin, clone = make_pair(tmp_path)
    to_sha = push_update(tmp_path, origin, "0.2.0", ["add feature", "bump to 0.2.0"])
    git(clone, "fetch", "origin", "master")
    monkeypatch.setenv("FAKE_UV_RECORD", str(tmp_path / "uv-calls.jsonl"))
    monkeypatch.delenv("FAKE_UV_FAIL", raising=False)
    (clone / "logs" / self_update.LOCK_FILE).write_text("{}", encoding="utf-8")  # taken by the caller
    return {
        "tmp": tmp_path,
        "clone": clone,
        "from_sha": git(clone, "rev-parse", "HEAD"),
        "to_sha": to_sha,
        "uv": make_fake_uv(tmp_path),
    }


def argv(s, base_url, *extra):
    return [
        "--repo", str(s["clone"]),
        "--uv", str(s["uv"]),
        "--mode", "git",
        "--git", GIT,
        "--from-sha", s["from_sha"],
        "--to-sha", s["to_sha"],
        "--from-version", "0.1.0",
        "--to-version", "0.2.0",
        "--base-url", base_url,
        "--log-path", str(s["clone"] / "logs" / "self-update-test.log"),
        "--health-timeout", "4",
        *extra,
    ]  # fmt: skip


def status(s) -> dict:
    return json.loads((s["clone"] / "logs" / self_update.STATUS_FILE).read_text(encoding="utf-8"))


def log_text(s) -> str:
    return (s["clone"] / "logs" / "self-update-test.log").read_text(encoding="utf-8")


def test_happy_path_fast_forwards(setup):
    with FakeReloadingServer(setup["clone"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 0
    st = status(setup)
    assert st["status"] == "ok"
    assert st["mode"] == "git"
    assert (st["from_sha"], st["to_sha"]) == (setup["from_sha"], setup["to_sha"])
    assert (st["from_version"], st["to_version"]) == ("0.1.0", "0.2.0")
    assert st["failed_step"] is None and st["finished_at"]
    assert git(setup["clone"], "rev-parse", "HEAD") == setup["to_sha"]
    assert git(setup["clone"], "status", "--porcelain") == ""
    assert not (setup["clone"] / "logs" / self_update.LOCK_FILE).exists()
    assert not (setup["clone"] / self_update.WORK_DIR).exists()  # git mode never uses it


def test_steps_run_in_order(setup):
    with FakeReloadingServer(setup["clone"]) as server:
        self_update.main(argv(setup, server.base_url))
    assert uv_calls(setup["tmp"]) == [
        ["run", "--no-sync", "alembic", "current"],
        ["sync", "--locked"],
        ["run", "--no-sync", "alembic", "upgrade", "head"],
    ]


def test_sync_sees_the_new_lock_before_the_code_swap(setup, monkeypatch):
    """Dependencies and migrations come from the target commit while the
    running code (src/) is still the old one: the reloader only fires at the swap."""
    seen = {}
    original = self_update.Updater.sync

    def spy(updater):
        seen["lock"] = (setup["clone"] / "uv.lock").read_text(encoding="utf-8")
        seen["src"] = sorted(p.name for p in (setup["clone"] / "src" / "renar_backend").iterdir())
        original(updater)

    monkeypatch.setattr(self_update.Updater, "sync", spy)
    with FakeReloadingServer(setup["clone"]) as server:
        self_update.main(argv(setup, server.base_url))
    assert seen["lock"] == "# lock for 0.2.0\n"
    assert seen["src"] == ["__init__.py"]


def test_no_dev_is_passed_to_sync(setup):
    with FakeReloadingServer(setup["clone"]) as server:
        self_update.main(argv(setup, server.base_url, "--no-dev"))
    assert ["sync", "--locked", "--no-dev"] in uv_calls(setup["tmp"])


def test_migrate_failure_rolls_back_to_from_sha(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "migrate")
    with FakeReloadingServer(setup["clone"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "rolled_back"
    assert st["failed_step"] == "migrate"
    assert git(setup["clone"], "rev-parse", "HEAD") == setup["from_sha"]
    assert git(setup["clone"], "status", "--porcelain") == ""
    assert not any("downgrade" in call for call in uv_calls(setup["tmp"]))  # nothing was migrated
    assert not (setup["clone"] / "logs" / self_update.LOCK_FILE).exists()


def test_verify_failure_downgrades_and_resets(setup):
    """The new worker never reports the new version: the migration that did
    run is downgraded to the recorded revision before the code goes back."""
    with FakeReloadingServer(setup["clone"], frozen_version="0.1.0") as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "rolled_back"
    assert st["failed_step"] == "verify"
    calls = uv_calls(setup["tmp"])
    downgrade = ["run", "--no-sync", "alembic", "downgrade", "abc123def456"]
    assert downgrade in calls
    assert calls.index(downgrade) < len(calls) - 1  # then the rollback's sync
    assert git(setup["clone"], "rev-parse", "HEAD") == setup["from_sha"]


def test_rollback_failure_reports_failed(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "sync")  # the update's sync and the rollback's sync both fail
    with FakeReloadingServer(setup["clone"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "failed"
    assert st["failed_step"] == "sync"
    assert "rollback-sync" in st["error"]
    assert not (setup["clone"] / "logs" / self_update.LOCK_FILE).exists()


def test_every_step_output_is_in_log(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "migrate")
    with FakeReloadingServer(setup["clone"]) as server:
        self_update.main(argv(setup, server.base_url))
    text = log_text(setup)
    for needle in (
        "FAKE-UV run --no-sync alembic current",
        "FAKE-UV sync --locked",
        "migration exploded",
        "[migrate] exited with 4",
        "[rollback-reset] $",
        "server is back on 0.1.0",
    ):
        assert needle in text, needle
    assert "[ERROR   ]" in text


def test_helper_runs_isolated_outside_the_venv(setup):
    """How launch() runs it: the base interpreter with -I, no venv packages."""
    with FakeReloadingServer(setup["clone"]) as server:
        proc = subprocess.run(
            [
                getattr(sys, "_base_executable", sys.executable),
                "-I",
                self_update.__file__,
                *argv(setup, server.base_url),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    assert proc.returncode == 0, proc.stderr
    assert status(setup)["status"] == "ok"


@pytest.mark.parametrize(
    ("drop", "message"),
    [
        ("--git", "--mode git needs --git, --from-sha and --to-sha"),
        ("--to-sha", "--mode git needs --git, --from-sha and --to-sha"),
    ],
)
def test_git_mode_refuses_missing_commits(setup, capsys, drop, message):
    args = argv(setup, "http://127.0.0.1:1")
    i = args.index(drop)
    del args[i : i + 2]
    with pytest.raises(SystemExit):
        self_update.parse_args(args)
    assert message in capsys.readouterr().err


def test_tarball_mode_refuses_a_missing_stage(capsys):
    with pytest.raises(SystemExit):
        self_update.parse_args(
            ["--repo", ".", "--uv", "uv", "--mode", "tarball", "--from-version", "1", "--to-version", "2"]
            + ["--base-url", "http://x", "--log-path", "x.log"]
        )
    assert "--mode tarball needs --stage" in capsys.readouterr().err
