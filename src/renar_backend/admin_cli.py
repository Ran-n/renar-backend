#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:23.680452
Revised: 2026/11/09 23:36:43.476603

Admin command-line tools, run on the server host (over SSH on prod).

``uv run admin-totp`` generates a new authenticator secret for the admin
panel's sign-in: it prints the secret, the ``otpauth://`` URI, a QR code for
the terminal and the ``ADMIN_TOTP_SECRET=…`` line to put in ``.env``.
Rotating it signs every admin session out.

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


def unban() -> None:
    raise SystemExit(unban_main())
