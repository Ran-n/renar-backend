#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 00:00:00.000000
Revised: 2026/08/18 11:05:47.672298

GET /media?status_filter=watching&order_by=last_watched — Home's "Watch
Next"/"Continue Watching" list. Two rules live entirely in this query (see
routers/media.py's `_unwatched_aired_episode_clause` docstring for why they
can't just filter on the LibraryEntry.status field instead):

1. A tv_show fully caught up on everything aired so far must not appear —
   it only re-enters once a new episode actually airs.
2. A show with a genuinely new unwatched episode (aired after the show's own
   last_watched_at) bubbles to position #2, right after whatever the user
   most recently actively watched.
"""

from datetime import date, timedelta

from renar_backend.database import SessionLocal
from renar_backend.models import Episode, EpisodeWatch, LibraryEntry, utcnow


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


# ---------- rule 2: new-episode ranking ----------


def test_new_episode_bumps_to_second_place(client, alice):
    _, headers = alice
    now = utcnow()
    # every show below also gets an old unwatched episode (aired well before
    # `now`) so none of them trip rule 1's fully-caught-up exclusion — this
    # test is purely about ranking among shows that all still qualify

    show_a = _add(client, headers, title="Show A")  # most recently watched — stays #1
    _add_episode(show_a["id"], 1, 1, date.today() - timedelta(days=30))
    _add_episode(show_a["id"], 1, 2, date.today() - timedelta(days=10))
    _mark_watched(show_a["id"], 1, 1)
    _set_last_watched(show_a["id"], now)

    show_b = _add(client, headers, title="Show B")  # watched 2 days ago, nothing new
    _add_episode(show_b["id"], 1, 1, date.today() - timedelta(days=30))
    _add_episode(show_b["id"], 1, 2, date.today() - timedelta(days=10))
    _mark_watched(show_b["id"], 1, 1)
    _set_last_watched(show_b["id"], now - timedelta(days=2))

    show_c = _add(client, headers, title="Show C")  # watched 3 days ago, but a NEW episode aired since
    _add_episode(show_c["id"], 1, 1, date.today() - timedelta(days=30))
    _add_episode(show_c["id"], 1, 2, date.today() - timedelta(days=10))
    _mark_watched(show_c["id"], 1, 1)
    _add_episode(show_c["id"], 1, 3, date.today() - timedelta(days=1))  # aired after show_c's last_watched_at
    _set_last_watched(show_c["id"], now - timedelta(days=3))

    # natural last_watched order would be A, B, C — C's fresh episode bumps
    # it ahead of B, but never displaces A from #1
    assert _watch_next(client, headers) == ["Show A", "Show C", "Show B"]


def test_old_backlog_episode_does_not_bump_ranking(client, alice):
    """An unwatched aired episode the user just hasn't gotten to yet — not
    something that arrived *since* their last watch — must not jump the
    show ahead of shows watched more recently. Distinct from the "excluded
    entirely" case: this show does have something left to watch, it's just
    not new."""
    _, headers = alice
    now = utcnow()

    show_a = _add(client, headers, title="Show A")  # most recently watched
    _add_episode(show_a["id"], 1, 1, date.today() - timedelta(days=30))
    _add_episode(show_a["id"], 1, 2, date.today() - timedelta(days=10))
    _mark_watched(show_a["id"], 1, 1)
    _set_last_watched(show_a["id"], now)

    show_b = _add(client, headers, title="Show B")  # watched 1 day ago, has an OLD unwatched episode
    _add_episode(show_b["id"], 1, 1, date.today() - timedelta(days=20))
    _mark_watched(show_b["id"], 1, 1)
    _add_episode(show_b["id"], 1, 2, date.today() - timedelta(days=15))  # aired well before last_watched_at
    _set_last_watched(show_b["id"], now - timedelta(days=1))

    assert _watch_next(client, headers) == ["Show A", "Show B"]
