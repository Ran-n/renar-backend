#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:17.395578
Revised: 2026/07/18 19:33:27.970634

Media library CRUD, filters, ownership, and community ratings.
"""

from renar_backend.database import SessionLocal
from renar_backend.models import EpisodeWatch, Notification, WatchEvent


def _create(client, headers, **overrides) -> dict:
    payload = {"media_type": "film", "title": "Heat"}
    payload.update(overrides)
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- create ----------


def test_create_film(client, alice):
    _, headers = alice
    item = _create(client, headers, year=1995, rating=9, status="completed")
    assert item["title"] == "Heat"
    assert item["year"] == 1995
    assert item["rating"] == 9
    assert item["status"] == "completed"


def test_create_duplicate_title_conflicts(client, alice):
    _, headers = alice
    _create(client, headers)
    r = client.post("/media", json={"media_type": "film", "title": "Heat"}, headers=headers)
    assert r.status_code == 409


def test_same_title_allowed_for_other_user(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers)
    _create(client, bob_headers)


def test_create_requires_auth(client):
    r = client.post("/media", json={"media_type": "film", "title": "Heat"})
    assert r.status_code == 401


def test_create_invalid_rating_rejected(client, alice):
    _, headers = alice
    r = client.post("/media", json={"media_type": "film", "title": "Heat", "rating": 11}, headers=headers)
    assert r.status_code == 422


def test_create_empty_title_rejected(client, alice):
    _, headers = alice
    r = client.post("/media", json={"media_type": "film", "title": ""}, headers=headers)
    assert r.status_code == 422


def test_create_unknown_media_type_rejected(client, alice):
    _, headers = alice
    r = client.post("/media", json={"media_type": "vinyl", "title": "Heat"}, headers=headers)
    assert r.status_code == 422


# ---------- list / filters ----------


def test_list_only_own_items(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers)
    _create(client, bob_headers, title="Alien")
    titles = [i["title"] for i in client.get("/media", headers=alice_headers).json()]
    assert titles == ["Heat"]


def test_list_filters(client, alice):
    _, headers = alice
    _create(client, headers, title="Heat", status="completed")
    _create(client, headers, media_type="tv_show", title="Dark", status="watching")

    by_type = client.get("/media", params={"media_type": "tv_show"}, headers=headers).json()
    assert [i["title"] for i in by_type] == ["Dark"]

    by_status = client.get("/media", params={"status_filter": "completed"}, headers=headers).json()
    assert [i["title"] for i in by_status] == ["Heat"]

    by_search = client.get("/media", params={"search": "ark"}, headers=headers).json()
    assert [i["title"] for i in by_search] == ["Dark"]


def test_list_pagination(client, alice):
    _, headers = alice
    for i in range(5):
        _create(client, headers, title=f"Title {i}")

    page1 = client.get("/media", params={"limit": 2, "offset": 0}, headers=headers).json()
    page2 = client.get("/media", params={"limit": 2, "offset": 2}, headers=headers).json()
    page3 = client.get("/media", params={"limit": 2, "offset": 4}, headers=headers).json()

    assert [i["title"] for i in page1] == ["Title 4", "Title 3"]
    assert [i["title"] for i in page2] == ["Title 2", "Title 1"]
    assert [i["title"] for i in page3] == ["Title 0"]

    no_limit_given = client.get("/media", headers=headers).json()
    assert len(no_limit_given) == 5


def test_list_default_limit(client, alice):
    _, headers = alice
    for i in range(65):
        _create(client, headers, title=f"Title {i}")

    capped = client.get("/media", headers=headers).json()
    assert len(capped) == 60  # default page size when `limit` is omitted

    page2 = client.get("/media", params={"offset": 60}, headers=headers).json()
    assert len(page2) == 5


def test_list_keys(client, alice, bob):
    _, headers = alice
    _, bob_headers = bob
    _create(client, headers, title="Heat", tmdb_id=101)
    _create(client, headers, media_type="tv_show", title="Some Show", url="https://example.com/show")
    _create(client, bob_headers, title="Alien", tmdb_id=202)  # someone else's — must not leak

    keys = client.get("/media/keys", headers=headers).json()
    assert {(k["media_type"], k["tmdb_id"], k["title"]) for k in keys} == {
        ("film", 101, "Heat"),
        ("tv_show", None, "Some Show"),
    }
    assert next(k for k in keys if k["title"] == "Some Show")["url"] == "https://example.com/show"


def test_get_media_by_tmdb(client, alice):
    _, headers = alice
    created = _create(client, headers, title="Heat", tmdb_id=101)

    found = client.get("/media/by_tmdb", params={"media_type": "film", "tmdb_id": 101}, headers=headers)
    assert found.status_code == 200
    assert found.json()["id"] == created["id"]

    missing = client.get("/media/by_tmdb", params={"media_type": "film", "tmdb_id": 999}, headers=headers)
    assert missing.status_code == 404


def test_get_media_by_tmdb_not_other_users(client, alice, bob):
    _, headers = alice
    _, bob_headers = bob
    _create(client, bob_headers, title="Alien", tmdb_id=202)

    r = client.get("/media/by_tmdb", params={"media_type": "film", "tmdb_id": 202}, headers=headers)
    assert r.status_code == 404


def test_list_favorites_only_paginated(client, alice):
    _, headers = alice
    _create(client, headers, title="Heat", is_favorite=True)
    _create(client, headers, title="Alien", is_favorite=False)
    _create(client, headers, title="Dark", media_type="tv_show", is_favorite=True)

    favorites = client.get("/media", params={"favorites_only": True}, headers=headers).json()
    assert {i["title"] for i in favorites} == {"Heat", "Dark"}

    favorites_page1 = client.get(
        "/media", params={"favorites_only": True, "limit": 1, "offset": 0}, headers=headers
    ).json()
    favorites_page2 = client.get(
        "/media", params={"favorites_only": True, "limit": 1, "offset": 1}, headers=headers
    ).json()
    assert [i["title"] for i in favorites_page1] == ["Dark"]
    assert [i["title"] for i in favorites_page2] == ["Heat"]


# ---------- get / patch / ownership ----------


def test_get_item(client, alice):
    _, headers = alice
    item = _create(client, headers)
    r = client.get(f"/media/{item['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Heat"


def test_get_missing_item_not_found(client, alice):
    _, headers = alice
    assert client.get("/media/9999", headers=headers).status_code == 404


def test_get_other_users_item_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    item = _create(client, alice_headers)
    assert client.get(f"/media/{item['id']}", headers=bob_headers).status_code == 404


def test_patch_updates_fields(client, alice):
    _, headers = alice
    item = _create(client, headers)
    r = client.patch(
        f"/media/{item['id']}",
        json={"rating": 8, "status": "completed", "is_favorite": True},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["rating"], body["status"], body["is_favorite"]) == (8, "completed", True)


def test_patch_other_users_item_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    item = _create(client, alice_headers)
    r = client.patch(f"/media/{item['id']}", json={"rating": 1}, headers=bob_headers)
    assert r.status_code == 404


# ---------- delete ----------


def test_delete_removes_item_and_history(client, alice):
    user, headers = alice
    item = _create(client, headers, media_type="tv_show", title="Dark")
    client.put(f"/media/{item['id']}/episodes/1/1", json={"watched": True}, headers=headers)
    client.post(f"/media/{item['id']}/rewatch", json={"season": 1, "episode": 1}, headers=headers)
    db = SessionLocal()
    try:
        db.add(
            Notification(
                user_id=user["id"],
                media_item_id=item["id"],
                title="New episode: Dark",
                body="S01E02",
            )
        )
        db.commit()
    finally:
        db.close()

    assert client.delete(f"/media/{item['id']}", headers=headers).status_code == 204
    assert client.get(f"/media/{item['id']}", headers=headers).status_code == 404

    db = SessionLocal()
    try:
        assert db.query(EpisodeWatch).count() == 0
        assert db.query(WatchEvent).count() == 0
        assert db.query(Notification).count() == 0
    finally:
        db.close()


def test_delete_other_users_item_not_found(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    item = _create(client, alice_headers)
    assert client.delete(f"/media/{item['id']}", headers=bob_headers).status_code == 404
    assert client.get(f"/media/{item['id']}", headers=alice_headers).status_code == 200


# ---------- community ratings ----------


def test_ratings_average_across_users(client, alice, bob):
    _, alice_headers = alice
    _, bob_headers = bob
    _create(client, alice_headers, tmdb_id=949, rating=9)
    _create(client, bob_headers, tmdb_id=949, rating=6)
    r = client.get("/media/ratings", params={"media_type": "film", "tmdb_id": 949}, headers=alice_headers)
    assert r.status_code == 200
    assert r.json() == {"average": 7.5, "count": 2}


def test_ratings_by_title_when_no_tmdb_id(client, alice):
    _, headers = alice
    _create(client, headers, rating=8)
    r = client.get("/media/ratings", params={"media_type": "film", "title": "Heat"}, headers=headers)
    assert r.json() == {"average": 8.0, "count": 1}


def test_ratings_requires_tmdb_id_or_title(client, alice):
    _, headers = alice
    r = client.get("/media/ratings", params={"media_type": "film"}, headers=headers)
    assert r.status_code == 422
