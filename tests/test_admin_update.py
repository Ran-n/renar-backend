#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:19.233482
Revised: 2026/11/09 23:36:45.140381

The admin Server Update page and its routes: each state's rendering (the
Update button enabled only when an update is available), the POST re-check,
lock and launch, the result banner, and the status endpoint the page polls.
update_check.check()/launch() are replaced here; test_update_check.py and
test_self_update.py cover them on real git repos.
"""

import pytest

from renar_backend import self_update, update_check
from renar_backend.routers.admin import update as update_page


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(update_check, "REPO", tmp_path)
    (tmp_path / "logs").mkdir()
    return tmp_path / "logs"


def _status(**kw) -> update_check.UpdateStatus:
    base = {"branch": "master", "head_sha": "a" * 40, "remote_sha": "b" * 40}
    return update_check.UpdateStatus(**{**base, **kw})


AVAILABLE = {"behind": ["bbbbbbb add feature", "ccccccc fix bug"], "behind_count": 2, "remote_version": "9.9.9"}


@pytest.fixture
def state(monkeypatch, logs):
    def set_state(**kw):
        monkeypatch.setattr(update_check, "check", lambda *a, **k: _status(**kw))

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


def test_available_renders_commits_and_enabled_button(client, admin_enabled, state):
    state(**AVAILABLE)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "2 new commits" in page
    assert "<code>bbbbbbb</code> add feature" in page
    assert "Update to 9.9.9" in page
    assert "disabled" not in _button(page)


def test_available_same_version_labels_commit_count(client, admin_enabled, state):
    from renar_backend.main import backend_version

    state(**{**AVAILABLE, "remote_version": backend_version()})
    assert "Update (2 commits)" in client.get("/admin/update", headers=admin_enabled).text


def test_more_commits_than_listed(client, admin_enabled, state):
    state(**{**AVAILABLE, "behind_count": 60})
    assert "and 58 more" in client.get("/admin/update", headers=admin_enabled).text


def test_blocked_dirty_renders_reason_and_paths(client, admin_enabled, state):
    state(
        blocked_reason="The working tree has uncommitted changes; commit or discard them first.", dirty_paths=["a.py"]
    )
    page = client.get("/admin/update", headers=admin_enabled).text
    assert "Blocked" in page
    assert "uncommitted changes" in page
    assert "<code>a.py</code>" in page
    assert "disabled" in _button(page)
    assert ">Retry</a>" not in page


def test_fetch_failure_offers_retry(client, admin_enabled, state):
    state(blocked_reason="Couldn't check for updates: timed out", retryable=True)
    page = client.get("/admin/update", headers=admin_enabled).text
    assert 'href="/admin/update">Retry</a>' in page
    assert "Up to date" not in page


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
    state(blocked_reason="Checked out on feature; switch to master to update.")
    monkeypatch.setattr(update_check, "launch", lambda *a, **k: pytest.fail("must not launch"))
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 409
    assert r.json()["detail"] == "Checked out on feature; switch to master to update."


def test_update_post_409s_when_up_to_date(client, admin_enabled, state):
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 409
    assert r.json()["detail"] == "Already up to date."


def test_update_post_launches_and_returns_202(client, admin_enabled, state, monkeypatch, logs):
    state(**AVAILABLE)
    launched = []
    monkeypatch.setattr(update_check, "launch", lambda st, version: launched.append((st, version)) or logs / "x.log")
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 202
    assert r.json()["log_path"].endswith("x.log")
    assert launched and launched[0][0].remote_sha == "b" * 40
    assert (logs / self_update.LOCK_FILE).exists()  # held for the helper, which releases it
    # a second press while it runs
    r = client.post("/admin/update", headers=admin_enabled)
    assert r.status_code == 409
    assert "already in progress" in r.json()["detail"]


def test_update_post_launch_failure_releases_lock(client, admin_enabled, state, monkeypatch, logs):
    state(**AVAILABLE)

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
