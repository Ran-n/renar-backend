#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.263995
Revised: 2026/07/16 13:35:29.169154
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .models import MediaType, WatchStatus
from .premium import PALETTE, PROGRESS_STYLES, THEME_NAMES


def _password_fits_bcrypt(password: str) -> str:
    # bcrypt (5.x) raises on inputs longer than 72 bytes instead of
    # truncating; reject them here so the client gets a 422, not a 500
    if len(password.encode()) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return password


# ---------- auth ----------


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    invite_code: str | None = None

    _password_len = field_validator("password")(_password_fits_bcrypt)


class RegistrationStatus(BaseModel):
    """Public (unauthenticated) view of the two site_settings fields the
    signup screen needs to decide what to render. Deliberately narrow — the
    rest of site_settings (rate limits, ban thresholds) is anti-abuse tuning
    that must never be exposed to an unauthenticated caller."""

    registration_open: bool
    invite_only: bool


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    language: str
    avatar: str | None = None
    created_at: datetime
    # premium state for the owner's own client: stored colors are returned
    # even while lapsed (the style picker shows the saved choice); public
    # payloads instead go through premium.flair(), which blanks them.
    premium_until: datetime | None = None
    is_premium: bool = False
    verified: bool = False
    verification_requested: bool = False
    badge: str | None = None
    ring_color: str | None = None
    name_color: str | None = None
    background: str | None = None
    theme: str = "gruvbox"
    show_original_titles: bool = False
    home_hero_enabled: bool = True
    home_on_launch: bool = True
    home_progress_style: str = "rings"
    home_season_color: str | None = None
    home_series_color: str | None = None
    has_seen_welcome: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    _password_len = field_validator("new_password")(_password_fits_bcrypt)


class PremiumStyleUpdate(BaseModel):
    """Both colors optional; explicit null clears one. Values must come from
    the server palette so nothing unreadable can be stored."""

    ring_color: str | None = None
    name_color: str | None = None
    home_season_color: str | None = None
    home_series_color: str | None = None

    @field_validator("ring_color", "name_color", "home_season_color", "home_series_color")
    @classmethod
    def _in_palette(cls, value: str | None) -> str | None:
        if value is not None and value not in PALETTE:
            raise ValueError("Color must be one of the palette options")
        return value


class CustomPosterSet(BaseModel):
    """Exactly one source: an uploaded image, or one of TMDB's alternate
    posters (downloaded server-side into the image store)."""

    image_b64: str | None = Field(default=None, max_length=8_000_000)
    tmdb_url: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> CustomPosterSet:
        if (self.image_b64 is None) == (self.tmdb_url is None):
            raise ValueError("Provide exactly one of image_b64 or tmdb_url")
        if self.tmdb_url is not None and not self.tmdb_url.startswith("https://image.tmdb.org/t/p/"):
            raise ValueError("tmdb_url must be a TMDB image URL")
        return self


class CropBox(BaseModel):
    """Fractional (0..1) region of an uploaded image to keep, chosen by the
    user panning it in the frontend's position picker before thumbnailing."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class ProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: EmailStr | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10, pattern=r"^[a-z]{2,10}$")
    avatar_b64: str | None = Field(default=None, max_length=8_000_000)  # raw upload, re-encoded server-side
    background_b64: str | None = Field(default=None, max_length=8_000_000)  # raw upload, re-encoded server-side
    avatar_crop: CropBox | None = None
    background_crop: CropBox | None = None
    theme: str | None = None
    show_original_titles: bool | None = None
    home_hero_enabled: bool | None = None
    home_on_launch: bool | None = None
    home_progress_style: str | None = None
    has_seen_welcome: bool | None = None

    @field_validator("theme")
    @classmethod
    def _valid_theme(cls, value: str | None) -> str | None:
        if value is not None and value not in THEME_NAMES:
            raise ValueError("Unknown theme")
        return value

    @field_validator("home_progress_style")
    @classmethod
    def _valid_progress_style(cls, value: str | None) -> str | None:
        if value is not None and value not in PROGRESS_STYLES:
            raise ValueError("Unknown progress style")
        return value


# ---------- media ----------


class TitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media_type: MediaType
    tmdb_id: int | None = None
    title: str
    year: int | None = None
    poster_url: str | None = None
    runtime_minutes: int | None = None
    total_episodes: int | None = None
    total_seasons: int | None = None
    genres: list[str] = []
    author: str | None = None
    page_count: int | None = None
    overview: str | None = None
    tagline: str | None = None
    show_status: str | None = None


class LibraryEntryCreate(BaseModel):
    # title-identifying fields: used once, to find-or-create the shared Title
    media_type: MediaType
    title: str = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1880, le=2100)
    poster_url: str | None = Field(default=None, max_length=500)
    tmdb_id: int | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    genres: list[str] | None = Field(default=None, max_length=20)
    author: str | None = Field(default=None, max_length=300)
    page_count: int | None = Field(default=None, ge=0)
    # user-owned fields
    url: str | None = Field(default=None, max_length=500)
    status: WatchStatus = WatchStatus.want_to_watch
    rating: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)
    episodes_watched: int = Field(default=0, ge=0)
    is_favorite: bool = False


class LibraryEntryUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    status: WatchStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)
    episodes_watched: int | None = Field(default=None, ge=0)
    is_favorite: bool | None = None


class LibraryEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    media_type: MediaType
    title: str
    display_title: str
    original_title: str | None = None
    year: int | None = None
    poster_url: str | None = None  # custom override when set + owner premium
    custom_poster_url: str | None = None  # the stored override itself (picker UI)
    backdrop_url: str | None = None  # custom override when set + owner premium
    custom_backdrop_url: str | None = None  # the stored override itself (picker UI)
    tmdb_id: int | None = None
    runtime_minutes: int | None = None
    total_episodes: int | None = None
    total_seasons: int | None = None
    genres: list[str] = []
    author: str | None = None
    page_count: int | None = None
    overview: str | None = None
    tagline: str | None = None
    show_status: str | None = None
    url: str | None = None
    status: WatchStatus
    rating: int | None = None
    notes: str | None = None
    current_season: int | None = None
    current_episode: int | None = None
    current_episode_name: str | None = None
    current_season_total_episodes: int | None = None
    next_season: int | None = None
    next_episode: int | None = None
    next_episode_name: str | None = None
    next_season_total_episodes: int | None = None
    episodes_watched: int
    is_favorite: bool
    created_at: datetime
    updated_at: datetime


# ---------- episodes ----------


class EpisodeSet(BaseModel):
    watched: bool = True
    rating: int | None = Field(default=None, ge=1, le=10)


class EpisodeBulk(BaseModel):
    season: int = Field(ge=0)
    episodes: list[int] = Field(min_length=1, max_length=500)
    watched: bool = True


# ---------- comments ----------


class CommentCreate(BaseModel):
    media_type: MediaType
    tmdb_id: int | None = None
    title: str | None = Field(default=None, max_length=300)
    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=0)
    parent_id: int | None = Field(default=None, ge=1)  # reply target; must be in the same thread
    text: str = Field(min_length=1, max_length=2000)


class CommentReportCreate(BaseModel):
    reason: str = Field(default="", max_length=500)


# ---------- rewatch ----------


class RewatchCreate(BaseModel):
    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=0)
