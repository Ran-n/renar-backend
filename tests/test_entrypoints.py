#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:11.076048
Revised: 2026/11/15 12:39:41.393913

Process entrypoints, with the server itself stubbed: `be` picking up the TLS
certificate and the uvicorn options it passes, the admin console-script
wrappers' exit codes, the app lifespan's dev-secret warning, and the
middleware stack with the abuse guard switched on.
"""

import asyncio
import io
import logging
import sys

import pytest
from fastapi import FastAPI

from renar_backend import __main__ as be
from renar_backend import admin_cli, main, update_check
from renar_backend.config import settings
from renar_backend.users.security import AbuseGuardMiddleware

# ---------------------------------------------------------------------------
# be (renar_backend.__main__)
# ---------------------------------------------------------------------------


def test_run_serves_https_when_the_certificate_exists(tmp_path, monkeypatch):
    cert, key = tmp_path / "fullchain.pem", tmp_path / "privkey.pem"
    cert.write_text("cert", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    monkeypatch.setattr(be, "_SSL_CERTFILE", cert)
    monkeypatch.setattr(be, "_SSL_KEYFILE", key)
    monkeypatch.setattr(be, "ensure_port_free", lambda host, port: None)
    pids = []
    monkeypatch.setattr(update_check, "write_server_pid", lambda port, scheme: pids.append((port, scheme)))
    monkeypatch.setattr(update_check, "remove_server_pid", lambda: pids.append("removed"))
    served = []
    monkeypatch.setattr(be, "_serve", served.append)

    be.run()

    assert served == [{"ssl_certfile": str(cert), "ssl_keyfile": str(key)}]
    assert pids == [(be._PORT, "https"), "removed"]


def test_serve_runs_the_reloading_app_with_a_capped_shutdown(monkeypatch):
    calls = []
    monkeypatch.setattr(be.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))

    be._serve({"ssl_certfile": "c.pem", "ssl_keyfile": "k.pem"})

    (app, kwargs), *rest = calls
    assert rest == []
    assert app == "renar_backend.main:asgi_app"
    assert kwargs["reload"] is True
    assert kwargs["reload_dirs"] == [be._SRC_DIR]
    assert kwargs["server_header"] is False
    assert kwargs["timeout_graceful_shutdown"] == 5
    assert (kwargs["ssl_certfile"], kwargs["ssl_keyfile"]) == ("c.pem", "k.pem")
    assert kwargs["log_config"]["root"]["handlers"] == ["app_console", "file", "errors_file"]


# ---------------------------------------------------------------------------
# admin console scripts
# ---------------------------------------------------------------------------


def test_totp_script_exits_with_the_command_status(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["admin-totp"])

    with pytest.raises(SystemExit) as exc:
        admin_cli.totp()

    assert exc.value.code == 0
    assert "ADMIN_TOTP_SECRET=" in capsys.readouterr().out


def test_totp_writes_to_a_stdout_without_reconfigure(monkeypatch):
    out = io.StringIO()  # no .reconfigure(), like some redirected streams
    monkeypatch.setattr(sys, "stdout", out)

    assert admin_cli.totp_main([]) == 0
    assert "Secret: " in out.getvalue()


def test_unban_script_exits_with_the_command_status(client, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["admin-unban", "not-an-ip"])

    with pytest.raises(SystemExit) as exc:
        admin_cli.unban()

    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# main.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("secret", "warned"),
    [("dev-only-not-a-real-secret", True), ("a-real-production-secret-0123456789", False)],
)
def test_lifespan_warns_only_about_the_dev_secret_key(monkeypatch, caplog, secret, warned):
    monkeypatch.setattr(settings, "secret_key", secret)
    monkeypatch.setattr(main, "exit_when_orphaned", lambda: None)
    monkeypatch.setattr(update_check, "write_worker_marker", lambda: None)
    started = []

    async def _idle():
        await asyncio.sleep(3600)

    def _start():
        task = asyncio.get_running_loop().create_task(_idle())
        started.append(task)
        return [task]

    monkeypatch.setattr(main.notifier, "start_periodic_tasks", _start)

    async def _cycle():
        async with main.lifespan(main.app):
            pass

    with caplog.at_level(logging.WARNING, logger=main.__name__):
        asyncio.run(_cycle())

    assert ("SECRET_KEY is the built-in dev default" in caplog.text) is warned
    assert started and started[0].cancelled()


@pytest.mark.parametrize("abuse_guard", [True, False])
def test_middleware_stack_puts_the_abuse_guard_outside_usage_tracking(abuse_guard):
    target = FastAPI()

    main.install_middleware(target, abuse_guard=abuse_guard)

    names = [m.cls.__name__ for m in target.user_middleware]
    expected = ["CORSMiddleware", "OriginCheckMiddleware", "SecurityHeadersMiddleware"]
    if abuse_guard:
        expected.append(AbuseGuardMiddleware.__name__)
    # the Access gate sits inside the abuse guard, so bans apply first
    expected += ["CloudflareAccessMiddleware", "UsageTrackingMiddleware"]
    assert names == expected
