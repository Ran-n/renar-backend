#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/16 09:55:31.503656
Revised: 2026/07/16 09:55:31.503656

Watch-time leaderboard (/stats/ranking): the users.total_watch_minutes
column maintained by a Postgres trigger (migration a7c2e9f4b816, mirrored
for tests by models.py registering the same DDL against LibraryEntry's
"after_create" event), and the ranking endpoint that reads it.
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from renar_backend.database import SessionLocal
from renar_backend.models import AppCounters, LibraryEntry, MediaType, Title, User, WatchStatus, utcnow
from renar_backend.routers.stats import _total_watch_minutes_by_user


def _set_premium(user_id: int, days: int = 30) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _watch_minutes(user_id: int) -> int:
    db = SessionLocal()
    try:
        return db.get(User, user_id).total_watch_minutes
    finally:
        db.close()


def _total_users_counter() -> int:
    db = SessionLocal()
    try:
        return db.get(AppCounters, 1).total_users
    finally:
        db.close()


def test_ranking_requires_premium(client, alice):
    _, headers = alice
    assert client.get("/stats/ranking", headers=headers).status_code == 403


def test_trigger_updates_on_completed_film(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    assert _watch_minutes(user["id"]) == 0
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=headers,
    )
    assert _watch_minutes(user["id"]) == 170


def test_trigger_updates_on_episode_watch(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2, 3]}, headers=headers)
    assert _watch_minutes(user["id"]) == 3 * 50


def test_trigger_updates_on_delete(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=headers,
    ).json()
    assert _watch_minutes(user["id"]) == 170
    client.delete(f"/media/{item['id']}", headers=headers)
    assert _watch_minutes(user["id"]) == 0


def test_trigger_ignores_unrelated_update(client, alice):
    """Rating/notes changes don't affect watch minutes — the trigger's WHEN
    clause should skip firing for those, not just happen to compute the same
    number; this only proves the number stays right, which is what matters."""
    user, headers = alice
    _set_premium(user["id"])
    item = client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=headers,
    ).json()
    client.patch(f"/media/{item['id']}", json={"rating": 8, "notes": "great"}, headers=headers)
    assert _watch_minutes(user["id"]) == 170


def test_trigger_cascades_on_shared_title_runtime_change(client, alice, bob):
    """A Title's runtime_minutes is shared across every user who has it in
    their library — changing it should update all of them, not just whoever
    happened to trigger the change."""
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    _set_premium(bob_user["id"])
    for headers in (alice_headers, bob_headers):
        client.post(
            "/media",
            json={
                "media_type": "film",
                "title": "Heat",
                "tmdb_id": 949,
                "status": "completed",
                "runtime_minutes": 170,
            },
            headers=headers,
        )
    assert _watch_minutes(alice_user["id"]) == 170
    assert _watch_minutes(bob_user["id"]) == 170

    db = SessionLocal()
    try:
        title = db.query(Title).filter(Title.tmdb_id == 949).first()
        title.runtime_minutes = 200
        db.commit()
    finally:
        db.close()

    assert _watch_minutes(alice_user["id"]) == 200
    assert _watch_minutes(bob_user["id"]) == 200


def test_column_matches_independent_computation(client, alice):
    """Cross-check the trigger-maintained column against
    _total_watch_minutes_by_user, an independent from-scratch computation."""
    user, headers = alice
    _set_premium(user["id"])
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=headers,
    )
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2]}, headers=headers)

    db = SessionLocal()
    try:
        expected = _total_watch_minutes_by_user(db, user["id"]).get(user["id"], 0)
        actual = db.get(User, user["id"]).total_watch_minutes
        assert actual == expected
    finally:
        db.close()


def test_ranking_rank_and_percentile(client, alice, bob):
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    _set_premium(bob_user["id"])
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 200},
        headers=alice_headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed", "runtime_minutes": 100},
        headers=bob_headers,
    )
    r = client.get("/stats/ranking", headers=alice_headers).json()
    assert r["rank"] == 1
    assert r["value"] == 200
    assert r["total_users"] == 2
    assert r["percentile"] == 50.0

    r_bob = client.get("/stats/ranking", headers=bob_headers).json()
    assert r_bob["rank"] == 2
    assert r_bob["value"] == 100
    assert r_bob["percentile"] == 100.0


def test_ranking_ties_break_by_registration_order(client, make_user):
    first, first_headers = make_user("first_reg")
    second, second_headers = make_user("second_reg")
    _set_premium(first["id"])
    _set_premium(second["id"])
    for headers in (first_headers, second_headers):
        client.post(
            "/media",
            json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
            headers=headers,
        )
    r_first = client.get("/stats/ranking", headers=first_headers).json()
    r_second = client.get("/stats/ranking", headers=second_headers).json()
    assert r_first["rank"] < r_second["rank"]


def test_ranking_metrics_bundled_and_ordered(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.get("/stats/ranking", headers=headers).json()
    assert r["metrics"] == [{"key": "watch_time", "label": "Total watch time", "unit": "minutes"}]


def test_ranking_unknown_metric_404s(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    assert client.get("/stats/ranking?metric=nonexistent", headers=headers).status_code == 404


def test_zero_activity_user_counted_not_dropped(client, alice, bob):
    """Regression test for the original bug: a user with zero watch time must
    still be counted in total_users and ranked last, not silently excluded
    from the pool (which used to produce e.g. "#7 of 6")."""
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    _set_premium(bob_user["id"])
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=alice_headers,
    )
    # bob never marks anything watched — total_watch_minutes stays 0

    r_alice = client.get("/stats/ranking", headers=alice_headers).json()
    assert r_alice["total_users"] == 2
    assert r_alice["rank"] == 1

    r_bob = client.get("/stats/ranking", headers=bob_headers).json()
    assert r_bob["total_users"] == 2
    assert r_bob["rank"] == 2
    assert r_bob["value"] == 0


def test_explicit_zero_runtime_not_replaced_by_default(client, alice):
    """runtime_minutes=0 is a real, schema-allowed value — the trigger's
    COALESCE(x, default) must preserve it, not silently substitute the
    110-minute default the way a naive `x or default` would."""
    user, headers = alice
    _set_premium(user["id"])
    client.post(
        "/media",
        json={"media_type": "film", "title": "Short Film", "status": "completed", "runtime_minutes": 0},
        headers=headers,
    )
    assert _watch_minutes(user["id"]) == 0

    db = SessionLocal()
    try:
        expected = _total_watch_minutes_by_user(db, user["id"]).get(user["id"], 0)
    finally:
        db.close()
    assert expected == 0  # /stats and /stats/ranking must agree


def test_trigger_decrements_on_episode_unwatch(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2, 3]}, headers=headers)
    assert _watch_minutes(user["id"]) == 3 * 50
    client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [2, 3], "watched": False},
        headers=headers,
    )
    assert _watch_minutes(user["id"]) == 1 * 50


def test_trigger_decrements_on_uncompleting_film(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=headers,
    ).json()
    assert _watch_minutes(user["id"]) == 170
    client.patch(f"/media/{item['id']}", json={"status": "dropped"}, headers=headers)
    assert _watch_minutes(user["id"]) == 0


def test_multiple_items_sum_correctly(client, alice):
    """Not just single-item deltas: several films/shows for the same user
    must aggregate, not overwrite each other's contribution."""
    user, headers = alice
    _set_premium(user["id"])
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed", "runtime_minutes": 117},
        headers=headers,
    )
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2]}, headers=headers)
    assert _watch_minutes(user["id"]) == 170 + 117 + 2 * 50


def test_book_and_youtube_never_contribute(client, alice):
    """Only film/tv_show count toward watch minutes, even when marked
    completed — a completed book or video must contribute nothing."""
    user, headers = alice
    _set_premium(user["id"])
    client.post(
        "/media",
        json={"media_type": "book", "title": "Dune", "status": "completed", "page_count": 412},
        headers=headers,
    )
    client.post(
        "/media",
        json={"media_type": "youtube", "title": "Some Video", "status": "completed", "url": "https://youtu.be/x"},
        headers=headers,
    )
    assert _watch_minutes(user["id"]) == 0


def test_trigger_ignores_unrelated_update_on_tv_show(client, alice):
    """Same guard as the film case, but for a tv_show entry — current_season/
    current_episode/is_favorite changes shouldn't touch the trigger either."""
    user, headers = alice
    _set_premium(user["id"])
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.post(f"/media/{show['id']}/episodes/bulk", json={"season": 1, "episodes": [1, 2]}, headers=headers)
    assert _watch_minutes(user["id"]) == 100
    client.patch(f"/media/{show['id']}", json={"is_favorite": True}, headers=headers)
    assert _watch_minutes(user["id"]) == 100


def test_non_premium_user_still_counts_toward_others_ranking(client, alice, bob):
    """Premium only gates who can VIEW /stats/ranking — a free user's watch
    time must still count toward everyone else's rank/total_users, since the
    leaderboard reflects all registered users, not just premium ones."""
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    # bob is NOT made premium — can't view /stats/ranking himself
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 500},
        headers=bob_headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed", "runtime_minutes": 100},
        headers=alice_headers,
    )

    assert client.get("/stats/ranking", headers=bob_headers).status_code == 403

    r_alice = client.get("/stats/ranking", headers=alice_headers).json()
    assert r_alice["total_users"] == 2
    assert r_alice["rank"] == 2  # bob's 500 minutes outrank alice's 100, even though bob can't see this


def test_ranking_middle_rank_with_three_users(client, alice, bob, make_user):
    a_user, a_headers = alice
    b_user, b_headers = bob
    c_user, c_headers = make_user("carol")
    for uid in (a_user["id"], b_user["id"], c_user["id"]):
        _set_premium(uid)
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 300},
        headers=a_headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed", "runtime_minutes": 200},
        headers=b_headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Up", "status": "completed", "runtime_minutes": 100},
        headers=c_headers,
    )
    r_b = client.get("/stats/ranking", headers=b_headers).json()
    assert r_b["rank"] == 2
    assert r_b["total_users"] == 3
    assert r_b["value"] == 200
    assert r_b["percentile"] == round(2 / 3 * 100, 1)


def test_trigger_updates_via_direct_patch_episodes_watched(client, alice):
    """episodes_watched is also settable straight through PATCH /media/{id}
    (LibraryEntryUpdate), a different application code path than
    /episodes/bulk (_sync_progress) — the trigger fires on the row's actual
    value changing, not on which endpoint caused it, but that needs to be
    verified through this specific path too, not just assumed from the
    bulk-endpoint test."""
    user, headers = alice
    _set_premium(user["id"])
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()
    client.patch(f"/media/{show['id']}", json={"episodes_watched": 4}, headers=headers)
    assert _watch_minutes(user["id"]) == 4 * 50


def test_concurrent_writes_no_lost_update(client, alice):
    """Multiple concurrent requests marking different episodes of the same
    show watched must not lose an update — each is its own transaction doing
    total_watch_minutes += delta on the same user row, which is only safe
    if Postgres's row lock actually serializes them rather than each reading
    a stale pre-write value."""
    import concurrent.futures

    user, headers = alice
    _set_premium(user["id"])
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "total_episodes": 26, "runtime_minutes": 50},
        headers=headers,
    ).json()

    episodes = list(range(1, 11))  # 10 distinct episodes, marked concurrently

    def mark(ep: int):
        return client.put(f"/media/{show['id']}/episodes/1/{ep}", json={"watched": True}, headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(mark, episodes))

    assert all(r.status_code == 200 for r in results)
    assert _watch_minutes(user["id"]) == 10 * 50


def test_account_deletion_cascade_does_not_crash(client, alice, bob):
    """Deleting an account cascades an ORM delete of every one of the user's
    media_items rows (accounts.delete_account), each firing the watch-minutes
    trigger while the user row still exists (children deleted before the
    parent) — must not crash, and must leave other users' totals untouched."""
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    _set_premium(bob_user["id"])
    client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "status": "completed", "runtime_minutes": 170},
        headers=alice_headers,
    )
    client.post(
        "/media",
        json={"media_type": "film", "title": "Alien", "status": "completed", "runtime_minutes": 100},
        headers=bob_headers,
    )
    assert _watch_minutes(bob_user["id"]) == 100

    resp = client.delete("/auth/me", headers=alice_headers)
    assert resp.status_code == 204

    db = SessionLocal()
    try:
        assert db.get(User, alice_user["id"]) is None
    finally:
        db.close()
    assert _watch_minutes(bob_user["id"]) == 100  # unaffected by alice's deletion


def test_trigger_handles_user_id_reassignment(client, alice, bob):
    """user_id on an existing entry isn't settable via the API today
    (LibraryEntryUpdate has no such field) — but the trigger function has
    explicit branching for OLD.user_id vs NEW.user_id, so it needs its own
    test rather than staying reachable only through a manual DB script.
    Exercised directly at the ORM level since there's no API path to it."""
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    _set_premium(bob_user["id"])

    db = SessionLocal()
    try:
        title = Title(media_type=MediaType.film, title="Reassign Test", runtime_minutes=90, title_key="reassign-test")
        db.add(title)
        db.commit()
        entry = LibraryEntry(user_id=alice_user["id"], title_id=title.id, status=WatchStatus.completed)
        db.add(entry)
        db.commit()
        assert _watch_minutes(alice_user["id"]) == 90
        assert _watch_minutes(bob_user["id"]) == 0

        entry.user_id = bob_user["id"]
        db.commit()
        assert _watch_minutes(alice_user["id"]) == 0
        assert _watch_minutes(bob_user["id"]) == 90

        db.delete(entry)
        db.delete(title)
        db.commit()
    finally:
        db.close()


def test_title_id_reassignment_is_a_known_gap(client, alice):
    """Documents a real, deliberate limitation rather than leaving it as a
    silent absence: the media_items trigger's WHEN clause only watches
    status/episodes_watched/user_id, not title_id. Reassigning an entry to a
    different title without touching those three fields in the same UPDATE
    does NOT recompute total_watch_minutes. This is unreachable through the
    API today (LibraryEntryUpdate has no title_id field) — if that ever
    changes, this test should start failing and prompt widening the WHEN
    clause, rather than the gap staying invisible."""
    user, headers = alice
    _set_premium(user["id"])

    db = SessionLocal()
    try:
        title_a = Title(media_type=MediaType.film, title="Title A", runtime_minutes=90, title_key="title-a-gap")
        title_b = Title(media_type=MediaType.film, title="Title B", runtime_minutes=200, title_key="title-b-gap")
        db.add_all([title_a, title_b])
        db.commit()
        entry = LibraryEntry(user_id=user["id"], title_id=title_a.id, status=WatchStatus.completed)
        db.add(entry)
        db.commit()
        assert _watch_minutes(user["id"]) == 90

        entry.title_id = title_b.id  # status/episodes_watched/user_id all unchanged
        db.commit()
        # known gap: still 90, not 200 — the trigger didn't fire for this change
        assert _watch_minutes(user["id"]) == 90

        db.delete(entry)
        db.delete(title_a)
        db.delete(title_b)
        db.commit()
    finally:
        db.close()


def test_total_users_counter_matches_actual_count(client, make_user):
    """app_counters.total_users (the ranking denominator) must track real
    registrations exactly — it exists specifically to avoid a live COUNT(*)
    FROM users, so it needs its own correctness check independent of the
    ranking endpoint that reads it."""
    db = SessionLocal()
    try:
        before_counter = db.get(AppCounters, 1).total_users
        before_actual = db.query(User).count()
        assert before_counter == before_actual
    finally:
        db.close()

    make_user("counter_check_user")

    db = SessionLocal()
    try:
        after_counter = db.get(AppCounters, 1).total_users
        after_actual = db.query(User).count()
        assert after_counter == after_actual == before_actual + 1
    finally:
        db.close()


def test_total_users_counter_decrements_on_account_deletion(client, alice):
    user, headers = alice
    before = _total_users_counter()
    resp = client.delete("/auth/me", headers=headers)
    assert resp.status_code == 204
    assert _total_users_counter() == before - 1


def test_app_counters_singleton_constraint(client):
    """A second row must be structurally impossible, not just conventionally
    avoided — every read/write in this codebase assumes id=1 is the only row."""
    db = SessionLocal()
    try:
        db.add(AppCounters(id=2, total_users=0))
        try:
            db.commit()
            raise AssertionError("expected IntegrityError from the id=1 CHECK constraint")
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_ranking_percentile_uses_counter_not_live_count(client, alice, bob):
    """End-to-end: total_users in the /stats/ranking response must come from
    the maintained counter and agree with reality, not just exist."""
    alice_user, alice_headers = alice
    bob_user, bob_headers = bob
    _set_premium(alice_user["id"])
    _set_premium(bob_user["id"])
    r = client.get("/stats/ranking", headers=alice_headers).json()
    assert r["total_users"] == _total_users_counter() == 2
