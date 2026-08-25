#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/09 14:29:25.931212
Revised: 2026/08/24 14:06:08.848940

TV Time import reconciliation: merging into titles the user already tracks
(manually or from a prior import), instead of skipping them outright.
"""

import csv
import io
import zipfile

import renar_backend.users.tvtime_import as imports_mod
from renar_backend.database import SessionLocal
from renar_backend.models import Comment, Episode, EpisodeWatch, LibraryEntry, List, ListItem, Title, WatchEvent


def _csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _build_zip(
    shows: list[dict] | None = None,
    followed: list[dict] | None = None,
    for_later: list[dict] | None = None,
    rates: list[dict] | None = None,
    episode_events: list[dict] | None = None,
    movie_events: list[dict] | None = None,
    show_comments: list[dict] | None = None,
    episode_comments: list[dict] | None = None,
    movie_comments: list[dict] | None = None,
    rewatches: list[dict] | None = None,
    lists: list[dict] | None = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "gdpr-data/user_tv_show_data.csv",
            _csv_bytes(shows or [], ["tv_show_id", "tv_show_name", "is_favorited"]),
        )
        zf.writestr(
            "gdpr-data/followed_tv_show.csv",
            _csv_bytes(followed or [], ["tv_show_id", "archived"]),
        )
        zf.writestr(
            "gdpr-data/user_show_special_status.csv",
            _csv_bytes(for_later or [], ["tv_show_id", "status"]),
        )
        zf.writestr(
            "gdpr-data/tv_show_rate.csv",
            _csv_bytes(rates or [], ["tv_show_id", "rating"]),
        )
        zf.writestr(
            "gdpr-data/tracking-prod-records-v2.csv",
            _csv_bytes(episode_events or [], ["s_id", "s_no", "ep_no", "created_at"]),
        )
        zf.writestr(
            "gdpr-data/tracking-prod-records.csv",
            _csv_bytes(
                movie_events or [],
                ["movie_name", "type", "runtime", "release_date", "created_at", "uuid"],
            ),
        )
        zf.writestr(
            "gdpr-data/show_comment.csv",
            _csv_bytes(show_comments or [], ["id", "parent_comment_id", "tv_show_id", "comment", "created_at"]),
        )
        zf.writestr(
            "gdpr-data/episode_comment.csv",
            _csv_bytes(
                episode_comments or [],
                [
                    "id",
                    "parent_comment_id",
                    "tv_show_name",
                    "episode_season_number",
                    "episode_number",
                    "comment",
                    "created_at",
                ],
            ),
        )
        zf.writestr(
            "gdpr-data/comments-prod-comments.csv",
            _csv_bytes(
                movie_comments or [],
                ["uuid", "parent_uuid", "type", "movie_name", "text", "created_at"],
            ),
        )
        zf.writestr(
            "gdpr-data/rewatched_episode.csv",
            _csv_bytes(
                rewatches or [],
                [
                    "episode_id",
                    "cpt",
                    "created_at",
                    "updated_at",
                    "tv_show_name",
                    "episode_season_number",
                    "episode_number",
                ],
            ),
        )
        zf.writestr(
            "gdpr-data/lists-prod-lists.csv",
            _csv_bytes(
                lists or [],
                [
                    "ordering",
                    "objects",
                    "s_key",
                    "is_public",
                    "type",
                    "name",
                    "created_at",
                    "user_id",
                    "description",
                    "lists",
                ],
            ),
        )
    return buf.getvalue()


def _title_id_for_entry(item_id: int) -> int:
    db = SessionLocal()
    try:
        return db.get(LibraryEntry, item_id).title_id
    finally:
        db.close()


def _comments(user_id: int, title_id: int) -> set[tuple]:
    db = SessionLocal()
    try:
        rows = (
            db.query(Comment.season, Comment.episode, Comment.text)
            .filter(Comment.user_id == user_id, Comment.title_id == title_id)
            .all()
        )
        return set(rows)
    finally:
        db.close()


def _watch_event_count(item_id: int, season: int, episode: int) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(WatchEvent)
            .filter(WatchEvent.media_item_id == item_id, WatchEvent.season == season, WatchEvent.episode == episode)
            .count()
        )
    finally:
        db.close()


def _episode_keys(item_id: int) -> set[tuple[int, int]]:
    db = SessionLocal()
    try:
        rows = db.query(EpisodeWatch.season, EpisodeWatch.episode).filter(EpisodeWatch.media_item_id == item_id).all()
        return set(rows)
    finally:
        db.close()


def _run(user_id: int, zip_bytes: bytes) -> dict:
    imports_mod.run(user_id, zip_bytes)
    return imports_mod._progress[user_id]["summary"]


def _patch_tmdb(
    monkeypatch, show_matches: dict[str, tuple[dict | None, dict]] | None = None, movie_match: dict | None = None
):
    def match_show(tvdb_id, name):
        # accepts either the old (found, details) shape or the full
        # (found, details, tvdb_fallback) one — padding keeps every
        # existing show_matches value in this file working unchanged.
        result = (show_matches or {}).get(tvdb_id, (None, {}))
        return (*result, None) if len(result) == 2 else result

    monkeypatch.setattr(imports_mod, "_match_show", match_show)
    monkeypatch.setattr(imports_mod, "_search_movie", lambda name, year: (movie_match, False))


# ---------- shows: new season on an already-tracked show ----------


def test_import_adds_new_season_episodes_to_already_tracked_show(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "total_episodes": 99}, headers=headers
    ).json()
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    assert _episode_keys(show["id"]) == {(1, 1)}

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        episode_events=[
            {"s_id": "100", "s_no": "1", "ep_no": "1", "created_at": "2026-01-01 00:00:00"},  # already watched
            {"s_id": "100", "s_no": "2", "ep_no": "1", "created_at": "2026-01-02 00:00:00"},  # new season
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary["error"] is None if "error" in summary else True
    assert _episode_keys(show["id"]) == {(1, 1), (2, 1)}
    # the existing show was reconciled (new episodes merged), not (re-)inserted as new
    assert summary["shows"] == 0
    assert summary["updated"] == 1
    assert summary["episodes"] == 1  # only the genuinely-new row was added


def test_import_does_not_duplicate_or_error_on_already_watched_episode(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()
    client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": True}, headers=headers)

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        episode_events=[{"s_id": "100", "s_no": "1", "ep_no": "1", "created_at": "2026-01-01 00:00:00"}],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert _episode_keys(show["id"]) == {(1, 1)}
    assert summary["episodes"] == 0


def test_import_does_not_overwrite_favorite_or_rating_already_set(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "is_favorite": True, "rating": 7},
        headers=headers,
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        rates=[{"tv_show_id": "100", "rating": "2"}],  # would map to a lower rating
    )
    _run(user["id"], zip_bytes)

    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["is_favorite"] is True
    assert item["rating"] == 7


def test_import_fills_favorite_and_rating_when_unset(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "1"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        rates=[{"tv_show_id": "100", "rating": "4"}],
    )
    _run(user["id"], zip_bytes)

    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["is_favorite"] is True
    assert item["rating"] == 80  # 4 on TV Time's 1-5 scale -> 80 on a 1-100 scale


def test_import_does_not_change_manually_set_show_status(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "status": "dropped"}, headers=headers
    ).json()

    # archived=0, not for_later -> TV Time's guess would be "watching"
    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
    )
    _run(user["id"], zip_bytes)

    item = client.get(f"/media/{show['id']}", headers=headers).json()
    assert item["status"] == "dropped"


def test_import_does_not_auto_complete_dropped_show_even_when_all_episodes_watched(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555, "total_episodes": 1, "status": "dropped"},
        headers=headers,
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        episode_events=[{"s_id": "100", "s_no": "1", "ep_no": "1", "created_at": "2026-01-01 00:00:00"}],
    )
    _run(user["id"], zip_bytes)

    item = client.get(f"/media/{show['id']}", headers=headers).json()
    # every episode is now watched, but "dropped" was a deliberate call
    assert item["episodes_watched"] == 1
    assert item["status"] == "dropped"


# ---------- movies: already-tracked film ----------


def test_import_upgrades_want_to_watch_film_to_completed_when_watched(client, alice, monkeypatch):
    user, headers = alice
    movie = client.post(
        "/media",
        json={"media_type": "film", "title": "Heat", "tmdb_id": 777, "status": "want_to_watch"},
        headers=headers,
    ).json()

    _patch_tmdb(monkeypatch, movie_match={"id": 777, "title": "Heat", "release_date": "1995-12-15"})
    zip_bytes = _build_zip(
        movie_events=[
            {
                "movie_name": "Heat",
                "type": "watch",
                "runtime": "0",
                "release_date": "1995-12-15",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    item = client.get(f"/media/{movie['id']}", headers=headers).json()
    assert item["status"] == "completed"
    assert summary["movies"] == 0
    assert summary["updated"] == 1


def test_import_does_not_downgrade_completed_film(client, alice, monkeypatch):
    user, headers = alice
    movie = client.post(
        "/media", json={"media_type": "film", "title": "Heat", "tmdb_id": 777, "status": "completed"}, headers=headers
    ).json()

    # not watched on TV Time (only "towatch"/follow events, no "watch")
    _patch_tmdb(monkeypatch, movie_match={"id": 777, "title": "Heat", "release_date": "1995-12-15"})
    zip_bytes = _build_zip(
        movie_events=[
            {
                "movie_name": "Heat",
                "type": "towatch",
                "runtime": "0",
                "release_date": "1995-12-15",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )
    _run(user["id"], zip_bytes)

    item = client.get(f"/media/{movie['id']}", headers=headers).json()
    assert item["status"] == "completed"


def test_import_skips_tmdb_search_for_unwatched_already_tracked_movie(client, alice, monkeypatch):
    """An already-tracked movie TV Time doesn't report as watched has nothing
    to reconcile, so the (network-costly) TMDB search should be skipped."""
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat", "tmdb_id": 777}, headers=headers)

    def _fail_search(name, year):
        raise AssertionError("TMDB search should have been skipped for an unwatched, already-tracked movie")

    monkeypatch.setattr(imports_mod, "_search_movie", _fail_search)
    zip_bytes = _build_zip(
        movie_events=[
            {
                "movie_name": "Heat",
                "type": "towatch",
                "runtime": "0",
                "release_date": "1995-12-15",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["skipped"] == 1


# ---------- comments ----------


def test_import_adds_show_and_episode_comments(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        show_comments=[{"tv_show_id": "100", "comment": "Loving this show", "created_at": "2026-01-01 00:00:00"}],
        episode_comments=[
            {
                "tv_show_name": "Dark",
                "episode_season_number": "1",
                "episode_number": "1",
                "comment": "What a premiere",
                "created_at": "2026-01-02 00:00:00",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 2
    assert summary["comments_skipped"] == 0
    title_id = _title_id_for_entry(show["id"])
    assert _comments(user["id"], title_id) == {
        (None, None, "Loving this show"),
        (1, 1, "What a premiere"),
    }


def test_import_skips_comments_on_unmatched_shows(client, alice, monkeypatch):
    user, _headers = alice
    _patch_tmdb(monkeypatch)  # nothing matches
    zip_bytes = _build_zip(
        show_comments=[{"tv_show_id": "100", "comment": "Never tracked this one", "created_at": "2026-01-01 00:00:00"}],
        episode_comments=[
            {
                "tv_show_name": "Unknown Show",
                "episode_season_number": "1",
                "episode_number": "1",
                "comment": "Also never tracked",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 0
    assert summary["comments_skipped"] == 2


def test_reimport_does_not_duplicate_comments(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        show_comments=[{"tv_show_id": "100", "comment": "Loving this show", "created_at": "2026-01-01 00:00:00"}],
    )
    _run(user["id"], zip_bytes)
    summary = _run(user["id"], zip_bytes)  # run again with identical data

    assert summary.get("error") is None
    assert summary["comments"] == 0
    title_id = _title_id_for_entry(show["id"])
    assert len(_comments(user["id"], title_id)) == 1


def test_import_links_reply_to_own_earlier_comment(client, alice, monkeypatch):
    """A reply whose parent is also this user's own exported comment should
    land as a real reply (Comment.parent_id set, no title/season/episode of
    its own), not a second root comment."""
    user, headers = alice
    client.post("/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers)

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        show_comments=[
            {"id": "1", "tv_show_id": "100", "comment": "Loving this show", "created_at": "2026-01-01 00:00:00"},
            {
                "id": "2",
                "parent_comment_id": "1",
                "tv_show_id": "100",
                "comment": "Me too!",
                "created_at": "2026-01-02 00:00:00",
            },
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 2
    assert summary["comments_skipped"] == 0
    db = SessionLocal()
    try:
        root = db.query(Comment).filter(Comment.user_id == user["id"], Comment.text == "Loving this show").one()
        reply = db.query(Comment).filter(Comment.user_id == user["id"], Comment.text == "Me too!").one()
    finally:
        db.close()
    assert reply.parent_id == root.id
    assert reply.title_id is None
    assert reply.season is None and reply.episode is None


def test_import_drops_reply_to_another_users_comment(client, alice, monkeypatch):
    """A reply whose parent isn't in this user's own export (i.e. a reply to
    someone else's comment) must not be filed as a fake root comment."""
    user, headers = alice
    client.post("/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers)

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        show_comments=[
            {
                "id": "2",
                "parent_comment_id": "999999",  # someone else's comment, not in this export
                "tv_show_id": "100",
                "comment": "Agreed",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 0
    assert summary["comments_skipped"] == 1
    db = SessionLocal()
    try:
        assert db.query(Comment).filter(Comment.user_id == user["id"]).count() == 0
    finally:
        db.close()


def test_import_adds_movie_comment_and_reply(client, alice, monkeypatch):
    user, headers = alice
    movie = client.post("/media", json={"media_type": "film", "title": "Heat", "tmdb_id": 777}, headers=headers).json()

    _patch_tmdb(monkeypatch, movie_match={"id": 777, "title": "Heat", "release_date": "1995-12-15"})
    zip_bytes = _build_zip(
        movie_events=[
            {
                "movie_name": "Heat",
                "type": "watch",
                "runtime": "0",
                "release_date": "1995-12-15",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
        movie_comments=[
            {
                "uuid": "c1",
                "type": "comment",
                "movie_name": "Heat",
                "text": "One of the greats",
                "created_at": "2026-01-01 00:00:00",
            },
            {
                "uuid": "c2",
                "parent_uuid": "c1",
                "type": "reply",
                "movie_name": "Heat",
                "text": "Agreed, De Niro and Pacino at their best",
                "created_at": "2026-01-02 00:00:00",
            },
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 2
    assert summary["comments_skipped"] == 0
    title_id = _title_id_for_entry(movie["id"])
    assert (None, None, "One of the greats") in _comments(user["id"], title_id)
    db = SessionLocal()
    try:
        root = db.query(Comment).filter(Comment.title_id == title_id, Comment.text == "One of the greats").one()
        reply = db.query(Comment).filter(Comment.parent_id == root.id).one()
        assert reply.text == "Agreed, De Niro and Pacino at their best"
        assert reply.title_id is None
    finally:
        db.close()


def test_import_ignores_movie_like_and_report_rows(client, alice, monkeypatch):
    """comments-prod-comments.csv mixes likes/reports into the same file via
    its `type` column — only comment/reply rows are real commentary."""
    user, headers = alice
    client.post("/media", json={"media_type": "film", "title": "Heat", "tmdb_id": 777}, headers=headers)

    _patch_tmdb(monkeypatch, movie_match={"id": 777, "title": "Heat", "release_date": "1995-12-15"})
    zip_bytes = _build_zip(
        movie_events=[
            {
                "movie_name": "Heat",
                "type": "watch",
                "runtime": "0",
                "release_date": "1995-12-15",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
        movie_comments=[
            {"uuid": "l1", "type": "like", "movie_name": "Heat", "text": "", "created_at": "2026-01-01 00:00:00"},
            {"uuid": "r1", "type": "report", "movie_name": "Heat", "text": "", "created_at": "2026-01-01 00:00:00"},
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 0
    assert summary["comments_skipped"] == 0


def test_import_skips_comments_on_unmatched_movies(client, alice, monkeypatch):
    user, _headers = alice
    _patch_tmdb(monkeypatch)  # nothing matches
    zip_bytes = _build_zip(
        movie_comments=[
            {
                "uuid": "c1",
                "type": "comment",
                "movie_name": "Never Tracked",
                "text": "Never tracked this one",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 0
    assert summary["comments_skipped"] == 1


# ---------- rewatches ----------


def test_import_adds_rewatch_events_and_backfills_episode_watch(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()
    # not previously marked watched — a rewatch record implies at least one watch
    assert _episode_keys(show["id"]) == set()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        rewatches=[
            {
                "episode_id": "1",
                "cpt": "2",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-02 00:00:00",
                "tv_show_name": "Dark",
                "episode_season_number": "1",
                "episode_number": "1",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["rewatches"] == 2
    assert summary["rewatches_skipped"] == 0
    assert _episode_keys(show["id"]) == {(1, 1)}
    assert _watch_event_count(show["id"], 1, 1) == 2


def test_reimport_tops_up_rewatch_count_without_duplicating(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        rewatches=[
            {
                "episode_id": "1",
                "cpt": "2",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-02 00:00:00",
                "tv_show_name": "Dark",
                "episode_season_number": "1",
                "episode_number": "1",
            }
        ],
    )
    _run(user["id"], zip_bytes)
    assert _watch_event_count(show["id"], 1, 1) == 2

    # re-run with a higher count: only the shortfall (1) should be added
    zip_bytes_2 = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        rewatches=[
            {
                "episode_id": "1",
                "cpt": "3",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-03 00:00:00",
                "tv_show_name": "Dark",
                "episode_season_number": "1",
                "episode_number": "1",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes_2)

    assert summary.get("error") is None
    assert summary["rewatches"] == 1
    assert _watch_event_count(show["id"], 1, 1) == 3


def test_import_skips_rewatches_on_unmatched_shows(client, alice, monkeypatch):
    user, _headers = alice
    _patch_tmdb(monkeypatch)  # nothing matches
    zip_bytes = _build_zip(
        rewatches=[
            {
                "episode_id": "1",
                "cpt": "2",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
                "tv_show_name": "Unknown Show",
                "episode_season_number": "1",
                "episode_number": "1",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["rewatches"] == 0
    assert summary["rewatches_skipped"] == 1


# ---------- concurrency: 8 worker threads racing on the same identity ----------


def _entry_count(user_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(LibraryEntry).filter(LibraryEntry.user_id == user_id).count()
    finally:
        db.close()


def _title_count(tmdb_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(Title).filter(Title.tmdb_id == tmdb_id).count()
    finally:
        db.close()


def test_concurrent_rows_resolving_to_same_show_insert_exactly_once(client, alice, monkeypatch):
    """40 rows with distinct TVDB ids all resolve to one TMDB show; the worker
    pool must produce exactly one Title and one LibraryEntry despite the race."""
    user, _headers = alice
    tvdb_ids = [str(i) for i in range(1, 41)]
    _patch_tmdb(monkeypatch, show_matches={t: ({"id": 999, "name": "Same Show"}, {}) for t in tvdb_ids})

    zip_bytes = _build_zip(
        shows=[{"tv_show_id": t, "tv_show_name": f"Same Show {t}", "is_favorited": "0"} for t in tvdb_ids],
        followed=[{"tv_show_id": t, "archived": "0"} for t in tvdb_ids],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["shows"] == 1
    # The 39 race losers are same-run duplicates of a brand-new show, not
    # pre-existing library entries — they must not inflate "skipped" (which
    # reads to the user as "already in your library"), since nothing here
    # existed before this import ran.
    assert summary["skipped"] == 0
    assert _entry_count(user["id"]) == 1
    assert _title_count(999) == 1


def test_concurrent_collision_losers_keep_their_episode_data(client, alice, monkeypatch):
    """Multiple brand-new TVDB rows resolving to the same TMDB show race the
    insert; only one wins it, but every row's episodes must still land on
    the single resulting entry instead of being dropped by the losers."""
    user, _headers = alice
    tvdb_ids = [str(i) for i in range(1, 21)]
    _patch_tmdb(monkeypatch, show_matches={t: ({"id": 999, "name": "Same Show"}, {}) for t in tvdb_ids})

    zip_bytes = _build_zip(
        shows=[{"tv_show_id": t, "tv_show_name": f"Same Show {t}", "is_favorited": "0"} for t in tvdb_ids],
        followed=[{"tv_show_id": t, "archived": "0"} for t in tvdb_ids],
        episode_events=[
            {"s_id": t, "s_no": "1", "ep_no": str(i + 1), "created_at": "2026-01-01 00:00:00"}
            for i, t in enumerate(tvdb_ids)
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert _entry_count(user["id"]) == 1
    db = SessionLocal()
    try:
        entry_id = db.query(LibraryEntry).filter(LibraryEntry.user_id == user["id"]).first().id
    finally:
        db.close()
    assert _episode_keys(entry_id) == {(1, i + 1) for i in range(len(tvdb_ids))}


def test_concurrent_reconcile_of_already_tracked_show_never_duplicates(client, alice, monkeypatch):
    user, headers = alice
    client.post("/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers)

    tvdb_ids = [str(i) for i in range(1, 13)]
    _patch_tmdb(monkeypatch, show_matches={t: ({"id": 555, "name": "Dark"}, {}) for t in tvdb_ids})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": t, "tv_show_name": "Dark", "is_favorited": "0"} for t in tvdb_ids],
        followed=[{"tv_show_id": t, "archived": "0"} for t in tvdb_ids],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["shows"] == 0
    assert summary["skipped"] == 12
    assert _entry_count(user["id"]) == 1
    assert _title_count(555) == 1


def test_reimport_is_idempotent(client, alice, monkeypatch):
    user, headers = alice
    show = client.post(
        "/media", json={"media_type": "tv_show", "title": "Dark", "tmdb_id": 555}, headers=headers
    ).json()

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        episode_events=[{"s_id": "100", "s_no": "1", "ep_no": "1", "created_at": "2026-01-01 00:00:00"}],
    )
    _run(user["id"], zip_bytes)
    summary = _run(user["id"], zip_bytes)  # run again with identical data

    assert summary.get("error") is None
    assert _episode_keys(show["id"]) == {(1, 1)}
    assert summary["episodes"] == 0
    assert summary["skipped"] == 1


def test_reimport_reconciles_show_that_was_unmatched_then_resolves(client, alice, monkeypatch):
    """A row TMDB couldn't match on the first import is created unmatched,
    keyed on the raw TV Time name (see the title_key comment in
    _process_show). A later re-import where TMDB now resolves a match —
    same row, same raw name, but a different (translated) TMDB title —
    must reconcile into that same entry instead of creating a duplicate."""
    user, headers = alice
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "200", "tv_show_name": "Aqui no hay quien viva", "is_favorited": "0"}],
        followed=[{"tv_show_id": "200", "archived": "0"}],
    )

    _patch_tmdb(monkeypatch, show_matches={"200": (None, {})})
    _run(user["id"], zip_bytes)

    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1
    assert entries[0]["tmdb_id"] is None
    assert entries[0]["title"] == "Aqui no hay quien viva"

    _patch_tmdb(monkeypatch, show_matches={"200": ({"id": 501, "name": "No One Could Live Here"}, {})})
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1  # no duplicate
    assert entries[0]["tmdb_id"] == 501
    assert entries[0]["title"] == "No One Could Live Here"


def test_reimport_reconciles_movie_that_was_unmatched_then_resolves(client, alice, monkeypatch):
    user, headers = alice
    zip_bytes = _build_zip(
        movie_events=[
            {
                "movie_name": "Il Buono, il Brutto, il Cattivo",
                "type": "watch",
                "runtime": "",
                "release_date": "",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    )

    monkeypatch.setattr(imports_mod, "_search_movie", lambda name, year: (None, False))
    _run(user["id"], zip_bytes)

    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1
    assert entries[0]["tmdb_id"] is None

    monkeypatch.setattr(
        imports_mod,
        "_search_movie",
        lambda name, year: ({"id": 429, "title": "The Good, the Bad and the Ugly"}, False),
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1  # no duplicate
    assert entries[0]["tmdb_id"] == 429
    assert entries[0]["title"] == "The Good, the Bad and the Ugly"


# ---------- TVDB fallback (TMDB has no match at all) ----------

_TVDB_FALLBACK = {
    "tvdb_id": 200,
    "name": "No One Could Live Here",
    "poster_url": "https://artworks.thetvdb.com/banners/posters/200.jpg",
    "runtime_minutes": 70,
    "total_episodes": 2,
    "total_seasons": 1,
    "year": 2003,
    "episodes": [
        {"season": 1, "episode_number": 1, "name": "Pilot", "air_date": "2003-09-22"},
        {"season": 1, "episode_number": 2, "name": "Episode Two", "air_date": "2003-09-29"},
    ],
}


def test_import_uses_tvdb_fallback_when_tmdb_has_no_match(client, alice, monkeypatch):
    """TMDB down/no match at all for a show TV Time gave a TVDB id for:
    the entry still gets tracked, with a poster and real episodes, via
    TheTVDB directly instead of sitting fully blank."""
    user, headers = alice
    _patch_tmdb(monkeypatch, show_matches={"200": (None, {}, _TVDB_FALLBACK)})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "200", "tv_show_name": "Aqui no hay quien viva", "is_favorited": "0"}],
        followed=[{"tv_show_id": "200", "archived": "0"}],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1
    item = entries[0]
    assert item["tmdb_id"] is None
    assert item["title"] == "No One Could Live Here"
    assert item["poster_url"] == "https://artworks.thetvdb.com/banners/posters/200.jpg"

    db = SessionLocal()
    try:
        rows = db.query(Episode).filter_by(title_id=_title_id_for_entry(item["id"])).all()
        assert {(r.season, r.episode_number, r.name) for r in rows} == {
            (1, 1, "Pilot"),
            (1, 2, "Episode Two"),
        }
    finally:
        db.close()


def test_reimport_with_tvdb_fallback_again_does_not_duplicate(client, alice, monkeypatch):
    user, headers = alice
    _patch_tmdb(monkeypatch, show_matches={"200": (None, {}, _TVDB_FALLBACK)})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "200", "tv_show_name": "Aqui no hay quien viva", "is_favorited": "0"}],
        followed=[{"tv_show_id": "200", "archived": "0"}],
    )
    _run(user["id"], zip_bytes)
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1


def test_reimport_upgrades_tvdb_fallback_entry_once_tmdb_resolves(client, alice, monkeypatch):
    """The exact healing path this feature exists for: a TVDB-fallback
    entry later reconciles into a real TMDB match, on the same entry."""
    user, headers = alice
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "200", "tv_show_name": "Aqui no hay quien viva", "is_favorited": "0"}],
        followed=[{"tv_show_id": "200", "archived": "0"}],
    )

    _patch_tmdb(monkeypatch, show_matches={"200": (None, {}, _TVDB_FALLBACK)})
    _run(user["id"], zip_bytes)
    first = client.get("/media", headers=headers).json()[0]

    _patch_tmdb(monkeypatch, show_matches={"200": ({"id": 501, "name": "No One Could Live Here"}, {})})
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    entries = client.get("/media", headers=headers).json()
    assert len(entries) == 1  # still the same entry, not a duplicate
    assert entries[0]["id"] == first["id"]
    assert entries[0]["tmdb_id"] == 501


def test_tvdb_fallback_entry_still_gets_comments_and_rewatches(client, alice, monkeypatch):
    """A TVDB-fallback show got a real LibraryEntry (poster + episodes), so
    it must not be treated as "unmatched" for comments/rewatches — those
    were previously gated on items_by_tvdb, which this entry is in."""
    user, headers = alice
    _patch_tmdb(monkeypatch, show_matches={"200": (None, {}, _TVDB_FALLBACK)})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "200", "tv_show_name": "Aqui no hay quien viva", "is_favorited": "0"}],
        followed=[{"tv_show_id": "200", "archived": "0"}],
        show_comments=[
            {
                "id": "1",
                "parent_comment_id": "",
                "tv_show_id": "200",
                "comment": "Great show",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
        rewatches=[
            {
                "episode_id": "1",
                "cpt": "2",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
                "tv_show_name": "Aqui no hay quien viva",
                "episode_season_number": "1",
                "episode_number": "1",
            }
        ],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["comments"] == 1
    assert summary["rewatches"] == 2  # cpt="2" -> two WatchEvent rows


# ---------- custom lists ----------


def _user_lists(user_id: int) -> list[List]:
    db = SessionLocal()
    try:
        return db.query(List).filter(List.user_id == user_id).order_by(List.created_at).all()
    finally:
        db.close()


def _list_items(list_id: int) -> list[ListItem]:
    db = SessionLocal()
    try:
        return db.query(ListItem).filter(ListItem.list_id == list_id).order_by(ListItem.position).all()
    finally:
        db.close()


def _list_count(user_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(List).filter(List.user_id == user_id).count()
    finally:
        db.close()


def _list_item_count(user_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(ListItem).join(List).filter(List.user_id == user_id).count()
    finally:
        db.close()


def _make_list_row(
    s_key: str = "my-list-uuid",
    name: str = "",
    created_at: str = "2023-01-12 00:00:00",
    objects: str = "",
    row_type: str = "list",
    description: str = "",
) -> dict:
    return {
        "ordering": "0",
        "objects": objects,
        "s_key": s_key,
        "is_public": "false",
        "type": row_type,
        "name": name,
        "created_at": created_at,
        "user_id": "42",
        "description": description,
        "lists": "",
    }


def _objects_str(*entries: dict) -> str:
    """Build a Go fmt.Sprintf-style objects string from a list of dicts."""
    parts = []
    for entry in entries:
        kv = " ".join(f"{k}:{v}" for k, v in entry.items())
        parts.append(f"map[{kv}]")
    return "[" + " ".join(parts) + "]"


def test_import_lists_named_list_with_series_and_movie(client, alice, monkeypatch):
    """A named list row with one series object (has TVDB id) and one movie object
    (uuid resolved via tracking-prod-records) lands as List + two ListItems."""
    user, headers = alice

    # pre-track the show and movie so their titles already exist in the DB
    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    monkeypatch.setattr(imports_mod, "_search_movie", lambda name, year: ({"id": 777, "title": "Heat"}, False))

    objects = _objects_str(
        {"created_at": "1.673605669e+09", "type": "series", "id": "100", "uuid": "show-uuid-1"},
        {"created_at": "1.673605689e+09", "type": "movie", "uuid": "heat-uuid-1"},
    )
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        movie_events=[
            {
                "movie_name": "Heat",
                "type": "watch",
                "runtime": "0",
                "release_date": "1995-12-15",
                "created_at": "2023-01-01 00:00:00",
                "uuid": "heat-uuid-1",
            }
        ],
        lists=[_make_list_row(name="My Favorites", objects=objects)],
    )
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["lists"] == 1
    assert summary["lists_updated"] == 0
    assert summary["list_items"] == 2
    assert summary["list_items_skipped"] == 0

    lst = _user_lists(user["id"])
    assert len(lst) == 1
    assert lst[0].name == "My Favorites"

    items = _list_items(lst[0].id)
    assert len(items) == 2
    assert items[0].position == 0
    assert items[1].position == 1

    # Verify title_ids point to Title rows, not LibraryEntry rows
    db = SessionLocal()
    try:
        t_series = db.get(Title, items[0].title_id)
        t_movie = db.get(Title, items[1].title_id)
        assert t_series is not None and t_series.tmdb_id == 555
        assert t_movie is not None and t_movie.tmdb_id == 777
    finally:
        db.close()


def test_import_lists_blank_name_gets_generic_fallback(client, alice, monkeypatch):
    """A list row with blank name and a non-built-in s_key gets a date-based fallback name."""
    user, _headers = alice
    _patch_tmdb(monkeypatch)

    zip_bytes = _build_zip(lists=[_make_list_row(s_key="some-random-uuid", name="", created_at="2023-01-12 00:00:00")])
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["lists"] == 1
    lst = _user_lists(user["id"])
    assert len(lst) == 1
    assert lst[0].name == "Imported list (2023-01-12)"


def test_import_lists_favorite_movies_builtin_name(client, alice, monkeypatch):
    """s_key='favorite-movies' with blank name resolves to 'Favorite Movies'."""
    user, _headers = alice
    _patch_tmdb(monkeypatch)

    zip_bytes = _build_zip(lists=[_make_list_row(s_key="favorite-movies", name="")])
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["lists"] == 1
    lst = _user_lists(user["id"])
    assert lst[0].name == "Favorite Movies"


def test_import_lists_collection_junk_row_is_skipped(client, alice, monkeypatch):
    """The 'collection' junk row (type blank, s_key='collection') must be silently
    skipped — it produces no List row and no error."""
    user, _headers = alice
    _patch_tmdb(monkeypatch)

    junk_row = _make_list_row(s_key="collection", name="", row_type="")
    real_row = _make_list_row(s_key="my-list", name="My List")

    zip_bytes = _build_zip(lists=[junk_row, real_row])
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    # only the real list row should have been created
    assert _list_count(user["id"]) == 1
    assert _user_lists(user["id"])[0].name == "My List"


def test_import_lists_reimport_is_idempotent(client, alice, monkeypatch):
    """Running the import twice with identical list data must not duplicate the
    List row or the ListItem rows; list_items_skipped increments instead."""
    user, _headers = alice

    _patch_tmdb(monkeypatch, show_matches={"100": ({"id": 555, "name": "Dark"}, {})})
    monkeypatch.setattr(imports_mod, "_search_movie", lambda name, year: (None, False))

    objects = _objects_str({"type": "series", "id": "100", "uuid": "s1"})
    zip_bytes = _build_zip(
        shows=[{"tv_show_id": "100", "tv_show_name": "Dark", "is_favorited": "0"}],
        followed=[{"tv_show_id": "100", "archived": "0"}],
        lists=[_make_list_row(name="Watchlist", objects=objects)],
    )
    _run(user["id"], zip_bytes)
    assert _list_count(user["id"]) == 1
    assert _list_item_count(user["id"]) == 1

    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    # no new list or items; existing list merged
    assert summary["lists"] == 0
    assert summary["lists_updated"] == 1
    assert summary["list_items"] == 0
    assert summary["list_items_skipped"] == 1
    assert _list_count(user["id"]) == 1
    assert _list_item_count(user["id"]) == 1


def test_import_lists_dead_uuid_is_skipped_not_error(client, alice, monkeypatch):
    """A movie object whose uuid has no matching row in tracking-prod-records.csv
    is skipped and counted, not treated as an error."""
    user, _headers = alice
    _patch_tmdb(monkeypatch)

    objects = _objects_str({"type": "movie", "uuid": "dead-uuid-no-match"})
    # tracking-prod-records.csv has NO row with uuid=dead-uuid-no-match
    zip_bytes = _build_zip(lists=[_make_list_row(name="Dead Movie List", objects=objects)])
    summary = _run(user["id"], zip_bytes)

    assert summary.get("error") is None
    assert summary["list_items_skipped"] == 1
    assert summary["list_items"] == 0
    # The List row itself is still created (we discovered dead uuid while processing items)
    assert _list_count(user["id"]) == 1
    assert _list_item_count(user["id"]) == 0
