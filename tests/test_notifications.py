#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.529415
Revised: 2026/09/02 10:58:00.022795

Notification center + the new-episode checker (with an injected TMDB fetch).
"""

from datetime import date, timedelta

from fastapi import HTTPException

from renar_backend.database import SessionLocal
from renar_backend.models import LibraryEntry, Notification, Title, WatchStatus
from renar_backend.social.notifier import check_new_episodes


def _seed_notification(user_id: int, **overrides) -> int:
    db = SessionLocal()
    try:
        n = Notification(user_id=user_id, title="New episode: Dark", body="S01E01", **overrides)
        db.add(n)
        db.commit()
        return n.id
    finally:
        db.close()


# ---------- endpoints ----------


def test_list_empty(client, alice):
    _, headers = alice
    assert client.get("/notifications", headers=headers).json() == []
    assert client.get("/notifications/unread_count", headers=headers).json() == {"count": 0}


def test_list_and_unread_count(client, alice):
    user, headers = alice
    _seed_notification(user["id"])
    listed = client.get("/notifications", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["title"] == "New episode: Dark"
    assert listed[0]["read"] is False
    assert client.get("/notifications/unread_count", headers=headers).json() == {"count": 1}


def test_mark_read(client, alice):
    user, headers = alice
    nid = _seed_notification(user["id"])
    assert client.post(f"/notifications/{nid}/read", headers=headers).status_code == 204
    assert client.get("/notifications", headers=headers).json()[0]["read"] is True
    assert client.get("/notifications/unread_count", headers=headers).json() == {"count": 0}


def test_unread_only_filter(client, alice):
    user, headers = alice
    nid = _seed_notification(user["id"], season=1, episode=1)
    _seed_notification(user["id"], season=1, episode=2)
    client.post(f"/notifications/{nid}/read", headers=headers)
    unread = client.get("/notifications", params={"unread_only": True}, headers=headers).json()
    assert len(unread) == 1
    assert unread[0]["read"] is False


def test_read_all(client, alice):
    user, headers = alice
    _seed_notification(user["id"], season=1, episode=1)
    _seed_notification(user["id"], season=1, episode=2)
    assert client.post("/notifications/read_all", headers=headers).status_code == 204
    assert client.get("/notifications/unread_count", headers=headers).json() == {"count": 0}


def test_delete_notification(client, alice):
    user, headers = alice
    nid = _seed_notification(user["id"])
    assert client.delete(f"/notifications/{nid}", headers=headers).status_code == 204
    assert client.get("/notifications", headers=headers).json() == []


def test_delete_all_notifications(client, alice):
    user, headers = alice
    _seed_notification(user["id"], season=1, episode=1)
    _seed_notification(user["id"], season=1, episode=2)
    assert client.delete("/notifications", headers=headers).status_code == 204
    assert client.get("/notifications", headers=headers).json() == []


def test_delete_all_notifications_does_not_affect_other_users(client, alice, bob):
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _seed_notification(alice_user["id"])
    _seed_notification(bob_user["id"])
    assert client.delete("/notifications", headers=alice_headers).status_code == 204
    assert client.get("/notifications", headers=alice_headers).json() == []
    assert len(client.get("/notifications", headers=bob_headers).json()) == 1


def test_other_users_notification_not_found(client, alice, bob):
    alice_user, _ = alice
    _, bob_headers = bob
    nid = _seed_notification(alice_user["id"])
    assert client.post(f"/notifications/{nid}/read", headers=bob_headers).status_code == 404
    assert client.delete(f"/notifications/{nid}", headers=bob_headers).status_code == 404


def test_missing_notification_not_found(client, alice):
    _, headers = alice
    assert client.post("/notifications/9999/read", headers=headers).status_code == 404
    assert client.delete("/notifications/9999", headers=headers).status_code == 404


# ---------- new-episode checker ----------


def _tracked_show(client, headers) -> dict:
    r = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 70523, "status": "watching"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _fake_fetch(air_date: str):
    def fetch(tmdb_id: int) -> dict:
        return {
            "name": "Dark",
            "last_episode_to_air": {
                "air_date": air_date,
                "season_number": 2,
                "episode_number": 3,
                "name": "Ghosts",
            },
        }

    return fetch


def test_checker_notifies_about_recent_episode(client, alice):
    from renar_backend import events

    user, headers = alice
    _tracked_show(client, headers)
    aired = (date.today() - timedelta(days=1)).isoformat()
    queue = events.subscribe(user["id"])
    try:
        db = SessionLocal()
        try:
            assert check_new_episodes(db, fetch=_fake_fetch(aired)) == 1
            # a second run must not create a duplicate
            assert check_new_episodes(db, fetch=_fake_fetch(aired)) == 0
        finally:
            db.close()

        listed = client.get("/notifications", headers=headers).json()
        assert len(listed) == 1
        assert listed[0]["kind"] == "new_episode"
        assert (listed[0]["season"], listed[0]["episode"]) == (2, 3)

        # a real new-episode notification must fan out to the user's other open
        # sessions (see events.py) so a second tab's bell updates immediately —
        # the no-duplicate second run must not fire a second event.
        assert queue.get_nowait() == "notification_changed"
        assert queue.empty()
    finally:
        events.unsubscribe(user["id"], queue)


def test_checker_skips_old_future_and_malformed_air_dates(client, alice):
    _, headers = alice
    _tracked_show(client, headers)
    db = SessionLocal()
    try:
        old = (date.today() - timedelta(days=30)).isoformat()
        future = (date.today() + timedelta(days=7)).isoformat()
        for air in (old, future, "not-a-date"):
            assert check_new_episodes(db, fetch=_fake_fetch(air)) == 0
    finally:
        db.close()


def test_checker_skips_already_watched_episode(client, alice):
    _, headers = alice
    show = _tracked_show(client, headers)
    client.put(f"/media/{show['id']}/episodes/2/3", json={"watched": True}, headers=headers)
    aired = (date.today() - timedelta(days=1)).isoformat()
    db = SessionLocal()
    try:
        assert check_new_episodes(db, fetch=_fake_fetch(aired)) == 0
    finally:
        db.close()


def test_checker_survives_fetch_failure(client, alice):
    _, headers = alice
    _tracked_show(client, headers)

    def broken_fetch(tmdb_id: int) -> dict:
        raise RuntimeError("TMDB down")

    db = SessionLocal()
    try:
        assert check_new_episodes(db, fetch=broken_fetch) == 0
    finally:
        db.close()


def test_checker_delinks_dead_tmdb_id_on_404(client, alice):
    """A 404 from TMDB means the id is gone — clear it for re-matching."""
    _, headers = alice
    _tracked_show(client, headers)

    def not_found_fetch(tmdb_id: int) -> dict:
        raise HTTPException(status_code=404, detail="Not found")

    db = SessionLocal()
    try:
        assert check_new_episodes(db, fetch=not_found_fetch) == 0
        title = db.query(Title).filter_by(title="Dark").one()
        assert title.tmdb_id is None
    finally:
        db.close()


def test_checker_skips_show_with_no_air_date(client, alice):
    """Missing air_date in last_episode_to_air must not create a notification."""
    _, headers = alice
    _tracked_show(client, headers)

    def fetch_no_air_date(tmdb_id: int) -> dict:
        return {
            "name": "Dark",
            "last_episode_to_air": {
                "air_date": None,
                "season_number": 2,
                "episode_number": 3,
                "name": "Episode",
            },
        }

    db = SessionLocal()
    try:
        assert check_new_episodes(db, fetch=fetch_no_air_date) == 0
    finally:
        db.close()


def test_checker_reactivates_completed_show_on_new_episode(client, alice):
    """A show parked as 'completed' must be flipped back to 'watching' when
    a new unwatched episode airs so it reappears on Home."""
    user, headers = alice
    show = _tracked_show(client, headers)

    # move to completed directly in the DB
    db = SessionLocal()
    try:
        db.get(LibraryEntry, show["id"]).status = WatchStatus.completed
        db.commit()
    finally:
        db.close()

    aired = (date.today() - timedelta(days=1)).isoformat()
    db = SessionLocal()
    try:
        n = check_new_episodes(db, fetch=_fake_fetch(aired))
        assert n == 1
        entry = db.get(LibraryEntry, show["id"])
        assert entry.status == WatchStatus.watching
    finally:
        db.close()
