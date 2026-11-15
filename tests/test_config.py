#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:24.134855
Revised: 2026/11/15 11:56:20.502382

Settings validation that must fail at boot rather than at first use.

``ADMIN_TOTP_SECRET`` is checked as base32 when the settings load: a typo
would otherwise only show up as a sign-in that never works. A leftover
plain ``ADMIN_PASSWORD`` and a ``ADMIN_PASSWORD_HASH`` that isn't Argon2id
stop the boot the same way, without ever printing the value.
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


# ---------- admin password: only its Argon2id hash is accepted ----------

_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHRzb21lc2FsdA$J4moa2MM0/6uf3HbY2Tf5Fux8JIBTwIhmhxGRbsY14E"


def test_no_admin_password_settings_loads():
    loaded = Settings(admin_password="", admin_password_hash="")
    assert (loaded.admin_password, loaded.admin_password_hash) == ("", "")


def test_argon2id_hash_accepted_and_trimmed():
    assert Settings(admin_password_hash=f"  {_HASH}\n").admin_password_hash == _HASH


def test_plain_admin_password_stops_the_boot_without_echoing_it():
    with pytest.raises(ValidationError) as exc:
        Settings(admin_password="correct horse battery")
    message = str(exc.value)
    assert (
        "ADMIN_PASSWORD is no longer read: run `uv run admin-password` and set ADMIN_PASSWORD_HASH instead" in message
    )
    assert "correct horse battery" not in message


@pytest.mark.parametrize(
    "bad", ["hunter2secret", "$2b$12$abcdefghijklmnopqrstuv", "$argon2i$v=19$m=16,t=2,p=1$c2FsdA$aGFzaA"]
)
def test_non_argon2id_hash_rejected_without_echoing_it(bad):
    with pytest.raises(ValidationError) as exc:
        Settings(admin_password_hash=bad)
    assert "ADMIN_PASSWORD_HASH is not an Argon2id hash" in str(exc.value)
    assert bad not in str(exc.value)


def test_plain_admin_password_in_the_environment_stops_the_boot(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "left-over-from-an-old-env")
    with pytest.raises(ValidationError, match="ADMIN_PASSWORD is no longer read"):
        Settings()


def test_hash_from_a_dotenv_file_keeps_its_dollar_signs(tmp_path, monkeypatch):
    """The single quotes `admin-password` prints are what stop python-dotenv
    from treating "$argon2id" as a variable to expand."""
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"ADMIN_PASSWORD_HASH='{_HASH}'\n", encoding="utf-8")
    assert Settings(_env_file=str(env)).admin_password_hash == _HASH
