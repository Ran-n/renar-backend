import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaType(str, enum.Enum):
    film = "film"
    tv_show = "tv_show"
    youtube = "youtube"


class WatchStatus(str, enum.Enum):
    want_to_watch = "want_to_watch"
    watching = "watching"
    completed = "completed"
    dropped = "dropped"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)  # base64 jpeg, 256px
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media_items: Mapped[list["MediaItem"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("user_id", "media_type", "title", name="uq_user_media_title"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), index=True)
    title: Mapped[str] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # youtube link etc.
    poster_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[WatchStatus] = mapped_column(
        Enum(WatchStatus), default=WatchStatus.want_to_watch
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TMDB metadata (used for stats)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # film total / tv per-episode
    total_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genres: Mapped[str | None] = mapped_column(String(300), nullable=True)  # comma-separated
    # TV-show progress
    current_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episodes_watched: Mapped[int] = mapped_column(Integer, default=0)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner: Mapped[User] = relationship(back_populates="media_items")
    episode_watches: Mapped[list["EpisodeWatch"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class EpisodeWatch(Base):
    """One row = this episode of this (user-owned) show was watched."""

    __tablename__ = "episode_watches"
    __table_args__ = (
        UniqueConstraint("media_item_id", "season", "episode", name="uq_item_episode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[MediaItem] = relationship(back_populates="episode_watches")


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "followed_id", name="uq_follow_pair"),
    )

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
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()
    likes: Mapped[list["CommentLike"]] = relationship(
        back_populates="comment", cascade="all, delete-orphan"
    )


class Notification(Base):
    """In-app notification, e.g. a new episode of a tracked show aired."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "media_item_id", "season", "episode", "kind",
            name="uq_notification_event",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_items.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), default="new_episode")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(String(500))
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommentLike(Base):
    __tablename__ = "comment_likes"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_like"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    comment: Mapped[Comment] = relationship(back_populates="likes")
