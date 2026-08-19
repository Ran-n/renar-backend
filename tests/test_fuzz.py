#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:42:31.539562
Revised: 2026/08/18 17:42:31.539562

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

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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
