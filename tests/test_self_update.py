#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.910309
Revised: 2026/11/10 13:53:25.686950

The self-update helper (self_update.py) in tarball mode, end to end: a real release tarball
unpacked by update_check.prepare() into a real project directory, with
``uv`` replaced by a fake executable that records its calls and a fake
reloading server answering ``GET /``. The helper runs in-process through
``main(argv)`` here; one test also runs it the way launch() does, as
``python -I`` in a separate process. Git mode is in test_self_update_git.py.
"""

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _update_fixture import (
    FEED_URL,
    FakeForge,
    FakeReloadingServer,
    make_fake_uv,
    make_project,
    uv_calls,
    write_be_pid,
)

from renar_backend import self_update, update_check


@pytest.fixture
def setup(tmp_path, monkeypatch):
    forge = FakeForge(tmp_path)
    monkeypatch.setattr(update_check, "_http", forge.client)
    monkeypatch.setattr(update_check.settings, "update_release_url", FEED_URL)
    project = make_project(tmp_path)
    write_be_pid(project)
    stage = update_check.prepare(update_check.check("0.1.0", project), project)
    monkeypatch.setenv("FAKE_UV_RECORD", str(tmp_path / "uv-calls.jsonl"))
    monkeypatch.delenv("FAKE_UV_FAIL", raising=False)
    (project / "logs" / self_update.LOCK_FILE).write_text("{}", encoding="utf-8")  # taken by the caller
    return {"tmp": tmp_path, "project": project, "stage": stage, "uv": make_fake_uv(tmp_path)}


def argv(s, base_url, *extra):
    return [
        "--repo", str(s["project"]),
        "--uv", str(s["uv"]),
        "--mode", "tarball",
        "--stage", str(s["stage"]),
        "--from-version", "0.1.0",
        "--to-version", "0.2.0",
        "--base-url", base_url,
        "--log-path", str(s["project"] / "logs" / "self-update-test.log"),
        "--health-timeout", "4",
        *extra,
    ]  # fmt: skip


def status(s) -> dict:
    return json.loads((s["project"] / "logs" / self_update.STATUS_FILE).read_text(encoding="utf-8"))


def log_text(s) -> str:
    return (s["project"] / "logs" / "self-update-test.log").read_text(encoding="utf-8")


def version_on_disk(project: Path) -> str:
    return (project / "pyproject.toml").read_text(encoding="utf-8").split('version = "')[1].split('"')[0]


def pkg(project: Path) -> set[str]:
    return {p.name for p in (project / "src" / "renar_backend").iterdir()}


def assert_old_release(project: Path) -> None:
    assert version_on_disk(project) == "0.1.0"
    assert (project / "uv.lock").read_text(encoding="utf-8") == "# lock for 0.1.0\n"
    assert pkg(project) == {"__init__.py", "old_only.py"}
    assert not (project / "alembic" / "versions").exists()
    assert not (project / "PKG-INFO").exists()


def assert_runtime_files_kept(project: Path) -> None:
    assert (project / ".env").read_text(encoding="utf-8") == "SECRET=1\n"
    assert (project / "media" / "poster.jpg").read_bytes() == b"jpg"
    assert (project / "logs" / "be.pid").exists()


def test_happy_path_installs_the_release(setup):
    project = setup["project"]
    with FakeReloadingServer(project) as server:
        assert self_update.main(argv(setup, server.base_url)) == 0
    st = status(setup)
    assert st["status"] == "ok"
    assert (st["from_version"], st["to_version"]) == ("0.1.0", "0.2.0")
    assert st["failed_step"] is None and st["finished_at"]
    assert version_on_disk(project) == "0.2.0"
    assert (project / "uv.lock").read_text(encoding="utf-8") == "# lock for 0.2.0\n"
    assert pkg(project) == {"__init__.py", "new_feature.py"}  # the old package is replaced, not merged
    assert (project / "alembic" / "versions" / "rev_new.py").is_file()
    assert_runtime_files_kept(project)
    assert not setup["stage"].exists()
    previous = project / self_update.WORK_DIR / self_update.PREVIOUS_DIR
    assert (previous / "src" / "renar_backend" / "old_only.py").is_file()  # kept for a manual way back
    assert '"0.1.0"' in (previous / "pyproject.toml").read_text(encoding="utf-8")
    assert not (project / "logs" / self_update.LOCK_FILE).exists()


def test_steps_run_in_order(setup):
    with FakeReloadingServer(setup["project"]) as server:
        self_update.main(argv(setup, server.base_url))
    assert uv_calls(setup["tmp"]) == [
        ["run", "--no-sync", "alembic", "current"],
        ["sync", "--locked"],
        ["run", "--no-sync", "alembic", "upgrade", "head"],
    ]


def test_sync_and_migrate_see_the_new_files_before_the_code_swap(setup, monkeypatch):
    """Dependencies and migrations come from the release while the running
    code (src/) is still the old one: the reloader only fires at the swap."""
    seen = {}
    original_sync, original_migrate = self_update.Updater.sync, self_update.Updater.migrate

    def spy_sync(updater):
        seen["lock"] = (setup["project"] / "uv.lock").read_text(encoding="utf-8")
        seen["src_at_sync"] = pkg(setup["project"])
        original_sync(updater)

    def spy_migrate(updater):
        seen["migration"] = (setup["project"] / "alembic" / "versions" / "rev_new.py").is_file()
        seen["src_at_migrate"] = pkg(setup["project"])
        original_migrate(updater)

    monkeypatch.setattr(self_update.Updater, "sync", spy_sync)
    monkeypatch.setattr(self_update.Updater, "migrate", spy_migrate)
    with FakeReloadingServer(setup["project"]) as server:
        self_update.main(argv(setup, server.base_url))
    assert seen["lock"] == "# lock for 0.2.0\n"
    assert seen["migration"] is True
    assert seen["src_at_sync"] == seen["src_at_migrate"] == {"__init__.py", "old_only.py"}


def test_a_previous_backup_is_replaced(setup):
    old = setup["project"] / self_update.WORK_DIR / self_update.PREVIOUS_DIR
    old.mkdir(parents=True)
    (old / "from-the-update-before.txt").write_text("x", encoding="utf-8")
    with FakeReloadingServer(setup["project"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 0
    assert not (old / "from-the-update-before.txt").exists()


def test_no_dev_is_passed_to_sync(setup):
    with FakeReloadingServer(setup["project"]) as server:
        self_update.main(argv(setup, server.base_url, "--no-dev"))
    assert ["sync", "--locked", "--no-dev"] in uv_calls(setup["tmp"])


def test_sync_failure_restores_the_old_files(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "sync-once")
    with FakeReloadingServer(setup["project"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "rolled_back"
    assert st["failed_step"] == "sync"
    assert_old_release(setup["project"])
    assert_runtime_files_kept(setup["project"])
    assert not setup["stage"].exists()


def test_migrate_failure_rolls_back_without_downgrade(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "migrate")
    with FakeReloadingServer(setup["project"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "rolled_back"
    assert st["failed_step"] == "migrate"
    assert_old_release(setup["project"])
    assert not any("downgrade" in call for call in uv_calls(setup["tmp"]))  # nothing was migrated
    assert not (setup["project"] / "logs" / self_update.LOCK_FILE).exists()


def test_verify_failure_downgrades_with_the_new_scripts_then_restores(setup, monkeypatch):
    """The new worker never reports the new version: the migration that did
    run is downgraded (while the new alembic/ is still in place) before the
    old files come back."""
    seen = {}
    original_run = self_update.Updater.run

    def spy(updater, cmd, step):
        if step == "rollback-migrate":
            seen["new_scripts"] = (updater.repo / "alembic" / "versions" / "rev_new.py").is_file()
        return original_run(updater, cmd, step)

    monkeypatch.setattr(self_update.Updater, "run", spy)
    with FakeReloadingServer(setup["project"], frozen_version="0.1.0") as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "rolled_back"
    assert st["failed_step"] == "verify"
    calls = uv_calls(setup["tmp"])
    downgrade = ["run", "--no-sync", "alembic", "downgrade", "abc123def456"]
    assert downgrade in calls
    assert calls.index(downgrade) < len(calls) - 1  # then the rollback's sync
    assert seen["new_scripts"] is True
    assert_old_release(setup["project"])


def test_rollback_failure_reports_failed(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "sync")  # the update's sync and the rollback's sync both fail
    with FakeReloadingServer(setup["project"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["status"] == "failed"
    assert st["failed_step"] == "sync"
    assert "rollback-sync" in st["error"]
    assert_old_release(setup["project"])  # the files still went back before the sync failed
    assert not (setup["project"] / "logs" / self_update.LOCK_FILE).exists()


def test_missing_stage_fails_before_touching_anything(setup):
    shutil.rmtree(setup["stage"])
    with FakeReloadingServer(setup["project"]) as server:
        assert self_update.main(argv(setup, server.base_url)) == 1
    st = status(setup)
    assert st["failed_step"] == "begin"
    assert_old_release(setup["project"])


def test_every_step_output_is_in_log(setup, monkeypatch):
    monkeypatch.setenv("FAKE_UV_FAIL", "migrate")
    with FakeReloadingServer(setup["project"]) as server:
        self_update.main(argv(setup, server.base_url))
    text = log_text(setup)
    for needle in (
        "FAKE-UV run --no-sync alembic current",
        "[stage] installed uv.lock",
        "[stage] installed alembic",
        "FAKE-UV sync --locked",
        "migration exploded",
        "[migrate] exited with 4",
        "[rollback-restore] restored uv.lock",
        "server is back on 0.1.0",
    ):
        assert needle in text, needle
    assert "[ERROR   ]" in text


def test_helper_runs_isolated_outside_the_venv(setup):
    """How launch() runs it: the base interpreter with -I, no venv packages."""
    with FakeReloadingServer(setup["project"]) as server:
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
    assert version_on_disk(setup["project"]) == "0.2.0"


def test_helper_imports_only_stdlib():
    tree = ast.parse(Path(self_update.__file__).read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import: the helper runs as a plain script"
            modules.add(node.module.split(".")[0])
    assert modules <= set(sys.stdlib_module_names), modules - set(sys.stdlib_module_names)
