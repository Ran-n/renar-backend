#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:11.618781
Revised: 2026/11/13 15:35:11.618781

Media router corners: localized titles in the library list, a concurrent
add of the same title, deriving the current episode from a watched count,
"Link to catalog" racing another request, re-setting the same episode still,
rewatch history on episodes whose watch row is gone (orphans left by older
bulk unmarks and TV Time imports), and the season/episode pairing check.
"""

import base64
import io
from datetime import timedelta

import pytest
from _race_helpers import commit_elsewhere, hide_selects
from PIL import Image as PILImage

from renar_backend.database import SessionLocal
from renar_backend.models import (
    Episode,
    EpisodeWatch,
    LibraryEntry,
    MediaType,
    Title,
    TmdbCache,
    User,
    WatchEvent,
    utcnow,
)
from renar_backend.routers import media


def _png_b64(color=(200, 30, 30)) -> str:
    out = io.BytesIO()
    PILImage.new("RGB", (20, 30), color).save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def _add(client, headers, **fields) -> dict:
    r = client.post("/media", json=fields, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _set_premium(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()


def _title_id(entry_id: int) -> int:
    db = SessionLocal()
    try:
        return db.get(LibraryEntry, entry_id).title_id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /media?lang=
# ---------------------------------------------------------------------------


def test_library_list_uses_cached_translations(client, alice, monkeypatch):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Spirited Away", tmdb_id=129)
    commit_elsewhere(
        TmdbCache(
            title_id=_title_id(film["id"]),
            kind="details",
            season=-1,
            language="es",
            payload={"title": "El viaje de Chihiro"},
        )
    )
    monkeypatch.setattr(media, "warm_title_translations", lambda ids, lang: pytest.fail("all translated"))

    (entry,) = client.get("/media", params={"lang": "es"}, headers=headers).json()

    assert (entry["title"], entry["display_title"]) == ("Spirited Away", "El viaje de Chihiro")


def test_library_list_warms_missing_translations(client, alice, monkeypatch):
    _, headers = alice
    film = _add(client, headers, media_type="film", title="Heat", tmdb_id=949)
    warmed = []
    monkeypatch.setattr(media, "warm_title_translations", lambda ids, lang: warmed.append((ids, lang)))

    (entry,) = client.get("/media", params={"lang": "es"}, headers=headers).json()

    assert entry["display_title"] == "Heat"
    assert warmed == [([_title_id(film["id"])], "es")]


# ---------------------------------------------------------------------------
# POST /media race
# ---------------------------------------------------------------------------


def test_concurrent_add_of_the_same_title_is_a_409(client, alice):
    user, headers = alice
    (title_id,) = commit_elsewhere(Title(media_type=MediaType.film, tmdb_id=603, title="The Matrix"))
    commit_elsewhere(LibraryEntry(user_id=user["id"], title_id=title_id))  # the other request's add
    remove = hide_selects(SessionLocal, LibraryEntry, times=1)  # our duplicate check ran first
    try:
        r = client.post("/media", json={"media_type": "film", "title": "The Matrix", "tmdb_id": 603}, headers=headers)
    finally:
        remove()

    assert r.status_code == 409
    assert r.json()["detail"] == "You already saved this title"


# ---------------------------------------------------------------------------
# PATCH /media/{id}
# ---------------------------------------------------------------------------


def test_watched_count_derives_the_current_episode(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523)
    title_id = _title_id(show["id"])
    commit_elsewhere(*[Episode(title_id=title_id, season=s, episode_number=e) for s, e in [(1, 1), (1, 2), (2, 1)]])

    r = client.patch(f"/media/{show['id']}", json={"episodes_watched": 3}, headers=headers)

    assert r.status_code == 200, r.text
    assert (r.json()["current_season"], r.json()["current_episode"]) == (2, 1)


def test_watched_count_past_the_catalog_stops_at_the_last_episode(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523)
    commit_elsewhere(Episode(title_id=_title_id(show["id"]), season=1, episode_number=1))

    r = client.patch(f"/media/{show['id']}", json={"episodes_watched": 9}, headers=headers)

    assert (r.json()["current_season"], r.json()["current_episode"]) == (1, 1)


def _unmatched_film(client, headers) -> dict:
    return _add(client, headers, media_type="film", title="Raw Import Name")


def test_relink_folds_into_a_title_created_concurrently(client, alice, monkeypatch):
    _, headers = alice
    entry = _unmatched_film(client, headers)
    (winner_id,) = commit_elsewhere(Title(media_type=MediaType.film, tmdb_id=680, title="Pulp Fiction"))
    monkeypatch.setattr(media, "find_title", lambda *a, **kw: None)  # looked before it existed
    monkeypatch.setattr(media, "cached_tmdb", lambda *a, **kw: {"id": 680, "title": "Pulp Fiction"})

    r = client.patch(f"/media/{entry['id']}", json={"tmdb_id": 680}, headers=headers)

    assert r.status_code == 200, r.text
    assert _title_id(entry["id"]) == winner_id


def test_relink_that_loses_the_claim_is_a_409(client, alice, monkeypatch):
    _, headers = alice
    entry = _unmatched_film(client, headers)
    monkeypatch.setattr(media, "cached_tmdb", lambda *a, **kw: {"id": 681, "title": "Jackie Brown"})
    monkeypatch.setattr(media, "backfill_title_tmdb_id", lambda *a, **kw: None)  # claim went elsewhere

    r = client.patch(f"/media/{entry['id']}", json={"tmdb_id": 681}, headers=headers)

    assert r.status_code == 409
    assert "just linked by another request" in r.json()["detail"]


# ---------------------------------------------------------------------------
# episode stills
# ---------------------------------------------------------------------------


def test_setting_the_same_still_again_collects_nothing(client, alice, monkeypatch):
    user, headers = alice
    _set_premium(user["id"])
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523)
    url = f"/media/{show['id']}/episodes/1/1/still"
    first = client.put(url, json={"image_b64": _png_b64()}, headers=headers).json()
    monkeypatch.setattr(media, "gc_image", lambda image_id, db: pytest.fail("same image: nothing to collect"))

    again = client.put(url, json={"image_b64": _png_b64()}, headers=headers)

    assert again.status_code == 200
    assert again.json()["still_url"] == first["still_url"]


# ---------------------------------------------------------------------------
# rewatch history on orphaned episode events
# ---------------------------------------------------------------------------


def _show_with_orphan_events(client, headers, *ratings) -> tuple[dict, list[int]]:
    """A watched episode with rewatches whose EpisodeWatch row is then lost,
    the state older bulk unmarks and TV Time imports could leave."""
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523)
    db = SessionLocal()
    try:
        events = [WatchEvent(media_item_id=show["id"], season=1, episode=1, rating=r) for r in ratings]
        db.add_all(events)
        db.commit()
        ids = [e.id for e in events]
        assert db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == show["id"]).count() == 0
    finally:
        db.close()
    return show, ids


def test_undo_rewatch_of_an_orphaned_episode(client, alice):
    _, headers = alice
    show, _ = _show_with_orphan_events(client, headers, 70, 80)

    r = client.request("DELETE", f"/media/{show['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)

    assert r.status_code == 200, r.text


def test_delete_rewatch_event_of_an_orphaned_episode(client, alice):
    _, headers = alice
    show, (first, second) = _show_with_orphan_events(client, headers, 70, 80)

    r = client.delete(f"/media/{show['id']}/rewatch-events/{second}", headers=headers)

    assert r.status_code == 200, r.text


def test_rate_rewatch_event_of_an_orphaned_episode(client, alice):
    _, headers = alice
    show, (event_id,) = _show_with_orphan_events(client, headers, 70)

    r = client.patch(f"/media/{show['id']}/rewatch-events/{event_id}", json={"rating": 95}, headers=headers)

    assert r.status_code == 200, r.text


def test_write_rating_for_an_episode_without_a_watch_row(client, alice):
    _, headers = alice
    show, (event_id,) = _show_with_orphan_events(client, headers, 60)
    db = SessionLocal()
    try:
        item = db.get(LibraryEntry, show["id"])
        media._write_rating(db, item, 1, 1, 88)
        db.commit()
        assert db.get(WatchEvent, event_id).rating == 88
    finally:
        db.close()


def test_rewatch_events_need_season_and_episode_together(client, alice):
    _, headers = alice
    show = _add(client, headers, media_type="tv_show", title="Dark", tmdb_id=70523)

    r = client.get(f"/media/{show['id']}/rewatch-events", params={"season": 1}, headers=headers)

    assert r.status_code == 422
    assert r.json()["detail"] == "season and episode must be given together"
