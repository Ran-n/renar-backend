#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:24.134855
Revised: 2026/11/09 23:36:45.461331

Settings validation that must fail at boot rather than at first use.

``ADMIN_TOTP_SECRET`` is checked as base32 when the settings load: a typo
would otherwise only show up as a sign-in that never works.
"""

import pytest
from pydantic import ValidationError

from renar_backend.config import Settings


def test_totp_secret_empty_allowed():
    assert Settings(admin_totp_secret="").admin_totp_secret == ""


def test_totp_secret_normalised():
    """Authenticator apps show the secret in spaced, lowercase groups."""
    assert Settings(admin_totp_secret="jbsw y3dp ehpk 3pxp").admin_totp_secret == "JBSWY3DPEHPK3PXP"


def test_totp_secret_unpadded_length_accepted():
    """pyotp secrets aren't always a multiple of 8 characters; padding is implied."""
    assert Settings(admin_totp_secret="JBSWY3DPEHPK3PX").admin_totp_secret == "JBSWY3DPEHPK3PX"


@pytest.mark.parametrize("bad", ["not-base32!", "JBSWY3DPEHPK3PX1", "0000000000000000"])
def test_totp_secret_invalid_base32_rejected(bad):
    with pytest.raises(ValidationError, match="ADMIN_TOTP_SECRET is not valid base32"):
        Settings(admin_totp_secret=bad)
