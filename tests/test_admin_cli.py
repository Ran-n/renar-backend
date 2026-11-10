#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:21:23.920913
Revised: 2026/11/09 23:36:44.820288

The server-side admin commands: ``admin-totp`` (new authenticator secret)
and ``admin-unban`` (lift every ban on an IP), on the real Postgres test
schema.
"""

import logging
import re

import pyotp
import pytest

from renar_backend import admin_cli
from renar_backend.config import Settings
from renar_backend.database import SessionLocal
from renar_backend.models import BannedIP, Strike


def test_totp_prints_secret_uri_qr_and_env_line(capsys):
    assert admin_cli.totp_main([]) == 0
    out = capsys.readouterr().out
    secret = re.search(r"^ADMIN_TOTP_SECRET=([A-Z2-7]+)$", out, re.MULTILINE).group(1)
    assert len(secret) == 32
    assert f"Secret: {secret}" in out
    uri = re.search(r"^URI:\s+(otpauth://\S+)$", out, re.MULTILINE).group(1)
    parsed = pyotp.parse_uri(uri)
    assert parsed.secret == secret
    assert parsed.issuer == "renar"
    assert "█" in out or "▀" in out or "▄" in out  # the terminal QR
    # the printed secret is one the server accepts
    assert Settings(admin_totp_secret=secret).admin_totp_secret == secret


def test_totp_new_secret_each_run(capsys):
    admin_cli.totp_main([])
    admin_cli.totp_main([])
    secrets = re.findall(r"^ADMIN_TOTP_SECRET=(\S+)$", capsys.readouterr().out, re.MULTILINE)
    assert len(set(secrets)) == 2


def test_unban_removes_permaban_and_strike(capsys):
    with SessionLocal() as db:
        db.add(BannedIP(ip="203.0.113.9", reason="admin login failed"))
        db.add(Strike(ip="203.0.113.9", count=3, reason="admin login failed"))
        db.add(Strike(ip="198.51.100.1", count=1, reason="other"))
        db.commit()
    assert admin_cli.unban_main(["203.0.113.9"]) == 0
    out = capsys.readouterr().out
    assert "Lifted 1 permanent ban(s) and 1 strike record(s) for 203.0.113.9" in out
    assert "systemctl restart renar-backend" in out
    with SessionLocal() as db:
        assert db.query(BannedIP).count() == 0
        assert [s.ip for s in db.query(Strike)] == ["198.51.100.1"]  # other IPs untouched


def test_unban_normalises_ipv6(capsys):
    with SessionLocal() as db:
        db.add(Strike(ip="2001:db8::1", count=1, reason="x"))
        db.commit()
    assert admin_cli.unban_main(["2001:0db8:0000::0001"]) == 0
    assert "1 strike record(s) for 2001:db8::1" in capsys.readouterr().out


def test_unban_nothing_recorded(capsys):
    assert admin_cli.unban_main(["192.0.2.5"]) == 0
    assert "192.0.2.5 has no ban or strike recorded." in capsys.readouterr().out


def test_unban_rejects_non_ip(caplog):
    with caplog.at_level(logging.ERROR, logger="renar_backend.admin_cli"):
        assert admin_cli.unban_main(["not-an-ip"]) == 2
    assert "not an IP address" in caplog.text


def test_unban_requires_argument():
    with pytest.raises(SystemExit) as exc:
        admin_cli.unban_main([])
    assert exc.value.code == 2
