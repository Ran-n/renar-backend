#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/08/05 21:48:04.042386

Builds a user's personal-data export (GDPR Art. 20 — the right to data
portability): every account, library and social fact Renar stores about
them, as one JSON file per data category (profile/library/comments/social)
inside a 7z archive for download — mirrors how Google Takeout and similar
exports split by category rather than shipping one giant blob. Runs on
export_queue's worker rather than inline in a request (see that module's
docstring for why a queue exists at all).

Deliberately not reusing the *_out Pydantic schemas: those shape API
responses for the frontend (expand params, computed URLs, etc.) and would
silently drop or reshape fields as that surface evolves. An export's job is
to be complete and stable, not to track the API — so it reads the ORM rows
directly and lists every field explicitly.
"""

import contextlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import py7zr
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Comment, ExportJob, Follow, LibraryEntry, Title, User
from ..social.comment_threads import resolve_root_scope

EXPORTS_ROOT = Path(settings.media_dir) / "exports"

# A ready export both blocks a fresh request (cooldown) and stops being
# offered for download (expiry) after the same window — with a matching
# cooldown and expiry, the moment re-requesting is allowed again is exactly
# the moment the old one disappears, so there's no in-between state where a
# stale-but-still-ready export and a fresh request could coexist. Premium
# gets a shorter window (once a day) as a compute-priority perk, same
# reasoning as export_queue's dequeue-order priority — the GDPR right
# itself (that an export exists at all, ever) stays identical for everyone;
# only how often a *fresh* one can be rebuilt differs.
EXPORT_EXPIRY_DAYS_FREE = 7
EXPORT_EXPIRY_DAYS_PREMIUM = 1


def export_path(user_id: int) -> Path:
    return EXPORTS_ROOT / f"{user_id}.7z"


def export_expiry_days(is_premium: bool) -> int:
    return EXPORT_EXPIRY_DAYS_PREMIUM if is_premium else EXPORT_EXPIRY_DAYS_FREE


def is_export_expired(completed_at: datetime | None, is_premium: bool = False) -> bool:
    """True once `completed_at` is missing or older than this account's
    tier-specific expiry window. Missing (None) covers a job that's
    queued/processing/failed — never "ready", so always treated as
    expired/absent rather than eternally valid."""
    if completed_at is None:
        return True
    return datetime.now(UTC) - completed_at >= timedelta(days=export_expiry_days(is_premium))


def export_is_ready(job: ExportJob | None, is_premium: bool) -> bool:
    """The single source of truth for "ready" that routers/export.py's
    status, download, and cooldown checks all share — a DB row saying
    finished/unexpired is not enough on its own: the row can outlive its
    file (deleted out of band, or written by an older build under a
    different name/format — this is a real bug that shipped once already,
    where export_status trusted the row alone and reported "ready" for a
    row whose file was a leftover `.zip` from before the format became
    `.7z`, while download_export's separate is_file() check correctly
    404'd the same request). Checking the file here too means both
    endpoints can never disagree again.
    """
    if job is None or not job.finished or job.error:
        return False
    if is_export_expired(job.completed_at, is_premium):
        return False
    return export_path(job.user_id).is_file()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _library_entry(item: LibraryEntry) -> dict:
    return {
        "title": item.title,
        "original_title": item.original_title,
        "year": item.year,
        "media_type": item.media_type.value,
        "tmdb_id": item.tmdb_id,
        "status": item.status.value,
        "rating": item.rating,
        "notes": item.notes,
        "is_favorite": item.is_favorite,
        "current_season": item.current_season,
        "current_episode": item.current_episode,
        "episodes_watched": item.episodes_watched,
        "added_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "episode_watches": [
            {
                "season": w.season,
                "episode": w.episode,
                "rating": w.rating,
                "watched_at": _iso(w.watched_at),
            }
            for w in item.episode_watches
        ],
    }


def _comment(db: Session, comment: Comment) -> dict:
    title_id, season, episode = resolve_root_scope(db, comment)
    title = db.get(Title, title_id) if title_id else None
    return {
        # `id`/`parent_id` are this instance's own row ids, not portable
        # identifiers — kept so build_import can restitch reply chains: a
        # reply's parent is either another comment in this same export (self
        # -reply, matched via these ids) or, when re-importing into the very
        # database this came from (the common "restore my account" case),
        # still resolvable as a live Comment.id belonging to someone else.
        # Meaningless noise for any other reader; never used as an API id.
        "id": comment.id,
        "parent_id": comment.parent_id,
        "text": comment.text,
        "title": title.title if title else None,
        "tmdb_id": title.tmdb_id if title else None,
        "media_type": title.media_type.value if title else None,
        "season": season,
        "episode": episode,
        "is_reply": comment.parent_id is not None,
        "created_at": _iso(comment.created_at),
    }


def build_export(user: User, db: Session) -> bytes:
    """Everything Renar stores about this account, as one JSON file per
    category inside a 7z archive. Only ever reads `user`'s own rows —
    nothing here can leak another account's data."""
    profile = {
        "username": user.username,
        "email": user.email,
        "language": user.language,
        "show_original_titles": user.show_original_titles,
        "theme": user.theme,
        "home_hero_enabled": user.home_hero_enabled,
        "home_on_launch": user.home_on_launch,
        "home_progress_style": user.home_progress_style,
        "home_season_color": user.home_season_color,
        "home_series_color": user.home_series_color,
        "countdown_colors": user.countdown_colors,
        "status_colors": user.status_colors,
        "episode_label_style": user.episode_label_style,
        "ring_color": user.ring_color,
        "name_color": user.name_color,
        "is_premium": user.is_premium,
        "verified": user.verified,
        "created_at": _iso(user.created_at),
        "last_active_at": _iso(user.last_active_at),
    }

    # Eager-load episode_watches in one extra query (selectinload) instead of
    # issuing one query per entry (N+1). Behaviorally identical — same rows,
    # same order as the lazy-load path but 2 queries total regardless of
    # library size.
    entries = (
        db.query(LibraryEntry)
        .options(selectinload(LibraryEntry.episode_watches))
        .filter(LibraryEntry.user_id == user.id)
        .all()
    )
    library = [_library_entry(item) for item in entries]

    comments = [
        _comment(db, c) for c in db.query(Comment).filter(Comment.user_id == user.id).order_by(Comment.created_at).all()
    ]

    following = [
        username
        for (username,) in db.query(User.username)
        .join(Follow, Follow.followed_id == User.id)
        .filter(Follow.follower_id == user.id)
        .all()
    ]
    followers = [
        username
        for (username,) in db.query(User.username)
        .join(Follow, Follow.follower_id == User.id)
        .filter(Follow.followed_id == user.id)
        .all()
    ]

    profile["exported_at"] = _iso(datetime.now(UTC))
    social = {"following": following, "followers": followers}

    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as zf:
        zf.writestr(json.dumps(profile, indent=2, ensure_ascii=False), "profile.json")
        zf.writestr(json.dumps(library, indent=2, ensure_ascii=False), "library.json")
        zf.writestr(json.dumps(comments, indent=2, ensure_ascii=False), "comments.json")
        zf.writestr(json.dumps(social, indent=2, ensure_ascii=False), "social.json")
    return buf.getvalue()


def write_export(user_id: int, content: bytes) -> None:
    path = export_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def delete_export(user_id: int) -> None:
    with contextlib.suppress(FileNotFoundError):
        export_path(user_id).unlink()


def purge_expired_exports(db: Session) -> int:
    """Delete the file and ExportJob row for every ready export past its
    account's expiry window (shorter for premium — see
    EXPORT_EXPIRY_DAYS_PREMIUM), so a forgotten download doesn't sit on disk
    indefinitely — nothing else ever calls delete_export (see that
    function's own history: it existed but was unreachable before this).
    Returns the number of exports purged. Periodic-task entry point is
    social/notifier.py's export cleanup loop; see task_runs.py for the
    admin-configurable schedule/toggle.

    Also drops each user's export_queue in-memory cache entry: that cache
    never naturally clears within a running process (see
    routers/export.py's export_status, which checks it first), so leaving
    a stale "ready" entry there would keep answering ready even after the
    file and row are both gone.
    """
    from . import export_queue  # local import: export_queue already imports from this module

    # The SQL filter only narrows to the widest possible window (premium's
    # shorter one) — an account's actual is_premium (a Python property
    # derived from premium_until, not a plain column) decides the real
    # cutoff per row below, since a query can't push a per-row-varying
    # interval into a single WHERE clause.
    cutoff = datetime.now(UTC) - timedelta(days=EXPORT_EXPIRY_DAYS_PREMIUM)
    candidates = (
        db.query(ExportJob, User)
        .join(User, User.id == ExportJob.user_id)
        .filter(ExportJob.finished.is_(True), ExportJob.error.is_(None), ExportJob.completed_at < cutoff)
        .all()
    )
    purged = 0
    for job, user in candidates:
        if not is_export_expired(job.completed_at, user.is_premium):
            continue
        delete_export(job.user_id)
        export_queue.forget(job.user_id)
        db.delete(job)
        purged += 1
    db.commit()
    return purged
