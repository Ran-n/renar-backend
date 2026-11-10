#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/08/18 17:16:06.552872
Revised: 2026/11/09 16:20:37.574737

Property-based tests (hypothesis) for pure validation/normalization
functions: instead of a handful of hand-picked examples, these assert an
invariant holds across a wide generated input space — the kind of edge
case (surrogate codepoints, byte-length vs. char-length mismatches under
multi-byte UTF-8, empty/whitespace-only strings) a fixed example list tends
to miss.
"""

import pydantic
import pytest
from hypothesis import given
from hypothesis import strategies as st

from renar_backend.app_releases import version_key
from renar_backend.models import normalize_title_key
from renar_backend.routers.auth import _normalize_email
from renar_backend.schemas import _HEX_COLOR_RE, BCRYPT_MAX_PASSWORD_BYTES, _password_fits_bcrypt

pytestmark = pytest.mark.property


# ---------- _password_fits_bcrypt ----------


@given(st.text(min_size=0, max_size=72))
def test_password_within_byte_cap_is_accepted_unchanged(password: str):
    if len(password.encode()) <= BCRYPT_MAX_PASSWORD_BYTES:
        assert _password_fits_bcrypt(password) == password


@given(st.text(min_size=73, max_size=200))
def test_password_over_byte_cap_is_always_rejected(password: str):
    if len(password.encode()) > BCRYPT_MAX_PASSWORD_BYTES:
        with pytest.raises(ValueError, match="72 bytes"):
            _password_fits_bcrypt(password)


# ---------- hex color validation (PremiumStyleUpdate) ----------


@given(
    st.text(alphabet="0123456789abcdefABCDEF", min_size=6, max_size=6).map(lambda s: f"#{s}"),
)
def test_well_formed_hex_color_matches(color: str):
    assert _HEX_COLOR_RE.match(color)


@given(st.text(min_size=0, max_size=10))
def test_hex_color_regex_never_matches_wrong_length_or_alphabet(text: str):
    is_valid_hex = len(text) == 7 and text[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in text[1:])
    if not is_valid_hex:
        assert _HEX_COLOR_RE.match(text) is None


# ---------- normalize_title_key ----------


@given(st.text(min_size=1, max_size=200))
def test_normalize_title_key_is_idempotent(title: str):
    once = normalize_title_key(title)
    assert normalize_title_key(once) == once


@given(st.text(alphabet=st.characters(whitelist_categories=("Lu", "Ll"), max_codepoint=0x7F), min_size=1, max_size=200))
def test_normalize_title_key_matches_across_case(title: str):
    # ASCII letters only: Unicode case conversion isn't always a clean
    # upper/lower bijection (e.g. Turkish dotless "ı".upper() == "I", but
    # "I".casefold() == "i" != "ı".casefold()) — a real difference in the
    # letters, not a bug in normalize_title_key, so it's out of scope here.
    assert normalize_title_key(title) == normalize_title_key(title.upper()) == normalize_title_key(title.lower())


@given(st.text(min_size=1, max_size=200), st.integers(min_value=0, max_value=5), st.integers(min_value=0, max_value=5))
def test_normalize_title_key_ignores_surrounding_whitespace(title: str, leading: int, trailing: int):
    padded = (" " * leading) + title + (" " * trailing)
    assert normalize_title_key(padded) == normalize_title_key(title)


# ---------- _normalize_email ----------


@given(st.emails())
def test_normalize_email_is_idempotent(email: str):
    once = _normalize_email(email)
    assert _normalize_email(once) == once


@given(st.emails())
def test_normalize_email_is_always_lowercase_and_stripped(email: str):
    normalized = _normalize_email(email)
    assert normalized == normalized.lower()
    assert normalized == normalized.strip()


# ---------- UserCreate length bounds (pydantic Field constraints) ----------


@given(st.text(min_size=3, max_size=50), st.text(min_size=8, max_size=72))
def test_username_and_password_within_bounds_never_raise_on_length(username: str, password: str):
    from renar_backend.schemas import UserCreate

    try:
        UserCreate(username=username, email="a@example.com", password=password)
    except pydantic.ValidationError as exc:
        # Any surviving error must be about content (e.g. EmailStr is fixed
        # here so it can't fire) — not about the length bounds themselves.
        for err in exc.errors():
            assert err["loc"][0] not in ("username", "password") or "length" not in err["type"]


# ---------- app_releases.version_key ----------

_versions = st.tuples(*[st.integers(min_value=0, max_value=999)] * 3).map(lambda t: ".".join(map(str, t)))


@given(st.lists(_versions, min_size=1, max_size=20, unique=True))
def test_latest_version_is_the_integer_tuple_max(versions: list[str]):
    """``latest`` picks by version_key; that must equal the numeric max,
    never the string max (which would rank 0.9.9 above 0.10.0)."""
    expected = max(versions, key=lambda v: tuple(int(p) for p in v.split(".")))
    assert max(versions, key=version_key) == expected
