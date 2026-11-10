#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:19.074462
Revised: 2026/11/10 16:17:28.475594

update_check in tarball mode (a project without .git): every state the
Server Update page can show against a fake release feed, prepare()'s
download, BLAKE3 check and unpacking of a real tarball, plus the lock, the
server/worker markers, the last-result file and how launch() starts the
helper. Git mode is in test_update_check_git.py.
"""

import io
import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime

import httpx
import pytest
from _update_fixture import FEED_URL, FakeForge, b3_line, build_tarball, make_project, write_be_pid

from renar_backend import self_update, update_check


@pytest.fixture
def forge(tmp_path, monkeypatch):
    forge = FakeForge(tmp_path)
    monkeypatch.setattr(update_check, "_http", forge.client)
    monkeypatch.setattr(update_check.settings, "update_release_url", FEED_URL)
    return forge


@pytest.fixture
def project(tmp_path, monkeypatch, forge):
    project = make_project(tmp_path)
    write_be_pid(project)
    monkeypatch.setattr(update_check, "REPO", project)
    return project


# ---- check ------------------------------------------------------------------


def test_newer_release_is_available(project, forge):
    st = update_check.check("0.1.0")
    assert st.blocked_reason is None
    assert st.available
    assert st.latest_version == "0.2.0"
    assert st.release_url == "https://forge.test/renar-backend/releases/v0.2.0"
    assert "shiny" in st.release_notes
    assert st.tarball_url.endswith("renar_backend-0.2.0.tar.gz")
    assert st.checksum_url.endswith("renar_backend-0.2.0.tar.gz.b3")


@pytest.mark.parametrize("running", ["0.2.0", "0.3.0", "1.0.0"])
def test_same_or_older_release_is_up_to_date(project, running):
    st = update_check.check(running)
    assert st.blocked_reason is None
    assert not st.available


def test_versions_compare_numerically(project, forge):
    forge.feed = {**forge.release(), "tag_name": "v0.10.0"}
    for asset in forge.feed["assets"]:
        asset["name"] = asset["name"].replace("0.2.0", "0.10.0")
    assert update_check.check("0.9.0").available


def test_tag_without_v_prefix(project, forge):
    forge.feed = {**forge.release(), "tag_name": "0.2.0"}
    assert update_check.check("0.1.0").available


def test_long_release_notes_are_capped(project, forge, monkeypatch):
    monkeypatch.setattr(update_check, "MAX_NOTES_CHARS", 10)
    forge.feed = {**forge.release(), "body": "x" * 50}
    assert update_check.check("0.1.0").release_notes == "x" * 10 + "\n…"


def test_a_project_without_git_uses_the_release_feed(project, forge):
    st = update_check.check("0.1.0")
    assert st.mode == update_check.MODE_TARBALL
    assert FEED_URL in forge.requests


def test_a_git_checkout_never_reads_the_release_feed(project, forge):
    (project / ".git").mkdir()  # not a real repo: git mode, and git itself refuses it
    st = update_check.check("0.1.0")
    assert st.mode == update_check.MODE_GIT
    assert st.blocked_reason and "git" in st.blocked_reason
    assert not st.available
    assert forge.requests == []


def test_lock_blocks_second_update(project):
    assert update_check.take_lock()
    assert not update_check.take_lock()
    assert update_check.check("0.1.0").blocked_reason == "An update is already in progress."
    update_check.release_lock()
    assert update_check.take_lock()


def test_stale_lock_is_replaced(project, caplog):
    lock = project / "logs" / self_update.LOCK_FILE
    lock.write_text("{}", encoding="utf-8")
    old = time.time() - update_check.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    assert update_check.take_lock()
    assert "removing stale self-update lock" in caplog.text


def test_missing_server_pid_blocks(project):
    (project / "logs" / "be.pid").unlink()
    assert "wasn't started with `uv run be`" in update_check.check("0.1.0").blocked_reason


def test_check_stamps_when_it_ran(project, forge):
    before = datetime.now(UTC)
    st = update_check.check("0.1.0")
    assert before <= st.checked_at <= datetime.now(UTC)
    assert st.checked_at.tzinfo is not None


def test_unparseable_running_version_blocks(project):
    assert "can't be compared" in update_check.check("0.1.0.dev3+local").blocked_reason


def test_feed_http_error_blocks_with_retry(project, forge, caplog):
    forge.feed_status = 503
    st = update_check.check("0.1.0")
    assert st.blocked_reason.startswith("Couldn't check for updates:")
    assert st.retryable
    assert not st.available
    assert "release lookup" in caplog.text


def test_feed_unreachable_blocks_with_retry(project, monkeypatch):
    def unreachable(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(
        update_check, "_http", lambda: httpx.Client(transport=httpx.MockTransport(unreachable), follow_redirects=True)
    )
    st = update_check.check("0.1.0")
    assert "no route" in st.blocked_reason
    assert st.retryable


@pytest.mark.parametrize(
    ("feed", "reason"),
    [
        ({"message": "Not Found"}, "without a tag_name"),
        ([], "without a tag_name"),
        ({"tag_name": "nightly", "assets": []}, "not a release version"),
        ({"tag_name": "v0.2.0", "assets": []}, "has no renar_backend-0.2.0.tar.gz"),
    ],
)
def test_unusable_release_blocks(project, forge, feed, reason):
    forge.feed = feed
    st = update_check.check("0.1.0")
    assert reason in st.blocked_reason
    assert not st.retryable


def test_release_without_checksum_blocks(project, forge):
    forge.feed = forge.release()
    forge.feed["assets"] = [a for a in forge.feed["assets"] if not a["name"].endswith(".b3")]
    assert ".b3 checksum" in update_check.check("0.1.0").blocked_reason


# ---- prepare ----------------------------------------------------------------


def test_prepare_unpacks_the_checked_release(project, forge):
    st = update_check.check("0.1.0")
    stage = update_check.prepare(st)
    assert stage == project / self_update.WORK_DIR / self_update.STAGE_DIR
    assert '"0.2.0"' in (stage / "pyproject.toml").read_text(encoding="utf-8")
    assert (stage / "src" / "renar_backend" / "new_feature.py").is_file()
    assert (stage / "alembic" / "versions" / "rev_new.py").is_file()
    assert not (stage / "PKG-INFO").exists()
    leftovers = sorted(p.name for p in stage.parent.iterdir())
    assert leftovers == [self_update.STAGE_DIR]  # no tarball, no unpack dir
    assert "https://cdn.forge.test/blob" in forge.requests  # followed the asset redirect
    # the running project is untouched until the helper runs
    assert '"0.1.0"' in (project / "pyproject.toml").read_text(encoding="utf-8")


def test_prepare_replaces_a_leftover_stage(project):
    stale = project / self_update.WORK_DIR / self_update.STAGE_DIR
    stale.mkdir(parents=True)
    (stale / "junk.txt").write_text("x", encoding="utf-8")
    stage = update_check.prepare(update_check.check("0.1.0"))
    assert not (stage / "junk.txt").exists()


def test_prepare_refuses_a_checksum_mismatch(project, forge):
    forge.checksum = f"{'0' * 64}  renar_backend-0.2.0.tar.gz\n"
    st = update_check.check("0.1.0")
    with pytest.raises(update_check.UpdateError, match="doesn't match its BLAKE3 sum"):
        update_check.prepare(st)
    assert list((project / self_update.WORK_DIR).iterdir()) == []


def test_prepare_refuses_a_checksum_for_another_file(project, forge):
    forge.checksum = f"{'0' * 64}  other.tar.gz\n"
    with pytest.raises(update_check.UpdateError, match="has no sum for"):
        update_check.prepare(update_check.check("0.1.0"))


def test_prepare_refuses_a_download_failure(project):
    st = update_check.check("0.1.0")
    st.tarball_url = "https://forge.test/dl/missing"
    with pytest.raises(update_check.UpdateError, match="Couldn't download the release"):
        update_check.prepare(st)


def test_prepare_refuses_an_oversized_download(project, monkeypatch):
    monkeypatch.setattr(update_check, "MAX_TARBALL_BYTES", 100)
    with pytest.raises(update_check.UpdateError, match="is over"):
        update_check.prepare(update_check.check("0.1.0"))
    assert list((project / self_update.WORK_DIR).iterdir()) == []


def _repack(forge, tarball: bytes) -> None:
    forge.tarball = tarball
    forge.checksum = b3_line(tarball, "renar_backend-0.2.0.tar.gz")


def test_prepare_refuses_paths_outside_the_stage(project, forge, tmp_path):
    _repack(forge, build_tarball(tmp_path, "0.2.0", extra={"../escape.txt": b"x"}))
    with pytest.raises(update_check.UpdateError, match="Couldn't unpack"):
        update_check.prepare(update_check.check("0.1.0"))
    assert not (project / self_update.WORK_DIR / "escape.txt").exists()
    assert not (project / "escape.txt").exists()


def test_prepare_refuses_more_than_one_top_folder(project, forge, tmp_path):
    _repack(forge, build_tarball(tmp_path, "0.2.0", extra={"stray.txt": b"x"}))
    with pytest.raises(update_check.UpdateError, match="one top-level folder"):
        update_check.prepare(update_check.check("0.1.0"))


def test_prepare_refuses_a_tarball_of_another_version(project, forge, tmp_path):
    wrong = build_tarball(tmp_path, "0.1.5")
    _repack(forge, wrong)
    with pytest.raises(update_check.UpdateError, match="contains version 0.1.5, not 0.2.0"):
        update_check.prepare(update_check.check("0.1.0"))
    assert not (project / self_update.WORK_DIR / self_update.STAGE_DIR).exists()


def test_prepare_refuses_a_tarball_without_the_package(project, forge):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b'[project]\nversion = "0.2.0"\n'
        info = tarfile.TarInfo("renar_backend-0.2.0/pyproject.toml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    _repack(forge, buf.getvalue())
    with pytest.raises(update_check.UpdateError, match="has no uv.lock"):
        update_check.prepare(update_check.check("0.1.0"))


def test_prepare_refuses_when_nothing_is_newer(project):
    with pytest.raises(update_check.UpdateError, match="Nothing newer"):
        update_check.prepare(update_check.check("0.2.0"))


# ---- markers, last result, launch -------------------------------------------


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
def test_launch_starts_isolated_detached_helper(project, monkeypatch, dev_deps):
    write_be_pid(project, port=8123, scheme="https", dev_deps=dev_deps)
    st = update_check.check("0.1.0")
    stage = update_check.prepare(st)
    started = {}

    def fake_popen(cmd, **kwargs):
        started["cmd"], started["kwargs"] = cmd, kwargs

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("UV", "/opt/uv")
    log_path = update_check.launch(st, stage)
    cmd, kwargs = started["cmd"], started["kwargs"]
    assert cmd[0] == getattr(sys, "_base_executable", sys.executable)
    assert cmd[1] == "-I"
    assert cmd[2] == self_update.__file__
    args = dict(zip(cmd[3::2], cmd[4::2], strict=False))
    assert args["--uv"] == "/opt/uv"
    assert args["--stage"] == str(stage)
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


def test_launch_without_uv_raises(project, monkeypatch):
    monkeypatch.delenv("UV", raising=False)
    monkeypatch.setattr(update_check.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="uv not found"):
        update_check.launch(update_check.UpdateStatus(current_version="0.1.0"), project)
