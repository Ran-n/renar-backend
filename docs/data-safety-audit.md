[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/08/27 09:52:03.159327 )
[//]: # (+ Revised: 	2026/11/09 11:49:59.068315 )
[//]: # ( ---------------------------------------------------------------------- )

# Data Safety Audit

Enumerates every user-linked data field Renar's backend stores, why, and how
long it's kept. Written to be reusable, field-for-field, for both Google
Play's Data Safety form and Apple's Privacy Nutrition Label at store
submission time — see `TODO.md`'s Publishing section.

Scope: `src/renar_backend/models.py`'s user-linked tables only. TMDB/TheTVDB
catalog data (titles, episodes, genres) isn't user data and is out of scope.

## Account (`User`)

| Field | Purpose | Retention |
|---|---|---|
| `username` | Public display identity, login | Until account deletion (see Account deletion below) |
| `email` | Login, transactional email (confirmation codes, password reset) | Until account deletion |
| `password_hash` | Authentication (bcrypt, never the plaintext) | Until account deletion |
| `pending_email` | In-flight email-change confirmation | Cleared once confirmed or account deleted |
| `avatar_id` / `background_id` | User-uploaded profile images | Until replaced or account deletion |
| `language`, `show_original_titles`, `theme`, `home_*`, `episode_label_style`, `*_color`, `countdown_colors`, `status_colors`, `has_seen_welcome` | Display/UX preferences, synced across the user's own devices | Until account deletion |
| `premium_until`, `verified`, `verification_requested` | Premium/verification entitlement state | Until account deletion |
| `banned`, `ban_reason` | Moderation state | Until account deletion |
| `deletion_requested_at` | Self-service deletion grace-period marker | Cleared on re-login (cancels); otherwise until the grace period elapses and the row is purged |
| `total_watch_minutes` | Precomputed ranking/leaderboard metric, derived from the user's own watch data | Until account deletion |
| `created_at`, `last_active_at` | Account age, usage-based admin metrics | Until account deletion |

## Library / watch history

| Table | Purpose | Retention |
|---|---|---|
| `LibraryEntry` | Tracked titles, status, rating, notes, custom poster/backdrop/episode-still uploads | Until the user removes the item or deletes their account |
| `EpisodeWatch`, `WatchEvent` | Per-episode/per-watch-through watch history, ratings | Same as above; deleted with the owning `LibraryEntry` |
| `EpisodeCustomStill` | User-uploaded per-episode images | Same as above |

## Social

| Table | Purpose | Retention |
|---|---|---|
| `Comment`, `CommentLike`, `CommentReport` | User-authored comments on titles/episodes, reactions, abuse reports | Until deleted by the author or moderated (see `routers/admin/moderation.py`); until account deletion otherwise |
| `Review`, `ReviewWhitelist` | User-authored title reviews, reviewer-flair eligibility | Until deleted by the author or account deletion |
| `Follow`, `List`, `ListItem` | Social follow graph, user-created custom lists | Until account deletion |

## Notifications

| Table | Purpose | Retention |
|---|---|---|
| `Notification` | New-episode/new-film alerts, in-app only (no push yet — see `TODO.md`'s push-notifications entry) | Until read/dismissed by the user or account deletion |

## Security / abuse prevention

| Field/Table | Purpose | Retention |
|---|---|---|
| `LoginEvent.user_id` + timestamp | Per-day login chart on the admin panel | Indefinite (append-only, low-volume — one row per login) |
| `EndpointStat`, `RequestDay` | Aggregated per-route/per-day request counters (usage metrics, rate-limiting), keyed by `user_id` where authenticated | Indefinite (aggregated counts, not raw request logs) |
| `BannedIP.ip`, `Strike.ip` | Abuse-prevention: banned/repeat-offender client IPs | `BannedIP` until an admin unbans; `Strike` until the ban threshold or the row ages out (see `docs/anti-abuse.md`) |
| Request IP (rate-limit middleware) | Transient in-process rate/flood detection (see `docs/anti-abuse.md`) | Not persisted per-account; only `BannedIP`/`Strike` (keyed by IP, not by user) survive a restart |

## Not collected

- Precise device location (no GPS/location permission requested).
- Payment/card data (premium is currently admin-granted only — see
  `TODO.md`'s Monetization section; no payment processor is
  integrated yet).
- Contacts, SMS, call logs, or any other device data beyond what's listed
  above.
- Advertising identifiers (no ad SDK integrated — see `TODO.md`'s
  parked Ads item).

## Account deletion

`DELETE /auth/me` (self-service) or an admin hard-delete both funnel through
`users/accounts.py::delete_account`, which removes every row above tied to
the account (library, watches, comments, reviews, lists, notifications,
login events, images) in FK-safe order, then the `User` row itself — see
that function for the exact deletion order. A grace period
(`SiteSettings.deletion_grace_days`) delays the final purge so a self-service
deletion can be cancelled by logging back in before then.

## Third parties data is shared with

- **TMDB / TheTVDB**: outbound lookups by title/tmdb_id only — no user PII is
  sent, only catalog queries.
- **Brevo** (transactional email): recipient email address + confirmation
  code, for account-related email only (see
  `users/email_confirmation.py`).
- No analytics, advertising, or data-broker third parties are integrated.
