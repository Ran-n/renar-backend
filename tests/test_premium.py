#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/10 18:25:42.607537
Revised: 2026/11/09 23:36:42.636280

Premium accounts: badge derivation, style colors, verification requests,
custom posters (upload + GC) and the admin grant/revoke/verify actions.
"""

import base64
import io
from datetime import timedelta

import pytest
from PIL import Image as PILImage

from renar_backend.database import SessionLocal
from renar_backend.models import Image, SiteSettings, Title, User, utcnow
from renar_backend.users.premium import PALETTE

pytestmark = pytest.mark.regression

COLOR = PALETTE[0]
COLOR2 = PALETTE[1]


def _set_premium(user_id: int, days: int = 30) -> None:
    """Directly set premium_until (negative days => lapsed subscription)."""
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _set_verified(user_id: int, value: bool = True) -> None:
    db = SessionLocal()
    try:
        db.get(User, user_id).verified = value
        db.commit()
    finally:
        db.close()


def _png_b64(color: tuple[int, int, int] = (200, 30, 30)) -> str:
    img = PILImage.new("RGB", (20, 30), color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def _image_count() -> int:
    db = SessionLocal()
    try:
        return db.query(Image).count()
    finally:
        db.close()


def _add_film(client, headers, title: str = "Heat", tmdb_id: int = 949) -> dict:
    r = client.post("/media", json={"media_type": "film", "title": title, "tmdb_id": tmdb_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- /auth/me premium fields ----------


def test_me_reports_free_account_defaults(client, alice):
    _, headers = alice
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_premium"] is False
    assert me["premium_until"] is None
    assert me["badge"] is None
    assert me["verified"] is False
    assert me["verification_requested"] is False
    assert me["ring_color"] is None
    assert me["name_color"] is None


def test_badge_premium_when_active(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_premium"] is True
    assert me["badge"] == "premium"


def test_verified_badge_replaces_premium(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    _set_verified(user["id"])
    assert client.get("/auth/me", headers=headers).json()["badge"] == "verified"


def test_badge_gone_when_premium_lapses(client, alice):
    user, headers = alice
    _set_premium(user["id"], days=-1)
    _set_verified(user["id"])
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_premium"] is False
    assert me["badge"] is None


# ---------- palette ----------


def test_palette_requires_auth(client):
    assert client.get("/premium/palette").status_code == 401


def test_palette_lists_hex_colors(client, alice):
    _, headers = alice
    colors = client.get("/premium/palette", headers=headers).json()["colors"]
    assert colors == list(PALETTE)
    assert all(c.startswith("#") and len(c) == 7 for c in colors)


# ---------- style ----------


def test_style_update_requires_premium(client, alice):
    _, headers = alice
    r = client.patch("/premium/style", json={"ring_color": COLOR}, headers=headers)
    assert r.status_code == 403


def test_style_update_roundtrip(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"ring_color": COLOR, "name_color": COLOR2}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["ring_color"] == COLOR
    assert me["name_color"] == COLOR2


def test_style_rejects_malformed_hex(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"ring_color": "not-a-color"}, headers=headers)
    assert r.status_code == 422


def test_style_accepts_hex_outside_the_suggested_palette(client, alice):
    # /premium/palette is a suggested-swatch list, not an enforced allowlist —
    # any well-formed hex is valid, palette or not.
    user, headers = alice
    _set_premium(user["id"])
    assert "#123456" not in PALETTE
    r = client.patch("/premium/style", json={"ring_color": "#123456"}, headers=headers)
    assert r.status_code == 200
    assert client.get("/auth/me", headers=headers).json()["ring_color"] == "#123456"


# ---------- countdown colors ----------


def test_countdown_colors_update_requires_premium(client, alice):
    _, headers = alice
    r = client.patch("/premium/style", json={"countdown_colors": {"urgent": COLOR}}, headers=headers)
    assert r.status_code == 403


def test_countdown_colors_roundtrip(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"countdown_colors": {"urgent": COLOR}}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["countdown_colors"] == {"urgent": COLOR}


def test_countdown_colors_merge_keeps_other_keys(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.patch("/premium/style", json={"countdown_colors": {"urgent": COLOR}}, headers=headers)
    r = client.patch("/premium/style", json={"countdown_colors": {"soon": COLOR2}}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["countdown_colors"] == {"urgent": COLOR, "soon": COLOR2}


def test_countdown_colors_clear_one_key_with_null(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.patch(
        "/premium/style",
        json={"countdown_colors": {"urgent": COLOR, "soon": COLOR2}},
        headers=headers,
    )
    r = client.patch("/premium/style", json={"countdown_colors": {"urgent": None}}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["countdown_colors"] == {"soon": COLOR2}


def test_countdown_colors_rejects_unknown_tier(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"countdown_colors": {"eventually": COLOR}}, headers=headers)
    assert r.status_code == 422


def test_countdown_colors_rejects_malformed_hex(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"countdown_colors": {"urgent": "not-a-color"}}, headers=headers)
    assert r.status_code == 422


def test_style_clear_color_with_null(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.patch("/premium/style", json={"ring_color": COLOR, "name_color": COLOR2}, headers=headers)
    r = client.patch("/premium/style", json={"ring_color": None}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["ring_color"] is None
    assert me["name_color"] == COLOR2  # untouched: only the sent field changed


# ---------- status colors ----------


def test_status_colors_update_requires_premium(client, alice):
    _, headers = alice
    r = client.patch("/premium/style", json={"status_colors": {"watching": COLOR}}, headers=headers)
    assert r.status_code == 403


def test_status_colors_roundtrip(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"status_colors": {"watching": COLOR}}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["status_colors"] == {"watching": COLOR}


def test_status_colors_merge_keeps_other_keys(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.patch("/premium/style", json={"status_colors": {"watching": COLOR}}, headers=headers)
    r = client.patch("/premium/style", json={"status_colors": {"completed": COLOR2}}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["status_colors"] == {"watching": COLOR, "completed": COLOR2}


def test_status_colors_clear_one_key_with_null(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.patch(
        "/premium/style",
        json={"status_colors": {"watching": COLOR, "completed": COLOR2}},
        headers=headers,
    )
    r = client.patch("/premium/style", json={"status_colors": {"watching": None}}, headers=headers)
    assert r.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["status_colors"] == {"completed": COLOR2}


def test_status_colors_rejects_unknown_status(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"status_colors": {"binged": COLOR}}, headers=headers)
    assert r.status_code == 422


def test_status_colors_rejects_malformed_hex(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.patch("/premium/style", json={"status_colors": {"watching": "not-a-color"}}, headers=headers)
    assert r.status_code == 422


# ---------- flair in public payloads ----------


def _premium_alice_with_style(client, alice) -> tuple[dict, dict]:
    user, headers = alice
    _set_premium(user["id"])
    client.patch("/premium/style", json={"ring_color": COLOR, "name_color": COLOR2}, headers=headers)
    return user, headers


def test_comment_carries_flair(client, alice, bob):
    _, a_headers = _premium_alice_with_style(client, alice)
    _, b_headers = bob
    client.post(
        "/comments",
        json={"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "great"},
        headers=a_headers,
    )
    (comment,) = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert comment["badge"] == "premium"
    assert comment["ring_color"] == COLOR
    assert comment["name_color"] == COLOR2


def test_comment_flair_blank_after_lapse(client, alice, bob):
    user, a_headers = _premium_alice_with_style(client, alice)
    _, b_headers = bob
    client.post(
        "/comments",
        json={"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "great"},
        headers=a_headers,
    )
    _set_premium(user["id"], days=-1)
    (comment,) = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert comment["badge"] is None
    assert comment["ring_color"] is None
    assert comment["name_color"] is None


def test_public_profile_includes_flair(client, alice, bob):
    user, _ = _premium_alice_with_style(client, alice)
    _, b_headers = bob
    profile = client.get(f"/users/{user['id']}", headers=b_headers).json()
    assert profile["badge"] == "premium"
    assert profile["ring_color"] == COLOR
    assert profile["name_color"] == COLOR2


def test_feed_includes_flair(client, alice, bob):
    a_user, a_headers = _premium_alice_with_style(client, alice)
    _, b_headers = bob
    client.post(f"/users/{a_user['id']}/follow", headers=b_headers)
    _add_film(client, a_headers)
    (row,) = client.get("/feed", headers=b_headers).json()
    assert row["badge"] == "premium"
    assert row["name_color"] == COLOR2


# ---------- is_reviewer flair, orthogonal to premium/verified ----------


def _whitelist_reviewer(user_id: int) -> None:
    from renar_backend.models import ReviewWhitelist

    db = SessionLocal()
    try:
        db.add(ReviewWhitelist(user_id=user_id))
        db.commit()
    finally:
        db.close()


def test_comment_carries_reviewer_badge(client, alice, bob):
    a_user, a_headers = alice
    _, b_headers = bob
    _whitelist_reviewer(a_user["id"])
    client.post(
        "/comments",
        json={"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "great"},
        headers=a_headers,
    )
    (comment,) = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert comment["is_reviewer"] is True


def test_comment_reviewer_badge_false_for_non_reviewer(client, alice, bob):
    _, a_headers = alice
    _, b_headers = bob
    client.post(
        "/comments",
        json={"media_type": "film", "tmdb_id": 949, "title": "Heat", "text": "great"},
        headers=a_headers,
    )
    (comment,) = client.get("/comments", params={"media_type": "film", "tmdb_id": 949}, headers=b_headers).json()
    assert comment["is_reviewer"] is False


def test_public_profile_includes_reviewer_badge(client, alice, bob):
    user, _ = alice
    _, b_headers = bob
    _whitelist_reviewer(user["id"])
    profile = client.get(f"/users/{user['id']}", headers=b_headers).json()
    assert profile["is_reviewer"] is True


def test_feed_includes_reviewer_badge(client, alice, bob):
    a_user, a_headers = alice
    _, b_headers = bob
    _whitelist_reviewer(a_user["id"])
    client.post(f"/users/{a_user['id']}/follow", headers=b_headers)
    _add_film(client, a_headers)
    (row,) = client.get("/feed", headers=b_headers).json()
    assert row["is_reviewer"] is True


# ---------- verification requests ----------


def test_verification_request_requires_premium(client, alice):
    _, headers = alice
    assert client.post("/premium/verification-request", headers=headers).status_code == 403


def test_verification_request_sets_flag(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    r = client.post("/premium/verification-request", headers=headers)
    assert r.status_code == 200
    assert r.json()["verification_requested"] is True


def test_verification_request_conflict_when_verified(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    _set_verified(user["id"])
    assert client.post("/premium/verification-request", headers=headers).status_code == 409


def test_verification_request_withdraw_works_without_premium(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.post("/premium/verification-request", headers=headers)
    _set_premium(user["id"], days=-1)
    r = client.delete("/premium/verification-request", headers=headers)
    assert r.status_code == 200
    assert r.json()["verification_requested"] is False


# ---------- custom posters ----------


def test_set_poster_requires_premium(client, alice):
    _, headers = alice
    item = _add_film(client, headers)
    r = client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    assert r.status_code == 403


def test_upload_poster_overrides_only_own_entry(client, alice, bob):
    a_user, a_headers = alice
    _, b_headers = bob
    _set_premium(a_user["id"])
    a_item = _add_film(client, a_headers)
    b_item = _add_film(client, b_headers)

    r = client.put(f"/media/{a_item['id']}/poster", json={"image_b64": _png_b64()}, headers=a_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["poster_url"].startswith("/images/")
    assert body["custom_poster_url"] == body["poster_url"]

    # the shared Title row and bob's entry are untouched
    db = SessionLocal()
    try:
        assert db.query(Title).filter(Title.tmdb_id == 949).one().poster_url is None
    finally:
        db.close()
    assert client.get(f"/media/{b_item['id']}", headers=b_headers).json()["poster_url"] is None


def test_poster_from_foreign_url_rejected(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    r = client.put(
        f"/media/{item['id']}/poster",
        json={"tmdb_url": "https://evil.example.com/x.jpg"},
        headers=headers,
    )
    assert r.status_code == 422


def test_poster_requires_exactly_one_source(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    url = "https://image.tmdb.org/t/p/w500/x.jpg"
    assert client.put(f"/media/{item['id']}/poster", json={}, headers=headers).status_code == 422
    r = client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64(), "tmdb_url": url}, headers=headers)
    assert r.status_code == 422


def test_poster_invalid_image_rejected(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    r = client.put(f"/media/{item['id']}/poster", json={"image_b64": "bm90IGFuIGltYWdl"}, headers=headers)
    assert r.status_code == 422


def test_poster_falls_back_when_premium_lapses(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)

    _set_premium(user["id"], days=-1)
    body = client.get(f"/media/{item['id']}", headers=headers).json()
    assert body["poster_url"] is None  # back to the Title poster (none here)
    assert body["custom_poster_url"] is not None  # the stored choice survives


def test_clear_poster_works_without_premium_and_gcs_image(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    assert _image_count() == 1

    _set_premium(user["id"], days=-1)
    r = client.delete(f"/media/{item['id']}/poster", headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_poster_url"] is None
    assert _image_count() == 0


def test_poster_replace_gcs_old_image(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64((200, 30, 30))}, headers=headers)
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64((30, 200, 30))}, headers=headers)
    assert _image_count() == 1


def test_delete_entry_gcs_poster_image(client, alice):
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    assert client.delete(f"/media/{item['id']}", headers=headers).status_code == 204
    assert _image_count() == 0


def test_set_poster_from_tmdb_records_source_url(client, alice, monkeypatch):
    """Picking a TMDB alternate (vs. uploading) should leave a trail back to
    the URL it came from, so the frontend's alternates picker can highlight
    the currently-active tile."""
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    url = "https://image.tmdb.org/t/p/w500/abc.jpg"
    monkeypatch.setattr("renar_backend.routers.media.fetch_poster_bytes", lambda u: base64.b64decode(_png_b64()))

    r = client.put(f"/media/{item['id']}/poster", json={"tmdb_url": url}, headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_poster_source_url"] == url

    # an upload has no source URL to record
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64((30, 30, 200))}, headers=headers)
    assert client.get(f"/media/{item['id']}", headers=headers).json()["custom_poster_source_url"] is None


def test_set_poster_from_tmdb_backfills_source_url_on_dedup_hit(client, alice, monkeypatch):
    """A dedup hit against an existing (upload-created) image row should
    still record the source URL if that row didn't have one yet — otherwise
    re-picking the exact same TMDB alternate a user already has set (a very
    likely first thing to try after this feature shipped, on an image set
    before this column existed) would silently never gain a source_url."""
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    png_bytes = base64.b64decode(_png_b64())

    # upload-created row: no source_url
    client.put(f"/media/{item['id']}/poster", json={"image_b64": _png_b64()}, headers=headers)
    assert client.get(f"/media/{item['id']}", headers=headers).json()["custom_poster_source_url"] is None

    # a TMDB pick that happens to produce byte-identical content dedups onto
    # that same row, and should backfill its source_url
    url = "https://image.tmdb.org/t/p/w500/dedup.jpg"
    monkeypatch.setattr("renar_backend.routers.media.fetch_poster_bytes", lambda u: png_bytes)
    r = client.put(f"/media/{item['id']}/poster", json={"tmdb_url": url}, headers=headers)
    assert r.status_code == 200
    assert r.json()["custom_poster_source_url"] == url
    assert _image_count() == 1  # still deduped onto one row, not a second


def test_shared_image_survives_poster_gc(client, alice):
    """Avatar and poster with identical bytes share one image row; clearing
    the poster must not delete the file the avatar still uses."""
    user, headers = alice
    _set_premium(user["id"])
    item = _add_film(client, headers)
    png = _png_b64()
    client.put(f"/media/{item['id']}/poster", json={"image_b64": png}, headers=headers)
    poster_url = client.get(f"/media/{item['id']}", headers=headers).json()["custom_poster_url"]

    # uploading the same source produces a different JPEG only if processing
    # differs; force sharing by setting the avatar to the poster's exact bytes
    raw = client.get(poster_url).content
    client.patch("/auth/profile", json={"avatar_b64": base64.b64encode(raw).decode()}, headers=headers)
    me = client.get("/auth/me", headers=headers).json()
    assert me["avatar"] == poster_url  # same hash — one shared row

    client.delete(f"/media/{item['id']}/poster", headers=headers)
    assert _image_count() == 1
    assert client.get(me["avatar"]).status_code == 200


def test_tmdb_posters_unconfigured_returns_503(client, alice):
    _, headers = alice
    r = client.get("/tmdb/posters", params={"media_type": "film", "tmdb_id": 949}, headers=headers)
    assert r.status_code == 503  # no TMDB_API_KEY in the test env


# ---------- /images/{hash} endpoint (routers/images.py) ----------


def test_image_invalid_hash_format_returns_404(client):
    """A hash that's not 64 hex chars must return 404 — covers images.py
    HASH_RE.match check (line 27)."""
    assert client.get("/images/not-a-hex-hash").status_code == 404
    assert client.get("/images/abc123").status_code == 404


def test_image_valid_hash_but_missing_file_returns_404(client):
    """A properly-formatted 64-char hex hash for a file that doesn't exist
    returns 404 — covers images.py path.is_file() check (line 30)."""
    missing_hash = "a" * 64
    assert client.get(f"/images/{missing_hash}").status_code == 404


# ---------- admin actions ----------


def test_admin_grant_and_revoke_premium(client, admin_enabled, alice):
    user, headers = alice
    r = client.post(
        f"/admin/users/{user['id']}/premium", data={"days": "30"}, headers=admin_enabled, follow_redirects=False
    )
    assert r.status_code == 303
    assert client.get("/auth/me", headers=headers).json()["is_premium"] is True

    r = client.post(f"/admin/users/{user['id']}/premium/revoke", headers=admin_enabled, follow_redirects=False)
    assert r.status_code == 303
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_premium"] is False
    assert me["premium_until"] is None


def test_admin_grant_premium_extends_active_subscription(client, admin_enabled, alice):
    user, headers = alice
    client.post(
        f"/admin/users/{user['id']}/premium", data={"days": "30"}, headers=admin_enabled, follow_redirects=False
    )
    client.post(
        f"/admin/users/{user['id']}/premium", data={"days": "30"}, headers=admin_enabled, follow_redirects=False
    )
    db = SessionLocal()
    try:
        until = db.get(User, user["id"]).premium_until
    finally:
        db.close()
    assert until > utcnow() + timedelta(days=59)


def test_admin_grant_premium_invalid_days_rejected(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/premium", data={"days": "0"}, headers=admin_enabled)
    assert r.status_code == 422


def test_admin_grant_premium_no_field_rejected(client, admin_enabled, alice):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/premium", data={}, headers=admin_enabled)
    assert r.status_code == 422


def test_admin_grant_premium_large_days_allowed(client, admin_enabled, alice):
    """The old 3650-day cap was an arbitrary sanity limit, not a real constraint."""
    user, headers = alice
    r = client.post(
        f"/admin/users/{user['id']}/premium", data={"days": "999999"}, headers=admin_enabled, follow_redirects=False
    )
    assert r.status_code == 303
    assert client.get("/auth/me", headers=headers).json()["is_premium"] is True


def test_admin_grant_premium_until_date(client, admin_enabled, alice):
    user, headers = alice
    until = (utcnow() + timedelta(days=10)).date().isoformat()
    r = client.post(
        f"/admin/users/{user['id']}/premium", data={"until_date": until}, headers=admin_enabled, follow_redirects=False
    )
    assert r.status_code == 303
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_premium"] is True
    assert me["premium_until"].startswith(until)


def test_admin_grant_premium_until_date_in_past_rejected(client, admin_enabled, alice):
    user, _ = alice
    until = (utcnow() - timedelta(days=1)).date().isoformat()
    r = client.post(f"/admin/users/{user['id']}/premium", data={"until_date": until}, headers=admin_enabled)
    assert r.status_code == 422


def test_admin_grant_premium_forever(client, admin_enabled, alice):
    user, headers = alice
    r = client.post(
        f"/admin/users/{user['id']}/premium", data={"forever": "1"}, headers=admin_enabled, follow_redirects=False
    )
    assert r.status_code == 303
    me = client.get("/auth/me", headers=headers).json()
    assert me["is_premium"] is True
    assert me["premium_until"].startswith("9999")


def test_admin_verify_and_unverify(client, admin_enabled, alice):
    user, headers = alice
    _set_premium(user["id"])
    client.post("/premium/verification-request", headers=headers)

    r = client.post(f"/admin/users/{user['id']}/verify", headers=admin_enabled, follow_redirects=False)
    assert r.status_code == 303
    me = client.get("/auth/me", headers=headers).json()
    assert me["verified"] is True
    assert me["verification_requested"] is False
    assert me["badge"] == "verified"

    client.post(f"/admin/users/{user['id']}/unverify", headers=admin_enabled, follow_redirects=False)
    assert client.get("/auth/me", headers=headers).json()["verified"] is False


def test_admin_premium_actions_missing_user_not_found(client, admin_enabled):
    assert client.post("/admin/users/9999/premium", data={"days": "30"}, headers=admin_enabled).status_code == 404
    assert client.post("/admin/users/9999/verify", headers=admin_enabled).status_code == 404


# ---------- feature-disabled kill-switch paths ----------


def _disable_feature(feature: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(SiteSettings, 1)
        if row is None:
            row = SiteSettings(id=1)
            db.add(row)
        setattr(row, f"premium_{feature}_enabled", False)
        db.commit()
    finally:
        db.close()


def test_style_update_rejected_when_feature_disabled(client, alice, monkeypatch):
    """When the admin has disabled the 'style' feature, PATCH /premium/style
    returns 403 even for premium users — covers routers/premium.py line 43."""
    from renar_backend import site_settings as ss_mod

    user, headers = alice
    _set_premium(user["id"])
    _disable_feature("style")
    ss_mod.invalidate()

    r = client.patch("/premium/style", json={"ring_color": COLOR}, headers=headers)
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_style_update_no_event_when_no_fields_sent(client, alice):
    """An empty PATCH body means model_dump(exclude_unset=True) returns {}, so
    `changes` stays empty throughout and publish_event is NOT called — covers
    routers/premium.py's `if changes:` False branch."""
    import asyncio

    from renar_backend import events

    user, headers = alice
    _set_premium(user["id"])

    queue = events.subscribe(user["id"])
    try:
        r = client.patch("/premium/style", json={}, headers=headers)
        assert r.status_code == 200
        # No event should have been published (changes was empty)
        try:
            queue.get_nowait()
            raise AssertionError("no event should have been published")
        except asyncio.QueueEmpty:
            pass
    finally:
        events.unsubscribe(user["id"], queue)


def test_verification_request_rejected_when_feature_disabled(client, alice):
    """When the admin has disabled the 'verification' feature, POST
    /premium/verification-request returns 403 — covers line 83."""
    from renar_backend import site_settings as ss_mod

    user, headers = alice
    _set_premium(user["id"])
    _disable_feature("verification")
    ss_mod.invalidate()

    r = client.post("/premium/verification-request", headers=headers)
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_premium_style_countdown_colors_null_clears_all(client, alice):
    """PATCH with countdown_colors=null passes validator returning None (line 258)."""
    user, headers = alice
    _set_premium(user["id"])
    client.patch("/premium/style", json={"countdown_colors": {"urgent": COLOR}}, headers=headers)
    r = client.patch("/premium/style", json={"countdown_colors": None}, headers=headers)
    assert r.status_code == 200


def test_premium_style_status_colors_null_clears_all(client, alice):
    """PATCH with status_colors=null passes validator returning None (line 270 in schemas.py)."""
    user, headers = alice
    _set_premium(user["id"])
    client.patch("/premium/style", json={"status_colors": {"watching": COLOR}}, headers=headers)
    r = client.patch("/premium/style", json={"status_colors": None}, headers=headers)
    assert r.status_code == 200
