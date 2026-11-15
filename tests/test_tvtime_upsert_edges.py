#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:12.124916
Revised: 2026/11/13 15:35:12.124916

TV Time importer building blocks on their own: the fuzzy matcher keeping the
best of several candidates, a list cell with no key:value pairs, and
_upsert_library_entry's reconcile/race paths (an entry with no catalog ids,
one folded into a concurrently created title, a lost insert race whose
winner can't be found, and an entry deleted since the import started).
"""

import pytest
from _race_helpers import commit_elsewhere

import renar_backend.users.tvtime_import as tvtime
from renar_backend.catalog.titles import normalize_title_key
from renar_backend.database import SessionLocal
from renar_backend.models import LibraryEntry, MediaType, Title, User, WatchStatus


def test_fuzzy_search_keeps_the_best_candidate(monkeypatch):
    results = {
        "results": [
            {"id": 1, "name": "Dark Matter", "original_name": ""},
            {"id": 2, "name": "Something Else", "original_name": ""},
        ]
    }
    monkeypatch.setattr(tvtime, "tmdb_get", lambda path, params: results)

    assert tvtime._fuzzy_search("Dark Matter x", "tv")["id"] == 1


def test_list_cell_without_key_value_pairs_is_skipped():
    assert tvtime._parse_list_objects("[map[justtext] map[id:5 type:series]]") == [{"id": "5", "type": "series"}]


# ---------------------------------------------------------------------------
# _upsert_library_entry
# ---------------------------------------------------------------------------


@pytest.fixture
def user_id(client):
    (uid,) = commit_elsewhere(User(username="tvtimer", email="tvtimer@example.com", password_hash="x"))
    return uid


def _upsert(user_id, title, *, tmdb_id=None, existing_map=None):
    return tvtime._upsert_library_entry(
        user_id,
        MediaType.tv_show,
        tmdb_id,
        title,
        {},
        {"status": WatchStatus.watching, "is_favorite": False, "rating": None},
        ("tv_show", normalize_title_key(title)),
        ("tv_show", tmdb_id) if tmdb_id else None,
        existing_map or {},
        tvtime._reconcile_show_entry,
    )


def _tracked(user_id, **title_fields) -> int:
    (title_id,) = commit_elsewhere(Title(media_type=MediaType.tv_show, **title_fields))
    (entry_id,) = commit_elsewhere(LibraryEntry(user_id=user_id, title_id=title_id, status=WatchStatus.watching))
    return entry_id


def test_reconcile_an_entry_that_has_no_catalog_ids(user_id):
    entry_id = _tracked(user_id, title="Obscure Show", title_key="obscure show")

    item_id, is_new, changed, error, dup = _upsert(
        user_id, "Obscure Show", existing_map={("tv_show", "obscure show"): entry_id}
    )

    assert (item_id, is_new, error, dup) == (entry_id, False, False, False)


def test_reconcile_folds_into_a_title_that_claimed_the_tmdb_id(user_id):
    entry_id = _tracked(user_id, title="Raw Name", title_key="raw name")
    (winner_id,) = commit_elsewhere(Title(media_type=MediaType.tv_show, tmdb_id=1399, title="Game of Thrones"))

    item_id, is_new, _, error, _ = _upsert(
        user_id, "Raw Name", tmdb_id=1399, existing_map={("tv_show", "raw name"): entry_id}
    )

    assert (item_id, is_new, error) == (entry_id, False, False)
    db = SessionLocal()
    try:
        assert db.get(LibraryEntry, entry_id).title_id == winner_id
    finally:
        db.close()


def test_lost_insert_race_with_no_findable_winner(user_id, monkeypatch):
    (title_id,) = commit_elsewhere(Title(media_type=MediaType.tv_show, tmdb_id=1400, title="Lost"))
    commit_elsewhere(LibraryEntry(user_id=user_id, title_id=title_id))  # the sibling row's insert
    monkeypatch.setattr(tvtime, "find_title", lambda *a, **kw: None)

    assert _upsert(user_id, "Lost", tmdb_id=1400) == (None, False, False, False, False)


def test_entry_deleted_since_the_import_started(user_id):
    assert _upsert(user_id, "Gone", existing_map={("tv_show", "gone"): 2147483647}) == (
        None,
        False,
        False,
        False,
        False,
    )
