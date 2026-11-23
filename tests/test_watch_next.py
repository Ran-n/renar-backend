#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/11/23 10:25:06.053552

GET /media?status_filter=watching&order_by=last_watched — Home's "Watch
Next"/"Continue Watching" list. The rules live in catalog/watch_next.py:

1. A tv_show fully caught up on everything aired so far must not appear —
   it only re-enters once a new episode actually airs.
2. Order: #1 is the last thing watched; then started shows with a new
   episode (aired after the user's last watch of them), newest air date
   first; then the rest by last watch; never-watched entries last; ties
   break on the newest entry.
3. restamp_last_watched (run after every import) fills last_watched_at from
   the real watch history, never moving a stamp backwards.
"""

from datetime import date, timedelta

from renar_backend.catalog.watch_next import restamp_last_watched
from renar_backend.database import SessionLocal
from renar_backend.models import Episode, EpisodeWatch, LibraryEntry, WatchEvent, WatchStatus, utcnow


def _add(client, headers, **kwargs) -> dict:
    payload = {"media_type": "tv_show", "status": "watching"} | kwargs
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _add_episode(item_id: int, season: int, episode_number: int, air_date: date) -> None:
    db = SessionLocal()
    try:
        entry = db.get(LibraryEntry, item_id)
        db.add(Episode(title_id=entry.title_id, season=season, episode_number=episode_number, air_date=air_date))
        db.commit()
    finally:
        db.close()


def _mark_watched(item_id: int, season: int, episode: int) -> None:
    db = SessionLocal()
    try:
        db.add(EpisodeWatch(media_item_id=item_id, season=season, episode=episode))
        db.commit()
    finally:
        db.close()


def _set_last_watched(item_id: int, when) -> None:
    db = SessionLocal()
    try:
        db.get(LibraryEntry, item_id).last_watched_at = when
        db.commit()
    finally:
        db.close()


def _watch_next(client, headers) -> list[str]:
    r = client.get("/media", params={"status_filter": "watching", "order_by": "last_watched"}, headers=headers)
    assert r.status_code == 200, r.text
    return [i["title"] for i in r.json()]


# ---------- rule 1: fully caught-up exclusion ----------


def test_fully_caught_up_show_excluded(client, alice):
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _add_episode(show["id"], 1, 1, date.today() - timedelta(days=5))
    _mark_watched(show["id"], 1, 1)
    _set_last_watched(show["id"], utcnow())

    assert _watch_next(client, headers) == []


def test_show_with_unwatched_aired_episode_stays_included(client, alice):
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _add_episode(show["id"], 1, 1, date.today() - timedelta(days=5))
    _add_episode(show["id"], 1, 2, date.today() - timedelta(days=2))
    _mark_watched(show["id"], 1, 1)  # episode 2 still unwatched
    _set_last_watched(show["id"], utcnow())

    assert _watch_next(client, headers) == ["Dark"]


def test_unaired_remaining_episode_does_not_prevent_exclusion(client, alice):
    """Caught up on everything actually aired — a future-dated episode still
    on the calendar must not keep the show in the list; it only re-enters
    once that episode's own air_date passes."""
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _add_episode(show["id"], 1, 1, date.today() - timedelta(days=5))
    _add_episode(show["id"], 1, 2, date.today() + timedelta(days=5))
    _mark_watched(show["id"], 1, 1)
    _set_last_watched(show["id"], utcnow())

    assert _watch_next(client, headers) == []


def test_film_never_excluded_regardless_of_episode_data(client, alice):
    """Films have no episode concept — the exclusion rule (tv_show-only)
    must never apply to one, even though a film with zero Episode rows
    would otherwise look exactly like a "nothing left aired" show."""
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Heat")
    _set_last_watched(film["id"], utcnow())

    assert _watch_next(client, headers) == ["Heat"]


def test_show_with_no_synced_episodes_stays_included(client, alice):
    """A show the user marked "watching" but whose season data was never
    synced (no Episode rows at all) has nothing to prove it's caught up —
    must not be excluded just for lacking data."""
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _set_last_watched(show["id"], utcnow())

    assert _watch_next(client, headers) == ["Dark"]


# ---------- rule 2: last watched, then new episodes, then recency ----------


def _in_progress(client, headers, title: str, last_watched) -> dict:
    """A show with an old unwatched episode left (so rule 1 keeps it) and
    the given last watch."""
    show = _add(client, headers, title=title)
    _add_episode(show["id"], 1, 1, date.today() - timedelta(days=60))
    _add_episode(show["id"], 1, 2, date.today() - timedelta(days=50))
    _mark_watched(show["id"], 1, 1)
    _set_last_watched(show["id"], last_watched)
    return show


def test_watching_something_moves_the_old_top_to_second(client, alice):
    _, headers = alice
    now = utcnow()
    _in_progress(client, headers, "Show A", now - timedelta(days=1))
    _in_progress(client, headers, "Show B", now - timedelta(days=2))
    _in_progress(client, headers, "Show C", now - timedelta(days=3))
    assert _watch_next(client, headers) == ["Show A", "Show B", "Show C"]

    _in_progress(client, headers, "Show X", now)

    assert _watch_next(client, headers) == ["Show X", "Show A", "Show B", "Show C"]


def test_a_new_episode_puts_its_show_at_second_place(client, alice):
    """C was last watched 5 days ago and a new episode aired yesterday: it
    goes right after A (the last thing watched), ahead of B, which was
    watched more recently than the new episode aired."""
    _, headers = alice
    now = utcnow()
    _in_progress(client, headers, "Show A", now)
    _in_progress(client, headers, "Show B", now - timedelta(hours=1))
    show_c = _in_progress(client, headers, "Show C", now - timedelta(days=5))
    _add_episode(show_c["id"], 1, 3, date.today() - timedelta(days=1))

    assert _watch_next(client, headers) == ["Show A", "Show C", "Show B"]


def test_new_episodes_rank_by_air_date_newest_first(client, alice):
    _, headers = alice
    now = utcnow()
    _in_progress(client, headers, "Show A", now)
    older_news = _in_progress(client, headers, "Older News", now - timedelta(days=20))
    _add_episode(older_news["id"], 1, 3, date.today() - timedelta(days=10))
    newer_news = _in_progress(client, headers, "Newer News", now - timedelta(days=30))
    _add_episode(newer_news["id"], 1, 3, date.today() - timedelta(days=2))
    _in_progress(client, headers, "Show B", now - timedelta(days=1))

    assert _watch_next(client, headers) == ["Show A", "Newer News", "Older News", "Show B"]


def test_the_last_watched_show_stays_first_even_with_news_elsewhere(client, alice):
    _, headers = alice
    now = utcnow()
    show_c = _in_progress(client, headers, "Show C", now - timedelta(days=5))
    _add_episode(show_c["id"], 1, 3, date.today())
    _in_progress(client, headers, "Show B", now - timedelta(days=1))

    assert _watch_next(client, headers) == ["Show B", "Show C"]


def test_a_new_episode_on_the_top_show_keeps_it_first(client, alice):
    _, headers = alice
    now = utcnow()
    top = _in_progress(client, headers, "Top", now - timedelta(days=3))
    _add_episode(top["id"], 1, 3, date.today() - timedelta(days=1))
    _in_progress(client, headers, "Show B", now - timedelta(days=4))

    assert _watch_next(client, headers) == ["Top", "Show B"]


def test_old_backlog_episode_does_not_lift_a_show(client, alice):
    """An unwatched episode that aired before the user's last watch of that
    show isn't news: the show stays at its own last watch."""
    _, headers = alice
    now = utcnow()
    _in_progress(client, headers, "Show A", now - timedelta(days=1))
    _in_progress(client, headers, "Show B", now - timedelta(days=10))  # backlog aired 50-60 days ago

    assert _watch_next(client, headers) == ["Show A", "Show B"]


def test_never_watched_entries_sort_last(client, alice):
    """Imported as "watching" but never started: every episode is unwatched,
    none of it is news to the user, and it must not crowd out shows they
    actually watch."""
    _, headers = alice
    untouched = _add(client, headers, title="Never Started")
    _add_episode(untouched["id"], 1, 1, date.today() - timedelta(days=1))
    _set_last_watched(untouched["id"], None)
    _in_progress(client, headers, "Show A", utcnow() - timedelta(days=30))
    _in_progress(client, headers, "Show B", utcnow() - timedelta(days=40))

    assert _watch_next(client, headers) == ["Show A", "Show B", "Never Started"]


def test_ties_break_on_the_newest_entry(client, alice):
    _, headers = alice
    when = utcnow() - timedelta(days=1)
    _in_progress(client, headers, "Older Entry", when)
    _in_progress(client, headers, "Newer Entry", when)

    assert _watch_next(client, headers) == ["Newer Entry", "Older Entry"]


def test_pages_follow_the_ranked_order(client, alice):
    """Paging happens after ranking: page 2 holds the boosted show that the
    plain recency order would have put last."""
    _, headers = alice
    now = utcnow()
    for days, title in enumerate(("Show A", "Show B", "Show C")):
        _in_progress(client, headers, title, now - timedelta(days=days))
    news = _in_progress(client, headers, "News", now - timedelta(days=9))
    _add_episode(news["id"], 1, 3, date.today() - timedelta(days=1))
    params = {"status_filter": "watching", "order_by": "last_watched", "limit": 2, "offset": 1}
    r = client.get("/media", params=params, headers=headers)
    assert [i["title"] for i in r.json()] == ["News", "Show B"]


# ---------- rule 3: restamping from watch history ----------


def _last_watched(item_id: int):
    db = SessionLocal()
    try:
        return db.get(LibraryEntry, item_id).last_watched_at
    finally:
        db.close()


def _restamp(user_id: int) -> int:
    db = SessionLocal()
    try:
        changed = restamp_last_watched(db, user_id)
        db.commit()
        return changed
    finally:
        db.close()


def _add_history(item_id: int, *, episode_at=None, event_at=None) -> None:
    db = SessionLocal()
    try:
        if episode_at is not None:
            db.add(EpisodeWatch(media_item_id=item_id, season=1, episode=1, watched_at=episode_at))
        if event_at is not None:
            db.add(WatchEvent(media_item_id=item_id, watched_at=event_at, is_initial=True))
        db.commit()
    finally:
        db.close()


def _without_history(item_id: int) -> None:
    """Drop the watch event POST /media logs for a "watching" entry and its
    stamp, so the entry starts with no history at all."""
    db = SessionLocal()
    try:
        db.query(WatchEvent).filter(WatchEvent.media_item_id == item_id).delete()
        db.get(LibraryEntry, item_id).last_watched_at = None
        db.commit()
    finally:
        db.close()


def _owner_id(item_id: int) -> int:
    db = SessionLocal()
    try:
        return db.get(LibraryEntry, item_id).user_id
    finally:
        db.close()


def test_restamp_fills_a_missing_stamp_from_episode_history(client, alice):
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _without_history(show["id"])
    watched = utcnow() - timedelta(days=400)
    _add_history(show["id"], episode_at=watched)

    assert _restamp(_owner_id(show["id"])) == 1
    assert _last_watched(show["id"]) == watched


def test_restamp_uses_watch_events_for_films(client, alice):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Heat", status="completed")
    _without_history(film["id"])
    watched = utcnow() - timedelta(days=90)
    _add_history(film["id"], event_at=watched)

    _restamp(_owner_id(film["id"]))

    assert _last_watched(film["id"]) == watched


def test_restamp_takes_the_later_of_both_histories(client, alice):
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _without_history(show["id"])
    newer = utcnow() - timedelta(days=1)
    _add_history(show["id"], episode_at=newer - timedelta(days=30), event_at=newer)

    _restamp(_owner_id(show["id"]))

    assert _last_watched(show["id"]) == newer


def test_restamp_never_moves_a_stamp_backwards(client, alice):
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _without_history(show["id"])
    recent = utcnow()
    _set_last_watched(show["id"], recent)
    _add_history(show["id"], episode_at=recent - timedelta(days=10))

    assert _restamp(_owner_id(show["id"])) == 0
    assert _last_watched(show["id"]) == recent


def test_restamp_leaves_entries_without_history_alone(client, alice):
    _, headers = alice
    show = _add(client, headers, title="Dark")
    _without_history(show["id"])

    assert _restamp(_owner_id(show["id"])) == 0
    assert _last_watched(show["id"]) is None


def test_restamp_skips_planned_entries(client, alice):
    _, headers = alice
    planned = _add(client, headers, title="Planned", status=WatchStatus.want_to_watch.value)
    _set_last_watched(planned["id"], None)
    _add_history(planned["id"], episode_at=utcnow() - timedelta(days=3))

    assert _restamp(_owner_id(planned["id"])) == 0
    assert _last_watched(planned["id"]) is None


def test_restamp_only_touches_the_given_user(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    alices = _add(client, alice_headers, title="Mine")
    _without_history(alices["id"])
    bobs = _add(client, bob_headers, title="Dark")
    _without_history(bobs["id"])
    _add_history(bobs["id"], episode_at=utcnow() - timedelta(days=3))

    assert _restamp(_owner_id(alices["id"])) == 0
    assert _last_watched(bobs["id"]) is None
