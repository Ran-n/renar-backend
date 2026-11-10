#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 00:00:00.000000
Revised: 2026/11/09 23:36:40.296797

Admin periodic-tasks page: cards grouped by media type (TV Shows, Films,
Security), one card per background task, each with its own enable toggle,
editable poll interval, and run status (ok/error/skipped, last run, next
run estimate). Every task is independently controllable — see task_runs.py.
"""

import html
import itertools
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import task_runs
from ...models import PeriodicTaskRun
from ...users.auth import require_admin as _require_admin
from ._html import _BASE_CSS, _FAVICON, _P, _PAGE_CSS, _RESPONSIVE_CSS, _fmt_ts, _logout_button

router = APIRouter()
_log = logging.getLogger(__name__)

_MIN_INTERVAL = 1
_MAX_INTERVAL = 10080  # one week

_TASKS_CSS = """
    .task-section { margin-bottom: 1.75rem; }
    .task-section-title {
      font-size: .72rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
      color: var(--text-3); margin-bottom: .7rem;
    }
    .task-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 1rem;
    }
    .task-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.1rem 1.25rem;
      display: flex; flex-direction: column; gap: .7rem;
    }
    .task-card.disabled { opacity: .6; }
    .task-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; }
    .task-label { font-size: .88rem; font-weight: 600; color: var(--text); }
    .task-desc { font-size: .74rem; color: var(--text-3); margin-top: .2rem; line-height: 1.4; }

    .switch { position: relative; display: inline-block; width: 38px; height: 21px; flex-shrink: 0; margin-top: .1rem; }
    .switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
    .switch-slider {
      position: absolute; inset: 0; background: var(--border-sub); border: 1px solid var(--border);
      border-radius: 999px; transition: background .15s, border-color .15s; pointer-events: none;
    }
    .switch-slider::before {
      content: ""; position: absolute; height: 15px; width: 15px; left: 2px; top: 2px;
      background: var(--text-2); border-radius: 50%; transition: transform .15s, background .15s;
    }
    .switch input:checked + .switch-slider { background: rgba(250,189,47,.22); border-color: var(--accent); }
    .switch input:checked + .switch-slider::before { transform: translateX(17px); background: var(--accent); }
    .switch input:focus-visible + .switch-slider { outline: 2px solid var(--accent); outline-offset: 2px; }

    .task-card-sep { height: 1px; background: var(--border-sub); }
    .task-status-row { display: flex; align-items: center; gap: .45rem; font-size: .82rem; font-weight: 600; }
    .task-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .task-ts { font-size: .72rem; color: var(--text-3); font-weight: 400; }
    .task-detail { font-size: .74rem; color: var(--text-2); line-height: 1.4; }

    .task-interval-row { display: flex; align-items: center; gap: .5rem; }
    .task-interval-row label { font-size: .72rem; color: var(--text-2); }
    .task-interval-input {
      background: var(--bg); border: 1px solid var(--border); color: var(--text);
      border-radius: 7px; padding: .3rem .5rem; font-size: .82rem; font-family: inherit;
      width: 72px;
    }
    .task-interval-input:focus { outline: none; border-color: var(--accent); }
    .task-interval-row span.unit { font-size: .72rem; color: var(--text-2); }
    .task-btn-save {
      background: var(--border-sub); border: 1px solid var(--border); color: var(--text);
      border-radius: 7px; padding: .3rem .8rem; font-size: .76rem; font-weight: 500; margin-left: auto;
    }
    .task-btn-save:hover { background: var(--border); border-color: var(--text-3); }
"""

_STATUS_DOT = {"ok": "#b8bb26", "error": "#fb4934", "skipped": "#928374"}
_STATUS_LABEL = {"ok": "OK", "error": "Error", "skipped": "Skipped"}


def _task_card(spec: task_runs.TaskSpec, run: PeriodicTaskRun | None) -> str:
    enabled = run.enabled if run is not None else True
    interval = run.interval_minutes if run is not None and run.interval_minutes is not None else spec.interval_minutes

    if not enabled:
        status, dot, ts, detail = "Disabled", "#928374", "&mdash;", ""
    elif run is None or run.last_finished_at is None:
        status, dot, ts, detail = "Never run", "#928374", "&mdash;", ""
    else:
        status = _STATUS_LABEL.get(run.last_status, (run.last_status or "").title())
        dot = _STATUS_DOT.get(run.last_status, "#928374")
        ts = _fmt_ts(run.last_finished_at)
        detail = html.escape(run.last_detail or "")
        if run.last_status == "ok":
            next_run = run.last_finished_at + timedelta(minutes=interval)
            next_note = f"next around {_fmt_ts(next_run)}"
            detail = f"{detail} &middot; {next_note}" if detail else next_note

    return f"""
      <div class="task-card{"" if enabled else " disabled"}">
        <div class="task-card-head">
          <div>
            <div class="task-label">{html.escape(spec.label)}</div>
            <div class="task-desc">{html.escape(spec.desc)}</div>
          </div>
          <form method="post" action="{_P}/periodic-tasks/toggle" style="display:contents">
            <input type="hidden" name="task_key" value="{html.escape(spec.key)}">
            <input type="hidden" name="value" value="{0 if enabled else 1}">
            <label class="switch">
              <input type="checkbox"{" checked" if enabled else ""} onchange="this.form.requestSubmit()">
              <span class="switch-slider"></span>
            </label>
          </form>
        </div>
        <div class="task-card-sep"></div>
        <div class="task-status-row"><span class="task-dot" style="background:{dot}"></span>{status}
          <span class="task-ts">&middot; {ts}</span>
        </div>
        {f'<div class="task-detail">{detail}</div>' if detail else ""}
        <div class="task-card-sep"></div>
        <form class="task-interval-row" method="post" action="{_P}/periodic-tasks/interval">
          <input type="hidden" name="task_key" value="{html.escape(spec.key)}">
          <label for="interval-{spec.key}">Every</label>
          <input class="task-interval-input" type="number" id="interval-{spec.key}" name="minutes"
                 value="{interval}" min="{_MIN_INTERVAL}" max="{_MAX_INTERVAL}" required>
          <span class="unit">min</span>
          <button class="task-btn-save" type="submit">Save</button>
        </form>
      </div>"""


def _render_periodic_tasks(runs: dict) -> str:
    sections = ""
    for group_name, specs in itertools.groupby(task_runs.TASKS, key=lambda s: s.group):
        cards = "".join(_task_card(spec, runs.get(spec.key)) for spec in specs)
        sections += (
            f'<div class="task-section"><div class="task-section-title">{html.escape(group_name)}</div>'
            f'<div class="task-grid">{cards}</div></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Periodic Tasks &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_TASKS_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">&#x23F1;</div>
      <div class="brand">
        <span class="brand-name">Periodic Tasks</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
    {_logout_button()}
  </header>

  <div class="page">
    {sections}
  </div>

</body>
</html>"""


@router.get("/periodic-tasks", response_class=HTMLResponse, include_in_schema=False)
def admin_periodic_tasks(_: str = Depends(_require_admin)):
    return _render_periodic_tasks(task_runs.list_runs())


@router.post("/periodic-tasks/toggle", include_in_schema=False)
def toggle_periodic_task(
    task_key: str = Form(...),
    value: str = Form(...),
    admin_user: str = Depends(_require_admin),
):
    allowed = {spec.key for spec in task_runs.TASKS}
    if task_key not in allowed:
        return RedirectResponse(f"{_P}/periodic-tasks", status_code=303)
    task_runs.set_enabled(task_key, value == "1")
    _log.info("admin=%s set periodic task %s enabled=%s", admin_user, task_key, value == "1")
    return RedirectResponse(f"{_P}/periodic-tasks", status_code=303)


@router.post("/periodic-tasks/interval", include_in_schema=False)
def set_periodic_task_interval(
    task_key: str = Form(...),
    minutes: int = Form(...),
    admin_user: str = Depends(_require_admin),
):
    allowed = {spec.key for spec in task_runs.TASKS}
    if task_key not in allowed or not (_MIN_INTERVAL <= minutes <= _MAX_INTERVAL):
        return RedirectResponse(f"{_P}/periodic-tasks", status_code=303)
    task_runs.set_interval_minutes(task_key, minutes)
    _log.info("admin=%s set periodic task %s interval=%d min", admin_user, task_key, minutes)
    return RedirectResponse(f"{_P}/periodic-tasks", status_code=303)
