#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:42:31.539562
Revised: 2026/09/07 15:13:02.152391

Fuzz tests (hypothesis): throw a wide range of malformed/random input at a
few request-parsing endpoints and assert the server never 500s — a 4xx
(rejected, as it should be) or 2xx (accepted) is fine, an unhandled
exception surfacing as a 500 is not. Unlike test_property.py's pure-function
invariants, these go through the real request/response cycle (TestClient),
catching failures that only show up once pydantic validation, the DB layer,
and error handling are all actually wired together — e.g. a value that
passes schema validation but breaks on the way into Postgres (NUL bytes in
a text column raise at the driver level, not the validator).
"""

import base64
import io
from contextlib import contextmanager
from datetime import timedelta

import pytest
from conftest import ADMIN_BASIC
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from renar_backend.database import SessionLocal
from renar_backend.models import ReviewWhitelist, User, utcnow
from renar_backend.routers.admin.users import PREMIUM_FOREVER

pytestmark = pytest.mark.fuzz

# deadline=None: these hit a real Postgres schema through TestClient, and
# per-example timing varies enough (connection setup, first-query warmup)
# that a wall-clock deadline flakes on timing, not correctness.
_fuzz_settings = settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

# BMP text including the codepoints most likely to trip something up at the
# DB layer or in string handling — NUL and other C0 controls — but not lone
# surrogates (0xD800-0xDFFF): those aren't valid standalone Unicode scalar
# values and can't be UTF-8-encoded to send as JSON over HTTP at all, so
# generating them would fuzz httpx's own encoder, not the server.
_fuzzy_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), min_codepoint=0, max_codepoint=0xFFFF),
    min_size=0,
    max_size=200,
)


@_fuzz_settings
@given(username=_fuzzy_text, email=_fuzzy_text, password=_fuzzy_text)
def test_register_never_500s_on_malformed_input(client, username, email, password):
    r = client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert r.status_code < 500, f"500 on username={username!r} email={email!r} password={password!r}:\n{r.text}"


@_fuzz_settings
@given(username=_fuzzy_text, password=_fuzzy_text)
def test_login_never_500s_on_malformed_input(client, username, password):
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code < 500, f"500 on username={username!r} password={password!r}:\n{r.text}"


@_fuzz_settings
@given(
    payload=st.dictionaries(
        st.sampled_from(["media_type", "title", "status", "rating", "notes", "year", "tmdb_id"]),
        # No NaN/Infinity: httpx's own JSON encoder rejects them before a
        # request is even sent (Python's json.dumps is not JSON-compliant
        # for either), so they'd fuzz the test's own transport, not the
        # server.
        st.one_of(
            st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False, allow_infinity=False), _fuzzy_text
        ),
        max_size=7,
    )
)
def test_media_create_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    r = client.post("/media", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text}"


@_fuzz_settings
@given(code=_fuzzy_text)
def test_confirm_email_never_500s_on_malformed_code(client, alice, code):
    _, headers = alice
    r = client.post("/auth/confirm-email-session", json={"code": code}, headers=headers)
    assert r.status_code < 500, f"500 on code={code!r}:\n{r.text}"


# ---------- comments.py (previously no fuzz coverage — see docs/backlog.md) ----------


@_fuzz_settings
@given(
    payload=st.dictionaries(
        st.sampled_from(["media_type", "tmdb_id", "title", "season", "episode", "parent_id", "text"]),
        st.one_of(
            st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False, allow_infinity=False), _fuzzy_text
        ),
        max_size=7,
    )
)
def test_create_comment_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    r = client.post("/comments", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text}"


@_fuzz_settings
@given(comment_id=st.integers(min_value=-(10**9), max_value=10**9))
def test_delete_comment_never_500s_on_arbitrary_comment_id(client, alice, comment_id):
    _, headers = alice
    r = client.delete(f"/comments/{comment_id}", headers=headers)
    assert r.status_code < 500, f"500 on comment_id={comment_id!r}:\n{r.text}"


# ---------- notifications.py (previously no fuzz coverage — see docs/backlog.md) ----------


@_fuzz_settings
@given(notification_id=st.integers(min_value=-(10**9), max_value=10**9))
def test_mark_read_never_500s_on_arbitrary_notification_id(client, alice, notification_id):
    _, headers = alice
    r = client.post(f"/notifications/{notification_id}/read", headers=headers)
    assert r.status_code < 500, f"500 on notification_id={notification_id!r}:\n{r.text}"


@_fuzz_settings
@given(notification_id=st.integers(min_value=-(10**9), max_value=10**9))
def test_delete_notification_never_500s_on_arbitrary_notification_id(client, alice, notification_id):
    _, headers = alice
    r = client.delete(f"/notifications/{notification_id}", headers=headers)
    assert r.status_code < 500, f"500 on notification_id={notification_id!r}:\n{r.text}"


# ---------- helpers for tests below ----------


def _grant_premium(user_id: int) -> None:
    """Grant 30-day premium to the given user directly (bypasses the admin UI)."""
    db = SessionLocal()
    try:
        db.get(User, user_id).premium_until = utcnow() + timedelta(days=30)
        db.commit()
    finally:
        db.close()


def _whitelist_reviewer(user_id: int) -> None:
    """Add user to the reviewer whitelist; no-op if already there."""
    db = SessionLocal()
    try:
        if not db.query(ReviewWhitelist).filter(ReviewWhitelist.user_id == user_id).first():
            db.add(ReviewWhitelist(user_id=user_id))
            db.commit()
    finally:
        db.close()


# ---------- premium.py (previously no fuzz coverage — see docs/backlog.md) ----------

# Fuzz the PATCH /premium/style validator branches:
#   - ring/name/home_season/home_series colors: arbitrary strings (most are
#     not #rrggbb → 422); the rare matching one hits the DB path
#   - countdown_colors dict: fuzz with garbage keys (must be COUNTDOWN_TIERS
#     members) and garbage values (must be #rrggbb or None)
#   - status_colors dict: fuzz with garbage keys (must be WatchStatus members)
# No NaN/Infinity: same reason as the media-create test above.
_fuzz_premium_style_value = st.one_of(
    st.none(),
    _fuzzy_text,
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.dictionaries(_fuzzy_text, st.one_of(st.none(), _fuzzy_text), max_size=4),
)


@_fuzz_settings
@given(
    payload=st.dictionaries(
        st.sampled_from([
            "ring_color",
            "name_color",
            "home_season_color",
            "home_series_color",
            "countdown_colors",
            "status_colors",
        ]),
        _fuzz_premium_style_value,
        max_size=6,
    )
)
def test_premium_style_never_500s_on_arbitrary_json(client, alice, payload):
    user, headers = alice
    _grant_premium(user["id"])
    r = client.patch("/premium/style", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text}"


# ---------- reviews.py (previously no fuzz coverage — see docs/backlog.md) ----------

# POST /media/reviews body is ReviewCreate: text (str, max=10000) and
# rating (int, ge=1, le=100).  The fuzz strategy intentionally covers:
#   - boundary-adjacent rating values (0, 1, 100, 101, huge negatives)
#   - oversized text (>10 000 chars) that must be rejected, not crash
#   - arbitrary wrong-typed values for both fields
# The user must be on the reviewer whitelist or every call returns 403 before
# reaching any validator; _whitelist_reviewer adds the row once per test run.
# media_type and title are supplied as query params so _resolve_target is
# actually reached (otherwise a totally missing target causes an early 422
# from _require_target, never exercising the rating/text validators).
_fuzz_review_payload = st.one_of(
    # boundary-focused: valid text, fuzzed rating around the ge=1/le=100 edges
    st.fixed_dictionaries({
        "text": _fuzzy_text,
        "rating": st.one_of(
            st.just(0),
            st.just(1),
            st.just(100),
            st.just(101),
            st.integers(min_value=-(10**9), max_value=10**9),
        ),
    }),
    # oversized text — schema must reject, not 500; st.just() sidesteps
    # Hypothesis's min_size>BUFFER_SIZE limit for a single representative case
    st.fixed_dictionaries({
        "text": st.just("x" * 10001),
        "rating": st.integers(min_value=1, max_value=100),
    }),
    # fully arbitrary dict: wrong types for both fields, extra keys
    st.dictionaries(
        st.sampled_from(["text", "rating", "garbage_key"]),
        st.one_of(st.none(), st.booleans(), st.integers(), _fuzzy_text),
        max_size=3,
    ),
)


@_fuzz_settings
@given(payload=_fuzz_review_payload)
def test_create_review_never_500s_on_arbitrary_inputs(client, alice, payload):
    user, headers = alice
    _whitelist_reviewer(user["id"])
    r = client.post(
        "/media/reviews",
        json=payload,
        params={"media_type": "film", "title": "Fuzz Movie"},
        headers=headers,
    )
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text}"


# ---------- lists.py (previously no fuzz coverage — see docs/backlog.md) ----------

# ListCreate / ListUpdate share the same schema: name (str, min_length=1,
# max_length=100).  Interesting cases: empty string (fails min_length=1),
# oversized string (fails max_length=100), non-string types, NUL bytes.
_fuzz_list_name = st.one_of(
    _fuzzy_text,
    st.just(""),
    st.just("x" * 101),
    st.just("x" * 1000),
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
)


@_fuzz_settings
@given(name=_fuzz_list_name)
def test_create_list_never_500s_on_arbitrary_name(client, alice, name):
    _, headers = alice
    r = client.post("/lists", json={"name": name}, headers=headers)
    assert r.status_code < 500, f"500 on name={name!r}:\n{r.text}"


@_fuzz_settings
@given(name=_fuzz_list_name)
def test_patch_list_never_500s_on_arbitrary_name(client, alice, name):
    # Create a real list so the PATCH route reaches the name validator rather
    # than returning 404 before any body parsing happens.
    _, headers = alice
    setup = client.post("/lists", json={"name": "Patch Fuzz Target"}, headers=headers)
    assert setup.status_code == 201, f"Setup failed: {setup.text}"
    list_id = setup.json()["id"]
    r = client.patch(f"/lists/{list_id}", json={"name": name}, headers=headers)
    assert r.status_code < 500, f"500 on list_id={list_id} name={name!r}:\n{r.text}"


# POST /lists/{list_id}/items body is ListItemCreate:
#   media_type (MediaType enum), tmdb_id (int|None), title (str|None, max=300).
#   _require_target raises 422 if both tmdb_id and title are absent/falsy —
#   same target-resolution shape as CommentCreate/ReviewCreate.  Strategy
#   mirrors the review test: one arm anchors a valid target (media_type +
#   title) and fuzzes tmdb_id plus wrong extra keys so _require_target is
#   bypassed and the title-resolution/DB path is actually reached.  A second
#   arm sends valid-enum media_type with fuzzed title (including empty/long).
#   A third arm sends fully arbitrary dicts to exercise early-rejection paths.
_fuzz_list_item_body = st.one_of(
    # valid target anchor: fuzz tmdb_id around the media_type+title happy path
    st.fixed_dictionaries({
        "media_type": st.just("film"),
        "title": st.just("Fuzz Item Movie"),
        "tmdb_id": st.one_of(
            st.none(),
            st.integers(min_value=-(10**9), max_value=10**9),
            _fuzzy_text,
        ),
    }),
    # valid target via title alone; also fuzz media_type with non-enum strings
    st.fixed_dictionaries({
        "media_type": st.one_of(st.just("film"), st.just("series"), _fuzzy_text),
        "title": _fuzzy_text,
    }),
    # fully arbitrary dict — missing/wrong target hits _require_target or pydantic early
    st.dictionaries(
        st.sampled_from(["media_type", "tmdb_id", "title"]),
        st.one_of(st.none(), st.booleans(), st.integers(), _fuzzy_text),
        max_size=3,
    ),
)


@_fuzz_settings
@given(payload=_fuzz_list_item_body)
def test_add_list_item_never_500s_on_arbitrary_body(client, alice, payload):
    _, headers = alice
    setup = client.post("/lists", json={"name": "Item Fuzz List"}, headers=headers)
    assert setup.status_code == 201, f"Setup failed: {setup.text}"
    list_id = setup.json()["id"]
    r = client.post(f"/lists/{list_id}/items", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on list_id={list_id} payload={payload!r}:\n{r.text}"


# PUT /lists/{list_id}/items/reorder body is ListItemReorder:
#   item_ids: list[int] = Field(min_length=1, max_length=2000)
# The endpoint validates set(item_ids) == existing item IDs exactly — any
# mismatch yields 422.  Fuzz covers: empty list (fails schema min_length=1),
# duplicate IDs, out-of-range ints, wrong element types, non-list item_ids,
# and a missing item_ids key entirely.
_fuzz_reorder_body = st.one_of(
    # correct field name, list of integers — nearly always mismatches an empty list's set
    st.fixed_dictionaries({
        "item_ids": st.lists(
            st.integers(min_value=-(10**9), max_value=10**9),
            min_size=0,
            max_size=20,
        ),
    }),
    # wrong element types inside item_ids
    st.fixed_dictionaries({
        "item_ids": st.lists(
            st.one_of(st.none(), _fuzzy_text, st.booleans(), st.floats(allow_nan=False, allow_infinity=False)),
            min_size=0,
            max_size=10,
        ),
    }),
    # item_ids not a list at all (scalar)
    st.fixed_dictionaries({
        "item_ids": st.one_of(st.none(), st.integers(), _fuzzy_text, st.booleans()),
    }),
    # arbitrary top-level dict — may omit item_ids key entirely
    st.dictionaries(
        st.sampled_from(["item_ids", "order", "ids"]),
        st.one_of(st.none(), st.integers(), _fuzzy_text),
        max_size=3,
    ),
)


@_fuzz_settings
@given(payload=_fuzz_reorder_body)
def test_reorder_list_items_never_500s_on_arbitrary_body(client, alice, payload):
    _, headers = alice
    setup = client.post("/lists", json={"name": "Reorder Fuzz List"}, headers=headers)
    assert setup.status_code == 201, f"Setup failed: {setup.text}"
    list_id = setup.json()["id"]
    r = client.put(f"/lists/{list_id}/items/reorder", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on list_id={list_id} payload={payload!r}:\n{r.text}"


# ---------- auth.py – PATCH /auth/profile (previously no fuzz coverage) ----------

# ProfileUpdate has six optional plain fields plus two CropBox-typed nested
# models (avatar_crop / background_crop).  The interesting validators are:
#   - language: regex ^[a-z]{2,10}$ — any non-lowercase-alpha or out-of-range
#     string must produce 422, not 500
#   - avatar_crop / background_crop: CropBox floats ge=0/le=1 — out-of-range
#     values and wrong types must be rejected cleanly
# The strategy mixes the plain scalar fields with nested dict payloads for the
# crop fields so both code paths (field validator + nested model parsing) are
# exercised, not just the top-level schema rejection.
_fuzz_crop_value = st.one_of(
    st.none(),
    _fuzzy_text,
    st.integers(),
    st.booleans(),
    st.dictionaries(
        st.sampled_from(["x", "y", "w", "h", "garbage"]),
        st.one_of(
            st.none(),
            _fuzzy_text,
            # wide float range: many values fall outside ge=0/le=1, exercising
            # the bounds validators
            st.floats(allow_nan=False, allow_infinity=False, min_value=-2.0, max_value=3.0),
        ),
        max_size=5,
    ),
)

_fuzz_profile_value = st.one_of(
    st.none(),
    _fuzzy_text,
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    _fuzz_crop_value,
)


@_fuzz_settings
@given(
    payload=st.dictionaries(
        st.sampled_from([
            "username",
            "email",
            "language",
            "avatar_b64",
            "background_b64",
            "avatar_crop",
            "background_crop",
            "theme",
            "show_original_titles",
            "home_hero_enabled",
        ]),
        _fuzz_profile_value,
        max_size=10,
    )
)
def test_update_profile_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    r = client.patch("/auth/profile", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text}"


# ---------- reviews.py – PATCH /media/reviews/{review_id} ----------

# ReviewUpdate is identical in schema to ReviewCreate: text (str, min=1,
# max=10000) and rating (int, ge=1, le=100).  The update path differs from
# create in one key way: there is no target-resolution step, only a 404 check
# (wrong owner → 404, not found → 404), then text.strip() + rating assignment.
# This exercises:
#   - boundary-adjacent rating values (0, 1, 100, 101, large negative)
#   - oversized text that must be rejected, not crash
#   - wrong-typed values for either field (None, bool, str for rating, etc.)
# Setup: create a real review once per hypothesis example, fuzz the PATCH, then
# always delete so the next example finds a clean title slot.  `assume()` guards
# the rare case where the review already exists (e.g. hypothesis found a 500 on
# a prior example and the delete never ran — skip that example rather than
# masking the bug with a fake 201 assertion failure).
# social.py: every endpoint in that module takes only path or query parameters;
# no endpoint has a Pydantic request body.  There is nothing to fuzz there.


# ---------- NUL-byte regression: confirmed crash inputs must yield 422 ----------
# These are deterministic (not hypothesis-driven) regression tests for the
# specific bug found by fuzz testing: any free-text field that reaches Postgres
# with a NUL (0x00) byte crashed with a psycopg DataError (500) because Pydantic
# accepted the byte as a valid 1-character string while Postgres rejects it.
# The fix adds a shared SafeStr annotated type (AfterValidator(_no_nul_bytes))
# applied to every free-text field across schemas.py.  All inputs below must
# now return 422, not 500.


def test_nul_byte_in_list_name_returns_422(client, alice):
    """Original crash site: POST /lists with name='\x00' must be 422, not 500."""
    _, headers = alice
    r = client.post("/lists", json={"name": "\x00"}, headers=headers)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"


def test_nul_byte_in_list_name_via_patch_returns_422(client, alice):
    """PATCH /lists/{id} with a NUL-containing name must also be 422."""
    _, headers = alice
    setup = client.post("/lists", json={"name": "NUL Patch Target"}, headers=headers)
    assert setup.status_code == 201
    list_id = setup.json()["id"]
    r = client.patch(f"/lists/{list_id}", json={"name": "prefix\x00suffix"}, headers=headers)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"


def test_nul_byte_in_comment_text_returns_422(client, alice):
    """POST /comments with NUL in text must be 422 — CommentCreate.text guard."""
    _, headers = alice
    r = client.post(
        "/comments",
        json={"media_type": "film", "title": "NUL Comment Movie", "text": "ok\x00bad"},
        headers=headers,
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"


def test_nul_byte_in_review_text_returns_422(client, alice):
    """POST /media/reviews with NUL in text must be 422 — ReviewCreate.text guard."""
    user, headers = alice
    _whitelist_reviewer(user["id"])
    r = client.post(
        "/media/reviews",
        json={"text": "\x00", "rating": 50},
        params={"media_type": "film", "title": "NUL Review Movie"},
        headers=headers,
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"


def test_nul_byte_in_profile_username_returns_422(client, alice):
    """PATCH /auth/profile with NUL in username must be 422 — ProfileUpdate guard."""
    _, headers = alice
    r = client.patch("/auth/profile", json={"username": "bad\x00name"}, headers=headers)
    assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"


def test_nul_byte_in_media_notes_returns_422(client, alice):
    """POST /media with NUL in notes must be 422 — LibraryEntryCreate.notes guard."""
    _, headers = alice
    r = client.post(
        "/media",
        json={"media_type": "film", "title": "NUL Notes Movie", "notes": "bad\x00note"},
        headers=headers,
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"


_SVC_NUL_SECRET = "nul-svc-regression-secret"


def test_nul_byte_in_ban_reason_returns_422(client):
    """POST /svc/bans with NUL in reason must be 422 — BanRequest.reason SafeStr guard."""
    from renar_backend.config import settings as _settings

    _settings.internal_service_secret = _SVC_NUL_SECRET
    try:
        r = client.post(
            "/svc/bans",
            json={"ip": "1.2.3.4", "reason": "bad\x00reason"},
            headers={"X-Internal-Secret": _SVC_NUL_SECRET},
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"
    finally:
        _settings.internal_service_secret = ""


def test_nul_byte_in_strike_reason_returns_422(client):
    """POST /svc/strikes with NUL in reason must be 422 — StrikeRequest.reason SafeStr guard."""
    from renar_backend.config import settings as _settings

    _settings.internal_service_secret = _SVC_NUL_SECRET
    try:
        r = client.post(
            "/svc/strikes",
            json={"ip": "1.2.3.4", "reason": "flood\x00bad"},
            headers={"X-Internal-Secret": _SVC_NUL_SECRET},
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}:\n{r.text}"
    finally:
        _settings.internal_service_secret = ""


# ---------- imports.py – POST /import (multipart binary upload) ----------


# POST /import takes a multipart file upload, not a JSON body. st.binary()
# generates arbitrary byte content; the detect() step rejects all garbage with
# 422 "Unrecognized export file" long before any importer run() is called. The
# invariant we're probing: detect() never panics on arbitrary bytes — an
# unhandled exception there would surface as a 500 before the router's own
# error handling ever fires. claimed_kind is also fuzzed: a mismatch with the
# detected kind (always None for garbage) short-circuits to 422, so no
# background import thread is ever started during these tests.
@_fuzz_settings
@given(
    content=st.binary(min_size=0, max_size=4096),
    claimed_kind=st.one_of(st.none(), _fuzzy_text, st.just("renar"), st.just("tvtime")),
)
def test_import_upload_never_500s_on_arbitrary_bytes(client, alice, content, claimed_kind):
    _, headers = alice
    form_data = {} if claimed_kind is None else {"claimed_kind": claimed_kind}
    r = client.post(
        "/import",
        files={"file": ("fuzz.bin", content, "application/octet-stream")},
        data=form_data,
        headers=headers,
    )
    assert r.status_code < 500, f"500 on len(content)={len(content)} claimed_kind={claimed_kind!r}:\n{r.text}"


# ---------- svc.py – POST /bans and POST /strikes (service-secret auth) ----------

# These endpoints authenticate via the X-Internal-Secret request header rather
# than a user JWT. The secret is set to a known test value inside each test
# function before each hypothesis example so the header passes _require_internal_secret,
# and restored to "" in the finally block to avoid leaking state into other tests.
#
# BanRequest / StrikeRequest.reason is SafeStr-guarded, so NUL bytes in the
# reason field are rejected at the validator level (422) before they can reach
# the DB layer.  The fuzz tests below confirm this holds across the full range
# of arbitrary string inputs, not just the deterministic regression inputs
# in the NUL-byte section above.
#
# NOTE: permaban() accumulates in-memory bans across hypothesis examples (the
# in-memory _permabanned set is only cleared by the autouse _fresh_db fixture,
# once per test function, not per example). This is intentional: it mirrors
# what a real server would do and doesn't affect the 500-vs-non-500 invariant.
_SVC_FUZZ_SECRET = "fuzz-svc-test-secret-xyz"


@_fuzz_settings
@given(ip=_fuzzy_text, reason=_fuzzy_text)
def test_svc_bans_never_500s_on_arbitrary_body(client, ip, reason):
    from renar_backend.config import settings as _settings

    _settings.internal_service_secret = _SVC_FUZZ_SECRET
    try:
        r = client.post(
            "/svc/bans",
            json={"ip": ip, "reason": reason},
            headers={"X-Internal-Secret": _SVC_FUZZ_SECRET},
        )
        assert r.status_code < 500, f"500 on ip={ip!r} reason={reason!r}:\n{r.text}"
    finally:
        _settings.internal_service_secret = ""


@_fuzz_settings
@given(ip=_fuzzy_text, reason=_fuzzy_text)
def test_svc_strikes_never_500s_on_arbitrary_body(client, ip, reason):
    from renar_backend.config import settings as _settings

    _settings.internal_service_secret = _SVC_FUZZ_SECRET
    try:
        r = client.post(
            "/svc/strikes",
            json={"ip": ip, "reason": reason},
            headers={"X-Internal-Secret": _SVC_FUZZ_SECRET},
        )
        assert r.status_code < 500, f"500 on ip={ip!r} reason={reason!r}:\n{r.text}"
    finally:
        _settings.internal_service_secret = ""


@_fuzz_settings
@given(payload=_fuzz_review_payload)
def test_update_review_never_500s_on_arbitrary_inputs(client, alice, payload):
    user, headers = alice
    _whitelist_reviewer(user["id"])
    # Create a fresh review targeted by the PATCH.  Each example deletes it at
    # the end so the next example can POST again without a 409 conflict.
    setup = client.post(
        "/media/reviews",
        json={"text": "Initial review text for fuzz update.", "rating": 5},
        params={"media_type": "film", "title": "Fuzz Update Movie"},
        headers=headers,
    )
    # If the review from a previous aborted example is still alive (e.g. a
    # prior crash prevented the delete), skip and let hypothesis try another.
    assume(setup.status_code == 201)
    review_id = setup.json()["id"]
    try:
        r = client.patch(f"/media/reviews/{review_id}", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on review_id={review_id} payload={payload!r}:\n{r.text}"
    finally:
        # Always clean up so the title slot is free for the next example,
        # regardless of whether the PATCH succeeded, failed, or asserted.
        client.delete(f"/media/reviews/{review_id}", headers=headers)


# ---------- media.py – PATCH /media/{item_id} (LibraryEntryUpdate) ----------

# LibraryEntryUpdate: status (WatchStatus|None), rating (int|None, ge=1, le=100),
# notes (SafeStr|None), tmdb_id (int|None, ge=1), current_season/current_episode/
# episodes_watched (int|None, ge=0), is_favorite (bool|None).
# Interesting cases:
#   - rating boundary values (0, 1, 100, 101, large negative)
#   - status as arbitrary strings (most are not valid WatchStatus → 422)
#   - wrong types across all fields (None, bool, str for int fields, etc.)
# A real film entry is created first so the handler reaches the body validators
# rather than returning 404 before any parsing happens.  The entry is deleted in
# `finally` so the title slot is free for the next hypothesis example.
_fuzz_library_update_payload = st.one_of(
    # boundary-focused: valid status strings, fuzz rating around ge=1/le=100
    st.fixed_dictionaries({
        "rating": st.one_of(
            st.just(0),
            st.just(1),
            st.just(100),
            st.just(101),
            st.none(),
            st.integers(min_value=-(10**9), max_value=10**9),
        ),
    }),
    # arbitrary status values — non-enum strings must yield 422, not 500
    st.fixed_dictionaries({
        "status": st.one_of(
            st.just("want_to_watch"),
            st.just("watching"),
            st.just("completed"),
            _fuzzy_text,
            st.none(),
            st.integers(),
            st.booleans(),
        ),
    }),
    # fully arbitrary payload mixing multiple fields with wrong types
    st.dictionaries(
        st.sampled_from(["status", "rating", "notes", "is_favorite", "current_season", "current_episode"]),
        st.one_of(
            st.none(), st.booleans(), st.integers(), _fuzzy_text, st.floats(allow_nan=False, allow_infinity=False)
        ),
        max_size=5,
    ),
)


@_fuzz_settings
@given(payload=_fuzz_library_update_payload)
def test_patch_media_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    setup = client.post(
        "/media",
        json={"media_type": "film", "title": "Fuzz Patch Media Film"},
        headers=headers,
    )
    # Skip if a stale entry from a prior aborted example is still alive.
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        r = client.patch(f"/media/{item_id}", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} payload={payload!r}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- media.py – POST /media/ratings/batch (RatingsBatchRequest) ----------

# RatingsBatchRequest: media_type (MediaType enum), tmdb_ids (list[int], min_length=1,
# max_length=100).  No library entry is needed — this is a read-only catalog lookup
# that doesn't touch the caller's own library at all.
# Strategy covers:
#   - valid enum media_type with fuzzed tmdb_ids (empty list, huge list, wrong element types)
#   - non-enum media_type strings → 422
#   - tmdb_ids as scalar, None, or list of non-integers
#   - fully arbitrary dicts (missing required fields)
_fuzz_ratings_batch_payload = st.one_of(
    # valid media_type, fuzz the tmdb_ids list shape and element types
    st.fixed_dictionaries({
        "media_type": st.one_of(st.just("film"), st.just("tv_show")),
        "tmdb_ids": st.one_of(
            st.lists(st.integers(min_value=-(10**9), max_value=10**9), min_size=0, max_size=200),
            st.lists(st.one_of(st.none(), _fuzzy_text, st.booleans()), min_size=0, max_size=10),
            st.just([]),
            st.none(),
            _fuzzy_text,
        ),
    }),
    # non-enum media_type — every value must produce 422, not 500
    st.fixed_dictionaries({
        "media_type": st.one_of(_fuzzy_text, st.none(), st.integers(), st.booleans()),
        "tmdb_ids": st.lists(st.integers(min_value=1, max_value=10**6), min_size=1, max_size=10),
    }),
    # fully arbitrary dict — may omit required fields entirely
    st.dictionaries(
        st.sampled_from(["media_type", "tmdb_ids"]),
        st.one_of(st.none(), st.booleans(), st.integers(), _fuzzy_text),
        max_size=2,
    ),
)


@_fuzz_settings
@given(payload=_fuzz_ratings_batch_payload)
def test_ratings_batch_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    r = client.post("/media/ratings/batch", json=payload, headers=headers)
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text}"


# ---------- media.py – POST/DELETE /media/{item_id}/rewatch (RewatchCreate) ----------

# RewatchCreate: season (int|None, ge=0), episode (int|None, ge=0).
# Both fields must be present together or both absent — a single-field payload
# is 422.  Negative values fail ge=0 → 422.  Wrong types fail Pydantic → 422.
# A completed film entry is created per example so the whole-title (season=None)
# rewatch path is reachable; episode-scoped rewatches need an EpisodeWatch row
# too, so those payload variants are expected to hit a 422 business-rule guard
# ("mark this episode watched before rewatching it") — still < 500.
_fuzz_rewatch_body = st.one_of(
    # whole-title scope — valid for a completed entry (season=None/episode=None)
    st.just({}),
    st.just({"season": None, "episode": None}),
    # out-of-range season/episode (negative values violate ge=0 → 422)
    st.fixed_dictionaries({
        "season": st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-(10**6), max_value=10**6)),
        "episode": st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-(10**6), max_value=10**6)),
    }),
    # wrong types for both fields
    st.fixed_dictionaries({
        "season": st.one_of(st.none(), _fuzzy_text, st.booleans(), st.floats(allow_nan=False, allow_infinity=False)),
        "episode": st.one_of(st.none(), _fuzzy_text, st.booleans(), st.floats(allow_nan=False, allow_infinity=False)),
    }),
    # only one field present — must be 422 (both or neither rule)
    st.fixed_dictionaries({"season": st.integers(min_value=0, max_value=100)}),
    st.fixed_dictionaries({"episode": st.integers(min_value=0, max_value=100)}),
)


@_fuzz_settings
@given(payload=_fuzz_rewatch_body)
def test_post_rewatch_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    # Completed film so whole-title (season=None) rewatch passes the status guard.
    setup = client.post(
        "/media",
        json={"media_type": "film", "title": "Fuzz Post Rewatch Film", "status": "completed"},
        headers=headers,
    )
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        r = client.post(f"/media/{item_id}/rewatch", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} payload={payload!r}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


@_fuzz_settings
@given(payload=_fuzz_rewatch_body)
def test_delete_rewatch_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    setup = client.post(
        "/media",
        json={"media_type": "film", "title": "Fuzz Delete Rewatch Film", "status": "completed"},
        headers=headers,
    )
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        # Starlette TestClient.delete() does not accept a `json=` kwarg —
        # DELETE with a request body requires client.request() instead.
        r = client.request("DELETE", f"/media/{item_id}/rewatch", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} payload={payload!r}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- media.py – PATCH /media/{item_id}/rewatch-events/{event_id} ----------

# WatchEventRatingUpdate: rating (int|None, ge=1, le=100).
# A real WatchEvent is needed — a completed film entry is created in setup so
# create_media automatically adds an initial WatchEvent (is_initial=True) for the
# film-scope (season=None, episode=None); the ID is retrieved via GET
# /rewatch-events.  An arbitrary event_id would return 404 < 500, but wouldn't
# exercise the rating validator at all.
_fuzz_watch_event_rating = st.one_of(
    # boundary values around ge=1/le=100
    st.just({"rating": 0}),
    st.just({"rating": 1}),
    st.just({"rating": 100}),
    st.just({"rating": 101}),
    st.just({"rating": None}),
    st.fixed_dictionaries({
        "rating": st.one_of(st.none(), st.integers(min_value=-(10**9), max_value=10**9)),
    }),
    # wrong types for rating
    st.fixed_dictionaries({
        "rating": st.one_of(_fuzzy_text, st.booleans(), st.floats(allow_nan=False, allow_infinity=False)),
    }),
    # empty body — rating field omitted entirely (defaults to None → valid → 200)
    st.just({}),
)


@_fuzz_settings
@given(payload=_fuzz_watch_event_rating)
def test_patch_rewatch_event_rating_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    # status=completed → create_media creates an initial WatchEvent for this film.
    setup = client.post(
        "/media",
        json={"media_type": "film", "title": "Fuzz Rewatch Event Film", "status": "completed"},
        headers=headers,
    )
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        events_r = client.get(f"/media/{item_id}/rewatch-events", headers=headers)
        assume(events_r.status_code == 200 and events_r.json())
        event_id = events_r.json()[0]["id"]
        r = client.patch(f"/media/{item_id}/rewatch-events/{event_id}", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} event_id={event_id} payload={payload!r}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- media.py – PUT /media/{item_id}/episodes/{season}/{episode} (EpisodeSet) ----------

# EpisodeSet: watched (bool, default True), rating (int|None, ge=1, le=100).
# season and episode are plain integer path parameters (no ge= constraint in the
# router), so arbitrary int values (including negative) reach the handler.
# The handler looks up or creates an EpisodeWatch row; a missing catalog entry is
# treated as allowed (see _assert_not_future_episode — None air_date → permitted).
# Strategy covers:
#   - boundary rating values (0, 1, 100, 101)
#   - wrong types for watched and rating fields
#   - arbitrary path-level season/episode values (including negative)
_fuzz_episode_set_body = st.one_of(
    # valid watched flag, boundary rating values
    st.fixed_dictionaries({
        "watched": st.booleans(),
        "rating": st.one_of(
            st.just(0),
            st.just(1),
            st.just(100),
            st.just(101),
            st.none(),
            st.integers(min_value=-(10**9), max_value=10**9),
        ),
    }),
    # wrong types for watched / rating
    st.fixed_dictionaries({
        "watched": st.one_of(st.none(), st.integers(), _fuzzy_text),
        "rating": st.one_of(st.none(), st.integers(min_value=1, max_value=100)),
    }),
    # arbitrary dict — may omit or duplicate keys
    st.dictionaries(
        st.sampled_from(["watched", "rating"]),
        st.one_of(st.none(), st.booleans(), st.integers(), _fuzzy_text),
        max_size=2,
    ),
)


@_fuzz_settings
@given(
    season=st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-5, max_value=50)),
    episode=st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-5, max_value=100)),
    payload=_fuzz_episode_set_body,
)
def test_set_episode_never_500s_on_arbitrary_inputs(client, alice, season, episode, payload):
    _, headers = alice
    setup = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Fuzz Episode Set Show"},
        headers=headers,
    )
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        r = client.put(f"/media/{item_id}/episodes/{season}/{episode}", json=payload, headers=headers)
        assert r.status_code < 500, (
            f"500 on item_id={item_id} season={season} episode={episode} payload={payload!r}:\n{r.text}"
        )
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- media.py – POST /media/{item_id}/episodes/bulk (EpisodeBulk) ----------

# EpisodeBulk: season (int, ge=0), episodes (list[int], min_length=1, max_length=500),
# watched (bool, default True).
# Strategy covers:
#   - negative season (fails ge=0 → 422)
#   - episodes list exceeding max_length=500 (→ 422)
#   - negative episode numbers in the list (no ge constraint on list elements in
#     the schema — these reach the DB layer, so we probe whether that crashes)
#   - wrong types for season, episodes, and watched
#   - fully arbitrary dicts missing the required season/episodes fields
_fuzz_episode_bulk_body = st.one_of(
    # in-schema shape — fuzz season boundary (ge=0) and episode list size/values
    st.fixed_dictionaries({
        "season": st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-10, max_value=50)),
        "episodes": st.lists(
            st.integers(min_value=-5, max_value=200),
            min_size=0,
            max_size=600,  # exceeds schema max_length=500 to probe that bound too
        ),
        "watched": st.booleans(),
    }),
    # wrong types for season, episodes, and watched
    st.fixed_dictionaries({
        "season": st.one_of(st.none(), _fuzzy_text, st.booleans()),
        "episodes": st.one_of(
            st.lists(st.one_of(st.none(), _fuzzy_text), min_size=1, max_size=5),
            st.none(),
            _fuzzy_text,
        ),
        "watched": st.one_of(st.none(), _fuzzy_text, st.integers()),
    }),
    # arbitrary dict — may omit required fields (season, episodes)
    st.dictionaries(
        st.sampled_from(["season", "episodes", "watched"]),
        st.one_of(st.none(), st.booleans(), st.integers(), _fuzzy_text),
        max_size=3,
    ),
)


@_fuzz_settings
@given(payload=_fuzz_episode_bulk_body)
def test_bulk_episodes_never_500s_on_arbitrary_json(client, alice, payload):
    _, headers = alice
    setup = client.post(
        "/media",
        json={"media_type": "tv_show", "title": "Fuzz Episode Bulk Show"},
        headers=headers,
    )
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        r = client.post(f"/media/{item_id}/episodes/bulk", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} payload={payload!r}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- regression tests for bugs the fuzz tests above found ----------


def test_patch_media_status_null_returns_422_not_500(client, alice):
    """Was: PATCH .../{id} {"status": null} -> setattr(item, "status", None)
    -> unhandled NotNullViolation (500). Now: the field validator on
    LibraryEntryUpdate.status rejects an explicit null before it ever
    reaches the DB."""
    _, headers = alice
    setup = client.post("/media", json={"media_type": "film", "title": "Status Null Regression"}, headers=headers)
    item_id = setup.json()["id"]
    try:
        r = client.patch(f"/media/{item_id}", json={"status": None}, headers=headers)
        assert r.status_code == 422, r.text
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


def test_patch_media_is_favorite_null_returns_422_not_500(client, alice):
    """Same bug class as the status one above, found by the full-suite run
    of the fuzz tests (not the isolated targeted run — hypothesis picked a
    different failing example that time): {"is_favorite": null} ->
    setattr(item, "is_favorite", None) -> unhandled NotNullViolation (500).
    `episodes_watched` shares the same NOT NULL-but-Optional shape and gets
    the same validator, though no fuzz run has hit it directly yet."""
    _, headers = alice
    setup = client.post("/media", json={"media_type": "film", "title": "Favorite Null Regression"}, headers=headers)
    item_id = setup.json()["id"]
    try:
        r = client.patch(f"/media/{item_id}", json={"is_favorite": None}, headers=headers)
        assert r.status_code == 422, r.text
        r = client.patch(f"/media/{item_id}", json={"episodes_watched": None}, headers=headers)
        assert r.status_code == 422, r.text
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


def test_rewatch_season_episode_integer_overflow_returns_422_not_500(client, alice):
    """Was: POST/DELETE .../rewatch {"season": false, "episode": 2147483648.0}
    coerced to (0, 2**31) by Pydantic, which fits `ge=0` but overflows
    Postgres INTEGER -> unhandled NumericValueOutOfRange (500). Now:
    RewatchCreate.season/episode carry le=PG_INT32_MAX."""
    _, headers = alice
    setup = client.post(
        "/media",
        json={"media_type": "film", "title": "Rewatch Overflow Regression", "status": "completed"},
        headers=headers,
    )
    item_id = setup.json()["id"]
    try:
        payload = {"season": False, "episode": 2147483648.0}
        r = client.post(f"/media/{item_id}/rewatch", json=payload, headers=headers)
        assert r.status_code == 422, r.text
        # Starlette TestClient.delete() does not accept a `json=` kwarg —
        # DELETE with a request body requires client.request() instead.
        r = client.request("DELETE", f"/media/{item_id}/rewatch", json=payload, headers=headers)
        assert r.status_code == 422, r.text
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


def test_bulk_episodes_duplicate_entries_deduped_not_500(client, alice):
    """Was: POST .../episodes/bulk {"season": 0, "episodes": [0, 0], "watched": true}
    -> `existing` is snapshotted once before the loop, so both iterations of
    episode 0 attempted an INSERT -> unhandled UniqueViolation (500). Now:
    bulk_episodes dedupes the incoming list before doing anything else."""
    _, headers = alice
    setup = client.post("/media", json={"media_type": "tv_show", "title": "Bulk Dup Regression"}, headers=headers)
    item_id = setup.json()["id"]
    try:
        r = client.post(
            f"/media/{item_id}/episodes/bulk",
            json={"season": 0, "episodes": [0, 0], "watched": True},
            headers=headers,
        )
        assert r.status_code == 200, r.text
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- media.py – CustomPosterSet endpoints (poster / backdrop / still) ----------

# PUT /media/{item_id}/poster, PUT /media/{item_id}/backdrop and
# PUT /media/{item_id}/episodes/{s}/{e}/still all take the same CustomPosterSet
# body: image_b64 XOR tmdb_url, enforced by a model validator. Their fuzz space
# is binary image *content*, not field types — arbitrary bytes travelling
# through decode_b64_image() → normalize_jpeg() (media/image_utils.py) → PIL,
# where a malformed/truncated/oversized payload must come back as a clean 422,
# never a 500 and never a half-written image row.
#
# The strategy therefore mixes:
#   - st.binary() re-encoded as valid base64 (well-formed envelope, garbage
#     payload — the shape a corrupt upload actually has)
#   - st.binary() shoved in raw as a latin-1 string (not valid base64 at all,
#     so decode_b64_image's own error path is exercised too)
#   - a real, tiny PNG so the success path runs among the failures and the
#     image store/GC path is genuinely exercised, not just the reject path
#   - fuzzed tmdb_url strings, with and without the required TMDB prefix
#   - fully arbitrary dicts (both sources, neither, wrong types)
#
# fetch_poster_bytes is stubbed for the duration of each example: the tmdb_url
# arm would otherwise make a real network call to image.tmdb.org for every
# prefix-valid string hypothesis generates. Stubbing it with valid image bytes
# is also what makes the tmdb_url arm *useful* — the fuzzed URL then reaches
# the DB as the image row's source_url instead of dying on a connection error.


def _png_bytes(size: tuple[int, int] = (4, 4)) -> bytes:
    """A real, minimal PNG — the success-path payload for the fuzz below."""
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", size, (7, 8, 9)).save(buf, format="PNG")
    return buf.getvalue()


_VALID_PNG_B64 = base64.b64encode(_png_bytes()).decode()

_fuzz_poster_body = st.one_of(
    # well-formed base64 envelope, arbitrary (almost never valid image) payload
    st.binary(min_size=0, max_size=4096).map(lambda b: {"image_b64": base64.b64encode(b).decode()}),
    # raw bytes as a string: usually not valid base64 either
    st.binary(min_size=0, max_size=512).map(lambda b: {"image_b64": b.decode("latin-1")}),
    # the one payload that must actually succeed
    st.just({"image_b64": _VALID_PNG_B64}),
    # fuzzed tmdb_url — bare, and with the required prefix prepended
    st.fixed_dictionaries({
        "tmdb_url": st.one_of(
            _fuzzy_text,
            _fuzzy_text.map(lambda s: f"https://image.tmdb.org/t/p/original/{s}.jpg"),
        )
    }),
    # arbitrary dict: both sources at once, neither, or wrong types
    st.dictionaries(
        st.sampled_from(["image_b64", "tmdb_url"]),
        st.one_of(st.none(), st.booleans(), st.integers(), _fuzzy_text),
        max_size=2,
    ),
)


@contextmanager
def _stubbed_tmdb_fetch():
    """Replace routers/media.py's fetch_poster_bytes with a stub returning a
    real PNG, so no fuzz example reaches the network."""
    from renar_backend.routers import media as media_router

    original = media_router.fetch_poster_bytes
    media_router.fetch_poster_bytes = lambda url: _png_bytes()
    try:
        yield
    finally:
        media_router.fetch_poster_bytes = original


@_fuzz_settings
@given(payload=_fuzz_poster_body)
def test_set_custom_poster_never_500s_on_arbitrary_image_content(client, alice, payload):
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "film", "title": "Fuzz Poster Film"}, headers=headers)
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        with _stubbed_tmdb_fetch():
            r = client.put(f"/media/{item_id}/poster", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} payload keys={sorted(payload)}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


@_fuzz_settings
@given(payload=_fuzz_poster_body)
def test_set_custom_backdrop_never_500s_on_arbitrary_image_content(client, alice, payload):
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "film", "title": "Fuzz Backdrop Film"}, headers=headers)
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        with _stubbed_tmdb_fetch():
            r = client.put(f"/media/{item_id}/backdrop", json=payload, headers=headers)
        assert r.status_code < 500, f"500 on item_id={item_id} payload keys={sorted(payload)}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


@_fuzz_settings
@given(
    payload=_fuzz_poster_body,
    season=st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-5, max_value=50)),
    episode=st.one_of(st.just(0), st.just(1), st.just(-1), st.integers(min_value=-5, max_value=100)),
)
def test_set_custom_episode_still_never_500s_on_arbitrary_image_content(client, alice, payload, season, episode):
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "tv_show", "title": "Fuzz Still Show"}, headers=headers)
    assume(setup.status_code == 201)
    item_id = setup.json()["id"]
    try:
        with _stubbed_tmdb_fetch():
            r = client.put(f"/media/{item_id}/episodes/{season}/{episode}/still", json=payload, headers=headers)
        assert r.status_code < 500, (
            f"500 on item_id={item_id} s={season} e={episode} payload keys={sorted(payload)}:\n{r.text}"
        )
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- regression tests for bugs the CustomPosterSet fuzz pass found ----------


def test_empty_image_b64_returns_422_not_500(client, alice):
    """Was: {"image_b64": ""} passed CustomPosterSet's exactly-one-source
    validator (which tests `is None`, and "" is not None) but was falsy at
    _resolve_raw_image's `if data.image_b64` branch, so it fell through to
    the TMDB path and called fetch_poster_bytes(None) -> unhandled httpx
    TypeError (500). Now: min_length=1 on both source fields keeps the
    validator's notion of "a source was given" and the branch's truthiness
    test in agreement."""
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "film", "title": "Empty B64 Regression"}, headers=headers)
    item_id = setup.json()["id"]
    try:
        for path in ("poster", "backdrop"):
            r = client.put(f"/media/{item_id}/{path}", json={"image_b64": ""}, headers=headers)
            assert r.status_code == 422, f"{path}: expected 422, got {r.status_code}:\n{r.text}"
        r = client.put(f"/media/{item_id}/episodes/1/1/still", json={"image_b64": ""}, headers=headers)
        assert r.status_code == 422, r.text
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


def test_control_character_in_tmdb_url_returns_422_not_500(client, alice):
    """Was: a tmdb_url carrying a non-printable ASCII character but still
    starting with the required https://image.tmdb.org/t/p/ prefix passed the
    schema, then made httpx raise InvalidURL — which does NOT subclass
    httpx.HTTPError, so fetch_poster_bytes' except clause missed it and it
    escaped as an unhandled 500. Now: CustomPosterSet rejects control
    characters up front (and fetch_poster_bytes catches InvalidURL as a
    second line of defence for any other caller)."""
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "film", "title": "Control Char URL Regression"}, headers=headers)
    item_id = setup.json()["id"]
    try:
        for bad in ("https://image.tmdb.org/t/p/a\x00b.jpg", "https://image.tmdb.org/t/p/a\nb.jpg"):
            r = client.put(f"/media/{item_id}/poster", json={"tmdb_url": bad}, headers=headers)
            assert r.status_code == 422, f"expected 422 for {bad!r}, got {r.status_code}:\n{r.text}"
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


def test_delete_entry_with_custom_episode_still_succeeds(client, alice):
    """Was: DELETE /media/{item_id} died with an unhandled ForeignKeyViolation
    (500) whenever the entry had a custom episode still — episode_custom_stills
    had no ORM relationship on LibraryEntry and no DB-level ON DELETE CASCADE,
    so nothing ever removed those rows on a single-entry delete (only
    users/accounts.py's whole-account purge handled them). Found because the
    still fuzz test above could not clean up between hypothesis examples. Now:
    LibraryEntry.episode_custom_stills cascades, and delete_media GCs the
    stills' image rows the same way it already did for poster/backdrop."""
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "tv_show", "title": "Still Delete Regression"}, headers=headers)
    item_id = setup.json()["id"]
    put = client.put(f"/media/{item_id}/episodes/1/1/still", json={"image_b64": _VALID_PNG_B64}, headers=headers)
    assert put.status_code == 200, put.text
    r = client.delete(f"/media/{item_id}", headers=headers)
    assert r.status_code == 204, r.text
    assert client.get(f"/media/{item_id}", headers=headers).status_code == 404


def test_valid_png_upload_still_succeeds(client, alice):
    """Guard for the two regression fixes above: tightening CustomPosterSet
    must not have broken the ordinary upload path."""
    user, headers = alice
    _grant_premium(user["id"])
    setup = client.post("/media", json={"media_type": "film", "title": "Valid Poster Upload"}, headers=headers)
    item_id = setup.json()["id"]
    try:
        r = client.put(f"/media/{item_id}/poster", json={"image_b64": _VALID_PNG_B64}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["custom_poster_url"], r.text
    finally:
        client.delete(f"/media/{item_id}", headers=headers)


# ---------- routers/admin/* (previously not audited for fuzz — see docs/backlog.md) ----------

# The 8 admin sub-routers render server-side HTML behind HTTP Basic, so they
# were skipped by the 2026-09-03 pass. Their input surface is real, though, and
# structurally *more* exposed than the JSON API's: every value arrives as a
# `Form(...)` or `Query(...)` parameter, which means no Pydantic model — and
# therefore none of the `SafeStr` / `PG_INT32_MAX` guards that pass added to
# the request schemas. What follows fuzzes the endpoints that actually take
# caller-controlled data.
#
# Deliberately NOT fuzzed, as low-value rather than missing:
#   - the pure no-body actions (ban/unban, verify/unverify, whitelist-review,
#     revoke-premium, cancel-deletion, reset-login-limit, reset-onboarding,
#     delete-user, invite revoke/restore/reset-uses): their only input is the
#     integer path parameter, covered once by the generic path-parameter test
#     below rather than by N copies of it
#   - the plain GET dashboards with no parameters (/admin, /admin/premium,
#     /admin/periodic-tasks, /admin/bans, /admin/usage): no input surface
#   - the checkbox-style toggles' *boolean* half (`value` is compared to "1",
#     so every other string means "off" and nothing can go wrong) — their
#     `feature`/`task_key` half IS fuzzed, since it selects an attribute name

_ADMIN_SETTINGS_FORM = {
    "registration_open": "1",
    "turnstile_enabled": "1",
    "turnstile_dev_hostnames": "",
    "email_confirmation_enabled": "1",
    "rate_limit_per_minute": "600",
    "flood_ban_per_minute": "2000",
    "auth_rate_limit_per_minute": "30",
    "register_per_hour_per_ip": "20",
    "login_backoff_threshold": "5",
    "login_backoff_account_threshold": "30",
    "login_backoff_minutes": "15",
    "probe_ban_threshold": "12",
    "probe_window_minutes": "10",
    "ban_minutes": "60",
    "strike_ban_threshold": "5",
    "exempt_ips": "",
    "tmdb_db_cache_hours": "24",
    "email_sender_name": "Renar",
    "email_sender_address": "noreply@renar.app",
    "confirmation_code_ttl_minutes": "15",
    "email_confirmation_grace_days": "7",
    "unconfirmed_account_cleanup_days": "14",
    "username_cooldown_days": "30",
    "deletion_grace_days": "30",
}

_ADMIN_SETTINGS_INT_FIELDS = sorted(k for k, v in _ADMIN_SETTINGS_FORM.items() if v.isdigit() and len(v) > 1)
_ADMIN_SETTINGS_TEXT_FIELDS = ["turnstile_dev_hostnames", "exempt_ips", "email_sender_name", "email_sender_address"]

# Straddles Postgres INTEGER's +/-2**31 boundary on purpose: every one of these
# fields is written to an `Integer` column with no bound of its own.
_pg_boundary_int = st.one_of(
    st.integers(min_value=-(2**33), max_value=2**33),
    st.sampled_from([0, -1, 2**31 - 1, 2**31, -(2**31), -(2**31) - 1, 2**62]),
)


@_fuzz_settings
@given(
    int_overrides=st.dictionaries(st.sampled_from(_ADMIN_SETTINGS_INT_FIELDS), _pg_boundary_int, max_size=4),
    text_overrides=st.dictionaries(st.sampled_from(_ADMIN_SETTINGS_TEXT_FIELDS), _fuzzy_text, max_size=4),
)
def test_admin_save_settings_never_500s_on_arbitrary_form(client, admin_enabled, int_overrides, text_overrides):
    payload = {**_ADMIN_SETTINGS_FORM, **{k: str(v) for k, v in int_overrides.items()}, **text_overrides}
    r = client.post("/admin/settings", data=payload, auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code < 500, f"500 on ints={int_overrides!r} text={text_overrides!r}:\n{r.text[:400]}"


@_fuzz_settings
@given(username=st.one_of(st.none(), _fuzzy_text), email=st.one_of(st.none(), _fuzzy_text))
def test_admin_edit_user_never_500s_on_arbitrary_form(client, admin_enabled, alice, username, email):
    user, _ = alice
    data = {k: v for k, v in (("username", username), ("email", email)) if v is not None}
    r = client.post(f"/admin/users/{user['id']}/edit", data=data, auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code < 500, f"500 on username={username!r} email={email!r}:\n{r.text[:400]}"


@_fuzz_settings
@given(new_password=_fuzzy_text)
def test_admin_set_password_never_500s_on_arbitrary_form(client, admin_enabled, alice, new_password):
    user, _ = alice
    r = client.post(
        f"/admin/users/{user['id']}/password",
        data={"new_password": new_password},
        auth=ADMIN_BASIC,
        follow_redirects=False,
    )
    assert r.status_code < 500, f"500 on new_password={new_password!r}:\n{r.text[:400]}"


# `days` is the interesting one: it feeds `base + timedelta(days=days)`, which
# overflows `datetime`'s own range (a plain OverflowError, not the DataError
# family) long before Postgres is ever involved.
@_fuzz_settings
@given(
    payload=st.one_of(
        st.fixed_dictionaries({
            "days": st.one_of(
                st.sampled_from(["0", "1", "-1", "36525", "36526", str(10**12), str(2**63)]),
                st.integers(min_value=-(10**15), max_value=10**15).map(str),
            )
        }),
        st.fixed_dictionaries({"until_date": st.one_of(_fuzzy_text, st.just("9999-12-31"), st.just("1900-01-01"))}),
        st.fixed_dictionaries({"forever": st.one_of(st.just("1"), st.just("0"), _fuzzy_text)}),
        st.just({}),
    )
)
def test_admin_grant_premium_never_500s_on_arbitrary_form(client, admin_enabled, alice, payload):
    user, _ = alice
    r = client.post(f"/admin/users/{user['id']}/premium", data=payload, auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code < 500, f"500 on payload={payload!r}:\n{r.text[:400]}"


@_fuzz_settings
@given(
    max_uses=st.one_of(st.none(), _fuzzy_text, _pg_boundary_int.map(str)),
    expires_at=st.one_of(st.none(), _fuzzy_text, st.just("2030-01-01"), st.just("99999-01-01")),
)
def test_admin_create_invite_never_500s_on_arbitrary_form(client, admin_enabled, max_uses, expires_at):
    data = {k: v for k, v in (("max_uses", max_uses), ("expires_at", expires_at)) if v is not None}
    r = client.post("/admin/invites/create", data=data, auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code < 500, f"500 on max_uses={max_uses!r} expires_at={expires_at!r}:\n{r.text[:400]}"


@_fuzz_settings
@given(method=_fuzzy_text, path=_fuzzy_text)
def test_admin_endpoint_detail_never_500s_on_arbitrary_query(client, admin_enabled, method, path):
    # method/path go straight into a WHERE comparison against text columns —
    # max_length=10/200 caps the size, nothing caps the *content*.
    r = client.get("/admin/usage/endpoint", params={"method": method, "path": path}, auth=ADMIN_BASIC)
    assert r.status_code < 500, f"500 on method={method!r} path={path!r}:\n{r.text[:400]}"


@_fuzz_settings
@given(feature=_fuzzy_text, task_key=_fuzzy_text, value=_fuzzy_text)
def test_admin_toggles_never_500s_on_arbitrary_key(client, admin_enabled, feature, task_key, value):
    # Both handlers use the fuzzed key to pick a SiteSettings attribute name
    # (`premium_{feature}_enabled`) or a task key — an allowlist miss must
    # redirect, never raise (or, worse, setattr an arbitrary attribute).
    r = client.post(
        "/admin/premium/toggle", data={"feature": feature, "value": value}, auth=ADMIN_BASIC, follow_redirects=False
    )
    assert r.status_code < 500, f"500 on feature={feature!r}:\n{r.text[:400]}"
    r = client.post(
        "/admin/periodic-tasks/toggle",
        data={"task_key": task_key, "value": value},
        auth=ADMIN_BASIC,
        follow_redirects=False,
    )
    assert r.status_code < 500, f"500 on task_key={task_key!r}:\n{r.text[:400]}"


@_fuzz_settings
@given(task_key=_fuzzy_text, minutes=_pg_boundary_int)
def test_admin_task_interval_never_500s_on_arbitrary_form(client, admin_enabled, task_key, minutes):
    r = client.post(
        "/admin/periodic-tasks/interval",
        data={"task_key": task_key, "minutes": str(minutes)},
        auth=ADMIN_BASIC,
        follow_redirects=False,
    )
    assert r.status_code < 500, f"500 on task_key={task_key!r} minutes={minutes!r}:\n{r.text[:400]}"


# One test for the whole family of admin routes whose only caller-controlled
# input is an integer path parameter. Any value outside Postgres INTEGER's
# range used to reach the driver as an unhandled DataError (500) — see
# main.py's `_handle_unstorable_value`.
_ADMIN_INT_PARAM_ROUTES = [
    ("get", "/admin/users/{i}"),
    ("get", "/admin/users/{i}/endpoints"),
    ("get", "/admin/users/{i}/library"),
    ("post", "/admin/users/{i}/ban"),
    ("post", "/admin/users/{i}/unban"),
    ("post", "/admin/users/{i}/premium/revoke"),
    ("post", "/admin/users/{i}/whitelist-review"),
    ("post", "/admin/users/{i}/verify"),
    ("post", "/admin/users/{i}/delete"),
    ("post", "/admin/invites/{i}/revoke"),
    ("post", "/admin/invites/{i}/delete"),
    ("post", "/admin/comments/{i}/delete"),
    ("post", "/admin/bans/{i}/delete"),
]


@_fuzz_settings
@given(
    route=st.sampled_from(_ADMIN_INT_PARAM_ROUTES),
    ident=st.one_of(
        st.integers(min_value=-(2**33), max_value=2**33),
        st.sampled_from([0, -1, 2**31 - 1, 2**31, -(2**31) - 1, 2**62]),
    ),
)
def test_admin_int_path_params_never_500(client, admin_enabled, route, ident):
    method, template = route
    r = getattr(client, method)(template.format(i=ident), auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code < 500, f"500 on {method.upper()} {template} ident={ident}:\n{r.text[:400]}"


@_fuzz_settings
@given(
    page=st.one_of(st.integers(min_value=-(2**33), max_value=2**33), st.sampled_from([0, 1, 2**31, 2**62])),
    user_id=st.one_of(st.integers(min_value=-(2**33), max_value=2**33), st.sampled_from([0, 1, 2**31, 2**62])),
    generated=_fuzzy_text,
)
def test_admin_listing_query_params_never_500(client, admin_enabled, page, user_id, generated):
    r = client.get("/admin/users", params={"page": page}, auth=ADMIN_BASIC)
    assert r.status_code < 500, f"500 on page={page}:\n{r.text[:400]}"
    r = client.get("/admin/comments", params={"user_id": user_id}, auth=ADMIN_BASIC)
    assert r.status_code < 500, f"500 on user_id={user_id}:\n{r.text[:400]}"
    r = client.get("/admin/invites", params={"generated": generated}, auth=ADMIN_BASIC)
    assert r.status_code < 500, f"500 on generated={generated!r}:\n{r.text[:400]}"


# ---------- regression tests for bugs the admin fuzz pass found ----------


def test_admin_settings_integer_overflow_returns_422_not_500(client, admin_enabled):
    """Was: every `int = Form(...)` field on POST /admin/settings was written
    straight to an `Integer` column with no upper bound, so 2**31 reached the
    driver as an unhandled NumericValueOutOfRange (500). Same bug class as the
    2026-09-03 RewatchCreate one, on the surface that pass never audited."""
    for field in ("rate_limit_per_minute", "ban_minutes", "deletion_grace_days"):
        payload = {**_ADMIN_SETTINGS_FORM, field: str(2**31)}
        r = client.post("/admin/settings", data=payload, auth=ADMIN_BASIC, follow_redirects=False)
        assert r.status_code == 422, f"{field}: expected 422, got {r.status_code}"


def test_admin_settings_nul_byte_in_text_field_returns_422_not_500(client, admin_enabled):
    """Was: the free-text `Form(...)` fields bypass Pydantic entirely, so none
    of them carried the SafeStr NUL-byte guard the request schemas got in the
    2026-09-03 pass — a NUL reached Postgres and 500'd."""
    for field in ("email_sender_name", "email_sender_address", "turnstile_dev_hostnames", "exempt_ips"):
        payload = {**_ADMIN_SETTINGS_FORM, field: "bad\x00value"}
        r = client.post("/admin/settings", data=payload, auth=ADMIN_BASIC, follow_redirects=False)
        assert r.status_code == 422, f"{field}: expected 422, got {r.status_code}"


def test_admin_edit_user_oversized_or_nul_value_returns_422_not_500(client, admin_enabled, alice):
    """Was: `username` is a String(50) column and `email` a String(255), with
    no length cap or NUL guard on the admin form — both an over-long value
    (StringDataRightTruncation) and a NUL byte crashed with a 500."""
    user, _ = alice
    for data in (
        {"username": "bad\x00name"},
        {"username": "x" * 200},
        {"email": "x" * 290 + "@example.com"},
    ):
        r = client.post(f"/admin/users/{user['id']}/edit", data=data, auth=ADMIN_BASIC, follow_redirects=False)
        assert r.status_code == 422, f"{data!r}: expected 422, got {r.status_code}"


def test_admin_grant_premium_absurd_days_clamps_instead_of_overflowing(client, admin_enabled, alice):
    """Was two separate 500s, both plain datetime OverflowErrors raised before
    any DB write (so main.py's DataError handler can't help): (a) a `days`
    value so large that `timedelta(days=days)` can't even be constructed
    (timedelta.max is ~10**9 days), and (b) granting any number of days on
    top of an already-permanent subscription, where `base` is the 9999-01-01
    PREMIUM_FOREVER sentinel. (b) was found by the grant-premium fuzz test
    happening to send `forever` and then `days` in the same run. Now both
    clamp to permanent. No upper bound on `days` was added — see
    test_premium.py's test_admin_grant_premium_large_days_allowed."""
    user, _ = alice
    for days in (10**12, 2**40):
        r = client.post(
            f"/admin/users/{user['id']}/premium",
            data={"days": str(days)},
            auth=ADMIN_BASIC,
            follow_redirects=False,
        )
        assert r.status_code == 303, f"days={days}: expected 303, got {r.status_code}:\n{r.text[:200]}"
    db = SessionLocal()
    try:
        assert db.get(User, user["id"]).premium_until >= PREMIUM_FOREVER
    finally:
        db.close()
    # topping up an already-permanent grant leaves it permanent, not overflowing
    r = client.post(f"/admin/users/{user['id']}/premium", data={"days": "1"}, auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code == 303, r.text
    db = SessionLocal()
    try:
        assert db.get(User, user["id"]).premium_until >= PREMIUM_FOREVER
    finally:
        db.close()
    # and an ordinary grant on a lapsed account still behaves normally
    db = SessionLocal()
    try:
        db.get(User, user["id"]).premium_until = None
        db.commit()
    finally:
        db.close()
    r = client.post(f"/admin/users/{user['id']}/premium", data={"days": "30"}, auth=ADMIN_BASIC, follow_redirects=False)
    assert r.status_code == 303, r.text


def test_oversized_int_path_param_returns_422_not_500(client, alice):
    """Was: any integer path/query parameter beyond Postgres INTEGER's range
    reached the driver as an unhandled DataError (500) — across the whole
    public API, not just admin. Now translated to a 422 by main.py's
    `_handle_unstorable_value`. Kept alongside the admin cases above because
    the fix is global and these are the routes real users can reach."""
    _, headers = alice
    big = 2**40
    for method, path in (
        ("get", f"/media/{big}"),
        ("delete", f"/media/{big}"),
        ("get", f"/media/{big}/episodes"),
        ("delete", f"/comments/{big}"),
        ("get", f"/lists/{big}"),
        ("post", f"/notifications/{big}/read"),
        ("get", f"/users/{big}"),
    ):
        r = getattr(client, method)(path, headers=headers)
        assert r.status_code == 422, f"{method.upper()} {path}: expected 422, got {r.status_code}:\n{r.text[:200]}"
