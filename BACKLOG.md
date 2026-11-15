[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/14 16:40:50.586421 )
[//]: # (+ Revised: 	2026/11/15 11:56:20.851748 )
[//]: # ( ---------------------------------------------------------------------- )

# Backlog

Ideas worth keeping that don't block 1.0 and aren't planned yet. Planned
work (everything that blocks 1.0) lives in `TODO.md`; nothing here is picked
up by "do next". Items are light on purpose: the full spec is written when
an item is promoted to `TODO.md`, against the code as it is then. Items
parked from `TODO.md` on 2026-11-14 keep their original text under Notes.

Next backlog number: 19

## Index

- [B1. Set up WSL on the dev machine and actually run mutmut](#b1-set-up-wsl-on-the-dev-machine-and-actually-run-mutmut)
- [B2. Planned: "watched on" (streaming source) import mapping](#b2-planned-watched-on-streaming-source-import-mapping)
- [B3. Additional external rating sources (IMDb, Rotten Tomatoes, Metacritic) alongside TMDB's `vote_average`](#b3-additional-external-rating-sources-imdb-rotten-tomatoes-metacritic-alongside-tmdbs-vote_average)
- [B4. Watched-on / streaming source tracking — user priority (2026-07-21)](#b4-watched-on--streaming-source-tracking--user-priority-2026-07-21)
- [B5. Ranking only covers total overall watch time; no badges/achievements exist yet](#b5-ranking-only-covers-total-overall-watch-time-no-badgesachievements-exist-yet)
- [B6. Registration-flow-around-the-toggle: two open product-policy questions remain, neither blocking](#b6-registration-flow-around-the-toggle-two-open-product-policy-questions-remain-neither-blocking)
- [B7. Real phone number confirmation on registration](#b7-real-phone-number-confirmation-on-registration)
- [B8. Share — add a deep link once the frontend's share cards are ready for one](#b8-share--add-a-deep-link-once-the-frontends-share-cards-are-ready-for-one)
- [B9. Social login: Continue with Google / Continue with Apple](#b9-social-login-continue-with-google--continue-with-apple)
- [B10. Recommendation feed: infinite-scroll "what to watch next"](#b10-recommendation-feed-infinite-scroll-what-to-watch-next)
- [B11. Push notifications (system notifications while the app is closed)](#b11-push-notifications-system-notifications-while-the-app-is-closed)
- [B12. No human-facing mailbox on `breren.com` yet (e.g. `support@`/`hello@`)](#b12-no-human-facing-mailbox-on-brerencom-yet-eg-supporthello)
- [B13. Admin/mod accounts still lack per-account roles](#b13-adminmod-accounts-still-lack-per-account-roles)
- [B14. No payment integration wired to the app stores — and mobile can't just reuse a web payment flow](#b14-no-payment-integration-wired-to-the-app-stores--and-mobile-cant-just-reuse-a-web-payment-flow)
- [B15. Diary: list every rewatch as its own entry](#b15-diary-list-every-rewatch-as-its-own-entry)
- [B16. Community average for season grades](#b16-community-average-for-season-grades)
- [B17. Streaming availability: country, subscribed services and a library filter](#b17-streaming-availability-country-subscribed-services-and-a-library-filter)

## Using the backlog

- Write for someone who has never seen the conversation: what happens today,
  what is wrong with it, and the result wanted.
- Number new items with "Next backlog number" (B1, B2, …), add them at the
  end, then increase that number. Deleting leaves a gap; nothing is renumbered.
- Keep the Index in file order: one `- [B<n>. title](#anchor)` line per item;
  update it whenever an item is added, retitled or deleted.
- Screenshots go in `docs/todo/B<n>-<slug>.png`, linked from the item.
- To build an item, promote it: it becomes a full `TODO.md` item and leaves
  this file.
- Items older than 6 months get reviewed: keep, promote or drop.

## Template

```markdown
## B<n>. <short imperative title>

**Added:** YYYY-MM-DD · Area: <area>
**Why:** what happens today and what is wrong with it.
**Goal:** the result, as the user will see it.

### Notes
- What is already known: files involved, constraints, related items, links.
```

---

## B1. Set up WSL on the dev machine and actually run mutmut

**Added:** 2026-11-14 · Area: Testing
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

`mutmut` refuses to run at all on native Windows — not a project
limitation, a hard-coded refusal in the tool itself (`mutmut --help`
prints "To run mutmut on Windows, please use the WSL" and exits without
doing anything, pointing at their own open tracking issue,
github.com/boxed/mutmut/issues/397, for native Windows support that
hasn't landed). The dev machine has the `wsl.exe` launcher but not a
working WSL runtime (`wsl --status`/`-l -v`/`--list` all fail with
`WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED` — the Windows optional feature
isn't enabled and no distro is installed). Needs: `wsl --install
--no-distribution` (enables the feature, likely needs a restart), a
distro (`wsl --install -d Ubuntu` or similar), then `uv`/Python set up
inside it to actually run `[tool.mutmut]`'s config against this repo.
Once that's done, the `[tool.mutmut]` config in `pyproject.toml` can be
verified for real instead of carrying the "unverified" caveat in
`docs/design-decisions.md`, and `paths_to_mutate` can be widened from
`models.py` + `schemas.py` toward the whole `src/` tree. This is the only
test type the suite has configured but never run.

## B2. Planned: "watched on" (streaming source) import mapping

**Added:** 2026-11-14 · Area: Import system (`routers/imports.py`) / TV Time import
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

Once the "Watched-on / streaming source tracking" feature (Features
below) exists, this importer needs matching read-and-map logic:
`watched_on_episode.csv`/`followed_tv_show_source.csv` (source id per
episode/show watch — both files are confirmed present in a real GDPR
export carrying `watched_on_source_id`; the field exists, only the enum
isn't documented anywhere in the export itself, so its meaning needs
reverse-engineering, e.g. by cross-checking a few known-source watches in
a real account against the app's UI). Explicitly decided *not* to build
in this pass: per-episode emotion reactions (`episode_emotion.csv`,
`tv_show_user_emotion_count.csv`) — real discrete `emotion_id` values do
exist in the export (unlike star votes, which don't carry a value at
all — see above), but adding a whole reaction system duplicates the
existing 1-100 rating for questionable value, and TV Time's emotion enum
isn't fully documented from the sample export (only 4 of what's
presumably ~8 values were observed, no confirmed label mapping).

## B3. Additional external rating sources (IMDb, Rotten Tomatoes, Metacritic) alongside TMDB's `vote_average`

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

OMDb (omdbapi.com) is the candidate
source — a single call returns IMDb rating + vote count, plus Rotten
Tomatoes and Metacritic scores in its `Ratings` array. Only the IMDb
entry carries a vote count; RT/Metacritic expose a score with no count
(neither has a public API of its own, so there's no way to backfill
that). OMDb looks up by IMDb ID, and `titles.imdb_id` is being added to
the schema (populated from TMDB's `external_ids`, alongside `tvdb_id`
and `wikidata_id`) specifically so this lookup doesn't need its own
title-matching step. Not scoped in detail yet — open questions: caching/
refresh cadence for OMDb responses, how a second/third rating source
folds into the existing weighted-mean blend (see `docs/design-
decisions.md`'s rating-scale entry), and whether RT/Metacritic scores
(no vote count) should even enter that weighted blend or just display
alongside it.

## B4. Watched-on / streaming source tracking — user priority (2026-07-21)

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

Record which platform/service an episode or movie was watched on (TV Time
has `watched_on_source_id` per episode watch, and a per-show
followed-source too). No field for this exists on
`EpisodeWatch`/`WatchEvent`/`LibraryEntry` yet. Not scoped in detail yet —
open questions: free-text vs. a fixed enum/picker of streaming services,
per-watch or per-show granularity, and whether it's shown/filterable in
the UI or just recorded. The TV Time importer would need
`watched_on_source_id`'s meaning reverse-engineered first (see the TV Time
import section above) before it can map source ids to whatever this ends
up being.

## B5. Ranking only covers total overall watch time; no badges/achievements exist yet

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

`routers/stats.py:205-210`'s `RANKING_METRICS` currently
registers a single metric, `watch_time` (total minutes across
everything). The ranking system is pluggable by design (add a
`RankingMetric` entry and it's picked up by `/stats/ranking` and
`/stats/ranking/metrics` automatically), so this is a scoping/build-out
gap, not an architecture gap. Wanted: more granular time-based rankings
(time watching shows vs. movies, time per show, per franchise, per
genre/category), likely computed from the same watch-history data
`routers/stats.py` already aggregates. Separately, a TV Time-style
**badge/achievement system — user priority (2026-07-21)** — unlockable badges for specific
accomplishments (e.g. finishing a franchise, a binge streak, watching
N hours of a genre) — doesn't exist at all yet: no `Achievement`
table, no per-user unlock rows, no UI for it. This is a real departure
from the current badge design, which is explicitly "one derived badge,
never a stored list" (see `docs/design-decisions.md`). Needs scoping:
which per-category rankings to add first, and what the badge set /
unlock conditions look like.

## B6. Registration-flow-around-the-toggle: two open product-policy questions remain, neither blocking

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

The toggle
(`SiteSettings.email_confirmation_enabled`) and its two bulk-confirm/
bypass mechanics above were each added reactively, one migration at a
time (`ffffe2b24717` grandfathering → `1b63409d9417` dropping it for a
direct bulk `email_confirmed = True` → `6d15f435ffcf` adding
`email_confirmation_bypassed`), rather than designed as one flow up
front. Worth a proper pass rather than another one-off patch.

**What shipped in the 2026-07-29 session** (context for the open
questions below — see `docs/design-decisions.md`'s "`email_confirmed`
is authoritative" entry for the full reasoning):
- Backend: migration `4b2026dc80cd` (email sender name/address and
  confirmation-code TTL moved from fixed constants onto `SiteSettings`)
  and migration `68156a912acf` (grace-period days and cleanup-days,
  same move), both admin-editable on the Site Settings page; migration
  `1b63409d9417` (dropped `email_confirmation_grandfathered`,
  bulk-marked every pre-rollout account `email_confirmed = True`
  directly); migration `6d15f435ffcf` (added
  `User.email_confirmation_bypassed`, set at registration when the
  toggle is off and at the admin's bulk-confirm-on-disable). New
  `/auth/confirm-email-session`, `/auth/resend-confirmation-session`,
  `/auth/change-unconfirmed-email-session` (bearer-token twins of the
  existing credential-based endpoints, for a still-logged-in but
  unconfirmed session); `_resend_confirmation`/`_confirm_email_code`'s
  "already confirmed" guard loosened to let a *bypassed* account through
  (and clear the flag on a real completed round trip), so the voluntary
  flow below has something to call. `routers/admin/users.py`: the email
  cell's tooltip now distinguishes a real OTP round trip from a bypassed
  one; `routers/admin/settings.py` grew the new Email section.
- Frontend: `confirm_email_view.py` reworked to support session mode
  (`use_session`), client-side code-expiry countdown, reactive
  stale/expired-code detection, and four distinct framings via
  `confirm_reason` (`register`, `login_reminder`, `login_blocked`,
  and the new `voluntary`). New `profile_view.py` "Verify email" tile,
  shown only when `/auth/me` reports `email_confirmation_bypassed`,
  routing into the same view in voluntary/session mode. `UserOut` gained
  `email_confirmation_bypassed` so the client can see it at all.
- Tests: `tests/test_email_confirmation.py` grew coverage for the bypass
  flag being set on both paths (registration-time, bulk-confirm-on-disable),
  re-enabling not retroactively re-locking anyone, a real OTP round trip
  leaving the flag `False`, and the new voluntary-confirmation-via-session
  path (`test_bypassed_account_can_request_and_complete_voluntary_confirmation`,
  `test_genuinely_confirmed_account_still_rejects_resend`). Full backend
  suite (552 tests) green.
- Docs: this backlog entry, plus a matching entry in renar-frontend's
  `TODO.md` and both repos' `docs/design-decisions.md` — see
  those for the reasoning behind each piece, not repeated here.

The toggle-flip race between `register()`'s single read of
`ss.email_confirmation_enabled` and the admin's bulk-confirm-on-disable
`UPDATE` was investigated and accepted as a low-probability, bounded risk
rather than engineered around — see `docs/design-decisions.md`'s
"Email-confirmation toggle-flip race: accepted, not engineered around."
Admin visibility into bypassed-vs-confirmed counts (previously an open
question here) now exists: `routers/admin/users.py`'s "Bypassed
Confirmation" stat tile.

Two open product-policy questions remain, neither blocking further
engineering work:
- **Re-enabling never re-locks anyone, on purpose
  (`test_reenabling_feature_does_not_unconfirm_bulk_confirmed_users`)**
  — is that the right permanent policy, or should there be a way to
  later require bypassed accounts to actually verify (e.g. if the site
  moves from invite-only/low-trust to open registration and wants to
  tighten retroactively)? Right now the only way back to "really
  confirmed" is the voluntary profile tile, which nothing nudges anyone
  toward.
- **Ranking currently doesn't distinguish real vs. bypassed
  confirmation** — `_compute_ranking` only checks `email_confirmed`,
  so a bypassed account (never proved ownership) ranks exactly like a
  verified one. Intentional per `docs/design-decisions.md`'s
  "`email_confirmed` is authoritative" entry, but worth an explicit
  product decision on whether that's acceptable long-term, especially
  if the toggle gets flipped off temporarily just to onboard a batch of
  users quickly.
- **The voluntary "Verify email" tile (renar-frontend's
  `profile_view.py`) is entirely passive** — shown, never surfaced via
  notification/reminder/badge. Decide whether that's sufficient or
  whether bypassed accounts should get any kind of nudge, and if so
  how that squares with "no obligation" being the whole point of the
  tile.

## B7. Real phone number confirmation on registration

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

Same shape as the
email-confirmation item above, but there's currently no phone number
field on `User` at all (`models.py:111-151`) — this needs the field
added first, plus an SMS-sending capability (no provider integration
exists yet; candidates like Twilio/Vonage aren't wired up), a generated
one-time code with expiry, and a verification endpoint accepting
`phone` + `code`. Open questions: is phone number required at
registration or optional/add-later; does it replace or supplement email
confirmation; which SMS provider (cost, coverage — matters if
international numbers are expected).

## B8. Share — add a deep link once the frontend's share cards are ready for one

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

renar-frontend's share buttons (title cards, title page,
comment tiles) already ship, generating a branded PNG card (Pillow,
client-side) and handing it to the native share sheet / clipboard — this
works standalone today, no link involved, since there's no public web
frontend hosted yet to link to (see renar-frontend's `TODO.md`).
This backend half is the add-on for whenever that changes: shareable deep
links or redirect URLs for a title page, a specific episode, and a
comment (anchor within a thread). Options: generate canonical share URLs
in the API response, or add a `/share/{type}/{id}` redirect endpoint.
Decide on a URL scheme once `renar.app` is actually hosting
something to redirect to.

## B9. Social login: Continue with Google / Continue with Apple

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

Not committed — revisit once real signup-funnel data shows password-registration
drop-off is a problem worth solving. Would need nullable `google_id`/`apple_id`
columns on `User` (with nullable `password_hash`), new Alembic migration, new
`/auth/google`/`/auth/apple` endpoints, `google-auth` + JWKS verification for
Apple, `GOOGLE_CLIENT_ID`/`APPLE_*` env vars. Apple requires an Apple Developer
account and is mandatory if Google sign-in is also offered on iOS. Decide on
native plugin bridge vs. OAuth web-redirect before scoping further.

## B10. Recommendation feed: infinite-scroll "what to watch next"

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

Not committed — needs design work on what signals feed the taste model before
scoping endpoints. Would need a "taste inferer" (model/heuristic from watch
history, ratings, dwell time), new endpoint(s) in `routers/recommendations.py`,
implicit-signal recording (skip, completion, dwell), and cold-start handling
for new users. Open question: in-house collaborative/content-based filtering
vs. external recommendation service.

## B11. Push notifications (system notifications while the app is closed)

**Added:** 2026-11-14 · Area: Features
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

`notifier.py`'s `check_new_episodes` only ever writes an in-app `Notification`
row — nothing reaches the device when the app isn't open. A killed-app
system notification from a server-side event requires going through the
OS's push channel (FCM on Android, APNs on iOS); there's no way around
that requirement on stock Android/iOS. Scoped approach: **OneSignal via
the `flet-onesignal` PyPI package** (actively maintained, MIT, requires
`flet>=0.80.0` — no known incompatibility with this repo's `flet==0.85.3`,
not yet smoke-tested) instead of hand-rolling `firebase_messaging` +
pubspec overrides — OneSignal hosts the device-token/delivery layer, the
backend only calls its REST send API. Still required regardless of this
choice: a Firebase project (Service Account JSON, Android FCM credentials)
and an Apple Developer account + APNs certificate for iOS — OneSignal sits
on top of those, it doesn't remove them.

**Platform scope: Android/iOS/mobile web only, Windows explicitly out.**
OneSignal's Windows support is WNS-on-UWP only, not the Windows App
SDK/WinUI3 target a modern Flet Windows build would use — and desktop
isn't a maintained distribution target for Renar in the first place (see
the Turnstile-widget desktop gap above), so this isn't worth chasing a
different provider for. Cost at this scope: free — OneSignal's Free plan
is unlimited mobile push sends, and web push is free up to 10,000
subscribers per send (paid tiers only kick in past that subscriber count,
not from notification volume) — worth revisiting only if/when web push
subscribers approach that number.

**Film releases currently generate no notification at all, in-app or
push.** `check_upcoming_films` (below) only refreshes `Title.release_date`
for `/upcoming` — it never writes a `Notification` row the way
`check_new_episodes` does for episodes. Since this backlog item is
explicitly "new episodes/films", closing that gap (a same-day-of-release
in-app + push notification, mirroring `check_new_episodes`'s dedupe-by-row
pattern but keyed on the film releasing rather than an episode airing) is
part of this item's scope, not a separate one.

**Decisions locked in during scoping (2026-07-21):**
- **REST shape:** extend `routers/notifications.py` with `POST
  /notifications/devices` and `DELETE /notifications/devices/{player_id}`
  rather than a new router — same auth dependency, two endpoints don't
  warrant a new file.
- **v1 kill switch:** none beyond "unset `ONESIGNAL_REST_API_KEY` = feature
  off", matching the existing `brevo_api_key` convention. No `site_settings`
  DB toggle for v1 — a live admin kill switch is a fast-follow, not launch-blocking.
- **Push call shape:** one OneSignal API call per `Notification` row
  created, fired synchronously right after `db.add(Notification(...))`,
  inside the existing per-show/per-title commit boundary (never batched
  across a whole scan) — a push failure must never block `Notification`
  creation or the notifier loop.
- **Tap deep-link:** push `data` payload carries `media_item_id` + `kind`;
  the tap handler reuses `notifications_view.py`'s existing
  `title_ctx`/`navigate_safe(page, "/title")` pattern to jump straight to
  the title, not a generic open-to-notifications-list.
- Confirmed **not** premium-gated — notifications are core tracking
  utility, not a cosmetic perk (see `premium.py`'s existing perk list, all cosmetic).
- Out of scope for v1: Windows/desktop, live admin kill switch, rich media
  push, retry/queueing on push failure, badge counts, OneSignal
  external_user_id linking, notification quiet-hours.

**Backend work:**
- New `DeviceToken` model (`models.py`, after `Notification`): `user_id`
  FK (indexed), `player_id` (`String(64)`, `UniqueConstraint` on
  `player_id` alone — not `(user_id, player_id)`, since a player_id is
  unique per OS-level install and registering it under a different
  logged-in user should move ownership, not duplicate the row),
  `platform` (`"android"`/`"ios"`/`"web"`), `created_at`. One row per
  device, so one-to-many against `User`, not a column on it. New Alembic
  migration (`down_revision` = current head `a4d6e1b8c2f7`), following
  `b2f7a6d391ea_add_import_jobs_table.py`'s template. `users/accounts.py`'s
  `delete_account` needs a new line purging `DeviceToken` rows for the
  user, same FK-safe-order pattern as every other user-referencing table there.
- `config.py`: `onesignal_app_id`/`onesignal_rest_api_key`, both
  `str = ""` next to `brevo_api_key`, same "empty = disabled, log instead
  of send" convention as `send_confirmation_email`. App ID isn't secret
  (ships client-side); REST key is server-only. Frontend gets its own
  `ONESIGNAL_APP_ID` in `renar-frontend/.env` rather than fetching it from
  the backend, since the SDK needs it very early at page/session setup.
- New `social/onesignal.py` helper mirroring `users/email_confirmation.py`'s
  Brevo integration line-for-line: pooled `httpx.Client`, `send_push(player_ids,
  title, body, data=None)` that never raises (logs-and-swallows on missing
  key or `httpx.HTTPError`) — callers in `notifier.py` depend on that guarantee.
- `check_new_episodes` (`social/notifier.py:109-119`) gains a `send_push`
  call right after each `db.add(Notification(...))`, inside the per-item
  loop, before the per-show `db.commit()`.
- `check_upcoming_films` (`social/notifier.py:131-162`) needs restructuring
  to close the "no film notification at all" gap noted above: shift its
  query from distinct `Title` rows to `LibraryEntry` rows (regaining
  per-user granularity, grouped by `tmdb_id` so one TMDB fetch still
  serves every tracking user, same shape `check_new_episodes` already
  uses), notify only once release day has actually arrived (a
  `RECENT_DAYS`-style window, not on every "coming soon" refresh), dedupe
  via the existing `Notification` unique constraint with a new
  `kind="film_released"` (season/episode stay `NULL`).

**Frontend work:**
- Add `flet-onesignal==0.85.*` to `[project.dependencies]` in
  `pyproject.toml` (next to `flet-webview` — confirmed via its own
  `pyproject.toml` that it depends only on `flet>=0.80.0`, no heavy native
  transitive deps the way `flet-web` has, so the dependency-groups
  isolation trick `flet-web` needs shouldn't apply here, but worth a `flet
  build apk` smoke test to confirm before assuming safe). Any Android
  manifest `meta-data` OneSignal needs should go through
  `[tool.flet.android.meta_data]` (a real supported `flet_cli` key) —
  **not** a hand-patch under `build/flutter/android/...`, which is exactly
  the fragility the Turnstile `usesCleartextTraffic` note already warns
  about (edits there aren't source-controlled and vanish on
  `--clear-cache`/a flet version bump/fresh checkout).
- `api_client.py`: `register_device_token(player_id, platform)` /
  `deregister_device_token(player_id)`, same `_request()` pattern as the
  existing `/notifications` methods (~line 707-725).
- SDK init in `main.py` near page/session setup (exact `flet-onesignal`
  call names not yet confirmed against the installed package — check
  before writing). Register hooks at two points: `complete_login`
  (`views/auth/auth_views.py:102-147`, the single shared post-login entry
  point for both normal login and post-email-confirm login) and the
  app-start saved-session restore in `main.py` (~268-287), so a device
  re-registers even without a fresh login. Deregister hook at logout
  (`views/profile/profile_view.py:449`) — must fire **before**
  `api.logout()` clears the bearer token, since deregistering needs auth.
- Tap-to-deep-link: OneSignal's "notification opened" callback reads
  `data.media_item_id` and reuses `notifications_view.py`'s existing
  `title_ctx` + `navigate_safe(page, "/title")` pattern.

**Backend test plan** (pytest, real DB, happy path + error paths per this
repo's convention): register/deregister endpoints (happy path, upsert
moves ownership between two users, wrong-owner deregister is a no-op, 401
unauthenticated); `check_new_episodes` sends push exactly once per
notified user with the right payload, a push failure never blocks the
`Notification` row or rolls back the commit, no `DeviceToken` means no
error; `check_upcoming_films` creates a `film_released` notification only
once release day arrives and dedupes on a second run, no notification
before release (regression guard for existing `/upcoming` behavior);
`onesignal.send_push` no-ops cleanly with the key unset and swallows HTTP errors.

**Manual verification needs a real Android device** — FCM token delivery
is unreliable on emulators. Full device (force-kill app → trigger
`check_new_episodes`/`check_upcoming_films` → confirm notification arrives
and tap opens the right title) → logout (confirm `device_tokens` row
deleted server-side) → uninstall/reinstall (confirm re-login registers a
fresh row, no error on the stale one) pass needed before shipping. iOS
pass (TestFlight/ad-hoc + APNs cert) is a stretch goal for the same pass,
not a blocker for an Android-first ship.

## B12. No human-facing mailbox on `breren.com` yet (e.g. `support@`/`hello@`)

**Added:** 2026-11-14 · Area: Infrastructure
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

Distinct from the OTP-sending item above (Brevo, transactional-only, no
inbox): this is for a real mailbox a person actually reads/replies from —
support requests, store-listing contact address, domain-registrar
correspondence. **Zoho Mail free plan** is the pick: up to 5 users, 5GB
each, free custom-domain mailbox with webmail + IMAP/POP, no card
required. **Domain: apex `breren.com`, not `renar.breren.com`** — mail
conventionally lives on the root domain regardless of which subdomain an
app's API sits on, and this keeps it usable if `breren.com` ever hosts
more than just Renar. Needs, once the subdomain/DNS work above lands:
domain verification TXT, MX records (`mx.zoho.com`/`mx2`/`mx3`), SPF/DKIM
TXT records, optionally DMARC. Not started — same Cloudflare DNS zone as
the Turnstile item above, so batch with that when DNS is next touched.

## B13. Admin/mod accounts still lack per-account roles

**Added:** 2026-11-14 · Area: Infrastructure
**Why:** the admin panel has one shared login: `ADMIN_USERNAME`,
`ADMIN_PASSWORD_HASH` (after `TODO.md` item 29) and `ADMIN_TOTP_SECRET` in `.env`,
checked in `users/admin_session.py`. That works for one operator but can't
give a second person access, take it away from one person, or tell from the
logs who did what. `models.User` has no role field (only `banned`,
`verified`, `is_premium`), so a moderator can't be an ordinary renar account
with extra rights. clavren keeps admins in their own table because it has no
user accounts; renar already has `users` with bcrypt password hashes, so
admin should be a role on those accounts instead of a second account system.
**Goal:** an admin or moderator signs in to the panel with their own renar
account plus their own authenticator code; the operator grants and removes
the role per account; `.env` holds no admin login at all.

### Notes

**Behaviour**

- Roles: `admin` (everything the panel does today) and `moderator`
  (Moderation and Users pages only, no Settings, Update, Invites, Premium,
  App Releases). An account has at most one role; no role = ordinary user.
- An account with a role can't use the panel until it has enrolled TOTP;
  enrolment shows the QR once and ten single-use recovery codes.
- TOTP secrets are stored encrypted (AES-256-GCM) with a key file outside
  the database (`ADMIN_KEY_FILE`, default `<data dir>/admin.key`, mode
  `0600`, created on first boot), so a database dump alone can't produce
  codes. Recovery codes are stored hashed.
- Sign-in uses the account's existing password (bcrypt, `users/auth.py`)
  plus the code; strikes, backoff and Exempt IPs behave as today.
- `uv run admin-grant <username> admin|moderator` and
  `uv run admin-revoke <username>` from the server shell; revoking ends that
  account's admin sessions at once. The panel can't remove the last `admin`.
- Session cookies carry the account id; the fingerprint includes the role
  and TOTP secret version, so a revoke or re-enrolment signs that account out.
- The admin audit log (where one exists) records the account, not "admin".
- `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` and `ADMIN_TOTP_SECRET` are
  removed; a migration-time CLI step grants `admin` to the operator's
  account first, and boot refuses those three variables if still set.
  `ADMIN_API_TOKEN` stays for scripts.

**Out of scope**

- A UI for granting roles (CLI only at first).
- Finer permissions than the two roles.
- Changing how app users sign in.

**Implementation**

Split into items before building (it's more than one sitting): (a) schema
and key file, (b) sign-in and sessions on accounts, (c) TOTP enrolment and
recovery codes, (d) moderator restrictions per page, (e) removing the `.env`
login. Each needs its own Implementation, Tests and Docs per the template;
`role` lives in its own table keyed by `user_id` if that keeps the schema
BCNF (run `tests/test_normalization.py`).

## B14. No payment integration wired to the app stores — and mobile can't just reuse a web payment flow

**Added:** 2026-11-14 · Area: Publishing (app stores, web, going public)
**Why / Goal:** free-form text carried over from `TODO.md`, kept whole under Notes; split it into
Why and Goal when the item is promoted.

### Notes

`premium_until` is admin-granted only today
(see `docs/design-decisions.md:441-450`); there's no Stripe/PayPal/IAP
integration at all yet. If premium becomes purchasable from inside the
mobile apps, Apple and Google **require their native in-app-purchase
systems** for digital subscriptions — routing that through a web checkout
(e.g. Stripe) inside the app is a store-rejection, not a warning.
Decide before scoping: (a) wire RevenueCat or raw StoreKit/Play Billing
for mobile premium, keeping any web-based Stripe flow separate, or (b)
ship the first store release with premium still admin-granted only and
add IAP in a later version. Option (b) is the smaller first step. If a
web checkout is added, prefer a merchant-of-record processor (Stripe Tax,
Paddle, or similar) rather than raw Stripe — it keeps VAT/sales-tax
collection and PCI card-data scope off Renar entirely.

## B15. Diary: list every rewatch as its own entry

**Added:** 2026-11-14 · Area: Features
**Why:** `GET /diary` (`routers/diary.py`) returns one row per watched
episode and one per completed film, dated at the latest watch. A film
watched in 2024 and again in 2026 shows once, in 2026; the 2024 watch is
missing from the log, although `WatchEvent` rows record each rewatch with
its own date and rating.
**Goal:** the diary lists every watch: the first watch and each rewatch,
each on its own day with the grade given that time.

### Notes

**Behaviour**

- A title or episode watched three times gives three diary rows.
- A rewatch row carries that rewatch's own rating (`WatchEvent.rating`),
  or none when it wasn't graded; the first watch keeps the entry's rating.
- Each row says which watch it is (`watch_number`, 1 for the first).
- Filters (`type`, `from`, `to`) and paging apply to the combined list.
- Deleting one rewatch (the existing per-event undo) removes its row only.

**Out of scope**

- Editing a watch date from the diary.
- Any change to how rewatches are recorded.

**Implementation**

1. `src/renar_backend/models.py`: read `WatchEvent` and how film and
   episode rewatches are stored, and write down in the docstring of
   `routers/diary.py` which row is the first watch and which are rewatches.
2. `src/renar_backend/routers/diary.py`: add the rewatch rows to the
   union, with the same columns; order by `watched_at` then a stable
   tie-break (source, id).
3. `src/renar_backend/schemas.py`, `DiaryEntryOut`: add `watch_number: int`
   (default 1).
4. `renar-frontend/src/renar_frontend/views/stats/diary_view.py`: show a
   small "rewatch" label on rows with `watch_number > 1`; add the string to
   all four locales in `i18n/translations.py`.

## B16. Community average for season grades

**Added:** 2026-11-14 · Area: Features
**Why:** a user can grade a season they finished
(`PUT /media/{id}/seasons/{season}/rating`, table `season_ratings`), but
the grade is only ever shown back to them. Titles and episodes show
Renar's community average next to the user's own; seasons show nothing,
and the season share card can only carry the sharer's grade.
**Goal:** each season shows the average grade Renar users gave it, with
the number of votes, the way episodes do.

### Notes

**Behaviour**

- A season with at least one grade has an average (1-100) and a count.
- Setting, changing or clearing a grade updates the average at once.
- Deleting an account removes its grades from the averages.
- A season nobody graded has no average (not zero).

**Out of scope**

- Any external (TMDB) season rating.
- Ranking or statistics built on season grades.

**Implementation**

1. `src/renar_backend/models.py` and a new Alembic revision: a
   `season_rating_aggregates` table (title, season, `rating_sum`,
   `rating_count`) kept by a database trigger on `season_ratings`, the
   same pattern as `episode_rating_aggregates` (see "the same trigger
   pattern" in `docs/design-decisions.md`), so the average never drifts
   from the rows.
2. `tests/test_normalization.py`: run it; register the aggregate the same
   way `episode_rating_aggregates` is, with the reason in
   `docs/design-decisions.md`.
3. `src/renar_backend/routers/media.py`, `list_episodes`: return
   `season_averages` (season → average and count) next to
   `season_ratings`; add the field to `EpisodeListOut` in `schemas.py`.
4. `renar-frontend/src/renar_frontend/views/title/title_view.py`: show the
   average beside the season rate button with the existing rating chip;
   pass it to the season share card when the user has no grade of their
   own or has "My rating on share cards" off.

## B17. Streaming availability: country, subscribed services and a library filter

**Added:** 2026-11-14 · Area: Features
**Why:** the app knows what a user wants to watch but not where they can
watch it. Nothing in the backend stores which streaming services a user
pays for, which country they are in, or which services carry a title: there
is no provider table, no country column on `users`, and `GET /media` can
only filter by type, status, favorites and search. A user with a long
"Planned" list has to look each title up elsewhere to find one they can
start tonight.
**Goal:** a user saves their country and the streaming services they have,
and `GET /media?available_only=true` returns only the library entries (any
status) that one of those services carries in that country. The frontend
half is renar-frontend's backlog item B22.

### Notes

**Behaviour**

- Availability comes from TMDB's watch-provider data (supplied by
  JustWatch): `/movie/{id}/watch/providers` and `/tv/{id}/watch/providers`
  return every country's offers in one call.
- Only offers a subscriber can watch without paying per title count:
  TMDB's `flatrate`, `free` and `ads` lists. `rent` and `buy` are ignored,
  because "I have Netflix" says nothing about renting.
- Free for every account, not a premium feature: it is a way to find
  something to watch, the app's core use.
- The country is a stored setting (ISO 3166-1 alpha-2, upper case), chosen
  by the user. The server only suggests one: `GET /streaming/mine` returns
  `suggested_country` from the `CF-IPCountry` request header when
  `settings.trust_proxy_headers` is true (prod sits behind Cloudflare), and
  null otherwise (the dev PC). Why stored and not always the header: a VPN
  or a trip would silently change every result, and dev has no header.
- `GET /streaming/regions` → `[{code, name}]`, the countries TMDB has
  provider data for, sorted by name.
- `GET /streaming/providers?country=ES` → `[{id, name, logo_url}]`, the
  services offered in that country (TMDB's movie and TV provider lists for
  that `watch_region`, merged by id, ordered by TMDB's `display_priority`).
  An unknown country code → 422.
- `GET /streaming/mine` → `{country_code, provider_ids, suggested_country}`
  (`country_code` null and `provider_ids` empty until set).
- `PUT /streaming/mine` with `{country_code, provider_ids}` replaces both.
  A country not in the regions list or a provider id not offered in that
  country → 422 naming the bad value. Saving starts a background sync of
  the offers of every library title of that user never synced before.
- `GET /media?available_only=true` keeps only entries whose title has an
  offer in the user's country from one of the user's services; it combines
  with every existing filter and with paging. No country or no services
  saved → 409 "Choose your country and streaming services first".
- A title without a `tmdb_id` has no offers and never matches.
- Offers go stale (catalogues change monthly): a title's offers are
  refreshed when it is first added to any library and then by a periodic
  task once they are 7 days old.
- TMDB down during a sync: the stored offers stay as they are, the failure
  is logged, and the next run retries.
- Account deletion removes the user's service rows; the `.renar` export
  and import carry `country_code` and the provider ids.

**Out of scope**

- Showing "where to watch" on a title page for services the user does not
  have, rent/buy prices and deep links into the services' apps.
- Recording where something was watched (backlog item B4) and its import mapping
  (backlog item B2).
- Detecting the country from GPS or the device locale.

**Implementation**

1. `src/renar_backend/models.py`: add `User.country_code`
   (`String(2)`, nullable); `StreamingProvider` (`id` = TMDB's
   `provider_id` as primary key, `name`, `logo_path`);
   `UserStreamingProvider` (`user_id`, `provider_id`, both foreign keys,
   together the primary key); `TitleWatchOffer` (`title_id`,
   `country_code`, `provider_id`, together the primary key, index on
   (`country_code`, `provider_id`)); `Title.watch_offers_synced_at`
   (timestamptz, nullable). Every table is all-key or key → attributes, so
   BCNF holds; run `tests/test_normalization.py` and do not widen its
   allowlists.
2. `alembic/versions/`: one revision creating the three tables and two
   columns, with a `downgrade` that drops them.
3. `src/renar_backend/tmdb/watch_providers.py` (new): `regions()` and
   `providers_for(country)` (TMDB `/watch/providers/regions`,
   `/watch/providers/movie` and `/watch/providers/tv`, memory-cached 24 h),
   and `sync_title_offers(db, title)`, which fetches the title's
   watch-provider payload with `tmdb_http`, upserts the `StreamingProvider`
   rows it names, replaces the title's `TitleWatchOffer` rows from the
   `flatrate`, `free` and `ads` lists of every country, and stamps
   `watch_offers_synced_at`. Named logger; a TMDB failure is logged at
   WARNING and leaves the rows untouched.
4. `src/renar_backend/routers/streaming.py` (new, prefix `/streaming`):
   the four endpoints above with `response_model`s added to
   `src/renar_backend/schemas.py`; register it in `main.py`. The PUT
   queues the background sync with `BackgroundTasks`, capped per request
   and paced like `notifier.resync_tmdb_metadata`.
5. `src/renar_backend/routers/media.py`, `list_media`: add
   `available_only: bool = False`; when true, 409 without settings, else an
   `exists()` filter on `TitleWatchOffer` joined to the user's
   `UserStreamingProvider` rows and country (one query, no per-row lookup).
6. `src/renar_backend/routers/media.py`, where a library entry is created
   and `refresh_title_details` runs: also call `sync_title_offers` for a
   title never synced.
7. `src/renar_backend/social/notifier.py` and `task_runs.py`: a periodic
   task `watch_offers_sync` that refreshes tracked titles whose
   `watch_offers_synced_at` is null or older than 7 days, paced, shown on
   the admin Periodic tasks page like the others.
8. `src/renar_backend/users/accounts.py` (`delete_account`),
   `users/export.py` and `users/renar_import.py`: delete, export and
   import the country and the service ids.
9. `src/renar_backend/users/security.py`: any new code path that can
   strike or ban must check `site_settings.exempt_ips` first (none is
   expected; check).
