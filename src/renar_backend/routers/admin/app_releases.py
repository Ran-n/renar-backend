#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/09 16:20:14.846659
Revised: 2026/11/09 23:36:43.647206

Admin App Releases: the JSON upload route renar-frontend's
``uv run build apk --split --publish`` calls, and an HTML page listing every
uploaded APK per platform with a delete button. Uploading from the page
itself is deliberately absent: builds come from the build command.
"""

import html
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ... import app_releases
from ...database import get_db
from ...models import AppRelease
from ...users.auth import require_admin as _require_admin
from ...users.auth import require_admin_or_api_token as _require_admin_or_token
from ..app_releases import AppReleasePlatform
from ._html import _BASE_CSS, _FAVICON, _P, _PAGE_CSS, _RESPONSIVE_CSS, _fmt_ts, _logout_button

router = APIRouter()
_log = logging.getLogger(__name__)

# Package/box outline: shared with the dashboard tile, used by no other tile.
APP_RELEASES_ICON_PATHS = (
    '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4'
    'a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>'
    '<polyline points="3.27 6.96 12 12.01 20.73 6.96"/>'
    '<line x1="12" y1="22.08" x2="12" y2="12"/>'
)

_RELEASES_CSS = """
    .pill-latest { background: rgba(184,187,38,.15); color: #b8bb26; margin-left: .4rem; }
    .td-hash { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .76rem; color: var(--text-2); }
    .td-notes { color: var(--text-2); font-size: .82rem; max-width: 420px; white-space: pre-wrap; }
"""

_VERSION_PATTERN = r"^\d{1,6}\.\d{1,6}\.\d{1,6}$"
_NOTES_MAX = 2000


def _clean_notes(value: str | None) -> str | None:
    # Postgres text columns reject NUL outright: answer 422, never a 500.
    if value is not None and "\x00" in value:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Notes must not contain NUL characters")
    return value.strip() or None if value is not None else None


@router.post("/app-releases", include_in_schema=False)
def upload_app_release(
    file: Annotated[UploadFile, File()],
    platform: Annotated[AppReleasePlatform, Form()],
    version: Annotated[str, Form(pattern=_VERSION_PATTERN)],
    notes: Annotated[str | None, Form(max_length=_NOTES_MAX)] = None,
    admin_user: str = Depends(_require_admin_or_token),
    db: Session = Depends(get_db),
):
    release, created = app_releases.store_upload(db, file.file, platform, version, _clean_notes(notes))
    if created:
        _log.info("admin=%s published app release %s %s", admin_user, platform, version)
    body = app_releases.to_out(release).model_dump(mode="json")
    return JSONResponse(body, status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


def _release_row(release: AppRelease, is_latest: bool) -> str:
    version = html.escape(release.version)
    latest_pill = '<span class="pill pill-latest">Latest</span>' if is_latest else ""
    size_mb = release.size_bytes / (1024 * 1024)
    return f"""
        <tr>
          <td class="td-label">{version}{latest_pill}</td>
          <td class="td-count">{size_mb:.1f} MB</td>
          <td class="td-ts">{_fmt_ts(release.uploaded_at)}</td>
          <td class="td-notes">{html.escape(release.changelog or "")}</td>
          <td class="td-hash" title="{release.blake3}">{release.blake3[:12]}</td>
          <td><div class="td-actions">
            <form method="post" action="{_P}/app-releases/{release.id}/delete"
                  onsubmit="return confirm('Delete {html.escape(release.platform)} {version}?')"
                  style="display:contents">
              <button class="btn-sm btn-purge" type="submit">Delete</button>
            </form>
          </div></td>
        </tr>"""


def _render_page(grouped: dict[str, list[AppRelease]]) -> str:
    cards = ""
    for platform in sorted(grouped):
        rows = "".join(_release_row(r, i == 0) for i, r in enumerate(grouped[platform]))
        cards += f"""
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">{html.escape(platform)}</h2>
        <span class="pill">{len(grouped[platform])} releases</span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>Version</th><th>Size</th><th>Uploaded (UTC)</th><th>Notes</th><th>BLAKE3</th><th></th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      </div>
    </div>"""
    if not cards:
        cards = (
            '<div class="card"><div class="empty">No releases uploaded yet. Publish one with '
            "<code>uv run build apk --split --publish</code> in renar-frontend.</div></div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>App Releases &middot; renar</title>
  <link rel="icon" href="{_FAVICON}">
  <style>{_BASE_CSS}{_PAGE_CSS}{_RELEASES_CSS}{_RESPONSIVE_CSS}</style>
</head>
<body>

  <header class="topbar">
    <a class="topbar-brand-link" href="{_P}">
      <div class="logo">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{APP_RELEASES_ICON_PATHS}</svg>
      </div>
      <div class="brand">
        <span class="brand-name">App Releases</span>
        <span class="brand-sub">renar</span>
      </div>
    </a>
    <div class="topbar-fill"></div>
    <a class="admin-pill" href="{_P}">Admin</a>
    {_logout_button()}
  </header>

  <div class="page">
    {cards}
  </div>

</body>
</html>"""


@router.get("/app-releases", response_class=HTMLResponse, include_in_schema=False)
def admin_app_releases(_: str = Depends(_require_admin), db: Session = Depends(get_db)):
    return _render_page(app_releases.all_by_platform(db))


@router.post("/app-releases/{release_id}/delete", include_in_schema=False)
def delete_app_release(
    release_id: int, admin_user: str = Depends(_require_admin_or_token), db: Session = Depends(get_db)
):
    if not app_releases.delete(db, release_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such release")
    _log.info("admin=%s deleted app release %d", admin_user, release_id)
    return RedirectResponse(f"{_P}/app-releases", status_code=303)
