#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:42:31.539562
Revised: 2026/09/03 14:06:02.113977

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

from datetime import timedelta

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from renar_backend.database import SessionLocal
from renar_backend.models import ReviewWhitelist, User, utcnow

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


# ---------- open gap: CustomPosterSet endpoints ----------
# PUT /media/{item_id}/poster, PUT /media/{item_id}/backdrop, and
# PUT /media/{item_id}/episodes/{s}/{e}/still are intentionally NOT fuzzed here.
# All three share the same CustomPosterSet body, which has an exactly-one-source
# model validator (image_b64 XOR tmdb_url): the interesting fuzz space is
# base64-encoded binary content with malformed/oversized/wrong-encoding payloads,
# plus URL strings pointing at unreachable/non-image resources — a meaningfully
# different shape from the simple-field-type fuzz applied to the endpoints above.
# They also require premium and involve image-decoding code (decode_b64_image,
# normalize_jpeg) that benefits from a focused binary-content fuzz pass rather
# than being squeezed into this general-purpose field-type sweep.
# Tracked as an open coverage gap for a future dedicated pass.
