#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 23:36:18.560391
Revised: 2026/11/11 11:11:07.066719

Admin Server Update: shows the running version and what's newer (the
incoming commits on origin/master for a git checkout, the latest release
and its notes otherwise), and an Update button that installs it, syncs
dependencies, migrates and reloads the server (see update_check.py and
self_update.py), with automatic rollback. The page polls
``/update/status`` while the update runs and reloads when it's done.
"""

import html
import logging
from datetime import UTC

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse

from ... import update_check
from ...users.auth import require_admin as _require_admin
from ._html import _BASE_CSS, _FAVICON, _P, _PAGE_CSS, _RESPONSIVE_CSS, _logout_button

router = APIRouter()
_log = logging.getLogger(__name__)

# Drive with a down arrow ("pull onto the server"): dashboard tile + top bar,
# used by no other tile.
SERVER_UPDATE_ICON_PATHS = (
    '<path d="M12 2v8"/><path d="m16 6-4 4-4-4"/>'
    '<rect x="2" y="14" width="20" height="8" rx="2"/>'
    '<path d="M6 18h.01"/><path d="M10 18h.01"/>'
)

_UPDATE_CSS = """
    .update-meta { display: grid; grid-template-columns: max-content 1fr; gap: .45rem 1.25rem;
                   padding: 1rem 1.5rem; font-size: .85rem; }
    .update-meta dt { color: var(--text-3); }
    .update-meta dd { margin: 0; color: var(--text); font-variant-numeric: tabular-nums; }
    .update-meta code, .update-body code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                                           font-size: .8rem; color: var(--text-2); }
    .update-body { padding: 1rem 1.5rem; font-size: .85rem; color: var(--text-2); }
    .update-body ul { margin: .5rem 0 0; padding-left: 1.1rem; }
    .update-body li { margin: .2rem 0; }
    .update-meta a { color: var(--text); }
    .update-notes { margin: .6rem 0 0; padding: .75rem 1rem; max-height: 22rem; overflow: auto;
                    white-space: pre-wrap; word-break: break-word; border-radius: 8px;
                    background: var(--border-sub); border: 1px solid var(--border);
                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem;
                    color: var(--text-2); }
    .update-reason { color: var(--orange); margin-bottom: .75rem; }
    .pill-ok { background: rgba(184,187,38,.15); color: #b8bb26; }
    .pill-new { background: rgba(250,189,47,.15); color: #fabd2f; }
    .pill-blocked { background: rgba(254,128,25,.15); color: #fe8019; }
    .update-actions { padding: 0 1.5rem 1.25rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
    .btn-update {
      background: #fabd2f; color: #282828; border-radius: 8px; padding: .55rem 1.2rem;
      font-size: .88rem; font-weight: 600;
    }
    .btn-update:hover:not(:disabled) { background: #fbf1c7; }
    .btn-update:disabled { opacity: .4; cursor: not-allowed; }
    .btn-check {
      background: transparent; color: var(--text-2); border: 1px solid var(--border); border-radius: 8px;
      padding: .45rem .9rem; font-size: .8rem;
    }
    .btn-check:hover:not(:disabled) { color: var(--text); border-color: var(--text-3); }
    .btn-check:disabled { opacity: .4; cursor: not-allowed; }
    .banner { border-radius: 10px; padding: .8rem 1.1rem; margin-bottom: 1.25rem; font-size: .85rem;
              border: 1px solid; }
    .banner code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; }
    .banner-ok { background: rgba(184,187,38,.1); border-color: rgba(184,187,38,.4); color: #b8bb26; }
    .banner-warn { background: rgba(254,128,25,.1); border-color: rgba(254,128,25,.4); color: #fe8019; }
    .banner-bad { background: rgba(251,73,52,.1); border-color: rgba(251,73,52,.4); color: #fb4934; }
    .banner-info { background: rgba(131,165,152,.1); border-color: rgba(131,165,152,.4); color: #83a598; }
    .updating { display: none; align-items: center; gap: .75rem; color: var(--text-2); font-size: .85rem; }
    .updating.on { display: flex; }
    .update-spinner {
      width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0;
      border: 2px solid rgba(250,189,47,.25); border-top-color: #fabd2f;
      animation: spin .8s linear infinite;
    }
"""

_UPDATE_JS = """
  <script>
    (function () {
      var btn = document.getElementById('update-btn');
      var busy = document.getElementById('updating');
      var msg = document.getElementById('updating-msg');
      var statusUrl = '__P__/update/status';
      var check = document.getElementById('check-btn');
      var checkedAt = document.getElementById('checked-at');
      if (checkedAt) {  // show the check time in the viewer's own time zone
        var t = new Date(checkedAt.getAttribute('datetime'));
        if (!isNaN(t)) {
          checkedAt.title = checkedAt.textContent;
          checkedAt.textContent = t.toLocaleString();
        }
      }
      if (check) {
        check.addEventListener('click', function () {  // every page load re-checks
          check.disabled = true;
          if (btn) { btn.disabled = true; }
          check.textContent = 'Checking…';
          window.location.reload();
        });
      }
      function poll(startedAt) {
        if (Date.now() - startedAt > 180000) {
          busy.querySelector('.update-spinner').style.display = 'none';
          msg.textContent = "The server didn't finish in 3 minutes; check the update log on the host.";
          return;
        }
        fetch(statusUrl, {cache: 'no-store', credentials: 'same-origin'})
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (s) {
            if (s && !s.running) { window.location.reload(); return; }
            setTimeout(function () { poll(startedAt); }, 2000);
          })
          .catch(function () { setTimeout(function () { poll(startedAt); }, 2000); });  // reloading
      }
      if (busy && busy.classList.contains('on')) { poll(Date.now()); }
      if (!btn) return;
      btn.addEventListener('click', function () {
        if (!confirm('Update and restart the server? Connected apps reconnect automatically.')) return;
        btn.disabled = true;
        fetch('__P__/update', {method: 'POST', credentials: 'same-origin'})
          .then(function (r) {
            if (r.status === 202) {
              busy.classList.add('on');
              msg.textContent = "Updating\\u2026 the server reloads; this page refreshes when it's done.";
              poll(Date.now());
            } else {
              return r.json().then(function (body) {
                alert(body.detail || ('Update refused (HTTP ' + r.status + ')'));
                window.location.reload();
              });
            }
          })
          .catch(function (e) { alert('Update request failed: ' + e); btn.disabled = false; });
      });
    })();
  </script>
"""


def _running_version() -> str:
    from ...main import backend_version  # main imports this router: resolve at call time

    return backend_version()


def _banner(result: update_check.LastResult | None, running: bool) -> str:
    if running:
        return ""
    if result is None or (result.seen and result.status in update_check.ONE_SHOT_RESULTS):
        return ""
    log = f" Log: <code>{html.escape(result.log_path)}</code>" if result.log_path else ""
    if result.status == "ok":
        return (
            f'<div class="banner banner-ok">Updated {html.escape(result.from_version)} &rarr; '
            f"{html.escape(result.to_version)}.</div>"
        )
    if result.status == "rolled_back":
        return (
            f'<div class="banner banner-warn">Update failed at <b>{html.escape(result.failed_step or "?")}</b>; '
            f"rolled back to {html.escape(result.from_version)}.{log}</div>"
        )
    if result.status == "failed":
        return (
            '<div class="banner banner-bad">Update failed and the rollback failed too '
            f"(at <b>{html.escape(result.failed_step or '?')}</b>); check the server.{log}</div>"
        )
    if result.status == "running":
        # Status says running but no lock: the helper died mid-way.
        return f'<div class="banner banner-bad">The last update stopped without finishing.{log}</div>'
    return f'<div class="banner banner-bad">The last update\'s result file is unreadable.{log}</div>'


def _meta(st: update_check.UpdateStatus, version: str) -> str:
    rows = [("Running version", html.escape(version))]
    if st.mode == update_check.MODE_GIT:
        rows.append(("Source", "git checkout (origin/master)"))
        rows.append(("Branch", html.escape(st.branch or "?")))
        rows.append(("Commit", f"<code>{html.escape(st.head_sha[:8]) if st.head_sha else '?'}</code>"))
    else:
        if st.latest_version and st.release_url:
            latest = f'<a href="{html.escape(st.release_url)}">{html.escape(st.latest_version)}</a>'
        else:
            latest = html.escape(st.latest_version or "?")
        rows.append(("Source", "release tarball"))
        rows.append(("Latest release", latest))
    checked = st.checked_at.astimezone(UTC)
    rows.append((
        "Checked",
        f'<time id="checked-at" datetime="{checked.isoformat(timespec="seconds")}">'
        f"{checked:%Y-%m-%d %H:%M:%S} UTC</time>",
    ))
    items = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    return f'\n      <dl class="update-meta">{items}</dl>'


def _available_body(st: update_check.UpdateStatus, version: str) -> tuple[str, str, str]:
    """(pill, body, button label) for an available update."""
    if st.mode == update_check.MODE_GIT:
        n = st.behind_count
        pill = f'<span class="pill pill-new">{n} new commit{"s" if n != 1 else ""}</span>'
        items = "".join(
            f"<li><code>{html.escape(sha)}</code> {html.escape(subject)}</li>"
            for sha, _, subject in (c.partition(" ") for c in st.behind)
        )
        hidden = n - len(st.behind)
        more = f"<li>and {hidden} more</li>" if hidden > 0 else ""
        body = f'<div class="update-body">Incoming:<ul>{items}{more}</ul></div>'
        if st.latest_version and st.latest_version != version:
            label = f"Update to {html.escape(st.latest_version)}"
        else:
            label = f"Update ({n} commit{'s' if n != 1 else ''})"
        return pill, body, label
    pill = '<span class="pill pill-new">New release</span>'
    notes = (
        f'<pre class="update-notes">{html.escape(st.release_notes.strip())}</pre>' if st.release_notes.strip() else ""
    )
    body = f'<div class="update-body">Release {html.escape(st.latest_version or "")}{notes}</div>'
    return pill, body, f"Update to {html.escape(st.latest_version or '')}"


def _state_card(st: update_check.UpdateStatus, version: str, running: bool) -> str:
    disabled, label = True, "Update"
    if running:
        pill = '<span class="pill pill-new">Updating</span>'
        body = ""
    elif st.blocked_reason:
        pill = '<span class="pill pill-blocked">Blocked</span>'
        dirty = "".join(f"<li><code>{html.escape(p)}</code></li>" for p in st.dirty_paths[:50])
        more = f"<li>and {len(st.dirty_paths) - 50} more</li>" if len(st.dirty_paths) > 50 else ""
        body = (
            f'<div class="update-body"><div class="update-reason">{html.escape(st.blocked_reason)}</div>'
            + (f"<ul>{dirty}{more}</ul>" if dirty else "")
            + "</div>"
        )
    elif st.available:
        pill, body, label = _available_body(st, version)
        disabled = False
    else:
        pill = '<span class="pill pill-ok">Up to date</span>'
        body = ""
    disabled_attr = " disabled" if disabled else ""
    check_label = "Retry" if st.retryable and not running else "Check now"
    return f"""
    <div class="card">
      <div class="card-header"><h2 class="card-title">Server</h2>{pill}</div>
      {_meta(st, version)}
      {body}
      <div class="update-actions">
        <button class="btn-update" id="update-btn" type="button"{disabled_attr}>{label}</button>
        <button class="btn-check" id="check-btn" type="button">{check_label}</button>
        <div class="updating{" on" if running else ""}" id="updating">
          <div class="update-spinner"></div><span id="updating-msg">An update is in progress&hellip;</span>
        </div>
      </div>
    </div>"""


def render_page(st: update_check.UpdateStatus, result: update_check.LastResult | None, version: str) -> str:
    running = update_check.lock_active()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Server Update &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_UPDATE_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{SERVER_UPDATE_ICON_PATHS}</svg>
      </div>
      <div class="brand">
        <span class="brand-name">Server Update</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
    {_logout_button()}
  </header>

  <div class="page">
    {_banner(result, running)}
    {_state_card(st, version, running)}
  </div>
  {_UPDATE_JS.replace("__P__", _P)}
</body>
</html>"""


@router.get("/update", response_class=HTMLResponse, include_in_schema=False)
def admin_update_page(_: str = Depends(_require_admin)):
    version = _running_version()
    st = update_check.check(version)
    result = update_check.last_result()
    page = render_page(st, result, version)
    if result is not None and not result.seen and result.status in update_check.ONE_SHOT_RESULTS:
        update_check.mark_result_seen()  # shown once; a reload or Check now drops it
    return HTMLResponse(page)


@router.get("/update/status", include_in_schema=False)
def admin_update_status(_: str = Depends(_require_admin)):
    result = update_check.last_result()
    return {"running": update_check.lock_active(), "result": result.status if result else None}


@router.post("/update", include_in_schema=False)
def admin_update_start(admin_user: str = Depends(_require_admin)):
    # The page may be stale: re-check every blocking condition now.
    st = update_check.check(_running_version())
    if st.blocked_reason:
        return JSONResponse({"detail": st.blocked_reason}, status_code=status.HTTP_409_CONFLICT)
    if not st.available:
        return JSONResponse({"detail": "Already up to date."}, status_code=status.HTTP_409_CONFLICT)
    if not update_check.take_lock():
        return JSONResponse({"detail": "An update is already in progress."}, status_code=status.HTTP_409_CONFLICT)
    try:
        stage = update_check.prepare(st)
    except update_check.UpdateError as exc:
        update_check.release_lock()
        _log.error("self-update (%s) refused: %s", st.mode, exc)
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        update_check.release_lock()
        _log.exception("could not prepare the %s self-update", st.mode)
        return JSONResponse(
            {"detail": "Couldn't prepare the update; see the server log."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    try:
        log_path = update_check.launch(st, stage)
    except Exception:
        update_check.release_lock()
        _log.exception("could not start the self-update helper")
        return JSONResponse(
            {"detail": "Couldn't start the update; see the server log."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    target = st.remote_sha[:8] if st.mode == update_check.MODE_GIT else st.latest_version
    _log.warning("admin=%s started a %s server update to %s", admin_user, st.mode, target)
    return JSONResponse({"log_path": str(log_path)}, status_code=status.HTTP_202_ACCEPTED)
