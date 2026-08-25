#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/24 12:37:49.981313
Revised: 2026/08/24 12:37:49.981313

Custom lists: create/rename/delete a list, add/remove/reorder items,
ownership, and normalization.
"""

import pytest

pytestmark = pytest.mark.regression


def _create_list(client, headers, name="Favorites") -> dict:
    r = client.post("/lists", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _add_item(client, headers, list_id, **overrides) -> dict:
    payload = {"media_type": "film", "tmdb_id": 949, "title": "Heat"}
    payload.update(overrides)
    r = client.post(f"/lists/{list_id}/items", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_own_lists(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    assert lst["name"] == "Favorites"
    assert lst["item_count"] == 0

    listed = client.get("/lists", headers=headers).json()
    assert [x["id"] for x in listed] == [lst["id"]]


def test_rename_list(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    r = client.patch(f"/lists/{lst['id']}", json={"name": "Rewatch"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Rewatch"


def test_delete_list_removes_items(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    _add_item(client, headers, lst["id"])
    assert client.delete(f"/lists/{lst['id']}", headers=headers).status_code == 204
    assert client.get("/lists", headers=headers).json() == []


def test_add_and_remove_item(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    item = _add_item(client, headers, lst["id"])
    assert item["title"] == "Heat"
    assert item["position"] == 0

    got = client.get(f"/lists/{lst['id']}", headers=headers).json()
    assert got["item_count"] == 1
    assert [i["id"] for i in got["items"]] == [item["id"]]

    assert client.delete(f"/lists/{lst['id']}/items/{item['id']}", headers=headers).status_code == 204
    got = client.get(f"/lists/{lst['id']}", headers=headers).json()
    assert got["item_count"] == 0


def test_adding_same_title_twice_conflicts(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    _add_item(client, headers, lst["id"])
    r = client.post(
        f"/lists/{lst['id']}/items",
        json={"media_type": "film", "tmdb_id": 949, "title": "Heat"},
        headers=headers,
    )
    assert r.status_code == 409


def test_add_item_by_tmdb_id_without_title_needs_known_title(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    r = client.post(
        f"/lists/{lst['id']}/items",
        json={"media_type": "film", "tmdb_id": 949},
        headers=headers,
    )
    assert r.status_code == 422


def test_reorder_items(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    a = _add_item(client, headers, lst["id"], tmdb_id=949, title="Heat")
    b = _add_item(client, headers, lst["id"], tmdb_id=550, title="Fight Club")
    assert [i["id"] for i in client.get(f"/lists/{lst['id']}", headers=headers).json()["items"]] == [
        a["id"],
        b["id"],
    ]

    r = client.put(
        f"/lists/{lst['id']}/items/reorder",
        json={"item_ids": [b["id"], a["id"]]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert [i["id"] for i in r.json()["items"]] == [b["id"], a["id"]]


def test_reorder_rejects_mismatched_item_set(client, alice):
    _, headers = alice
    lst = _create_list(client, headers)
    a = _add_item(client, headers, lst["id"])
    r = client.put(f"/lists/{lst['id']}/items/reorder", json={"item_ids": [a["id"], 999999]}, headers=headers)
    assert r.status_code == 422


def test_other_users_list_is_not_found(client, alice, bob):
    _, a_headers = alice
    _, b_headers = bob
    lst = _create_list(client, a_headers)

    assert client.get(f"/lists/{lst['id']}", headers=b_headers).status_code == 404
    assert client.patch(f"/lists/{lst['id']}", json={"name": "x"}, headers=b_headers).status_code == 404
    assert client.delete(f"/lists/{lst['id']}", headers=b_headers).status_code == 404
    assert (
        client.post(
            f"/lists/{lst['id']}/items",
            json={"media_type": "film", "tmdb_id": 949, "title": "Heat"},
            headers=b_headers,
        ).status_code
        == 404
    )


def test_delete_account_removes_lists(client, alice):
    from conftest import hard_delete

    from renar_backend.database import SessionLocal
    from renar_backend.models import List, ListItem

    user, headers = alice
    lst = _create_list(client, headers)
    _add_item(client, headers, lst["id"])

    hard_delete(user["id"])

    db = SessionLocal()
    try:
        assert db.query(List).count() == 0
        assert db.query(ListItem).count() == 0
    finally:
        db.close()
