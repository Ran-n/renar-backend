import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    owner: Mapped[User] = relationship(back_populates="media_items")
