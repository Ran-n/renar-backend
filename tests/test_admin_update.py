#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:19.233482
Revised: 2026/11/10 16:17:28.131846

The admin Server Update page and its routes: each state's rendering (the
Update button enabled only when an update is available), the POST re-check,
lock and launch, the result banner, and the status endpoint the page polls.
Both sources render: release tarball and git checkout.
update_check.check()/prepare()/launch() are replaced here; the
test_update_check*.py and test_self_update*.py files cover them on real
tarballs and real git repos.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from renar_backend import self_update, update_check
from renar_backend.routers.admin import update as update_page


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    (tmp_path / "logs").mkdir()
    return tmp_path / "logs"


def _status(current: str, **kw) -> update_check.UpdateStatus:
    base = {"current_version": current, "latest_version": current}
    return update_check.UpdateStatus(**{**base, **kw})


AVAILABLE = {
    "latest_version": "9.9.9",
    "release_url": "https://forge.test/releases/v9.9.9",
    "release_notes": "### Added\n- <b>shiny</b>",
}


@pytest.fixture
def state(monkeypatch, logs):
    def set_state(**kw):
        monkeypatch.setattr(update_check, "check", lambda current, *a, **k: _status(current, **kw))

    set_state()
    return set_state


def _button(page: str) -> str:
    start = page.index('id="update-btn"')
    return page[start : page.index(">", start)]


def test_update_page_requires_admin(client, admin_enabled, state):
    r = client.get("/admin/update", follow_redirects=False)
    assert r.status_code == 303
    assert client.post("/admin/update", follow_redirects=False).status_code == 401
    assert client.get("/admin/update/status", follow_redirects=False).status_code == 303


def test_up_to_date_renders_disabled_button(client, admin_enabled, state):
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "Up to date" in page
    assert "disabled" in _button(page)
    assert 'action="/admin/logout"' in page


def test_available_renders_release_and_enabled_button(client, admin_enabled, state):
    state(**AVAILABLE)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "New release" in page
    assert '<a href="https://forge.test/releases/v9.9.9">9.9.9</a>' in page
    assert '<pre class="update-notes">### Added\n- &lt;b&gt;shiny&lt;/b&gt;</pre>' in page
    assert "Update to 9.9.9" in page
    assert "disabled" not in _button(page)


def test_release_without_notes_renders_no_notes_box(client, admin_enabled, state):
    state(**{**AVAILABLE, "release_notes": "  "})
    page = client.get("/admin/update", headers=admin_enabled).text
    assert 'class="update-notes"' not in page
    assert "disabled" not in _button(page)


def test_tarball_mode_shows_release_source(client, admin_enabled, state):
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "<dt>Source</dt><dd>release tarball</dd>" in page
    assert "<dt>Branch</dt>" not in page


def test_blocked_renders_reason_and_disabled_button(client, admin_enabled, state):
    state(blocked_reason="Release 9.9.9 has no renar_backend-9.9.9.tar.gz.", latest_version=None)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "Blocked" in page
    assert "has no renar_backend-9.9.9.tar.gz" in page
    assert "<dt>Latest release</dt><dd>?</dd>" in page
    assert "disabled" in _button(page)
    assert ">Retry</a>" not in page


GIT = {"mode": update_check.MODE_GIT, "branch": "master", "head_sha": "a" * 40, "remote_sha": "b" * 40}
GIT_AVAILABLE = {
    **GIT,
    "behind": ["bbbbbbb add feature", "ccccccc fix <bug>"],
    "behind_count": 2,
    "latest_version": "9.9.9",
}


def test_git_mode_up_to_date_shows_branch_and_commit(client, admin_enabled, state):
    state(**GIT)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "<dt>Source</dt><dd>git checkout (origin/master)</dd>" in page
    assert "<dt>Branch</dt><dd>master</dd>" in page
    assert "<code>aaaaaaaa</code>" in page
    assert "Latest release" not in page
    assert "Up to date" in page
    assert "disabled" in _button(page)


def test_git_mode_available_lists_commits(client, admin_enabled, state):
    state(**GIT_AVAILABLE)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "2 new commits" in page
    assert "<code>bbbbbbb</code> add feature" in page
    assert "fix &lt;bug&gt;" in page
    assert "Update to 9.9.9" in page
    assert "disabled" not in _button(page)


def test_git_mode_same_version_labels_commit_count(client, admin_enabled, state):
    from renar_backend.main import backend_version

    state(**{**GIT_AVAILABLE, "latest_version": backend_version()})
    assert "Update (2 commits)" in client.get("/admin/update", headers=admin_enabled).text


def test_git_mode_more_commits_than_listed(client, admin_enabled, state):
    state(**{**GIT_AVAILABLE, "behind_count": 60})
    assert "and 58 more" in client.get("/admin/update", headers=admin_enabled).text


def test_git_mode_dirty_tree_lists_paths(client, admin_enabled, state):
    state(
        **GIT,
        blocked_reason="The working tree has uncommitted changes; commit or discard them first.",
        dirty_paths=["a.py"],
    )
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "uncommitted changes" in page
    assert "<code>a.py</code>" in page
    assert "disabled" in _button(page)


def test_git_mode_post_launches_without_a_stage(client, admin_enabled, state, monkeypatch, logs):
    state(**GIT_AVAILABLE)
    launched = []
    monkeypatch.setattr(update_check, "prepare", lambda st: None)
    monkeypatch.setattr(update_check, "launch", lambda st, where: launched.append((st, where)) or logs / "x.log")
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 202
    assert launched[0][0].mode == update_check.MODE_GIT
    assert launched[0][0].remote_sha == "b" * 40
    assert launched[0][1] is None


def _check_button(page: str) -> str:
    start = page.index('id="check-btn"')
    return page[start : page.index("</button>", start)]


def test_fetch_failure_offers_retry(client, admin_enabled, state):
    state(blocked_reason="Couldn't check for updates: timed out", retryable=True)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert _check_button(page).endswith(">Retry")
    assert "Up to date" not in page


@pytest.mark.parametrize(
    "kw",
    [{}, AVAILABLE, {"blocked_reason": "Repository has local changes."}],
    ids=["up_to_date", "available", "blocked"],
)
def test_every_state_has_an_enabled_check_now_button(client, admin_enabled, state, kw):
    state(**kw)
    button = _check_button(client.get("/admin/update", headers=admin_enabled).text)
    assert button.endswith(">Check now")
    assert "disabled" not in button


def test_check_now_reloads_the_page(client, admin_enabled, state):
    page = client.get("/admin/update", headers=admin_enabled).text
    script = page[page.index("getElementById('check-btn')") :]
    assert "window.location.reload()" in script[: script.index("})();")]


def test_page_shows_when_it_checked(client, admin_enabled, state, monkeypatch):
    when = datetime(2026, 11, 10, 15, 4, 5, tzinfo=UTC)
    monkeypatch.setattr(update_check, "check", lambda current, *a, **k: _status(current, checked_at=when))
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "<dt>Checked</dt>" in page
    assert '<time id="checked-at" datetime="2026-11-10T15:04:05+00:00">2026-11-10 15:04:05 UTC</time>' in page


def test_checked_time_is_shown_in_utc(client, admin_enabled, state, monkeypatch):
    when = datetime(2026, 11, 10, 16, 4, 5, tzinfo=timezone(timedelta(hours=1)))
    monkeypatch.setattr(update_check, "check", lambda current, *a, **k: _status(current, checked_at=when))
    page = client.get("/admin/update", headers=admin_enabled).text
    assert ">2026-11-10 15:04:05 UTC</time>" in page


def test_reason_is_escaped(client, admin_enabled, state):
    state(blocked_reason="<script>x</script>")
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page


def test_running_update_shows_spinner(client, admin_enabled, state, logs):
    (logs / self_update.LOCK_FILE).write_text("{}", encoding="utf-8")
    page = client.get("/admin/update", headers=admin_enabled).text
    assert 'class="updating on"' in page
    assert "disabled" in _button(page)


def test_update_post_rechecks_and_409s_when_blocked(client, admin_enabled, state, monkeypatch):
    state(blocked_reason="This is a git checkout; update it with git.")
    monkeypatch.setattr(update_check, "prepare", lambda *a, **k: pytest.fail("must not download"))
    monkeypatch.setattr(update_check, "launch", lambda *a, **k: pytest.fail("must not launch"))
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 409
    assert r.json()["detail"] == "This is a git checkout; update it with git."


def test_update_post_409s_when_up_to_date(client, admin_enabled, state):
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 409
    assert r.json()["detail"] == "Already up to date."


def test_update_post_prepares_launches_and_returns_202(client, admin_enabled, state, monkeypatch, logs):
    state(**AVAILABLE)
    stage = logs.parent / "stage"
    prepared, launched = [], []
    monkeypatch.setattr(update_check, "prepare", lambda st: prepared.append(st) or stage)
    monkeypatch.setattr(update_check, "launch", lambda st, where: launched.append((st, where)) or logs / "x.log")
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 202
    assert r.json()["log_path"].endswith("x.log")
    assert prepared[0].latest_version == "9.9.9"
    assert launched[0][0].latest_version == "9.9.9" and launched[0][1] == stage
    assert (logs / self_update.LOCK_FILE).exists()  # held for the helper, which releases it
    # a second press while it runs
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 409
    assert "already in progress" in r.json()["detail"]


def test_update_post_refused_download_releases_lock(client, admin_enabled, state, monkeypatch, logs):
    state(**AVAILABLE)

    def refuse(st):
        raise update_check.UpdateError("renar_backend-9.9.9.tar.gz doesn't match its BLAKE3 sum")

    monkeypatch.setattr(update_check, "prepare", refuse)
    monkeypatch.setattr(update_check, "launch", lambda *a, **k: pytest.fail("must not launch"))
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 502
    assert "BLAKE3" in r.json()["detail"]
    assert not (logs / self_update.LOCK_FILE).exists()


def test_update_post_prepare_crash_releases_lock(client, admin_enabled, state, monkeypatch, logs):
    state(**AVAILABLE)

    def boom(st):
        raise OSError("disk full")

    monkeypatch.setattr(update_check, "prepare", boom)
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 500
    assert r.json()["detail"] == "Couldn't prepare the update; see the server log."
    assert not (logs / self_update.LOCK_FILE).exists()


def test_update_post_launch_failure_releases_lock(client, admin_enabled, state, monkeypatch, logs):
    state(**AVAILABLE)
    monkeypatch.setattr(update_check, "prepare", lambda st: logs.parent / "stage")

    def boom(*a, **k):
        raise RuntimeError("uv not found")

    monkeypatch.setattr(update_check, "launch", boom)
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 500
    assert not (logs / self_update.LOCK_FILE).exists()


def test_status_endpoint(client, admin_enabled, state, logs):
    assert client.get("/admin/update/status", headers=admin_enabled).json() == {"running": False, "result": None}
    (logs / self_update.LOCK_FILE).write_text("{}", encoding="utf-8")
    (logs / self_update.STATUS_FILE).write_text('{"status": "running"}', encoding="utf-8")
    assert client.get("/admin/update/status", headers=admin_enabled).json() == {"running": True, "result": "running"}


@pytest.mark.parametrize(
    ("record", "needle", "css"),
    [
        ('{"status": "ok", "from_version": "0.1.0", "to_version": "0.2.0"}', "Updated 0.1.0 &rarr; 0.2.0", "banner-ok"),
        (
            '{"status": "rolled_back", "from_version": "0.1.0", "failed_step": "migrate", "log_path": "L.log"}',
            "Update failed at <b>migrate</b>; rolled back to 0.1.0.",
            "banner-warn",
        ),
        ('{"status": "failed", "failed_step": "sync", "log_path": "L.log"}', "rollback failed too", "banner-bad"),
        ("{corrupt", "unreadable", "banner-bad"),
        ('{"status": "running"}', "stopped without finishing", "banner-bad"),
    ],
)
def test_update_page_shows_last_result_banner(client, admin_enabled, state, logs, record, needle, css):
    (logs / self_update.STATUS_FILE).write_text(record, encoding="utf-8")
    page = client.get("/admin/update", headers=admin_enabled).text
    assert needle in page
    assert f'class="banner {css}"' in page


def test_dashboard_has_server_update_tile(client, admin_enabled, state):
    page = client.get("/admin/", headers=admin_enabled).text
    assert 'href="/admin/update"' in page
    assert update_page.SERVER_UPDATE_ICON_PATHS in page
