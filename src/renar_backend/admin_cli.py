#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:23.680452
Revised: 2026/11/15 11:56:17.346820

Admin command-line tools, run on the server host (over SSH on prod).

``uv run admin-totp`` generates a new authenticator secret for the admin
panel's sign-in: it prints the secret, the ``otpauth://`` URI, a QR code for
the terminal and the ``ADMIN_TOTP_SECRET=…`` line to put in ``.env``.
Rotating it signs every admin session out.

``uv run admin-password`` asks for the admin password twice (hidden) and
prints the ``ADMIN_PASSWORD_HASH='…'`` line to put in ``.env``: the server
only ever stores the Argon2id hash. Changing it signs every admin session
out.

``uv run admin-unban <ip>`` lifts every ban on an IP (permanent ban row and
strike/temp-ban row), e.g. after locking yourself out of the panel with
failed sign-ins. Bans are also cached in the running server's memory, so
restart it afterwards (``sudo systemctl restart renar-backend`` on prod).

Output goes through ``sys.stdout.write``: it is the command's result, not a
log line. Errors go through ``logging``.
"""

import argparse
import ipaddress
import logging
import sys

_log = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 12


def totp_main(argv: list[str] | None = None) -> int:
    import pyotp
    import segno

    from .config import settings

    argparse.ArgumentParser(prog="admin-totp", description="Generate an admin authenticator secret.").parse_args(argv)
    # The QR is drawn with block characters; a Windows console or pipe
    # defaults to a legacy code page that can't encode them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    secret = pyotp.random_base32()
    name = settings.admin_username or "admin"
    uri = pyotp.TOTP(secret).provisioning_uri(name=name, issuer_name="renar")
    sys.stdout.write(f"Secret: {secret}\nURI:    {uri}\n\nScan this with your authenticator app:\n\n")
    sys.stdout.write(segno.make(uri).terminal(compact=True) or "")
    sys.stdout.write(
        f"\nThen put this line in .env and restart the server:\n\nADMIN_TOTP_SECRET={secret}\n"
        "\nThis signs out every current admin session.\n"
    )
    return 0


def password_problem(first: str, second: str) -> str | None:
    """Why this pair of entries can't become the admin password, if so."""
    if not first:
        return "the password is empty"
    if len(first) < MIN_PASSWORD_LENGTH:
        return f"the password is shorter than {MIN_PASSWORD_LENGTH} characters"
    if first != second:
        return "the two passwords differ"
    return None


def password_env_line(password: str) -> str:
    """The ``.env`` line for ``password``. Single quotes: python-dotenv
    doesn't interpolate inside them, so the hash's "$" signs survive."""
    from argon2 import PasswordHasher

    return f"ADMIN_PASSWORD_HASH='{PasswordHasher().hash(password)}'"


def password_main(argv: list[str] | None = None) -> int:
    import getpass

    argparse.ArgumentParser(
        prog="admin-password", description="Hash a new admin password for ADMIN_PASSWORD_HASH."
    ).parse_args(argv)
    first = getpass.getpass("New admin password: ")
    second = getpass.getpass("Repeat it: ")
    problem = password_problem(first, second)
    if problem:
        sys.stderr.write(f"admin-password: {problem}\n")
        return 1
    sys.stdout.write(
        f"{password_env_line(first)}\n"
        "\nPut this line in .env and restart the server. This signs out every current admin session.\n"
    )
    return 0


def unban_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admin-unban", description="Lift every ban on an IP address.")
    parser.add_argument("ip")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        ip = str(ipaddress.ip_address(args.ip))
    except ValueError:
        _log.error("not an IP address: %r", args.ip)
        return 2

    from .database import SessionLocal
    from .models import BannedIP, Strike

    with SessionLocal() as db:
        permabans = db.query(BannedIP).filter(BannedIP.ip == ip).delete()
        strikes = db.query(Strike).filter(Strike.ip == ip).delete()
        db.commit()
    if not permabans and not strikes:
        sys.stdout.write(f"{ip} has no ban or strike recorded.\n")
        return 0
    sys.stdout.write(
        f"Lifted {permabans} permanent ban(s) and {strikes} strike record(s) for {ip}.\n"
        "Restart the server so it forgets its in-memory copy of the ban "
        "(prod: sudo systemctl restart renar-backend).\n"
    )
    return 0


def totp() -> None:
    raise SystemExit(totp_main())


def password() -> None:
    raise SystemExit(password_main())


def unban() -> None:
    raise SystemExit(unban_main())
