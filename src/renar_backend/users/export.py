#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/21 00:00:00.000000
Revised: 2026/07/27 08:29:08.786267

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
from datetime import UTC, datetime
from pathlib import Path

import py7zr
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Comment, Follow, LibraryEntry, Title, User
from ..social.comment_threads import resolve_root_scope

EXPORTS_ROOT = Path(settings.media_dir) / "exports"


def export_path(user_id: int) -> Path:
    return EXPORTS_ROOT / f"{user_id}.7z"


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
