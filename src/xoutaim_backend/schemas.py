#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.263995
Revised: 2026/07/07 13:25:16.263995
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import MediaType, WatchStatus


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

    _password_len = field_validator("password")(_password_fits_bcrypt)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    language: str
    avatar: str | None = None
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    _password_len = field_validator("new_password")(_password_fits_bcrypt)


class ProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: EmailStr | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10, pattern=r"^[a-z]{2,10}$")
    avatar_b64: str | None = Field(default=None, max_length=8_000_000)  # raw upload, re-encoded server-side


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
    genres: str | None = None
    author: str | None = None
    page_count: int | None = None


class LibraryEntryCreate(BaseModel):
    # title-identifying fields: used once, to find-or-create the shared Title
    media_type: MediaType
    title: str = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1880, le=2100)
    poster_url: str | None = Field(default=None, max_length=500)
    tmdb_id: int | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    genres: str | None = Field(default=None, max_length=300)
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
    year: int | None = None
    poster_url: str | None = None
    tmdb_id: int | None = None
    runtime_minutes: int | None = None
    total_episodes: int | None = None
    genres: str | None = None
    author: str | None = None
    page_count: int | None = None
    url: str | None = None
    status: WatchStatus
    rating: int | None = None
    notes: str | None = None
    current_season: int | None = None
    current_episode: int | None = None
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
    text: str = Field(min_length=1, max_length=2000)


# ---------- rewatch ----------


class RewatchCreate(BaseModel):
    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=0)
