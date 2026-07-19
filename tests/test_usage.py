#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/09 09:40:00.000000
Revised: 2026/07/18 19:33:27.761806

Per-endpoint usage tracking middleware and the admin usage dashboard, its
per-endpoint drill-down, and the per-user library drill-down.
"""

from conftest import ADMIN_BASIC as BASIC
from conftest import register

from renar_backend.database import SessionLocal
from renar_backend.models import EndpointStat, RequestDay


def _stats():
    db = SessionLocal()
    try:
        return db.query(EndpointStat).all()
    finally:
        db.close()


def _count(method, path, user_id=...):
    db = SessionLocal()
    try:
        q = db.query(EndpointStat).filter(EndpointStat.method == method, EndpointStat.path == path)
        if user_id is not ...:
            q = (
                q.filter(EndpointStat.user_id.is_(None))
                if user_id is None
                else q.filter(EndpointStat.user_id == user_id)
            )
        rows = q.all()
        return sum(r.count for r in rows)
    finally:
        db.close()


# ---------- tracking middleware ----------


def test_authenticated_request_recorded(client, alice):
    user, headers = alice
    before = _count("GET", "/auth/me", user["id"])
    client.get("/auth/me", headers=headers)
    client.get("/auth/me", headers=headers)
    assert _count("GET", "/auth/me", user["id"]) == before + 2


def test_templated_path_is_bucketed_not_exploded(client, alice):
    _, headers = alice
    item = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    client.get(f"/media/{item['id']}", headers=headers)
    client.get(f"/media/{item['id']}", headers=headers)
    # The route template is stored, so repeated IDs collapse into one row.
    assert _count("GET", "/media/{item_id}") == 2
    paths = {s.path for s in _stats()}
    assert not any(p.rstrip("/").endswith(str(item["id"])) for p in paths)


def test_anonymous_request_recorded_with_null_user(client):
    register(client, "alice")
    client.post("/auth/login", data={"username": "alice", "password": "password123"})
    assert _count("POST", "/auth/login", None) >= 1


def test_root_and_health_not_tracked(client):
    client.get("/")
    client.get("/health")
    paths = {s.path for s in _stats()}
    assert "/" not in paths
    assert "/health" not in paths


def test_admin_pages_not_tracked(client, admin_enabled):
    client.get("/admin", auth=BASIC)
    client.get("/admin/usage", auth=BASIC)
    assert not any(s.path.startswith("/admin") for s in _stats())


# ---------- usage dashboard ----------


def test_usage_page_requires_auth(client, admin_enabled):
    assert client.get("/admin/usage").status_code == 401


def test_usage_overview_shows_endpoint(client, admin_enabled, alice):
    _, headers = alice
    client.get("/auth/me", headers=headers)
    r = client.get("/admin/usage", auth=BASIC)
    assert r.status_code == 200
    assert "Requests by endpoint" in r.text
    # method + path render in separate elements; the path keeps its true case
    assert ">/auth/me<" in r.text
    assert "/Auth/Me" not in r.text  # the old capitalize bug must stay gone
    assert 'class="ep-method' in r.text
    assert "Connections per day" in r.text
    assert "New signups per day" in r.text


def test_usage_appears_in_dashboard(client, admin_enabled):
    r = client.get("/admin", auth=BASIC)
    assert 'href="/admin/usage"' in r.text


# ---------- endpoint drill-down ----------


def test_endpoint_detail_requires_auth(client, admin_enabled):
    assert client.get("/admin/usage/endpoint?method=GET&path=/media").status_code == 401


def test_endpoint_detail_lists_callers(client, admin_enabled, alice):
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers)
    r = client.get("/admin/usage/endpoint?method=POST&path=/media", auth=BASIC)
    assert r.status_code == 200
    assert user["username"] in r.text
    assert f'href="/admin/users/{user["id"]}"' in r.text  # links back to the user


# ---------- library drill-down ----------


def test_user_library_filters_by_type(client, admin_enabled, alice):
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers)
    client.post("/media", json={"media_type": "tv_show", "title": "Dune: Prophecy"}, headers=headers)
    r = client.get(f"/admin/users/{user['id']}/library?media_type=film", auth=BASIC)
    assert r.status_code == 200
    assert "Heat" in r.text
    assert "Dune: Prophecy" not in r.text


def test_user_library_filters_by_status(client, admin_enabled, alice):
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat", "status": "completed"}, headers=headers)
    client.post("/media", json={"media_type": "film", "title": "Dark", "status": "watching"}, headers=headers)
    r = client.get(f"/admin/users/{user['id']}/library?status=completed", auth=BASIC)
    assert r.status_code == 200
    assert "Heat" in r.text
    assert "Dark" not in r.text


def test_user_library_unknown_user_not_found(client, admin_enabled):
    assert client.get("/admin/users/9999/library", auth=BASIC).status_code == 404


def test_user_detail_links_to_library(client, admin_enabled, alice):
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers)
    r = client.get(f"/admin/users/{user['id']}", auth=BASIC)
    assert f"/admin/users/{user['id']}/library?media_type=film" in r.text


# ---------- per-user endpoint aggregate + full breakdown ----------


def test_user_detail_shows_requests_per_day_chart(client, admin_enabled, alice):
    user, headers = alice
    for _ in range(3):
        client.get("/auth/me", headers=headers)
    r = client.get(f"/admin/users/{user['id']}", auth=BASIC)
    assert r.status_code == 200
    assert "Requests per day" in r.text
    assert f"/admin/users/{user['id']}/endpoints" in r.text  # link into the full breakdown


def test_authenticated_request_records_request_day(client, alice):
    user, headers = alice
    client.get("/auth/me", headers=headers)
    client.get("/auth/me", headers=headers)
    db = SessionLocal()
    try:
        rows = db.query(RequestDay).filter(RequestDay.user_id == user["id"]).all()
        assert len(rows) == 1  # same day collapses into one row
        assert rows[0].count >= 2
    finally:
        db.close()


def test_anonymous_request_records_no_request_day(client):
    register(client, "alice")
    client.post("/auth/login", data={"username": "alice", "password": "password123"})
    db = SessionLocal()
    try:
        assert db.query(RequestDay).count() == 0  # only authenticated requests count
    finally:
        db.close()


def test_user_endpoints_full_page_lists_all(client, admin_enabled, alice):
    user, headers = alice
    client.get("/auth/me", headers=headers)
    item = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers).json()
    client.get(f"/media/{item['id']}", headers=headers)
    r = client.get(f"/admin/users/{user['id']}/endpoints", auth=BASIC)
    assert r.status_code == 200
    assert ">/auth/me<" in r.text
    assert ">/media/{item_id}<" in r.text


def test_user_endpoints_full_page_requires_auth(client, admin_enabled, alice):
    user, _ = alice
    assert client.get(f"/admin/users/{user['id']}/endpoints").status_code == 401


def test_user_endpoints_unknown_user_not_found(client, admin_enabled):
    assert client.get("/admin/users/9999/endpoints", auth=BASIC).status_code == 404


def test_chart_bars_expose_hover_value(client, admin_enabled, alice):
    user, headers = alice
    client.get("/auth/me", headers=headers)
    r = client.get(f"/admin/users/{user['id']}", auth=BASIC).text
    # bars carry the value in data-tip, and the floating tooltip is wired up
    assert 'data-tip="' in r
    assert 'id="chart-tip"' in r
    assert "getElementById('chart-tip')" in r


# ---------- cascade on delete ----------


def test_admin_delete_user_removes_endpoint_stats(client, admin_enabled, alice):
    user, headers = alice
    client.get("/auth/me", headers=headers)
    assert _count("GET", "/auth/me", user["id"]) >= 1

    assert client.post(f"/admin/users/{user['id']}/delete", auth=BASIC, follow_redirects=False).status_code == 303

    db = SessionLocal()
    try:
        assert db.query(EndpointStat).filter(EndpointStat.user_id == user["id"]).count() == 0
        assert db.query(RequestDay).filter(RequestDay.user_id == user["id"]).count() == 0
    finally:
        db.close()


def test_self_delete_removes_usage_rows(client, alice):
    user, headers = alice
    client.get("/auth/me", headers=headers)
    assert client.delete("/auth/me", headers=headers).status_code == 204

    db = SessionLocal()
    try:
        # the trailing DELETE /auth/me request must not resurrect rows for the
        # now-deleted user (no dangling FK)
        assert db.query(EndpointStat).filter(EndpointStat.user_id == user["id"]).count() == 0
        assert db.query(RequestDay).filter(RequestDay.user_id == user["id"]).count() == 0
    finally:
        db.close()
