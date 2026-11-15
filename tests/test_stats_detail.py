#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:00:36.004449
Revised: 2026/11/13 15:35:12.523138

GET /stats aggregation details (favourites, completed shows, streaks, time
windows, most-watched) and the ranking endpoints' less-travelled paths.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeWatch, LibraryEntry, User, utcnow
from renar_backend.routers import stats
from renar_backend.routers.stats import _as_utc, _streaks, _total_watch_minutes_by_user


def _set_premium(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()


def _add(client, headers, **fields) -> dict:
    r = client.post("/media", json=fields, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _set_watch_times(item_id: int, *when: datetime) -> None:
    """Backdate an item's episode watches, oldest episode first."""
    db = SessionLocal()
    try:
        watches = (
            db.query(EpisodeWatch)
            .filter(EpisodeWatch.media_item_id == item_id)
            .order_by(EpisodeWatch.season, EpisodeWatch.episode)
            .all()
        )
        assert len(watches) == len(when)
        for watch, ts in zip(watches, when, strict=True):
            watch.watched_at = ts
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_as_utc_tags_naive_datetimes_and_keeps_aware_ones():
    naive = datetime(2026, 1, 2, 3, 4)
    assert _as_utc(naive) == naive.replace(tzinfo=UTC)
    aware = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    assert _as_utc(aware) is aware


def test_streaks_empty():
    assert _streaks([]) == (0, 0)


def test_streaks_current_run_ending_today():
    today = date.today()
    days = [today - timedelta(days=n) for n in (9, 8, 2, 1, 0)]
    assert _streaks(days) == (3, 3)


def test_streaks_alive_as_of_yesterday():
    today = date.today()
    days = [today - timedelta(days=n) for n in (3, 2, 1)]
    assert _streaks(days) == (3, 3)


def test_streaks_longest_run_in_the_past_and_none_current():
    today = date.today()
    days = [today - timedelta(days=n) for n in (20, 19, 18, 17, 5)]
    assert _streaks(days) == (0, 4)


def test_streaks_current_run_stops_at_a_gap():
    today = date.today()
    days = [today - timedelta(days=n) for n in (4, 3, 1, 0)]
    assert _streaks(days) == (2, 2)


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------


def test_stats_counts_favourites_ratings_and_deciles(client, alice):
    _, headers = alice
    heat = _add(client, headers, media_type="film", title="Heat", status="completed", rating=95)
    client.patch(f"/media/{heat['id']}", json={"is_favorite": True}, headers=headers)
    _add(client, headers, media_type="film", title="Alien", status="completed", rating=10)
    _add(client, headers, media_type="film", title="Saw", status="completed", rating=11)

    s = client.get("/stats", headers=headers).json()

    assert s["favorites"] == 1
    assert s["avg_rating"] == round((95 + 10 + 11) / 3)
    assert s["rating_distribution"] == {"1-10": 1, "11-20": 1, "91-100": 1}


def test_stats_completed_show_without_episode_tracking_counts_in_full(client, alice):
    _, headers = alice
    _add(
        client,
        headers,
        media_type="tv_show",
        title="Dark",
        status="completed",
        total_episodes=26,
        runtime_minutes=50,
    )

    s = client.get("/stats", headers=headers).json()

    assert s["shows_completed"] == 1
    assert s["shows_watching"] == 0
    assert s["episodes_watched"] == 26
    assert s["tv_minutes"] == 26 * 50
    assert s["most_watched_shows"][0]["episodes"] == 26


def test_stats_unwatched_show_is_left_out_of_most_watched(client, alice):
    _, headers = alice
    _add(client, headers, media_type="tv_show", title="Later", status="want_to_watch", total_episodes=8)
    show = _add(client, headers, media_type="tv_show", title="Now", runtime_minutes=30)
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1]}, headers=headers)

    s = client.get("/stats", headers=headers).json()

    assert s["shows_watching"] == 1
    assert [m["title"] for m in s["most_watched_shows"]] == ["Now"]
    assert s["by_status"] == {"want_to_watch": 1, "watching": 1}


def test_stats_time_windows_and_weekday(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", runtime_minutes=50)
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2, 3]}, headers=headers)
    now = datetime.now(UTC)
    old, mid, recent = now - timedelta(days=60), now - timedelta(days=15), now - timedelta(hours=1)
    _set_watch_times(show["id"], old, mid, recent)

    s = client.get("/stats", headers=headers).json()

    assert s["episodes_last_7_days"] == 1
    assert s["episodes_last_30_days"] == 2
    assert sum(s["activity_by_weekday"].values()) == 3
    assert s["most_active_day"] in s["activity_by_weekday"]
    assert s["current_streak_days"] == 1
    assert s["longest_streak_days"] == 1


# ---------------------------------------------------------------------------
# _total_watch_minutes_by_user (trigger cross-check helper)
# ---------------------------------------------------------------------------


def test_total_watch_minutes_for_every_user(client, alice, bob):
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _add(client, alice_headers, media_type="film", title="Heat", status="completed", runtime_minutes=170)
    _add(client, alice_headers, media_type="film", title="Alien", status="want_to_watch", runtime_minutes=117)
    _add(
        client,
        bob_headers,
        media_type="tv_show",
        title="Dark",
        status="completed",
        total_episodes=10,
        runtime_minutes=50,
    )
    db = SessionLocal()
    try:
        totals = _total_watch_minutes_by_user(db)
        rows = db.query(LibraryEntry).count()
    finally:
        db.close()

    assert rows == 3
    assert totals == {alice_user["id"]: 170, bob_user["id"]: 500}


# ---------------------------------------------------------------------------
# ranking endpoints
# ---------------------------------------------------------------------------


def test_ranking_metrics_endpoint_lists_metrics(client, alice):
    user, headers = alice
    _set_premium(user["id"])

    r = client.get("/stats/ranking/metrics", headers=headers)

    assert r.status_code == 200
    assert r.json() == [{"key": "watch_time", "label": "Total watch time", "unit": "minutes"}]


def test_ranking_selects_the_requested_metric(client, alice):
    user, headers = alice
    _set_premium(user["id"])

    r = client.get("/stats/ranking", params={"metric": "watch_time"}, headers=headers)

    assert r.status_code == 200
    assert r.json()["metric"] == "watch_time"


def test_ranking_404s_when_no_metric_is_configured(client, alice, monkeypatch):
    user, headers = alice
    _set_premium(user["id"])
    monkeypatch.setattr(stats, "RANKING_METRICS", {})

    r = client.get("/stats/ranking", headers=headers)

    assert r.status_code == 404
    assert r.json()["detail"] == "No ranking metrics configured"


@pytest.mark.parametrize("path", ["/stats/ranking", "/stats/ranking/metrics"])
def test_ranking_endpoints_403_when_the_feature_is_off(client, alice, monkeypatch, path):
    user, headers = alice
    _set_premium(user["id"])
    monkeypatch.setattr(stats, "feature_enabled", lambda feature: False)

    r = client.get(path, headers=headers)

    assert r.status_code == 403
