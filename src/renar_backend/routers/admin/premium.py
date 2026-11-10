#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/20 00:00:00.000000
Revised: 2026/11/09 23:36:40.464070

Admin premium-features page: one card per premium perk, each with its own
instant on/off switch (SiteSettings.premium_<feature>_enabled). Independent
of the Site Settings page — see routers/admin/settings.py's own hint linking
back here.
"""

import html
import logging

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ... import site_settings as _site_settings_mod
from ...database import get_db
from ...models import SiteSettings
from ...site_settings import get_site_settings
from ...users.auth import require_admin as _require_admin
from ...users.premium import PREMIUM_FEATURES
from ._html import _BASE_CSS, _FAVICON, _P, _PAGE_CSS, _RESPONSIVE_CSS, _logout_button

router = APIRouter()
_log = logging.getLogger(__name__)

# The exact crown shape from frontend assets/badge_premium.svg (the actual
# badge shown next to a premium user's name), flattened to a single fill so
# it drops into a monochrome icon slot instead of that asset's gold gradient.
# Keep in sync with the frontend file if that artwork ever changes shape.
_CROWN = (
    '<circle cx="2.7" cy="6" r="1.7"/><circle cx="12" cy="3.2" r="1.9"/><circle cx="21.3" cy="6" r="1.7"/>'
    '<path d="M2.7 8.1 7.7 11.5 12 5.6 16.3 11.5 21.3 8.1 19.8 16.3 4.2 16.3Z"/>'
    '<rect x="4.2" y="17.5" width="15.6" height="2.7" rx="1.35"/>'
    '<path d="M12 9.4 14.1 12 12 14.6 9.9 12Z" opacity=".5"/>'
)


def _crown_icon(size: int, fill: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 -1.25 24 24" fill="{fill}">{_CROWN}</svg>'
    )


def _icon(paths: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        f"{paths}</svg>"
    )


# (feature key, card label, card description, card icon) — key matches the
# PremiumFeature literal in users/premium.py; the SiteSettings column is
# f"premium_{key}_enabled". Grouped below into the two sections users
# actually think in: what shows on their profile vs. how the app looks to them.
_PROFILE_FEATURES: tuple[tuple[str, str, str, str], ...] = (
    (
        "style",
        "Profile style",
        "Ring/username color picker and per-status Library accent colors (PATCH /premium/style).",
        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.2" fill="currentColor" stroke="none"/>',
    ),
    (
        "verification",
        "Verification requests",
        "Letting premium users request the verified badge (POST /premium/verification-request).",
        '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.4 2.4 4.6-4.8"/>',
    ),
    (
        "background",
        "Profile background image",
        "Uploading a custom profile background image.",
        '<rect x="3" y="4.5" width="18" height="15" rx="2"/><circle cx="8.5" cy="10" r="1.5"/>'
        '<path d="m4 17.5 5-5 4 4 3-3 4 4"/>',
    ),
)
_APPEARANCE_FEATURES: tuple[tuple[str, str, str, str], ...] = (
    (
        "themes",
        "Paid themes",
        "Every theme except the free gruvbox default.",
        '<rect x="3" y="3" width="8" height="8" rx="1.6"/><rect x="13" y="3" width="8" height="8" rx="1.6"/>'
        '<rect x="8" y="13" width="8" height="8" rx="1.6"/>',
    ),
    (
        "progress_style",
        "Paid progress styles",
        'Home screen progress indicator styles other than the free "rings".',
        '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    ),
    (
        "episode_label",
        "Paid episode label styles",
        'Episode label formats other than the free "cross" (1×05) style.',
        '<path d="M6 3.5h12v17l-6-4-6 4v-17z"/>',
    ),
)
_STATS_FEATURES: tuple[tuple[str, str, str, str], ...] = (
    (
        "ranking",
        "Leaderboard ranking",
        "Where a premium user stands against everyone else (GET /stats/ranking).",
        '<path d="M8 20V10M16 20V4M4 20h16" stroke-linecap="round"/>',
    ),
)

_PREMIUM_CSS = """
    .page-intro { font-size: .82rem; color: var(--text-2); margin-bottom: 1.5rem; max-width: 640px; }

    .status-row { display: flex; gap: .75rem; margin-bottom: 1.75rem; flex-wrap: wrap; }
    .status-chip {
      display: flex; align-items: center; gap: .55rem;
      background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
      padding: .6rem .9rem;
    }
    .status-chip-label { font-size: .72rem; color: var(--text-2); }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .status-chip-value { font-size: .82rem; font-weight: 600; }

    .feature-section { margin-bottom: 1.75rem; }
    .feature-section-title {
      font-size: .72rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
      color: var(--text-3); margin-bottom: .7rem;
    }
    .feature-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 1rem;
    }
    .feature-card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 1.1rem 1.25rem;
      display: flex; flex-direction: column; gap: .8rem;
      transition: border-color .15s, opacity .15s;
    }
    .feature-card.disabled { opacity: .55; }
    .feature-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; }
    .feature-icon {
      width: 36px; height: 36px; border-radius: 9px; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      background: rgba(250,189,47,.12); color: var(--accent);
      transition: background .15s, color .15s;
    }
    .feature-card.disabled .feature-icon { background: var(--border-sub); color: var(--text-3); }
    .feature-copy { display: flex; flex-direction: column; gap: .3rem; }
    .feature-label { font-size: .88rem; font-weight: 600; color: var(--text); }
    .feature-desc { font-size: .74rem; color: var(--text-3); line-height: 1.4; }

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
"""


def _feature_card(key: str, label: str, desc: str, icon_paths: str, enabled: bool) -> str:
    return f"""
      <div class="feature-card{"" if enabled else " disabled"}">
        <div class="feature-card-head">
          <div class="feature-icon">{_icon(icon_paths)}</div>
          <form method="post" action="{_P}/premium/toggle" style="display:contents">
            <input type="hidden" name="feature" value="{key}">
            <input type="hidden" name="value" value="{0 if enabled else 1}">
            <label class="switch">
              <input type="checkbox"{" checked" if enabled else ""} onchange="this.form.requestSubmit()">
              <span class="switch-slider"></span>
            </label>
          </form>
        </div>
        <div class="feature-copy">
          <div class="feature-label">{html.escape(label)}</div>
          <div class="feature-desc">{html.escape(desc)}</div>
        </div>
      </div>"""


def _feature_section(title: str, features: tuple, ss: SiteSettings) -> str:
    cards = "".join(
        _feature_card(key, label, desc, icon, getattr(ss, f"premium_{key}_enabled"))
        for key, label, desc, icon in features
    )
    return (
        f'<div class="feature-section"><div class="feature-section-title">{html.escape(title)}</div>'
        f'<div class="feature-grid">{cards}</div></div>'
    )


def _render_premium_page(ss: SiteSettings) -> str:
    all_features = _PROFILE_FEATURES + _APPEARANCE_FEATURES + _STATS_FEATURES
    on_count = sum(getattr(ss, f"premium_{key}_enabled") for key, *_ in all_features)
    total = len(all_features)
    status_dot = "#b8bb26" if on_count == total else "#fabd2f" if on_count else "#fb4934"

    sections = (
        _feature_section("Profile & identity", _PROFILE_FEATURES, ss)
        + _feature_section("Appearance & personalization", _APPEARANCE_FEATURES, ss)
        + _feature_section("Stats & competition", _STATS_FEATURES, ss)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Premium Features &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_PREMIUM_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">{_crown_icon(18, "var(--bg)")}</div>
      <div class="brand">
        <span class="brand-name">Premium Features</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
    {_logout_button()}
  </header>

  <div class="page">
    <div class="status-row">
      <div class="status-chip">
        <span class="status-dot" style="background:{status_dot}"></span>
        <span class="status-chip-label">Premium features</span>
        <span class="status-chip-value">{on_count}/{total} on</span>
      </div>
    </div>
    <p class="page-intro">
      Each switch independently rejects that one perk for every user, regardless of
      individual subscriptions &mdash; changes apply immediately, no save button needed.
      Existing premium_until dates are kept and take effect again as soon as a switch
      is turned back on.
    </p>
    {sections}
  </div>

</body>
</html>"""


@router.get("/premium", response_class=HTMLResponse, include_in_schema=False)
def admin_premium(_: str = Depends(_require_admin), db: Session = Depends(get_db)):
    return _render_premium_page(get_site_settings(db))


@router.post("/premium/toggle", include_in_schema=False)
def toggle_premium_feature(
    feature: str = Form(...),
    value: str = Form(...),
    admin_user: str = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    if feature not in PREMIUM_FEATURES:
        return RedirectResponse(f"{_P}/premium", status_code=303)
    ss = get_site_settings(db)
    enabled = value == "1"
    setattr(ss, f"premium_{feature}_enabled", enabled)
    db.commit()
    _site_settings_mod.invalidate()
    _log.info("admin=%s set premium feature %s enabled=%s", admin_user, feature, enabled)
    return RedirectResponse(f"{_P}/premium", status_code=303)
