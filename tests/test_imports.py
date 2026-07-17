#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/09 14:29:25.931212
Revised: 2026/07/10 13:42:46.181230

TV Time import reconciliation: merging into titles the user already tracks
(manually or from a prior import), instead of skipping them outright.
"""

import csv
import io
import zipfile

import renar_backend.routers.imports as imports_mod
from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeWatch, LibraryEntry, Title


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
            _csv_bytes(movie_events or [], ["movie_name", "type", "runtime", "release_date", "created_at"]),
        )
    return buf.getvalue()


def _episode_keys(item_id: int) -> set[tuple[int, int]]:
    db = SessionLocal()
    try:
        rows = db.query(EpisodeWatch.season, EpisodeWatch.episode).filter(EpisodeWatch.media_item_id == item_id).all()
        return set(rows)
    finally:
        db.close()


def _run(user_id: int, zip_bytes: bytes) -> dict:
    imports_mod._run_import(user_id, zip_bytes)
    return imports_mod._progress[user_id]["summary"]


def _patch_tmdb(
    monkeypatch, show_matches: dict[str, tuple[dict | None, dict]] | None = None, movie_match: dict | None = None
):
    monkeypatch.setattr(imports_mod, "_match_show", lambda tvdb_id, name: (show_matches or {}).get(tvdb_id, (None, {})))
    monkeypatch.setattr(imports_mod, "_search_movie", lambda name, year: movie_match)


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
    assert item["rating"] == 8  # 4 on TV Time's 1-5 scale -> 8 on a 1-10 scale


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
    assert summary["skipped"] == 39
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
