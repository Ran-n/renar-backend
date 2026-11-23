#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:12.279088
Revised: 2026/11/23 08:13:12.729477

TV Time import runs that hit the leftover summary/edge branches: a movie row
that lost a same-run insert race or resolved to nothing, two unmatched
names that the episode fallback maps to the same episode, a re-import whose
rewatches are already all logged, a comment on a show deleted mid-import,
and a reply with no TV Time id of its own.
"""

from test_tvtime_import_gaps import _build_zip, _patch_tmdb, _run

import renar_backend.users.tvtime_import as tvtime
from renar_backend.database import SessionLocal
from renar_backend.models import Comment, LibraryEntry

_DARK = {"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}
_FOLLOWED = {"tv_show_id": "100", "archived": "0"}


def _movie_event(name: str) -> dict:
    return {
        "movie_name": name,
        "type": "watch",
        "runtime": "0",
        "release_date": "",
        "created_at": "2026-01-01 00:00:00",
        "uuid": name,
    }


def test_movie_summary_for_a_race_loser_and_an_unresolved_row(client, alice, monkeypatch):
    user, _ = alice
    _patch_tmdb(monkeypatch)
    outcomes = {
        # (item_id, unmatched, is_new, changed, error, duplicate_in_run)
        "Raced": (None, None, False, False, False, False),
        "Twin": (None, None, False, False, False, False),
    }

    def _process_movie(user_id, name, m, existing_map):
        if name == "Twin":
            # lost the insert race to a sibling row: reconciled into the
            # winner's entry, already counted once by that sibling
            return 1, None, False, False, False, True
        return outcomes[name]

    monkeypatch.setattr(tvtime, "_process_movie", _process_movie)

    summary = _run(user["id"], _build_zip(movie_events=[_movie_event("Raced"), _movie_event("Twin")]))

    assert summary.get("error") is None
    assert (summary["movies"], summary["updated"], summary["skipped"], summary["errors"]) == (0, 0, 1, 0)


def test_episode_fallback_counts_one_episode_named_two_ways(client, alice, monkeypatch):
    user, _ = alice
    _patch_tmdb(monkeypatch)  # movie search finds nothing: both names stay unmatched
    monkeypatch.setattr(tvtime, "_search_tv", lambda name: {"id": 70523, "name": "Dark"})
    episode = {"season": 1, "episode": 1, "name": "Secrets"}
    monkeypatch.setattr(tvtime, "_show_episode_pool", lambda tmdb_id: [episode])
    monkeypatch.setattr(tvtime, "_match_episode_in_pool", lambda part, pool: episode)

    summary = _run(user["id"], _build_zip(movie_events=[_movie_event("Dark - Secrets"), _movie_event("Dark: Secrets")]))

    assert summary.get("error") is None
    assert summary["episodes"] == 1
    assert summary["unmatched"] == []


def _rewatch(cpt: str) -> dict:
    return {
        "episode_id": "1",
        "cpt": cpt,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
        "tv_show_name": "Dark",
        "episode_season_number": "1",
        "episode_number": "1",
    }


def test_reimported_rewatches_add_nothing_new(client, alice, monkeypatch):
    user, _ = alice
    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    data = _build_zip(shows=[_DARK], followed=[_FOLLOWED], rewatches=[_rewatch("2")])

    first = _run(user["id"], data)
    second = _run(user["id"], data)

    assert first["rewatches"] == 2
    assert (second["rewatches"], second["rewatches_skipped"]) == (0, 0)


def test_comment_on_a_show_deleted_mid_import_is_skipped(client, alice, monkeypatch):
    user, _ = alice
    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    real = tvtime._process_show

    def _process_then_deleted(*args, **kwargs):
        result = real(*args, **kwargs)
        db = SessionLocal()
        try:
            db.query(LibraryEntry).filter(LibraryEntry.id == result[1]).delete()
            db.commit()
        finally:
            db.close()
        return result

    monkeypatch.setattr(tvtime, "_process_show", _process_then_deleted)
    comments = [{"id": "c1", "parent_comment_id": "", "tv_show_id": "100", "comment": "Wow", "created_at": ""}]

    summary = _run(user["id"], _build_zip(shows=[_DARK], followed=[_FOLLOWED], show_comments=comments))

    assert summary.get("error") is None
    assert (summary["comments"], summary["comments_skipped"]) == (0, 1)


def test_a_reply_without_its_own_id_is_still_imported(client, alice, monkeypatch):
    user, _ = alice
    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    comments = [
        {"id": "root", "parent_comment_id": "", "tv_show_id": "100", "comment": "Wow", "created_at": ""},
        {"id": "", "parent_comment_id": "root", "tv_show_id": "100", "comment": "Same", "created_at": ""},
    ]

    summary = _run(user["id"], _build_zip(shows=[_DARK], followed=[_FOLLOWED], show_comments=comments))

    assert summary["comments"] == 2
    db = SessionLocal()
    try:
        reply = db.query(Comment).filter(Comment.text == "Same").one()
        assert reply.parent_id is not None
    finally:
        db.close()


def test_import_stamps_last_watched_from_the_imported_history(client, alice, monkeypatch):
    """Home orders by last_watched_at; the import must set it to the real
    date of the latest imported watch, not leave it empty."""
    user, _ = alice
    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})

    _run(user["id"], _build_zip(shows=[_DARK], followed=[_FOLLOWED], rewatches=[_rewatch("1")]))

    db = SessionLocal()
    try:
        entry = db.query(LibraryEntry).filter_by(user_id=user["id"]).one()
        assert (entry.status.value, entry.last_watched_at.date().isoformat()) == ("watching", "2026-01-02")
    finally:
        db.close()
