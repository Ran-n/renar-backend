#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/14 00:22:43.927158
Revised: 2026/11/14 22:43:29.003570

GET /diary: the caller's watched episodes and films, newest first, with
type and date filters and paging.
"""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from renar_backend.database import SessionLocal
from renar_backend.models import Episode, EpisodeWatch, LibraryEntry, User, utcnow

pytestmark = pytest.mark.regression


def _show(client, headers, **overrides) -> dict:
    payload = {"media_type": "tv_show", "title": "Dark", "total_episodes": 10} | overrides
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _film(client, headers, completed: bool = True, **overrides) -> dict:
    payload = {"media_type": "film", "title": "Heat"} | overrides
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    film = r.json()
    if completed:
        r = client.patch(f"/media/{film['id']}", json={"status": "completed"}, headers=headers)
        assert r.status_code == 200, r.text
    return film


def _watch(client, headers, item_id: int, season: int, episode: int, **body) -> None:
    r = client.put(f"/media/{item_id}/episodes/{season}/{episode}", json={"watched": True, **body}, headers=headers)
    assert r.status_code == 200, r.text


def _stamp_episode(item_id: int, season: int, episode: int, when: datetime) -> None:
    db = SessionLocal()
    try:
        row = db.query(EpisodeWatch).filter_by(media_item_id=item_id, season=season, episode=episode).one()
        row.watched_at = when
        db.commit()
    finally:
        db.close()


def _stamp_film(item_id: int, when: datetime) -> None:
    db = SessionLocal()
    try:
        db.get(LibraryEntry, item_id).last_watched_at = when
        db.commit()
    finally:
        db.close()


def _diary(client, headers, **params) -> list[dict]:
    r = client.get("/diary", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _keys(entries: list[dict]) -> list[tuple]:
    return [(e["type"], e["title"], e["season"], e["episode"]) for e in entries]


DAY = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


def test_diary_empty(client, alice):
    _, headers = alice
    assert _diary(client, headers) == []


def test_diary_needs_auth(client):
    assert client.get("/diary").status_code == 401


def test_diary_lists_episodes_and_films_newest_first(client, alice):
    """Episodes and films share one list ordered by watch date, each with
    its own rating and the fields the client needs to open the title."""
    _, headers = alice
    show = _show(client, headers, tmdb_id=70523)
    film = _film(client, headers, tmdb_id=949)
    _watch(client, headers, show["id"], 1, 1, rating=80)
    _watch(client, headers, show["id"], 1, 2)
    client.patch(f"/media/{film['id']}", json={"rating": 95}, headers=headers)
    _stamp_episode(show["id"], 1, 1, DAY - timedelta(days=2))
    _stamp_film(film["id"], DAY - timedelta(days=1))
    _stamp_episode(show["id"], 1, 2, DAY)

    entries = _diary(client, headers)
    assert _keys(entries) == [("episode", "Dark", 1, 2), ("film", "Heat", None, None), ("episode", "Dark", 1, 1)]
    newest, film_entry, oldest = entries
    assert newest["rating"] is None
    assert oldest["rating"] == 80
    assert oldest["item_id"] == show["id"]
    assert oldest["tmdb_id"] == 70523
    assert oldest["media_type"] == "tv_show"
    assert film_entry["rating"] == 95
    assert film_entry["item_id"] == film["id"]
    assert film_entry["media_type"] == "film"
    assert film_entry["episode_name"] is None
    assert datetime.fromisoformat(film_entry["watched_at"]) == DAY - timedelta(days=1)


def test_diary_only_shows_own_watches(client, alice, bob):
    _, a = alice
    _, b = bob
    show = _show(client, a)
    _watch(client, a, show["id"], 1, 1)
    _film(client, b)
    assert _keys(_diary(client, a)) == [("episode", "Dark", 1, 1)]
    assert _keys(_diary(client, b)) == [("film", "Heat", None, None)]


def test_diary_skips_unwatched_films_and_shows_without_episodes(client, alice):
    """A film that is only planned or in progress is not a watch, and a show
    has no entry of its own: only its watched episodes do."""
    _, headers = alice
    _film(client, headers, completed=False)
    _film(client, headers, completed=False, title="Collateral", status="watching")
    _show(client, headers)
    assert _diary(client, headers) == []


def test_diary_unwatching_an_episode_removes_its_entry(client, alice):
    _, headers = alice
    show = _show(client, headers)
    _watch(client, headers, show["id"], 1, 1)
    r = client.put(f"/media/{show['id']}/episodes/1/1", json={"watched": False}, headers=headers)
    assert r.status_code == 200, r.text
    assert _diary(client, headers) == []


def test_diary_film_rewatch_moves_the_entry_not_duplicates_it(client, alice):
    """One entry per film: a rewatch brings it to its latest date."""
    _, headers = alice
    film = _film(client, headers)
    _stamp_film(film["id"], DAY - timedelta(days=30))
    assert client.post(f"/media/{film['id']}/rewatch", json={}, headers=headers).status_code == 200
    entries = _diary(client, headers)
    assert len(entries) == 1
    assert datetime.fromisoformat(entries[0]["watched_at"]) > DAY


def test_diary_type_filter(client, alice):
    _, headers = alice
    show = _show(client, headers)
    _film(client, headers)
    _watch(client, headers, show["id"], 1, 1)
    assert _keys(_diary(client, headers, type="film")) == [("film", "Heat", None, None)]
    assert _keys(_diary(client, headers, type="episode")) == [("episode", "Dark", 1, 1)]
    assert client.get("/diary", params={"type": "show"}, headers=headers).status_code == 422


def test_diary_date_range_includes_both_ends(client, alice):
    """`from`/`to` are whole UTC days: a watch at 00:00 on `from` and one at
    23:59 on `to` are both in, the minute before and after are out."""
    _, headers = alice
    show = _show(client, headers)
    stamps = {
        1: datetime(2026, 5, 9, 23, 59, tzinfo=UTC),
        2: datetime(2026, 5, 10, 0, 0, tzinfo=UTC),
        3: datetime(2026, 5, 11, 23, 59, tzinfo=UTC),
        4: datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
    }
    for episode, when in stamps.items():
        _watch(client, headers, show["id"], 1, episode)
        _stamp_episode(show["id"], 1, episode, when)
    in_range = _diary(client, headers, **{"from": "2026-05-10", "to": "2026-05-11"})
    assert [e["episode"] for e in in_range] == [3, 2]
    assert [e["episode"] for e in _diary(client, headers, **{"from": "2026-05-11"})] == [4, 3]
    assert [e["episode"] for e in _diary(client, headers, to="2026-05-09")] == [1]
    assert [e["episode"] for e in _diary(client, headers, **{"from": "2026-05-10", "to": "2026-05-10"})] == [2]


def test_diary_date_range_follows_the_callers_utc_offset(client, alice):
    """A client that groups entries by its local day sends its offset: the
    range then covers its local days. Used to be UTC days only, so a watch
    just after local midnight (still the day before in UTC) fell out of the
    day the client listed it under."""
    _, headers = alice
    show = _show(client, headers)
    stamps = {
        1: datetime(2026, 5, 9, 21, 59, tzinfo=UTC),  # 23:59 on the 9th at UTC+2
        2: datetime(2026, 5, 9, 22, 0, tzinfo=UTC),  # 00:00 on the 10th at UTC+2
        3: datetime(2026, 5, 10, 21, 59, tzinfo=UTC),  # 23:59 on the 10th at UTC+2
        4: datetime(2026, 5, 10, 22, 0, tzinfo=UTC),  # 00:00 on the 11th at UTC+2
    }
    for episode, when in stamps.items():
        _watch(client, headers, show["id"], 1, episode)
        _stamp_episode(show["id"], 1, episode, when)
    tenth = {"from": "2026-05-10", "to": "2026-05-10"}
    assert [e["episode"] for e in _diary(client, headers, **tenth, utc_offset=120)] == [3, 2]
    assert [e["episode"] for e in _diary(client, headers, **tenth)] == [4, 3]  # UTC days by default
    # west of UTC the local day starts later: the 9th at UTC-3 runs 03:00 UTC to 03:00 UTC on the 10th
    ninth = {"from": "2026-05-09", "to": "2026-05-09"}
    assert [e["episode"] for e in _diary(client, headers, **ninth, utc_offset=-180)] == [2, 1]
    assert _diary(client, headers, to="2026-05-08", utc_offset=-180) == []


def test_diary_range_across_a_clock_change_uses_each_ends_offset(client, alice):
    """A range that crosses a daylight-saving change is cut at the right
    local midnight at both ends: 24 to 26 Oct 2026 in Madrid starts at
    UTC+2 and ends at UTC+1 (clocks go back on the 25th)."""
    _, headers = alice
    show = _show(client, headers)
    stamps = {
        1: datetime(2026, 10, 23, 21, 59, tzinfo=UTC),  # 23:59 on the 23rd, UTC+2: out
        2: datetime(2026, 10, 23, 22, 0, tzinfo=UTC),  # 00:00 on the 24th, UTC+2: in
        3: datetime(2026, 10, 26, 22, 30, tzinfo=UTC),  # 23:30 on the 26th, UTC+1: in
        4: datetime(2026, 10, 26, 23, 0, tzinfo=UTC),  # 00:00 on the 27th, UTC+1: out
    }
    for episode, when in stamps.items():
        _watch(client, headers, show["id"], 1, episode)
        _stamp_episode(show["id"], 1, episode, when)
    span = {"from": "2026-10-24", "to": "2026-10-26"}
    assert [e["episode"] for e in _diary(client, headers, **span, utc_offset=120, utc_offset_to=60)] == [3, 2]
    # one offset for both ends (the old behaviour) drops the last local hour
    assert [e["episode"] for e in _diary(client, headers, **span, utc_offset=120)] == [2]
    assert client.get("/diary", params={"utc_offset_to": 900}, headers=headers).status_code == 422


@pytest.mark.parametrize("offset", [-841, 841, "east"])
def test_diary_utc_offset_out_of_range_rejected(client, alice, offset):
    _, headers = alice
    assert client.get("/diary", params={"utc_offset": offset}, headers=headers).status_code == 422


def test_diary_inverted_or_invalid_dates_rejected(client, alice):
    _, headers = alice
    r = client.get("/diary", params={"from": "2026-05-11", "to": "2026-05-10"}, headers=headers)
    assert r.status_code == 422
    assert "from" in r.json()["detail"]
    assert client.get("/diary", params={"from": "yesterday"}, headers=headers).status_code == 422


def test_diary_paging_covers_everything_once(client, alice):
    """Pages don't overlap or skip, even when a bulk mark stamps many
    episodes in the same instant; a short page is the last one."""
    _, headers = alice
    show = _show(client, headers)
    r = client.post(
        f"/media/{show['id']}/episodes/bulk",
        json={"season": 1, "episodes": [1, 2, 3, 4, 5], "watched": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    for episode in range(1, 6):
        _stamp_episode(show["id"], 1, episode, DAY)  # identical instants
    pages = [_diary(client, headers, page=n, page_size=2) for n in (1, 2, 3, 4)]
    assert [len(p) for p in pages] == [2, 2, 1, 0]
    assert [e["episode"] for p in pages for e in p] == [5, 4, 3, 2, 1]


def test_diary_paging_bounds_rejected(client, alice):
    _, headers = alice
    for params in ({"page": 0}, {"page_size": 0}, {"page_size": 101}):
        assert client.get("/diary", params=params, headers=headers).status_code == 422


def test_diary_episode_name_from_catalog(client, alice):
    """An episode the catalog knows carries its name; an unknown one is null."""
    _, headers = alice
    show = _show(client, headers)
    _watch(client, headers, show["id"], 1, 1)
    _watch(client, headers, show["id"], 1, 2)
    db = SessionLocal()
    try:
        title_id = db.get(LibraryEntry, show["id"]).title_id
        db.add(Episode(title_id=title_id, season=1, episode_number=1, name="Secrets"))
        db.commit()
    finally:
        db.close()
    names = {e["episode"]: e["episode_name"] for e in _diary(client, headers)}
    assert names == {1: "Secrets", 2: None}


def test_diary_poster_is_the_titles_or_the_premium_override(client, alice):
    """The poster is the title's, unless the caller is premium and set a
    custom one: same rule as everywhere else a library entry is shown."""
    from renar_backend.models import Image

    user, headers = alice
    film = _film(client, headers)
    db = SessionLocal()
    try:
        entry = db.get(LibraryEntry, film["id"])
        entry.title_ref.poster_url = "/tmdb/heat.jpg"
        image = Image(hash="abc123", size_bytes=1)
        db.add(image)
        db.flush()
        entry.custom_poster_image_id = image.id
        db.commit()
    finally:
        db.close()
    assert _diary(client, headers)[0]["poster_url"] == "/tmdb/heat.jpg"
    db = SessionLocal()
    try:
        db.get(User, user["id"]).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()
    assert _diary(client, headers)[0]["poster_url"] == "/images/abc123"


def test_diary_localizes_titles_from_cache_and_warms_the_rest(client, alice, monkeypatch):
    """`lang` uses a cached translation when there is one and queues the
    missing titles for background translation, never blocking on TMDB."""
    from renar_backend.routers import diary

    _, headers = alice
    heat = _film(client, headers)
    other = _film(client, headers, title="Collateral")
    db = SessionLocal()
    try:
        heat_title = db.get(LibraryEntry, heat["id"]).title_id
        other_title = db.get(LibraryEntry, other["id"]).title_id
    finally:
        db.close()
    monkeypatch.setattr(diary, "localized_titles", lambda db, ids, lang: {heat_title: "Fuego contra fuego"})
    warmed = []
    monkeypatch.setattr(diary, "warm_title_translations", lambda ids, lang: warmed.append((ids, lang)))
    titles = {e["title"] for e in _diary(client, headers, lang="es")}
    assert titles == {"Fuego contra fuego", "Collateral"}
    assert warmed == [([other_title], "es")]
    warmed.clear()
    assert {e["title"] for e in _diary(client, headers, lang="en")} == {"Heat", "Collateral"}
    assert warmed == []


@pytest.mark.property
@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    offsets=st.lists(st.integers(min_value=0, max_value=5), min_size=1, max_size=8),
    page_size=st.integers(min_value=1, max_value=4),
)
def test_diary_pages_concatenate_to_the_sorted_whole(client, make_user, offsets, page_size):
    """For any set of watch dates (ties included) and any page size, walking
    the pages yields every watch exactly once, newest first."""
    import uuid

    _, headers = make_user(f"u{uuid.uuid4().hex[:10]}")
    show = _show(client, headers, total_episodes=len(offsets))
    for episode, days in enumerate(offsets, start=1):
        _watch(client, headers, show["id"], 1, episode)
        _stamp_episode(show["id"], 1, episode, DAY - timedelta(days=days))
    walked, page = [], 1
    while chunk := _diary(client, headers, page=page, page_size=page_size):
        walked += chunk
        page += 1
    assert sorted(e["episode"] for e in walked) == list(range(1, len(offsets) + 1))
    stamps = [e["watched_at"] for e in walked]
    assert stamps == sorted(stamps, reverse=True)


def test_diary_lang_with_every_title_translated_queues_no_warm_up(client, alice, monkeypatch):
    """When the cache already holds every title in `lang`, nothing is
    queued for translation."""
    from renar_backend.routers import diary

    _, headers = alice
    heat = _film(client, headers)
    db = SessionLocal()
    try:
        heat_title = db.get(LibraryEntry, heat["id"]).title_id
    finally:
        db.close()
    warmed = []
    monkeypatch.setattr(diary, "localized_titles", lambda db, ids, lang: {heat_title: "Fuego contra fuego"})
    monkeypatch.setattr(diary, "warm_title_translations", lambda ids, lang: warmed.append((ids, lang)))
    assert [e["title"] for e in _diary(client, headers, lang="es")] == ["Fuego contra fuego"]
    assert warmed == []
