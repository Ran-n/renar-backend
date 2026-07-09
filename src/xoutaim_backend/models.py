#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.419974
Revised: 2026/07/09 13:01:54.554117
"""

import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    column,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_title_key(title: str) -> str:
    """Fallback identity for a title with no tmdb_id: used by both Title.title_key
    and Comment.title_key so a manually-entered title and its comment thread
    always agree on which "global" title they belong to.
    """
    return title.strip().casefold()


class MediaType(enum.StrEnum):
    film = "film"
    tv_show = "tv_show"
    youtube = "youtube"
    book = "book"


class WatchStatus(enum.StrEnum):
    want_to_watch = "want_to_watch"
    watching = "watching"
    paused = "paused"
    completed = "completed"
    dropped = "dropped"


class Image(Base):
    """Content-addressed stored file: one row per unique blake3 hash.

    The actual bytes live on disk as <images_dir>/<hash>.jpg; multiple users
    with the same picture share one row and one file.
    """

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BannedIP(Base):
    """Permanently banned client IP, persisted so bans survive restarts.

    Earned either instantly (honeypot hits) or by accumulating enough
    strikes (see Strike below). Rows are removable from the admin panel
    (/admin/bans).
    """

    __tablename__ = "banned_ips"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45), unique=True, index=True)  # 45 chars fits IPv6
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Strike(Base):
    """Persisted repeat-offender counter, one row per offending IP.

    Backs temporary bans (rate-limit floods, route probing) so the
    escalating ban duration and offense count survive a restart instead of
    resetting — one row per IP, not one row per offense, so this can never
    grow unbounded. Once `count` reaches settings.strike_ban_threshold the
    IP is promoted to a permanent ban (BannedIP).
    """

    __tablename__ = "strikes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45), unique=True, index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(String(255), default="")
    banned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_offense_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(10), default="en")
    avatar_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), nullable=True)
    banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ban_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Usage statistics, surfaced in the admin panel.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    login_count: Mapped[int] = mapped_column(Integer, default=0)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)

    avatar_image: Mapped[Image | None] = relationship()
    library_entries: Mapped[list[LibraryEntry]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def avatar(self) -> str | None:
        """URL path the frontend can fetch, e.g. /images/<hash>."""
        return f"/images/{self.avatar_image.hash}" if self.avatar_image else None


class LoginEvent(Base):
    """One row per successful login, kept so the admin panel can chart
    connections-per-day. Everything else the panel graphs (comments, library
    adds, watches) is derived from those tables' own timestamps; logins are the
    only activity with no other timestamped record, so they get this log.

    Append-only and low-volume (one row per login, not per request).
    """

    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class EndpointStat(Base):
    """Aggregated request counter: one row per (method, route template, user).

    Populated by UsageTrackingMiddleware. Keyed by the route *template*
    (`/media/{item_id}`, never `/media/42`) so the row count is bounded by the
    number of endpoints, not by traffic — one upserted row, never one row per
    request. `user_id` is null for anonymous/unauthenticated calls. Powers the
    admin usage dashboard's "requests by endpoint" graph and its per-endpoint
    (which users called it) drill-down.
    """

    __tablename__ = "endpoint_stats"
    __table_args__ = (UniqueConstraint("method", "path", "user_id", name="uq_endpoint_stat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RequestDay(Base):
    """Per-user, per-day request counter — the time-series behind the admin
    panel's "requests per day" chart. One upserted row per (user, calendar day),
    so it's bounded by users × days, never by traffic. Only authenticated
    requests are counted (anonymous traffic isn't a user's activity);
    EndpointStat holds the per-endpoint totals, this holds the per-day totals.
    """

    __tablename__ = "request_days"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_request_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class Title(Base):
    """A movie/show/book/video, shared across every user who tracks it.

    Identity is the tmdb_id when we have one; manually-entered items (or ones
    without a TMDB/catalog match) fall back to a normalized title_key. Either
    way, this row is the single source of truth for title/year/poster/genres/
    etc. — user-specific state lives on LibraryEntry instead.
    """

    __tablename__ = "titles"
    __table_args__ = (
        Index(
            "uq_title_tmdb",
            "media_type",
            "tmdb_id",
            unique=True,
            sqlite_where=column("tmdb_id").isnot(None),
            postgresql_where=column("tmdb_id").isnot(None),
        ),
        Index(
            "uq_title_key",
            "media_type",
            "title_key",
            unique=True,
            sqlite_where=column("tmdb_id").is_(None),
            postgresql_where=column("tmdb_id").is_(None),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), index=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # film total / tv per-episode
    total_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[str | None] = mapped_column(String(300), nullable=True)  # comma-separated
    author: Mapped[str | None] = mapped_column(String(300), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LibraryEntry(Base):
    """One user's personal tracking of a Title: status, rating, notes,
    progress, favorite. Title/year/poster/etc. are NOT here — they live on
    the shared Title row and are immutable through this entry.
    """

    __tablename__ = "media_items"
    __table_args__ = (UniqueConstraint("user_id", "title_id", name="uq_user_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id"), index=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # personal link: youtube link etc.
    status: Mapped[WatchStatus] = mapped_column(Enum(WatchStatus), default=WatchStatus.want_to_watch)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TV-show progress
    current_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episodes_watched: Mapped[int] = mapped_column(Integer, default=0)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="library_entries")
    title_ref: Mapped[Title] = relationship()
    episode_watches: Mapped[list[EpisodeWatch]] = relationship(back_populates="item", cascade="all, delete-orphan")
    watch_events: Mapped[list[WatchEvent]] = relationship(cascade="all, delete-orphan")
    notifications: Mapped[list[Notification]] = relationship(cascade="all, delete-orphan")

    # ---- convenience passthroughs so callers can keep reading item.title, item.year, etc. ----
    @property
    def media_type(self) -> MediaType:
        return self.title_ref.media_type

    @property
    def title(self) -> str:
        return self.title_ref.title

    @property
    def year(self) -> int | None:
        return self.title_ref.year

    @property
    def poster_url(self) -> str | None:
        return self.title_ref.poster_url

    @property
    def tmdb_id(self) -> int | None:
        return self.title_ref.tmdb_id

    @property
    def runtime_minutes(self) -> int | None:
        return self.title_ref.runtime_minutes

    @property
    def total_episodes(self) -> int | None:
        return self.title_ref.total_episodes

    @property
    def genres(self) -> str | None:
        return self.title_ref.genres

    @property
    def author(self) -> str | None:
        return self.title_ref.author

    @property
    def page_count(self) -> int | None:
        return self.title_ref.page_count


class EpisodeWatch(Base):
    """One row = this episode of this (user-owned) show was watched."""

    __tablename__ = "episode_watches"
    __table_args__ = (UniqueConstraint("media_item_id", "season", "episode", name="uq_item_episode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[LibraryEntry] = relationship(back_populates="episode_watches")


class WatchEvent(Base):
    """One row = one watch of this item (or episode), including rewatches.

    Unlike EpisodeWatch (at most one row per episode = "currently watched"),
    this is an append-only log: rewatching an episode or a whole film/book
    just adds another row here. season/episode are both null for a
    whole-item (film/book) watch event.
    """

    __tablename__ = "watch_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("follower_id", "followed_id", name="uq_follow_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    followed_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    """Comments attach to a global title (TMDB id, or title text as fallback)."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType))
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title_key: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()
    likes: Mapped[list[CommentLike]] = relationship(back_populates="comment", cascade="all, delete-orphan")


class Notification(Base):
    """In-app notification, e.g. a new episode of a tracked show aired."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "media_item_id",
            "season",
            "episode",
            "kind",
            name="uq_notification_event",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[int | None] = mapped_column(ForeignKey("media_items.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), default="new_episode")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(String(500))
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommentLike(Base):
    __tablename__ = "comment_likes"
    __table_args__ = (UniqueConstraint("comment_id", "user_id", name="uq_comment_like"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    comment: Mapped[Comment] = relationship(back_populates="likes")
