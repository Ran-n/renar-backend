#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/07 13:25:14.419974
Revised: 2026/08/02 18:29:48.585693
"""

import enum
from collections.abc import Iterable
from datetime import UTC, date, datetime

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    column,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session, relationship

from .database import Base
from .db_triggers import USER_COUNT_TRIGGER_SQL, WATCH_MINUTES_TRIGGER_SQL


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
    # The TMDB alternate URL this was downloaded from, when it was set that
    # way rather than uploaded — lets the frontend's alternates picker mark
    # which tile is the current pick without re-deriving/guessing an image
    # identity. Null for uploads (no source URL to record) and for images
    # created before this column existed.
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


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
    # Bumped whenever the password changes (self-service or admin reset).
    # get_current_user rejects any bearer token issued before this moment, so
    # a leaked token stops working as soon as the password it was minted
    # under is replaced, instead of staying valid for the rest of its
    # ACCESS_TOKEN_EXPIRE_MINUTES lifetime. NULL means "never changed since
    # this column existed" — no cutoff to enforce.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True once the user has completed a code-confirmation round trip proving
    # ownership of `email` (see users/email_confirmation.py). Indexed: it's
    # filtered on every /stats/ranking request (routers/stats.py._compute_ranking)
    # to keep unconfirmed/throwaway accounts out of the leaderboard. Backfilled
    # to True for every pre-existing account by migration (see its docstring
    # for why: an account-age-based grace period would otherwise lock out an
    # established user base on day one).
    email_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    # True when email_confirmed was set to True without the user ever
    # completing the code round trip: either they registered while
    # SiteSettings.email_confirmation_enabled was off (routers/auth.py's
    # register), or an admin disabled that toggle while this account was
    # still unconfirmed (routers/admin/settings.py's bulk-confirm). Purely
    # informational — nothing re-gates on it — so an admin auditing the user
    # list can tell "confirmed via the real flow" from "confirmed because
    # the requirement was off at the time."
    email_confirmation_bypassed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Set while an email-change is awaiting its two-step confirmation
    # (see routers/auth.py's update_profile) — `email` itself only ever
    # changes once the new address's own code is confirmed.
    pending_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    # When set, library tiles show Title.original_title instead of the
    # localized display_title (see list_media's `lang` param).
    show_original_titles: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    avatar_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), nullable=True, index=True)
    background_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), nullable=True, index=True)
    banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ban_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Premium is a timestamp, not a bool: active while utcnow() < premium_until,
    # so lapsing, renewals and admin-granted trial time are all one field.
    premium_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Admin-granted; the displayed badge is derived (verified wins over premium)
    # and disappears while premium is lapsed — the stored flags stay put.
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    # Chosen from premium.PALETTE (validated server-side); kept when premium
    # lapses but only served/applied while premium is active.
    ring_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    name_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # Chosen from premium.THEME_NAMES (validated server-side); kept when
    # premium lapses but reverts to the free theme on next apply.
    theme: Mapped[str] = mapped_column(String(20), default="gruvbox", server_default="gruvbox")
    # Home screen preferences. Independent of each other: hero_enabled controls
    # whether Home shows the featured "continue watching" card at all (off
    # falls back to a plain in-progress list); on_launch controls whether the
    # app opens on Home or Library. Synced server-side (like theme) so the
    # choice follows the account across devices, not just one client.
    home_hero_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    home_on_launch: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Home screen progress indicator. "rings" is the only free style (same
    # premium gate as theme, enforced in the /auth/profile route); season/
    # series colors are premium-only regardless of style, chosen from
    # premium.PALETTE, kept when premium lapses but only applied while active.
    home_progress_style: Mapped[str] = mapped_column(String(20), default="rings", server_default="rings")
    home_season_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    home_series_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # Per-status accent overrides for Library cards (badge bar / progress
    # color) — premium-only, keyed by WatchStatus value, colors chosen from
    # premium.PALETTE (validated server-side). Missing keys fall back to the
    # theme's default accent for that status. Kept when premium lapses but
    # only applied while active, same as the home season/series colors.
    status_colors: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    # Season/episode label format shown next to episode titles (Upcoming,
    # Title, Episode). "cross" ("1×05") is the only free style, same premium
    # gate as theme/progress style, enforced in the /auth/profile route.
    episode_label_style: Mapped[str] = mapped_column(String(20), default="cross", server_default="cross")
    # Set once the first-login welcome tour has been shown (or skipped).
    # Synced server-side so it doesn't re-appear on a different device.
    has_seen_welcome: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Ranking metrics (see routers/stats.py RANKING_METRICS): kept up to date
    # incrementally at write time (each write recomputes just the acting
    # user's own value — never a full-table scan), so leaderboard rank/total
    # can be read with a plain indexed COUNT query instead of aggregating
    # every user's library on every request.
    total_watch_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # The only usage fact stored here: everything else the admin panel shows
    # (login count, last login, request totals) is derived from login_events /
    # request_days / endpoint_stats. last_active_at has no other timestamped
    # record at full precision (request_days is per-day), so it lives here.
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    avatar_image: Mapped[Image | None] = relationship(foreign_keys=[avatar_id])
    background_image: Mapped[Image | None] = relationship(foreign_keys=[background_id])
    library_entries: Mapped[list[LibraryEntry]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def avatar(self) -> str | None:
        """URL path the frontend can fetch, e.g. /images/<hash>."""
        return f"/images/{self.avatar_image.hash}" if self.avatar_image else None

    @property
    def background(self) -> str | None:
        """URL path for the profile background banner, e.g. /images/<hash>."""
        return f"/images/{self.background_image.hash}" if self.background_image else None

    @property
    def is_premium(self) -> bool:
        return self.premium_until is not None and self.premium_until > utcnow()

    @property
    def badge(self) -> str | None:
        """The single badge shown next to the username: verified replaces
        premium (never both), and no badge at all once premium lapses."""
        if not self.is_premium:
            return None
        return "verified" if self.verified else "premium"


class AppCounters(Base):
    """Singleton row (id is always 1) holding site-wide counters too cheap to
    justify their own table, but too expensive to recompute with COUNT(*) on
    every read at scale — COUNT(*) has no O(1) shortcut in Postgres's MVCC
    even with an index, since visibility must be checked per row. Maintained
    by a trigger on the counted table (see db_triggers.py), same pattern as
    users.total_watch_minutes: the database keeps it correct atomically,
    nothing in application code has to remember to update it.

    total_users specifically backs /stats/ranking's percentile denominator —
    see routers/stats.py._compute_ranking and docs/design-decisions.md."""

    __tablename__ = "app_counters"
    __table_args__ = (CheckConstraint("id = 1", name="ck_app_counters_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    total_users: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class SiteSettings(Base):
    """Singleton row (id is always 1) holding admin-tunable runtime settings.

    Anti-abuse limits and registration flags live here so they can be changed
    from the admin panel without a server restart or an `.env` edit. Values
    are seeded from config.py defaults on the first read (upsert-on-read in
    site_settings.get_site_settings), then owned by the database.
    """

    __tablename__ = "site_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_site_settings_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    invite_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    registration_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # On/off switch for the Cloudflare Turnstile check on /auth/register,
    # independent of whether TURNSTILE_SITE_KEY/TURNSTILE_SECRET_KEY are set
    # in .env (see config.py) — lets an admin fall back to IP rate-limiting
    # only without touching those credentials.
    turnstile_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # On/off switch for the registration/email-change confirmation-code flow
    # (see users/email_confirmation.py, routers/auth.py's register/login).
    # Off: new accounts are marked email_confirmed on creation instead of
    # having to verify, and login is never gated on it. Flipping this off
    # also bulk-confirms every currently-unconfirmed user (see
    # routers/admin/settings.py's save_settings) — "off" means the concept
    # stops mattering at all, not that existing unconfirmed accounts stay
    # silently excluded from /stats/ranking or blocked at login forever.
    email_confirmation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Per-feature kill switches for premium perks — each independently
    # disables one perk for every user regardless of premium_until, without
    # touching the others. Existing subscriptions are preserved on the user
    # row either way; a feature switched back on immediately honors them
    # again. See users/premium.py::feature_enabled for the lookup and
    # PremiumFeature for the fixed set of valid names. Custom poster/backdrop
    # overrides are unaffected (still gated on is_premium alone) since
    # they're a display concern, not a subsystem entry point.
    premium_style_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    premium_verification_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    premium_background_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    premium_themes_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    premium_progress_style_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    premium_episode_label_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    premium_ranking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    auth_rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30)
    register_per_hour_per_ip: Mapped[int] = mapped_column(Integer, default=20)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=600)
    flood_ban_per_minute: Mapped[int] = mapped_column(Integer, default=2000)
    login_backoff_threshold: Mapped[int] = mapped_column(Integer, default=5)
    login_backoff_account_threshold: Mapped[int] = mapped_column(Integer, default=30)
    login_backoff_minutes: Mapped[int] = mapped_column(Integer, default=15)
    probe_ban_threshold: Mapped[int] = mapped_column(Integer, default=12)
    probe_window_minutes: Mapped[int] = mapped_column(Integer, default=10)
    ban_minutes: Mapped[int] = mapped_column(Integer, default=60)
    strike_ban_threshold: Mapped[int] = mapped_column(Integer, default=5)
    # False unless there's an actual reverse proxy/CDN in front of the app —
    # see client_ip() in users/security.py for why trusting X-Forwarded-For
    # without one lets any client spoof its IP.
    trust_proxy_headers: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # IPs that skip the guard entirely (monitoring, local tooling).
    exempt_ips: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Persisted TMDB copies (tmdb_cache table) younger than this are served
    # without contacting TMDB; older ones refresh on access and are served
    # stale only while TMDB is unreachable (see tmdb/tmdb_store.py::_is_fresh).
    tmdb_db_cache_hours: Mapped[int] = mapped_column(Integer, default=24)
    # Transactional email (see users/email_confirmation.py) — seeded from
    # config.py's BREVO_API_KEY-adjacent settings, then owned live here.
    email_sender_address: Mapped[str] = mapped_column(String, default="noreply@renar.app")
    email_sender_name: Mapped[str] = mapped_column(String, default="Renar")
    confirmation_code_ttl_minutes: Mapped[int] = mapped_column(Integer, default=15)
    email_confirmation_grace_days: Mapped[int] = mapped_column(Integer, default=7)
    unconfirmed_account_cleanup_days: Mapped[int] = mapped_column(Integer, default=14)


class PeriodicTaskRun(Base):
    """One row per background task key (see task_runs.TASKS): whether it's
    enabled, its admin-configurable poll interval, and its last-run outcome.

    Replaces the old grouped SiteSettings booleans (episode_check_enabled,
    film_check_enabled, bans_check_enabled) and the single shared
    EPISODE_CHECK_MINUTES env var — each task is now independently
    controllable. A missing row (task never toggled/run) is treated as
    enabled with the task's coded default interval; see task_runs.py.
    """

    __tablename__ = "periodic_task_runs"

    task_key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_detail: Mapped[str] = mapped_column(Text, default="", server_default="")


class InviteCode(Base):
    """Admin-generated registration token for invite-only mode.

    A code is valid when: not revoked, (max_uses is None or uses < max_uses),
    and (expires_at is None or expires_at > utcnow()). max_uses is None for
    an unlimited-use code (e.g. a public "join us" link).

    created_by_user_id is None when generated from the admin panel (that auth
    is a single env-configured HTTP Basic credential, not a users.id row);
    the field is here for future user-generated referral codes. In that case
    created_by_admin instead carries the HTTP Basic admin's plain username.
    """

    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_by_admin: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # No Python-side default: every caller (admin panel, tests) passes this
    # explicitly, and a default=1 here would silently override an explicit
    # None (unlimited) at flush time.
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Timestamp of the most recent redemption. Registration already refuses a
    # redemption once uses >= max_uses (routers/auth.py), so once a code is
    # exhausted this is exactly the moment it became exhausted — lets the
    # admin panel tell whether a code that's both past its expires_at and at
    # its use cap hit one before the other.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])


class EmailConfirmationCode(Base):
    """A one-time code proving ownership of an email address — registration,
    or either leg of the two-step email-change flow (update_profile in
    routers/auth.py). `code_hash` is bcrypt (see users/email_confirmation.py),
    never plaintext — unlike InviteCode above, this guards account takeover,
    not just registration gating. `attempts` caps brute-force guesses against
    the 6-digit space independently of `expires_at`; `consumed_at` makes a
    code single-use and lets a resend invalidate whatever it replaces without
    a delete (kept for audit)."""

    __tablename__ = "email_confirmation_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(20))  # "register" | "change_authorize" | "change_confirm"
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


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


class Genre(Base):
    """One genre label ("Drama", "Science Fiction"), shared by every title
    that carries it — titles link to it through the title_genres table.
    """

    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)


title_genres = Table(
    "title_genres",
    Base.metadata,
    Column("title_id", ForeignKey("titles.id"), primary_key=True),
    # genre_id gets its own index: the composite PK only covers title_id-first
    # lookups, and genre deletes / by-genre queries filter on genre_id alone
    Column("genre_id", ForeignKey("genres.id"), primary_key=True, index=True),
)


class Title(Base):
    """A movie or show, shared across every user who tracks it.

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
            postgresql_where=column("tmdb_id").isnot(None),
        ),
        Index(
            "uq_title_key",
            "media_type",
            "title_key",
            unique=True,
            postgresql_where=column("tmdb_id").is_(None),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), index=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    # TMDB's own original_title/original_name: language-independent, unlike
    # `title` above (which is frozen to whatever language first added it).
    original_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Landscape backdrop/still, for full-bleed hero art — portrait poster_url
    # looks stretched and blurry when filled into a wide banner slot.
    backdrop_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)  # film total / tv per-episode
    total_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_seasons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # TMDB's production status verbatim ("Returning Series", "Ended",
    # "Canceled", ...): shown to users, and lets the notifier stop polling
    # finished shows.
    show_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    next_episode_air_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_episode_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_episode_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Film-only; TV release timing lives in next_episode_air_date above.
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    genre_rows: Mapped[list[Genre]] = relationship(secondary=title_genres, order_by=Genre.name)

    @property
    def genres(self) -> list[str]:
        return [g.name for g in self.genre_rows]


class TmdbCache(Base):
    """Persisted copy of a raw TMDB response for a tracked Title.

    Write-through cache, not source of truth: endpoints re-fetch from TMDB
    when a row is older than settings.tmdb_db_cache_hours and fall back to
    the stored payload when TMDB is unreachable, so detail pages keep
    working offline. Only titles somebody tracks/comments on get rows —
    explore browsing stays memory-cached only — so growth is bounded by
    the titles table. Registered as a deliberate cache in
    tests/test_normalization.py's spirit: payload is TMDB's data, not ours.
    """

    __tablename__ = "tmdb_cache"
    __table_args__ = (UniqueConstraint("title_id", "kind", "season", "language", name="uq_tmdb_cache_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # details | season | credits
    season: Mapped[int] = mapped_column(Integer, default=-1)  # -1 for non-season kinds (keeps the unique key simple)
    # app language code ("en", "gl", "pt", "es"); "en" is the source-of-truth
    # copy that also syncs the typed Title/Episode columns, see tmdb_store.py
    language: Mapped[str] = mapped_column(String(5), default="en")
    payload: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Episode(Base):
    """One row = one TMDB-known episode of a tracked TV show: catalog data
    (air date, name) shared across every user who tracks the show, synced
    from TMDB season payloads. Not per-user watch state — see EpisodeWatch
    for "did this user watch it".
    """

    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("title_id", "season", "episode_number", name="uq_episode_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    episode_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    air_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


def prefetch_episode_cache(db: Session, title_ids: Iterable[int | None]) -> None:
    """Batch-loads every episode for the given titles in one query and
    stashes them on the session, keyed by title_id.

    LibraryEntry's episode-derived properties (current_episode_name,
    next_episode, ...) read from this cache when present instead of each
    issuing their own query — without it, listing a library with N
    in-progress shows fires up to 4*N per-row queries (and repeated full
    per-show episode scans), which is what makes an unfiltered library
    listing crawl for large libraries.
    """
    ids = {tid for tid in title_ids if tid is not None}
    if not ids:
        return
    cache: dict[int, list[Episode]] = db.info.setdefault("episode_cache_by_title", {})
    ids -= cache.keys()
    if not ids:
        return
    for tid in ids:
        cache[tid] = []
    episodes = (
        db.query(Episode).filter(Episode.title_id.in_(ids)).order_by(Episode.season, Episode.episode_number).all()
    )
    for ep in episodes:
        cache[ep.title_id].append(ep)


class ExternalImage(Base):
    """Maps an external image (TMDB poster/still) to a row in the
    content-addressed image store, so all cached image bytes live in one
    place (media/images) and identical files are stored once.
    """

    __tablename__ = "external_images"
    __table_args__ = (UniqueConstraint("source", "key", name="uq_external_image"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # tmdb | openlibrary
    key: Mapped[str] = mapped_column(String(255))  # e.g. "w342/abc.jpg" or a cover id
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), index=True)

    image: Mapped[Image] = relationship()


class LibraryEntry(Base):
    """One user's personal tracking of a Title: status, rating, notes,
    progress, favorite. Title/year/poster/etc. are NOT here — they live on
    the shared Title row and are immutable through this entry.
    """

    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("user_id", "title_id", name="uq_user_title"),
        Index("ix_media_items_user_id_status", "user_id", "status"),
        Index("ix_media_items_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_media_items_user_id_last_watched_at", "user_id", "last_watched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title_id: Mapped[int] = mapped_column(ForeignKey("titles.id"), index=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # optional personal link for the item
    status: Mapped[WatchStatus] = mapped_column(Enum(WatchStatus), default=WatchStatus.want_to_watch)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Coarse TV-show progress. These are user-asserted facts, NOT caches: a
    # user can track "I'm 37 episodes in" without recording which episodes
    # (episode_watches rows). When per-episode rows DO exist, _sync_progress
    # recomputes these from them (one-way, single write path) — that derived
    # case is a registered exception in tests/test_normalization.py.
    current_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episodes_watched: Mapped[int] = mapped_column(Integer, default=0)
    # Set only when the user actually marks an episode (or, for a film, the
    # item itself) watched/rewatched — unlike updated_at, this deliberately
    # does NOT move on a favorite toggle, rating, note, or status edit, so
    # Home's "in progress" ordering can reflect genuine watch activity only.
    last_watched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    # Premium-only poster override, always a stored image (TMDB alternates are
    # downloaded into the store, uploads land there directly). Per-entry, so it
    # never touches the shared Title row; kept but not served once premium lapses.
    custom_poster_image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), nullable=True, index=True)
    # Premium-only backdrop override, same shape/rules as custom_poster_image_id.
    custom_backdrop_image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="library_entries")
    title_ref: Mapped[Title] = relationship()
    custom_poster_image: Mapped[Image | None] = relationship(foreign_keys=[custom_poster_image_id])
    custom_backdrop_image: Mapped[Image | None] = relationship(foreign_keys=[custom_backdrop_image_id])
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
    def original_title(self) -> str | None:
        return self.title_ref.original_title

    @property
    def display_title(self) -> str:
        """The title's name in the requesting user's language, when known.

        list_media stamps `_display_title` per-request (from cached TMDB
        translations); everything else — including plain ORM access outside
        that endpoint — falls back to the shared Title.title.
        """
        return getattr(self, "_display_title", None) or self.title_ref.title

    @property
    def year(self) -> int | None:
        return self.title_ref.year

    @property
    def custom_poster_url(self) -> str | None:
        """The stored override itself, regardless of premium state — the
        poster picker needs to show it even while premium is lapsed."""
        return f"/images/{self.custom_poster_image.hash}" if self.custom_poster_image else None

    @property
    def custom_poster_source_url(self) -> str | None:
        """The TMDB alternate URL the current custom poster was picked from,
        when known — lets the alternates picker highlight the active tile.
        None for an uploaded poster or one set before Image.source_url
        existed."""
        return self.custom_poster_image.source_url if self.custom_poster_image else None

    @property
    def poster_url(self) -> str | None:
        if self.custom_poster_image is not None and self.owner.is_premium:
            return self.custom_poster_url
        return self.title_ref.poster_url

    @property
    def custom_backdrop_url(self) -> str | None:
        """The stored override itself, regardless of premium state — the
        backdrop picker needs to show it even while premium is lapsed."""
        return f"/images/{self.custom_backdrop_image.hash}" if self.custom_backdrop_image else None

    @property
    def custom_backdrop_source_url(self) -> str | None:
        """Same as `custom_poster_source_url`, for the backdrop override."""
        return self.custom_backdrop_image.source_url if self.custom_backdrop_image else None

    @property
    def backdrop_url(self) -> str | None:
        if self.custom_backdrop_image is not None and self.owner.is_premium:
            return self.custom_backdrop_url
        return self.title_ref.backdrop_url

    @property
    def _episodes(self) -> list[Episode]:
        """This title's episodes, sorted by (season, episode_number).

        Serves from the per-request cache `prefetch_episode_cache` fills in
        (so listing a whole library issues one batched query instead of one
        per row); falls back to a direct per-title query when no cache was
        primed (single-entry reads etc).
        """
        session = object_session(self)
        if session is None:
            return []
        cache = session.info.get("episode_cache_by_title")
        if cache is not None:
            return cache.get(self.title_id, [])
        return (
            session.query(Episode)
            .filter_by(title_id=self.title_id)
            .order_by(Episode.season, Episode.episode_number)
            .all()
        )

    @property
    def current_episode_name(self) -> str | None:
        if self.current_season is None or self.current_episode is None:
            return None
        for ep in self._episodes:
            if ep.season == self.current_season and ep.episode_number == self.current_episode:
                return ep.name
        return None

    @property
    def _next_episode_row(self) -> Episode | None:
        """The episode right after current_season/current_episode in the
        show's catalog order — "next to watch", not "last watched"."""
        episodes = self._episodes
        if not episodes:
            return None
        if self.current_season is None or self.current_episode is None:
            return episodes[0]
        for i, ep in enumerate(episodes):
            if ep.season == self.current_season and ep.episode_number == self.current_episode:
                return episodes[i + 1] if i + 1 < len(episodes) else None
        return episodes[0]

    @property
    def next_season(self) -> int | None:
        ep = self._next_episode_row
        return ep.season if ep else None

    @property
    def next_episode(self) -> int | None:
        ep = self._next_episode_row
        return ep.episode_number if ep else None

    @property
    def next_episode_name(self) -> str | None:
        ep = self._next_episode_row
        return ep.name if ep else None

    @property
    def next_season_total_episodes(self) -> int | None:
        """Episode count of the season the next episode is in, for a
        season-scoped progress bar next to the next-episode label."""
        season = self.next_season
        if season is None:
            return None
        count = sum(1 for ep in self._episodes if ep.season == season)
        return count or None

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
    def total_seasons(self) -> int | None:
        return self.title_ref.total_seasons

    @property
    def current_season_total_episodes(self) -> int | None:
        """Episode count of the season the user is currently on, for a
        season-scoped progress bar (distinct from the whole-show total)."""
        if self.current_season is None:
            return None
        count = sum(1 for ep in self._episodes if ep.season == self.current_season)
        return count or None

    @property
    def overview(self) -> str | None:
        return self.title_ref.overview

    @property
    def tagline(self) -> str | None:
        return self.title_ref.tagline

    @property
    def show_status(self) -> str | None:
        return self.title_ref.show_status

    @property
    def genres(self) -> list[str]:
        return self.title_ref.genres


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


class EpisodeCustomStill(Base):
    """Premium per-episode still override, same shape/rules as
    LibraryEntry.custom_backdrop_image_id: a TMDB alternate downloaded
    server-side into the image store. Kept separate from EpisodeWatch since a
    still can be set on an episode the user hasn't watched yet, and a row
    here must never be mistaken for "this episode was watched"."""

    __tablename__ = "episode_custom_stills"
    __table_args__ = (UniqueConstraint("media_item_id", "season", "episode", name="uq_item_episode_custom_still"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    media_item_id: Mapped[int] = mapped_column(ForeignKey("media_items.id"), index=True)
    season: Mapped[int] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    still_image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), index=True)

    still_image: Mapped[Image] = relationship()


class WatchEvent(Base):
    """One row = one watch of this item (or episode), including rewatches.

    Unlike EpisodeWatch (at most one row per episode = "currently watched"),
    this is an append-only log: rewatching an episode or a whole film just
    adds another row here. season/episode are both null for a whole-item
    (film) watch event.
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
    """Comments attach to a global Title row (shared across users), optionally
    scoped to one (season, episode). The API still addresses threads by
    (media_type, tmdb_id-or-title); the router resolves that to a Title.

    Replies are comments whose parent_id points at another comment in the same
    thread (arbitrary depth). Only a root comment (parent_id is NULL) stores
    title_id/season/episode: a reply's scope is the thread it belongs to, a
    fact about its root, not independent data about the reply row itself —
    storing a copy on every reply would be a transitive dependency (BCNF).
    comment_threads.resolve_root_scope() derives it by walking parent_id up
    to the root instead. Deleting a comment deletes its whole reply subtree.
    """

    __tablename__ = "comments"
    __table_args__ = (Index("ix_comment_target", "title_id", "season", "episode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Non-null only on root comments (parent_id is NULL) — see class docstring.
    title_id: Mapped[int | None] = mapped_column(ForeignKey("titles.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    author: Mapped[User] = relationship()
    title_ref: Mapped[Title | None] = relationship()
    likes: Mapped[list[CommentLike]] = relationship(back_populates="comment", cascade="all, delete-orphan")
    reports: Mapped[list[CommentReport]] = relationship(back_populates="comment", cascade="all, delete-orphan")
    parent: Mapped[Comment | None] = relationship(back_populates="replies", remote_side="Comment.id")
    replies: Mapped[list[Comment]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="Comment.created_at",
    )


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
        # Backs list_notifications' unread_only filter and unread_count — both
        # filter (user_id, read) together, so the composite index serves both
        # instead of a standalone `read` index (low-cardinality, near-useless
        # alone) plus a separate scan on user_id.
        Index("ix_notifications_user_id_read", "user_id", "read"),
        # Backs list_notifications' default order (user_id filter + created_at
        # desc), same pattern as LibraryEntry.ix_media_items_user_id_updated_at.
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    media_item_id: Mapped[int | None] = mapped_column(ForeignKey("media_items.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="new_episode")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(String(500))
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CommentLike(Base):
    """A user's reaction to a comment: +1 (like) or -1 (dislike). One row per
    (comment, user) — reacting the other way flips this row's value rather
    than adding a second one, so a user can never both like and dislike the
    same comment.
    """

    __tablename__ = "comment_likes"
    __table_args__ = (UniqueConstraint("comment_id", "user_id", name="uq_comment_like"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    value: Mapped[int] = mapped_column(Integer, default=1)

    comment: Mapped[Comment] = relationship(back_populates="likes")


class CommentReport(Base):
    """A user flagging a comment for moderator attention. One row per
    (comment, reporter) — repeat reports are no-ops. Reports are surfaced in
    the admin comment manager, which is where the flagged comment gets
    deleted (or the report ignored).
    """

    __tablename__ = "comment_reports"
    __table_args__ = (UniqueConstraint("comment_id", "user_id", name="uq_comment_report"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    comment: Mapped[Comment] = relationship(back_populates="reports")


class ImportJob(Base):
    """Durable marker for a user's last outcome from a given import origin
    (routers/imports.py's registry — TV Time, a Renar export, and whatever
    gets added later, e.g. Letterboxd).

    Each importer keeps live progress in its own in-memory dict, which
    doesn't survive a server restart — without this row, a restart mid-import
    silently looks identical to "never run" to the status endpoint, and the
    frontend reports a false "Import complete ✓". Written only at job start
    and at completion/failure (not per progress tick), so a status poll that
    finds no in-memory entry can still tell "interrupted" apart from "never
    ran" from this row's `finished` flag.

    Keyed by (user_id, kind) rather than user_id alone: an account can have
    a past import from more than one origin (e.g. migrated from TV Time,
    later also restored a Renar export), and each origin's outcome/summary
    shape is independent of the others'.
    """

    __tablename__ = "import_jobs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), primary_key=True)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExportJob(Base):
    """Durable marker for a user's personal-data export (GDPR Art. 20 — the
    right to data portability). Every user can request one regardless of
    premium status — `is_premium` only feeds the worker's priority queue
    (see users/export_queue.py) — premium requests are dequeued first
    because they're paying for compute priority, never as a way to withhold
    the export itself, which stays free and available to everyone.

    Same shape as ImportJob and for the same reason: routers/export.py keeps
    live progress in an in-memory dict that doesn't survive a restart, so a
    status poll after one needs this row to tell "queued job got dropped by
    the restart" apart from "never requested". The finished export file
    itself lives on disk (users/export.py::export_path), not in this row.

    `queued_at` is bumped on every request, not just the first — it's the
    "last requested" timestamp, not a creation timestamp. `completed_at` is
    set only on a successful finish and drives both the request cooldown and
    the ready-export expiry (see users/export.py::is_export_expired and
    migration 275461ed120c); it stays None while queued/processing/failed.
    """

    __tablename__ = "export_jobs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Alembic migrations are the source of truth for real deployments, but tests
# build the schema straight from Base.metadata.create_all() and never run
# migrations (see tests/conftest.py) — so a trigger created only via a
# migration's op.execute() would silently never exist there. Registering the
# same DDL here, against LibraryEntry's own table "after_create" event, makes
# create_all() create it too. Attached to LibraryEntry (media_items) rather
# than Base.metadata itself: a metadata-level DDL event fires once for the
# whole create_all() call, before any individual table is actually created
# (confirmed empirically — it is NOT "after all tables", despite the name),
# so DDL referencing table names must instead hang off a table that's
# guaranteed to be created last among the ones it touches. media_items has FK
# columns to users and titles, so SQLAlchemy's dependency sort always creates
# both of those first — by the time this fires, all three exist.
event.listen(LibraryEntry.__table__, "after_create", DDL(WATCH_MINUTES_TRIGGER_SQL))

# app_counters has no FK to users (it's a singleton counter row, not a
# per-user fact), so there's no natural dependency SQLAlchemy's creation-order
# sort would pick up on its own — add_is_dependent_on declares one explicitly,
# the same tool SQLAlchemy provides for exactly this "must be created after,
# but there's no real foreign key" case. That guarantees users exists by the
# time app_counters' own after_create fires, so the trigger DDL below (which
# references both tables) is safe.
AppCounters.__table__.add_is_dependent_on(User.__table__)
event.listen(AppCounters.__table__, "after_create", DDL(USER_COUNT_TRIGGER_SQL))
