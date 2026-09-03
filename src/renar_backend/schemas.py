#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:16.263995
Revised: 2026/09/03 14:06:02.021190
"""

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .models import COUNTDOWN_TIERS, MediaType, WatchStatus
from .users.premium import EPISODE_LABEL_STYLES, PROGRESS_STYLES, THEME_NAMES

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# bcrypt (5.x) raises on inputs longer than 72 bytes instead of truncating
# silently.  This constant is the single authoritative cap used by the schema
# validator below and by the admin reset-password endpoint.
BCRYPT_MAX_PASSWORD_BYTES = 72

# Postgres INTEGER (int4) upper bound.  A Pydantic int field with no `le=`
# happily accepts values Postgres can't store (e.g. 2**31), which then reach
# the DB driver as an unhandled DataError/NumericValueOutOfRange (500) rather
# than a clean 422 — fuzz-discovered on RewatchCreate.season/episode.
PG_INT32_MAX = 2147483647


def _password_fits_bcrypt(password: str) -> str:
    # Reject oversized passwords here so the client gets a 422, not a 500
    if len(password.encode()) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("Password must be at most 72 bytes")
    return password


def _no_nul_bytes(value: str) -> str:
    # Postgres text columns reject NUL (0x00) outright — a value containing
    # one reaches the DB driver as an unhandled DataError (500) rather than
    # a clean 422.  This validator is the single authoritative guard; it is
    # wired into every free-text field that is written to or queried against
    # a Postgres text column, via the SafeStr annotated type below.
    if "\x00" in value:
        raise ValueError("must not contain NUL bytes")
    return value


# Annotated type for any free-text field that reaches Postgres.  Pydantic
# v2 runs AfterValidator only when the value is a str (not None), so
# `SafeStr | None` is safe — None values skip the check correctly.
SafeStr = Annotated[str, AfterValidator(_no_nul_bytes)]


# ---------- auth ----------


class UserCreate(BaseModel):
    username: SafeStr = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    invite_code: str | None = None
    # Empty when Turnstile isn't configured server-side (see
    # users/turnstile.py::verify_turnstile) — not required in that case.
    turnstile_token: str = ""

    _password_len = field_validator("password")(_password_fits_bcrypt)


class RegistrationStatus(BaseModel):
    """Public (unauthenticated) view of the site_settings/config fields the
    signup screen needs to decide what to render. Deliberately narrow — the
    rest of site_settings (rate limits, ban thresholds) is anti-abuse tuning
    that must never be exposed to an unauthenticated caller."""

    registration_open: bool
    invite_only: bool
    # Turnstile site keys are meant to be public/embedded client-side —
    # unlike turnstile_secret_key, this is safe to hand back here. None
    # means Turnstile isn't configured and the register screen shouldn't
    # render the widget at all.
    turnstile_site_key: str | None = None
    # When False, register() returns an already-confirmed user with no code
    # sent (see SiteSettings.email_confirmation_enabled) — the register
    # screen needs this up front to know whether to route through
    # /confirm-email at all after submitting, or log straight in.
    email_confirmation_enabled: bool = True


class TurnstileSession(BaseModel):
    """One-time widget session — see users/turnstile.py's module docstring
    for why the widget page lives on the backend rather than the frontend."""

    session_id: str
    site_key: str


class TurnstileTokenStatus(BaseModel):
    """Polled by the register screen after configuring the widget. None
    until the widget's own callback (users/turnstile.py's widget_html JS)
    reports a resolved token."""

    token: str | None = None


class ConfirmEmailRequest(BaseModel):
    """Credential-based, not bearer-token-based — see routers/auth.py's
    /auth/confirm-email docstring for why: once the login grace period
    (auth.py's `login`) expires, an unconfirmed user can no longer obtain a
    token at all, so a token-gated confirm endpoint would lock them out
    permanently."""

    username: str
    password: str
    code: str = Field(min_length=6, max_length=6)


class ResendConfirmationRequest(BaseModel):
    username: str
    password: str


class ConfirmEmailSessionRequest(BaseModel):
    """Bearer-token variant of ConfirmEmailRequest, for a user who's already
    holding a valid token (still inside the login grace period) — see
    routers/auth.py's confirm_email_session docstring for why this doesn't
    weaken the credential-based endpoint's guarantees."""

    code: str = Field(min_length=6, max_length=6)


class ChangeUnconfirmedEmailRequest(BaseModel):
    """Fixing a typo'd address before the account has ever been confirmed —
    see routers/auth.py's change_unconfirmed_email docstring for why this is
    a direct rewrite (no old-address approval step), unlike update_profile's
    two-step change for an already-confirmed account."""

    username: str
    password: str
    email: EmailStr


class ChangeUnconfirmedEmailSessionRequest(BaseModel):
    """Bearer-token variant of ChangeUnconfirmedEmailRequest, for a user
    who's already holding a valid token (still inside the login grace
    period) — see routers/auth.py's change_unconfirmed_email_session
    docstring for why this doesn't weaken the credential-based endpoint's
    guarantees."""

    email: EmailStr


class ChangeUnconfirmedEmailResult(BaseModel):
    email: str


class ConfirmEmailResult(BaseModel):
    # "confirmed": the code's purpose is done (register, or the new
    # address's own change_confirm code) — the frontend can log in normally.
    # "change_pending_new_email": the old address's change_authorize code was
    # accepted; a fresh code was just sent to the new (pending) address and
    # confirming *that* one is what finishes the change.
    status: str


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
    email_confirmed: bool = False
    # True when email_confirmed was set without the real code round trip
    # (registered while confirmation wasn't required) — lets the client offer
    # a voluntary, non-blocking "verify your email" action (see
    # routers/auth.py's _resend_confirmation / _confirm_email_code).
    email_confirmation_bypassed: bool = False
    # Days left before an unconfirmed account is blocked at login — None once
    # confirmed (nothing to count down) or when confirmation is off entirely.
    # Computed in routers/auth.py's `me()`, not a real column; lets the
    # frontend show the actual remaining count instead of a hardcoded mirror
    # of the grace-period constant (see renar-frontend's confirm_email_view.py).
    grace_days_remaining: int | None = None
    # Set while a self-service deletion is pending (see routers/auth.py's
    # DELETE /auth/me and POST /auth/me/cancel-deletion) — None means no
    # deletion is scheduled. Lets the frontend show a grace-period banner
    # with a cancel action.
    deletion_requested_at: datetime | None = None
    # Days left before the account_purge periodic task permanently deletes
    # the account — None while no deletion is pending. Computed in
    # routers/auth.py's `me()`, same pattern as grace_days_remaining above.
    deletion_grace_days_remaining: int | None = None
    verified: bool = False
    verification_requested: bool = False
    # Whether this user is on the reviews whitelist (see models.py's
    # ReviewWhitelist) — computed in routers/auth.py's `me()`, lets the
    # frontend gate the Reviews composer without a separate round trip.
    can_review: bool = False
    # Mirrors can_review — same ReviewWhitelist check, under the key
    # premium.flair()'s public payloads (comments/reviews/profiles/feed) use
    # for the same fact, so the frontend's badge rendering can read one key
    # regardless of whether it's looking at its own profile or someone
    # else's.
    is_reviewer: bool = False
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
    countdown_colors: dict[str, str] | None = None
    status_colors: dict[str, str] | None = None
    episode_label_style: str = "cross"
    has_seen_welcome: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    _password_len = field_validator("new_password")(_password_fits_bcrypt)


class PremiumStyleUpdate(BaseModel):
    """All colors optional; explicit null clears one. Any well-formed hex
    color is accepted — GET /premium/palette is just a suggested-swatch
    list, not an enforced allowlist."""

    ring_color: str | None = None
    name_color: str | None = None
    home_season_color: str | None = None
    home_series_color: str | None = None
    # explicit null clears all overrides; a dict clears/sets one key at a
    # time via {"tier": "#hex" | None} — omitted keys keep their value
    countdown_colors: dict[str, str | None] | None = None
    # explicit null clears all overrides; a dict clears/sets one key at a
    # time via {"status": "#hex" | None} — omitted keys keep their value
    status_colors: dict[str, str | None] | None = None

    @field_validator("ring_color", "name_color", "home_season_color", "home_series_color")
    @classmethod
    def _valid_hex(cls, value: str | None) -> str | None:
        if value is not None and not _HEX_COLOR_RE.fullmatch(value):
            raise ValueError("Color must be a hex value like #rrggbb")
        return value

    @field_validator("countdown_colors")
    @classmethod
    def _valid_countdown_colors(cls, value: dict[str, str | None] | None) -> dict[str, str | None] | None:
        if value is None:
            return value
        for tier, color in value.items():
            if tier not in COUNTDOWN_TIERS:
                raise ValueError(f"Unknown countdown tier: {tier}")
            if color is not None and not _HEX_COLOR_RE.fullmatch(color):
                raise ValueError("Color must be a hex value like #rrggbb")
        return value

    @field_validator("status_colors")
    @classmethod
    def _valid_status_colors(cls, value: dict[str, str | None] | None) -> dict[str, str | None] | None:
        if value is None:
            return value
        for status, color in value.items():
            if status not in WatchStatus.__members__:
                raise ValueError(f"Unknown status: {status}")
            if color is not None and not _HEX_COLOR_RE.fullmatch(color):
                raise ValueError("Color must be a hex value like #rrggbb")
        return value


class CropBox(BaseModel):
    """Fractional (0..1) region of an uploaded image to keep, chosen by the
    user panning it in the frontend's position picker before thumbnailing."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


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


class ProfileUpdate(BaseModel):
    username: SafeStr | None = Field(default=None, min_length=3, max_length=50)
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
    episode_label_style: str | None = None
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

    @field_validator("episode_label_style")
    @classmethod
    def _valid_episode_label_style(cls, value: str | None) -> str | None:
        if value is not None and value not in EPISODE_LABEL_STYLES:
            raise ValueError("Unknown episode label style")
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
    overview: str | None = None
    tagline: str | None = None
    show_status: str | None = None
    release_date: date | None = None


class LibraryEntryCreate(BaseModel):
    # title-identifying fields: used once, to find-or-create the shared Title
    media_type: MediaType
    title: SafeStr = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1880, le=2100)
    poster_url: str | None = Field(default=None, max_length=500)
    tmdb_id: int | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    total_episodes: int | None = Field(default=None, ge=0)
    genres: list[str] | None = Field(default=None, max_length=20)
    # user-owned fields
    url: SafeStr | None = Field(default=None, max_length=500)
    status: WatchStatus = WatchStatus.want_to_watch
    rating: int | None = Field(default=None, ge=1, le=100)
    notes: SafeStr | None = None
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)
    episodes_watched: int = Field(default=0, ge=0)
    is_favorite: bool = False


class LibraryEntryUpdate(BaseModel):
    # relink an unmatched entry (Title.tmdb_id is None) to a TMDB match the
    # user picked in the "Link to catalog" search — see update_media's
    # _relink_tmdb. Not usable to change an already-linked entry's match.
    tmdb_id: int | None = Field(default=None, ge=1)
    url: SafeStr | None = Field(default=None, max_length=500)
    status: WatchStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=100)
    notes: SafeStr | None = None
    current_season: int | None = Field(default=None, ge=0)
    current_episode: int | None = Field(default=None, ge=0)
    episodes_watched: int | None = Field(default=None, ge=0)
    is_favorite: bool | None = None

    @field_validator("status", "episodes_watched", "is_favorite")
    @classmethod
    def _not_explicitly_null(cls, v: object, info) -> object:
        # These three fields are Optional only so a PATCH can omit them
        # (leave unchanged, via update_media's exclude_unset=True) — none of
        # them is nullable on the DB side (media_items.status/episodes_watched/
        # is_favorite are all NOT NULL). Explicitly sending e.g.
        # {"status": null} or {"is_favorite": null} used to reach
        # setattr(item, field, None) and die as an unhandled IntegrityError
        # (500); fuzz-discovered on both status and is_favorite.
        if v is None:
            raise ValueError(f"{info.field_name} must not be explicitly null")
        return v


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
    custom_poster_source_url: str | None = None  # TMDB URL it was picked from, if known (picker UI)
    backdrop_url: str | None = None  # custom override when set + owner premium
    custom_backdrop_url: str | None = None  # the stored override itself (picker UI)
    custom_backdrop_source_url: str | None = None  # TMDB URL it was picked from, if known (picker UI)
    tmdb_id: int | None = None
    runtime_minutes: int | None = None
    total_episodes: int | None = None
    total_seasons: int | None = None
    genres: list[str] = []
    overview: str | None = None
    tagline: str | None = None
    show_status: str | None = None
    release_date: date | None = None
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
    rating: int | None = Field(default=None, ge=1, le=100)


class EpisodeBulk(BaseModel):
    season: int = Field(ge=0, le=PG_INT32_MAX)
    episodes: list[Annotated[int, Field(le=PG_INT32_MAX)]] = Field(min_length=1, max_length=500)
    watched: bool = True


# ---------- lists ----------


class ListCreate(BaseModel):
    name: SafeStr = Field(min_length=1, max_length=100)


class ListUpdate(BaseModel):
    name: SafeStr = Field(min_length=1, max_length=100)


class ListItemCreate(BaseModel):
    # same target-resolution shape as CommentCreate below — the frontend
    # knows a title by (media_type, tmdb_id), never the internal title_id
    media_type: MediaType
    tmdb_id: int | None = None
    title: SafeStr | None = Field(default=None, max_length=300)


class ListItemReorder(BaseModel):
    # every item id currently in the list, in the caller's desired order —
    # position is rewritten wholesale from this, not diffed against the
    # existing order (see routers/lists.py)
    item_ids: list[int] = Field(min_length=1, max_length=2000)


class ListItemOut(BaseModel):
    """One title inside a custom list — shape returned by POST /{list_id}/items
    and embedded in the items array of ListDetailOut."""

    id: int
    title_id: int
    media_type: MediaType
    tmdb_id: int | None = None
    title: str
    poster_url: str | None = None
    position: int


class ListOut(BaseModel):
    """Summary of a custom list (no items) — shape returned by GET /lists,
    POST /lists, and PATCH /lists/{list_id}."""

    id: int
    name: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class ListDetailOut(BaseModel):
    """Full custom list including its ordered items — shape returned by
    GET /lists/{list_id} and PUT /lists/{list_id}/items/reorder."""

    id: int
    name: str
    item_count: int
    created_at: datetime
    updated_at: datetime
    items: list[ListItemOut] = []


# ---------- social ----------


class PublicUserOut(BaseModel):
    """Public profile shape returned by /users/search, /users/{user_id},
    /users/{user_id}/following, and /users/{user_id}/followers.
    Mirrors _public_users_batch() in routers/social.py field-for-field."""

    id: int
    username: str
    avatar: str | None = None
    # premium flair (from users/premium.py's flair())
    badge: str | None = None
    ring_color: str | None = None
    name_color: str | None = None
    background: str | None = None
    is_reviewer: bool = False
    created_at: datetime
    followers: int = 0
    following: int = 0
    items: int = 0
    total_watch_minutes: int = 0
    is_following: bool = False
    is_me: bool = False


class FeedEntryOut(BaseModel):
    """One activity-feed item — shape returned by GET /feed.
    Mirrors the dict literal inside activity_feed() in routers/social.py."""

    user_id: int
    username: str
    # premium flair (from users/premium.py's flair())
    badge: str | None = None
    ring_color: str | None = None
    name_color: str | None = None
    background: str | None = None
    is_reviewer: bool = False
    item_id: int
    media_type: str
    title: str
    year: int | None = None
    poster_url: str | None = None
    status: str
    rating: int | None = None
    tmdb_id: int | None = None
    episodes_watched: int = 0
    total_episodes: int | None = None
    updated_at: datetime


# ---------- tmdb ----------


class TmdbResultOut(BaseModel):
    """One search/trending/popular result — shape returned by /tmdb/search,
    /tmdb/trending, and /tmdb/popular. Mirrors _map_results() and
    _map_local_titles() (the TMDB-down fallback) in routers/tmdb.py."""

    tmdb_id: int
    title: str
    year: int | None = None
    poster_url: str | None = None
    overview: str = ""
    # None in the local-catalog fallback (_map_local_titles) when TMDB is down;
    # always an int from the live TMDB path (_map_results, which sets 0 for no data)
    vote_average: int | None = None
    vote_count: int = 0


class TmdbSeasonSummaryOut(BaseModel):
    """Season header inside TmdbDetailsOut.seasons — one entry per non-special
    season. Mirrors the inner dict in _map_details()."""

    season: int
    name: str
    episode_count: int = 0
    air_date: str | None = None


class TmdbDetailsOut(BaseModel):
    """Full title detail page — shape returned by GET /tmdb/details.
    Mirrors _map_details() in routers/tmdb.py field-for-field."""

    tmdb_id: int
    title: str | None = None
    original_title: str | None = None
    year: int | None = None
    runtime_minutes: int | None = None
    total_episodes: int | None = None
    total_seasons: int | None = None
    genres: list[str] = []
    poster_url: str | None = None
    backdrop_url: str | None = None
    overview: str | None = None
    tagline: str | None = None
    vote_average: int | None = None
    vote_count: int = 0
    show_status: str | None = None
    last_air_year: int | None = None
    # None for films (they have no season structure)
    seasons: list[TmdbSeasonSummaryOut] | None = None
    # Raw TMDB "YYYY-MM-DD" release/first-air date; distinct from `year` —
    # used by the frontend to badge a not-yet-released title.
    release_date: str | None = None


class TmdbImageOut(BaseModel):
    """One alternate poster/backdrop/episode-still entry — shape returned by
    /tmdb/posters, /tmdb/backdrops, and /tmdb/episode-stills."""

    preview_url: str
    url: str


class TmdbPersonOut(BaseModel):
    """Director / creator entry inside TmdbCreditsOut.directors."""

    name: str
    profile_url: str | None = None


class TmdbCastMemberOut(BaseModel):
    """One cast member in TmdbCreditsOut.cast."""

    name: str
    character: str = ""
    profile_url: str | None = None


class TmdbCrewMemberOut(BaseModel):
    """One crew member in TmdbCreditsOut.crew (excludes the director/creator,
    who surfaces in TmdbCreditsOut.directors instead)."""

    name: str
    # job title (e.g. "Screenplay", "Director of Photography")
    character: str = ""
    department: str = ""
    profile_url: str | None = None


class TmdbGuestStarOut(BaseModel):
    """Guest star on one episode, nested inside TmdbEpisodeOut.guest_stars."""

    name: str
    character: str = ""
    profile_url: str | None = None


class TmdbCreditsOut(BaseModel):
    """Full credits bundle — shape returned by GET /tmdb/credits.
    Mirrors the return dict of credits_tmdb() in routers/tmdb.py."""

    cast: list[TmdbCastMemberOut] = []
    crew: list[TmdbCrewMemberOut] = []
    directors: list[TmdbPersonOut] = []
    director_role: str = ""


class TmdbEpisodeOut(BaseModel):
    """One episode in a season listing — shape returned by GET /tmdb/season.
    Mirrors the inner dict of season_tmdb() in routers/tmdb.py."""

    season: int
    episode: int
    name: str
    air_date: str | None = None
    runtime: int | None = None
    overview: str = ""
    still_url: str | None = None
    vote_average: int | None = None
    vote_count: int = 0
    guest_stars: list[TmdbGuestStarOut] = []


# ---------- reviews ----------


class ReviewCreate(BaseModel):
    text: SafeStr = Field(min_length=1, max_length=10000)
    rating: int = Field(ge=1, le=100)


class ReviewUpdate(BaseModel):
    text: SafeStr = Field(min_length=1, max_length=10000)
    rating: int = Field(ge=1, le=100)


class ReviewOut(BaseModel):
    """Public shape returned by every /media/reviews endpoint that produces a
    body — list, create (201), and update. Mirrors _review_out() in
    routers/reviews.py field-for-field so FastAPI's response_model= doesn't
    silently drop any field the frontend consumes."""

    id: int
    title_id: int
    user_id: int
    username: str
    avatar: str | None = None
    # premium flair fields (from users/premium.py's flair())
    badge: str | None = None
    ring_color: str | None = None
    name_color: str | None = None
    background: str | None = None
    is_reviewer: bool = False
    text: str
    rating: int
    created_at: datetime
    updated_at: datetime
    mine: bool


# ---------- comments ----------


class CommentCreate(BaseModel):
    media_type: MediaType
    tmdb_id: int | None = None
    title: SafeStr | None = Field(default=None, max_length=300)
    season: int | None = Field(default=None, ge=0)
    episode: int | None = Field(default=None, ge=0)
    parent_id: int | None = Field(default=None, ge=1)  # reply target; must be in the same thread
    text: SafeStr = Field(min_length=1, max_length=2000)


class CommentReportCreate(BaseModel):
    reason: SafeStr = Field(default="", max_length=500)


class CommentOut(BaseModel):
    """Public shape returned by GET /comments and POST /comments. Mirrors
    _comment_out() in routers/comments.py field-for-field — see that
    function for the per-field semantics. Replies are nested recursively;
    model_rebuild() below resolves the forward reference."""

    id: int
    user_id: int
    parent_id: int | None = None
    username: str
    avatar: str | None = None
    # premium flair fields (from users/premium.py's flair())
    badge: str | None = None
    ring_color: str | None = None
    name_color: str | None = None
    background: str | None = None
    is_reviewer: bool = False
    text: str
    created_at: datetime
    likes: int
    dislikes: int
    liked_by_me: bool
    disliked_by_me: bool
    mine: bool
    reported_by_me: bool
    seen_by_author: bool
    author_rating: int | None = None
    replies: list["CommentOut"] = []  # noqa: UP037 — self-reference; removing quotes causes NameError at class body eval


CommentOut.model_rebuild()


# ---------- notifications ----------


class NotificationOut(BaseModel):
    """Public shape returned by GET /notifications. Mirrors _out() in
    routers/notifications.py field-for-field."""

    id: int
    kind: str
    title: str
    body: str
    media_item_id: int | None = None
    season: int | None = None
    episode: int | None = None
    read: bool
    created_at: datetime


class UnreadCountOut(BaseModel):
    """Shape returned by GET /notifications/unread_count."""

    count: int


# ---------- rewatch ----------


class RewatchCreate(BaseModel):
    season: int | None = Field(default=None, ge=0, le=PG_INT32_MAX)
    episode: int | None = Field(default=None, ge=0, le=PG_INT32_MAX)


class WatchEventRatingUpdate(BaseModel):
    """Payload for PATCH /media/{item_id}/rewatch-events/{event_id}.

    Sets or clears the rating for one specific watch-through. When the
    targeted event is the latest for its (season, episode) scope, the
    cache column (LibraryEntry.rating / EpisodeWatch.rating) is updated
    too so the community aggregate stays in sync.
    """

    rating: int | None = Field(default=None, ge=1, le=100)


# ---------- ratings ----------


class RatingsBatchRequest(BaseModel):
    media_type: MediaType
    tmdb_ids: list[int] = Field(min_length=1, max_length=100)


# ---------- import ----------


class ImportSourceOut(BaseModel):
    """One importable origin — shape returned by GET /import/sources."""

    kind: str
    label: str


class ImportStartedOut(BaseModel):
    """Shape returned by POST /import (202 Accepted)."""

    status: str
    kind: str


class ImportStatusOut(BaseModel):
    """Live-or-persisted import progress — shape returned by GET /import/status.

    ``summary`` is a free-form dict whose keys depend on the importer kind
    (renar vs. tvtime); ``None`` while an import has never run or is still
    in-flight.
    """

    stage: str
    finished: bool
    error: str | None = None
    summary: dict | None = None
    done: int
    total: int
    kind: str | None = None


# ---------- export ----------


class ExportRequestedOut(BaseModel):
    """Shape returned by POST /export/data (202 Accepted)."""

    status: str


class ExportStatusOut(BaseModel):
    """Shape returned by GET /export/data/status.

    ``error`` is only present when ``state`` is ``"failed"``; omitting it
    for every other state avoids a spurious ``null`` in the JSON body.
    """

    state: str
    error: str | None = None


# ---------- upcoming ----------


class UpcomingItemOut(BaseModel):
    """One upcoming release (TV episode or film) — shape returned by
    GET /upcoming and GET /upcoming/history."""

    item_id: int
    media_type: str
    title: str
    tmdb_id: int | None = None
    poster_url: str | None = None
    date: str
    days_until: int
    season: int | None = None
    episode: int | None = None
    episode_name: str | None = None


# ---------- svc ----------


class BansOut(BaseModel):
    """Shape returned by GET /svc/bans.

    ``ips`` is the list of permanently banned IPs; ``temp_bans`` maps each
    active temp-banned IP to its Unix-timestamp expiry (float)."""

    ips: list[str]
    temp_bans: dict[str, float]


class SvcStatusOut(BaseModel):
    """Simple acknowledgement returned by POST /svc/bans."""

    status: str


class StrikeResultOut(BaseModel):
    """Shape returned by POST /svc/strikes."""

    permanent: bool
    banned_until: float | None = None
