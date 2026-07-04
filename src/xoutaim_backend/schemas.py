from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import MediaType, WatchStatus


# ---------- auth ----------

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    avatar: str | None = None
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: EmailStr | None = None
    avatar_b64: str | None = Field(default=None, max_length=8_000_000)  # raw upload, re-encoded server-side


# ---------- media ----------

class MediaItemBase(BaseModel):
    media_type: MediaType
    title: str = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1880, le=2100)
    url: str | None = Field(default=None, max_length=500)
    poster_url: str | None = Field(default=None, max_length=500)
    status: WatchStatus = WatchStatus.want_to_watch
    rating: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    tmdb_id: int | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    genres: str | None = Field(default=None, max_length=300)
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)
    episodes_watched: int = Field(default=0, ge=0)
    is_favorite: bool = False
    author: str | None = Field(default=None, max_length=300)
    page_count: int | None = Field(default=None, ge=0)


class MediaItemCreate(MediaItemBase):
    pass


class MediaItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1880, le=2100)
    url: str | None = Field(default=None, max_length=500)
    poster_url: str | None = Field(default=None, max_length=500)
    status: WatchStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    tmdb_id: int | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    genres: str | None = Field(default=None, max_length=300)
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)
    episodes_watched: int | None = Field(default=None, ge=0)
    is_favorite: bool | None = None
    author: str | None = Field(default=None, max_length=300)
    page_count: int | None = Field(default=None, ge=0)


class MediaItemOut(MediaItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
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
    text: str = Field(min_length=1, max_length=2000)
