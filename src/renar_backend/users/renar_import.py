#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/27 00:00:00.000000
Revised: 2026/08/11 09:36:15.490976

Import a Renar-native export (users/export.py's .7z of profile/library/
comments/social JSON) back into an account — the write side of GDPR Art.
20's data portability, so an account restored after loss (or moved to a
fresh install pointed at an empty database) gets everything back, not just
a document to look at. One of several importers registered in
routers/imports.py's dispatch table (see that module's docstring).

Unlike routers/imports.py's TV Time import, every library row already
carries its own tmdb_id — there is no fuzzy title matching here, so this
runs synchronously per row on one thread rather than fanning out TMDB
lookups across a worker pool.

Merge semantics mirror the TV Time importer throughout: an existing row
never gets clobbered, only filled in where it was empty or extended with
new episode/comment/follow data — so re-running an import (or importing
into an account that already has data) is always safe.

Comment reply threads: this account's own export only contains its own
comments (see export.py), so a reply's parent is only reconstructible when
that parent is ALSO one of this user's own comments present in the same
export (a self-reply chain). A reply to someone else's comment is dropped
rather than guessed at — attaching it to an unrelated row by unverifiable
id coincidence would misrepresent it, and cross-instance ids aren't
comparable at all. Same documented limitation as the TV Time importer.

Only `following` is restored on the social side: `followers` records other
accounts' choice to follow this one, which isn't this account's to recreate.
"""

import io
import json
import logging
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

import py7zr
from sqlalchemy.orm import Session

from ..catalog.titles import find_or_create_title, normalize_title_key
from ..database import SessionLocal
from ..models import (
    Comment,
    EpisodeWatch,
    Follow,
    ImportJob,
    LibraryEntry,
    MediaType,
    Title,
    User,
    WatchStatus,
)
from ..tmdb.tmdb_store import refresh_title_details

_log = logging.getLogger(__name__)

KIND = "renar"
LABEL = "Renar"

# No TMDB matching happens here (every row already carries its own tmdb_id),
# so a run is cheap compared to the TV Time importer — a larger budget of
# concurrent runs is safe. Independent from other registered importers'
# budgets; see routers/imports.py's docstring.
MAX_CONCURRENT_IMPORTS = 5
_slots = threading.Semaphore(MAX_CONCURRENT_IMPORTS)

_progress: dict[int, dict] = {}


def detect(data: bytes) -> bool:
    """A Renar export is a 7z archive containing profile.json (see
    users/export.py) — distinctive enough that no other importer could
    plausibly produce a file matching this."""
    try:
        with py7zr.SevenZipFile(io.BytesIO(data)) as archive:
            names = archive.getnames()
    except py7zr.Bad7zFile:
        return False
    return "profile.json" in names


def acquire_slot() -> bool:
    return _slots.acquire(blocking=False)


def release_slot() -> None:
    _slots.release()


# Settings restored verbatim onto the importing account. Deliberately
# excludes username/email/is_premium/verified/created_at/last_active_at/
# exported_at — those are identity or account-state facts, not preferences,
# and an old export shouldn't be able to downgrade e.g. a currently-premium
# account back to free.
_PROFILE_FIELDS = (
    "language",
    "show_original_titles",
    "theme",
    "home_hero_enabled",
    "home_on_launch",
    "home_progress_style",
    "home_season_color",
    "home_series_color",
    "countdown_colors",
    "status_colors",
    "episode_label_style",
    "ring_color",
    "name_color",
)


def progress(user_id: int) -> dict | None:
    return _progress.get(user_id)


def is_running(user_id: int) -> bool:
    live = _progress.get(user_id)
    return bool(live and not live.get("finished", True))


def start_job(user_id: int) -> None:
    _progress[user_id] = {"stage": "Starting", "done": 0, "total": 0, "finished": False, "error": None, "summary": None}
    _mark_job(user_id, finished=False, error=None, summary=None)


def _set(user_id: int, **kw) -> None:
    _progress.setdefault(user_id, {}).update(kw)


def _mark_job(user_id: int, *, finished: bool, error: str | None = None, summary: dict | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(ImportJob, (user_id, KIND))
        if job is None:
            job = ImportJob(user_id=user_id, kind=KIND)
            db.add(job)
        job.finished = finished
        job.error = error
        job.summary = summary
        db.commit()
    except Exception:
        db.rollback()
        _log.warning("Failed to persist renar-export import job state for user_id=%s", user_id, exc_info=True)
    finally:
        db.close()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _read_json(directory: Path, name: str) -> dict | list:
    path = directory / name
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_profile(user: User, profile: dict) -> None:
    for field in _PROFILE_FIELDS:
        if field in profile and profile[field] is not None:
            setattr(user, field, profile[field])


def _valid_rating(value) -> int | None:
    """Ratings here come straight from an export file, not a validated API
    request — a corrupted, hand-edited, or foreign-version export could carry
    anything. Mirrors the API schemas' `ge=1, le=100` bound so a bad value
    can't slip into the DB (and then render raw/unclamped) via import alone."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value if 1 <= value <= 100 else None


def _reconcile_library_entry(entry: LibraryEntry, incoming: dict) -> bool:
    """Fill gaps on an already-tracked entry; never overwrite what's there."""
    changed = False
    if incoming.get("is_favorite") and not entry.is_favorite:
        entry.is_favorite = True
        changed = True
    if entry.rating is None and _valid_rating(incoming.get("rating")) is not None:
        entry.rating = incoming["rating"]
        changed = True
    if not entry.notes and incoming.get("notes"):
        entry.notes = incoming["notes"]
        changed = True
    return changed


def _sync_progress(item: LibraryEntry, db: Session) -> None:
    watches = db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item.id).all()
    if not watches:
        return
    item.episodes_watched = len(watches)
    last = max(watches, key=lambda w: (w.season, w.episode))
    item.current_season, item.current_episode = last.season, last.episode
    if (
        item.total_episodes
        and item.episodes_watched >= item.total_episodes
        and item.status not in (WatchStatus.dropped, WatchStatus.paused)
    ):
        item.status = WatchStatus.completed


def _import_library(db: Session, user_id: int, rows: list[dict], summary: dict) -> None:
    existing_rows = (
        db.query(LibraryEntry.id, Title)
        .join(Title, LibraryEntry.title_id == Title.id)
        .filter(LibraryEntry.user_id == user_id)
        .all()
    )
    existing_map: dict[tuple, int] = {}
    for entry_id, t in existing_rows:
        if t.tmdb_id:
            existing_map[(t.media_type.value, t.tmdb_id)] = entry_id
        existing_map[(t.media_type.value, t.title_key or normalize_title_key(t.title))] = entry_id

    _set(user_id, stage="Importing library", done=0, total=len(rows))
    touched_items: set[int] = set()
    for n, row in enumerate(rows, 1):
        if n % 50 == 0:
            _set(user_id, done=n)
        try:
            media_type = MediaType(row["media_type"])
            status = WatchStatus(row["status"])
        except ValueError:
            summary["library_skipped"] += 1
            continue
        title_name = row.get("title") or ""
        tmdb_id = row.get("tmdb_id")
        tmdb_key = (media_type.value, tmdb_id) if tmdb_id else None
        title_key = (media_type.value, normalize_title_key(title_name))
        item_id = existing_map.get(tmdb_key) if tmdb_key else None
        if item_id is None:
            item_id = existing_map.get(title_key)

        if item_id is None:
            title = find_or_create_title(db, media_type, tmdb_id, title_name, year=row.get("year"))
            refresh_title_details(db, title)
            entry = LibraryEntry(
                user_id=user_id,
                title_id=title.id,
                status=status,
                rating=_valid_rating(row.get("rating")),
                notes=row.get("notes"),
                is_favorite=bool(row.get("is_favorite")),
            )
            db.add(entry)
            db.flush()
            item_id = entry.id
            existing_map[tmdb_key or title_key] = item_id
            summary["library_entries"] += 1
        else:
            entry = db.get(LibraryEntry, item_id)
            if _reconcile_library_entry(entry, row):
                summary["library_updated"] += 1
                touched_items.add(item_id)
            else:
                summary["library_skipped"] += 1

        seen = {
            (w.season, w.episode) for w in db.query(EpisodeWatch).filter(EpisodeWatch.media_item_id == item_id).all()
        }
        for w in row.get("episode_watches") or []:
            key = (w.get("season"), w.get("episode"))
            if key in seen or key[0] is None or key[1] is None:
                continue
            seen.add(key)
            db.add(
                EpisodeWatch(
                    media_item_id=item_id,
                    season=w["season"],
                    episode=w["episode"],
                    rating=_valid_rating(w.get("rating")),
                    watched_at=_parse_iso(w.get("watched_at")) or datetime.now(UTC),
                )
            )
            touched_items.add(item_id)
            summary["episodes"] += 1
    db.commit()

    for item_id in touched_items:
        item = db.get(LibraryEntry, item_id)
        if item is not None:
            _sync_progress(item, db)
    db.commit()


def _import_comments(db: Session, user_id: int, rows: list[dict], summary: dict) -> None:
    _set(user_id, stage="Importing comments", done=0, total=len(rows))
    roots = [c for c in rows if c.get("parent_id") is None]
    replies = [c for c in rows if c.get("parent_id") is not None]
    orig_to_new: dict[int, int] = {}

    def _existing_root(title_id: int, season: int | None, episode: int | None, text: str) -> int | None:
        return (
            db.query(Comment.id)
            .filter(
                Comment.user_id == user_id,
                Comment.title_id == title_id,
                Comment.season == season,
                Comment.episode == episode,
                Comment.text == text,
            )
            .scalar()
        )

    def _existing_reply(parent_id: int, text: str) -> int | None:
        return (
            db.query(Comment.id)
            .filter(Comment.user_id == user_id, Comment.parent_id == parent_id, Comment.text == text)
            .scalar()
        )

    done = 0
    for c in roots:
        done += 1
        if done % 100 == 0:
            _set(user_id, done=done)
        media_type_str, tmdb_id, title_name, text = c.get("media_type"), c.get("tmdb_id"), c.get("title"), c.get("text")
        if not media_type_str or not title_name or not text:
            summary["comments_skipped"] += 1
            continue
        title = find_or_create_title(db, MediaType(media_type_str), tmdb_id, title_name)
        existing = _existing_root(title.id, c.get("season"), c.get("episode"), text)
        if existing is not None:
            orig_to_new[c["id"]] = existing
            continue
        comment = Comment(
            user_id=user_id,
            title_id=title.id,
            season=c.get("season"),
            episode=c.get("episode"),
            text=text,
            created_at=_parse_iso(c.get("created_at")) or datetime.now(UTC),
        )
        db.add(comment)
        db.flush()
        orig_to_new[c["id"]] = comment.id
        summary["comments"] += 1

    pending = replies
    progress_made = True
    while pending and progress_made:
        progress_made = False
        still_pending = []
        for c in pending:
            done += 1
            if done % 100 == 0:
                _set(user_id, done=done)
            parent_new_id = orig_to_new.get(c["parent_id"])
            if parent_new_id is None:
                still_pending.append(c)
                continue
            text = c.get("text") or ""
            existing = _existing_reply(parent_new_id, text) if text else None
            if existing is not None:
                orig_to_new[c["id"]] = existing
            elif text:
                comment = Comment(
                    user_id=user_id,
                    title_id=None,
                    parent_id=parent_new_id,
                    season=None,
                    episode=None,
                    text=text,
                    created_at=_parse_iso(c.get("created_at")) or datetime.now(UTC),
                )
                db.add(comment)
                db.flush()
                orig_to_new[c["id"]] = comment.id
                summary["comments"] += 1
            progress_made = True
        pending = still_pending
    # Whatever's left replies to a comment outside this export (someone
    # else's) — can't be attached without misrepresenting it.
    summary["comments_skipped"] += len(pending)
    db.commit()


def _import_social(db: Session, user_id: int, social: dict, summary: dict) -> None:
    following = social.get("following") or []
    _set(user_id, stage="Restoring follows", done=0, total=len(following))
    for n, username in enumerate(following, 1):
        if n % 50 == 0:
            _set(user_id, done=n)
        target = db.query(User.id).filter(User.username == username).scalar()
        if target is None or target == user_id:
            summary["follows_skipped"] += 1
            continue
        exists = db.query(Follow.id).filter_by(follower_id=user_id, followed_id=target).scalar()
        if exists is not None:
            summary["follows_skipped"] += 1
            continue
        db.add(Follow(follower_id=user_id, followed_id=target))
        summary["follows"] += 1
    db.commit()


def run(user_id: int, archive_bytes: bytes) -> None:
    db: Session = SessionLocal()
    summary = {
        "library_entries": 0,
        "library_updated": 0,
        "library_skipped": 0,
        "episodes": 0,
        "comments": 0,
        "comments_skipped": 0,
        "follows": 0,
        "follows_skipped": 0,
    }
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with py7zr.SevenZipFile(io.BytesIO(archive_bytes), "r") as archive:
                archive.extractall(path=tmp_dir)
            tmp_path = Path(tmp_dir)
            profile = _read_json(tmp_path, "profile.json") or {}
            library = _read_json(tmp_path, "library.json") or []
            comments = _read_json(tmp_path, "comments.json") or []
            social = _read_json(tmp_path, "social.json") or {}

        _set(user_id, stage="Restoring profile settings", done=0, total=0)
        user = db.get(User, user_id)
        _apply_profile(user, profile)
        db.commit()

        _import_library(db, user_id, library, summary)
        _import_comments(db, user_id, comments, summary)
        _import_social(db, user_id, social, summary)

        _set(user_id, stage="Done", finished=True, summary=summary, error=None)
        _mark_job(user_id, finished=True, error=None, summary=summary)
        _log.info(
            "Renar-export import finished for user_id=%s: %s library entries, %s episodes, %s comments, %s follows",
            user_id,
            summary["library_entries"],
            summary["episodes"],
            summary["comments"],
            summary["follows"],
        )
    except Exception:
        db.rollback()
        _log.exception("Renar-export import failed for user_id=%s", user_id)
        generic_error = "Import failed due to an internal error. Please try again or contact support."
        _set(user_id, stage="Failed", finished=True, error=generic_error, summary=summary)
        _mark_job(user_id, finished=True, error=generic_error, summary=summary)
    finally:
        db.close()
