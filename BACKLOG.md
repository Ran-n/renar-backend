[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/14 16:40:50.586421 )
[//]: # (+ Revised: 	2026/11/22 03:03:53.200781 )
[//]: # ( ---------------------------------------------------------------------- )

# Backlog

Ideas worth keeping that don't block 1.0 and aren't planned yet. Planned
work (everything that blocks 1.0) lives in `TODO.md`; nothing here is picked
up by "do next". Items are light on purpose: the full spec is written when
an item is promoted to `TODO.md`, against the code as it is then. Items
parked from `TODO.md` on 2026-11-14 keep their original text under Notes.

| To do | Backlog |
|:-----:|:-------:|
| **6** | **32** |

Next backlog number: 35

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
- [B19. Stop the worker threads and close the HTTP clients cleanly on shutdown](#b19-stop-the-worker-threads-and-close-the-http-clients-cleanly-on-shutdown)
- [B20. Keep confirmation codes, invite codes and e-mail addresses out of the logs, and make the log level configurable](#b20-keep-confirmation-codes-invite-codes-and-e-mail-addresses-out-of-the-logs-and-make-the-log-level-configurable)
- [B21. Test the migrations down to base and through every revision with data](#b21-test-the-migrations-down-to-base-and-through-every-revision-with-data)
- [B22. Add live tests against TMDB, TheTVDB, Brevo and Turnstile](#b22-add-live-tests-against-tmdb-thetvdb-brevo-and-turnstile)
- [B23. Add rendered browser tests for the admin panel](#b23-add-rendered-browser-tests-for-the-admin-panel)
- [B24. Fetch TMDB in parallel in the notifier checks and the translation warm-up](#b24-fetch-tmdb-in-parallel-in-the-notifier-checks-and-the-translation-warm-up)
- [B25. Enforce the clean-code limits with ruff and a file-length check](#b25-enforce-the-clean-code-limits-with-ruff-and-a-file-length-check)
- [B26. Split `users/tvtime_import.py` into a package by import stage](#b26-split-userstvtime_importpy-into-a-package-by-import-stage)
- [B27. Split the admin panel page modules](#b27-split-the-admin-panel-page-modules)
- [B28. Split `models.py` and `schemas.py` by domain](#b28-split-modelspy-and-schemaspy-by-domain)
- [B29. Split the remaining files over 500 lines](#b29-split-the-remaining-files-over-500-lines)
- [B30. Choose a source-tree skeleton for Python FastAPI backends and move to it](#b30-choose-a-source-tree-skeleton-for-python-fastapi-backends-and-move-to-it)
- [B31. Add the file header to the 48 files that lack it](#b31-add-the-file-header-to-the-48-files-that-lack-it)
- [B32. Rename the default branch from `master` to `main` on every forge](#b32-rename-the-default-branch-from-master-to-main-on-every-forge)
- [B33. Rewrite the README as a landing page](#b33-rewrite-the-readme-as-a-landing-page)

## Using the backlog

- Write for someone who has never seen the conversation: what happens today,
  what is wrong with it, and the result wanted.
- Number new items with "Next backlog number" (B1, B2, …), add them at the
  end, then increase that number. Deleting leaves a gap; nothing is renumbered.
- Keep the Index in file order: one `- [B<n>. title](#anchor)` line per item;
  update it whenever an item is added, retitled or deleted.
- Keep the count table above the Index equal to the items here and in `TODO.md`,
  in both files.
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

## B19. Stop the worker threads and close the HTTP clients cleanly on shutdown

**Added:** 2026-11-21 · Area: Reliability
**Why:** `~/.claude/memory/feedback_universal_behaviours.md` says every
thread, background worker and child process is stopped cleanly before the
process exits, on every quit path. Today the FastAPI `lifespan` in
`src/renar_backend/main.py` cancels only the eight periodic tasks from
`social/notifier.py::start_periodic_tasks`. Imports run on bare daemon
threads (`routers/imports.py` line 140, `threading.Thread(target=_run,
daemon=True)`), data exports on a daemon `export-worker` thread
(`users/export_queue.py` line 78), and both die mid-work when the worker
exits (a self-update reload, a `systemctl restart`). The module-level
`httpx.Client`s (`tmdb/tmdb_http.py` `http_client` and `image_http_client`,
`tvdb/tvdb_http.py`, `users/email_confirmation.py`, `users/turnstile.py`)
are never closed, and `engine.dispose()` only runs in the stale-plan
handler. The interruption is reported ("Import was interrupted by a server
restart. Please re-run it.", `routers/imports.py` line 178), so nothing is
lost silently, but the user has to start over.
**Goal:** on shutdown the server stops taking new imports and exports, lets
running ones finish or stop at a safe point within a bounded time, closes
every HTTP client and disposes the engine, and logs each step.

### Notes
- Found by the standards audit (former item 38).
- uvicorn's `timeout_graceful_shutdown` is already capped in `__main__.py`
  (`_serve`) because `/events` SSE streams never close by themselves; the
  worker drain must fit inside that cap.
- Imports commit per entry (`docs/design-decisions.md`, "Renar-export
  reconcile locks the row and commits per entry"), so stopping between
  entries is safe; the export worker would need its partial file removed.
- Tests: the checklist's Shutdown/lifecycle row in
  `~/.claude/memory/feedback_tests.md` (each quit path, assert the thread
  ended and the clients are closed).

## B20. Keep confirmation codes, invite codes and e-mail addresses out of the logs, and make the log level configurable

**Added:** 2026-11-21 · Area: Logging / Security
**Why:** `~/.claude/memory/feedback_logging.md` says never to log secrets,
raw tokens or PII, and that the log level comes from `LOG_LEVEL`
(default `INFO`). Today `users/email_confirmation.py` line 135 logs, at
INFO, the full e-mail address and the confirmation code whenever
`BREVO_API_KEY` is unset; `routers/admin/invites.py` lines 754, 771, 816
and 833 log the invite code itself on revoke, restore, reset and delete.
The level is hard-coded: `main.py` calls `logging.basicConfig(level=
logging.INFO, …)` at import time and `__main__.py::_log_config` sets the
root logger to `"INFO"`; there is no `LOG_LEVEL` setting in `config.py` or
`docs/environment-variables.md`. App modules log through the root logger
(64 `getLogger(__name__)` calls) instead of a `renar_backend` logger with
`propagate = False`.
**Goal:** the logs name the account (user id) and the invite's id, never a
code or an address; `LOG_LEVEL=DEBUG` in `.env` makes the server verbose
without a code change.

### Notes
- Found by the standards audit (former item 38).
- With Brevo unset (the dev PC) the code is still needed to test
  registration: decide how a developer gets it (for example only when
  `LOG_LEVEL=DEBUG` and the address masked), and write the choice in
  `docs/design-decisions.md`.
- `tests/test_logging_config.py` and `tests/test_main_logging.py` pin the
  current config and must change with it; add `caplog` tests asserting no
  code or address reaches any record.

## B21. Test the migrations down to base and through every revision with data

**Added:** 2026-11-21 · Area: Tests
**Why:** `~/.claude/memory/feedback_tests.md` (checklist, "Migrations")
wants `alembic upgrade head` on an empty DB, then `downgrade base`, then
upgrade again, plus a walk through every revision one at a time with data
inserted once its tables exist, checking the data survives each step.
`tests/test_migrations.py` only upgrades an empty schema to head and
compares it with the models and triggers
(`test_upgrade_from_empty_reaches_head`,
`test_migrated_schema_matches_the_models`,
`test_migrated_triggers_match_create_all`); no test ever runs a
`downgrade()`, although all 87 revisions in `alembic/versions/` define one.
**Goal:** a broken `downgrade()` or a revision that drops data fails the
suite.

### Notes
- Found by the standards audit (former item 38).
- Uses the same throwaway Postgres schema pattern as `tests/conftest.py`
  (`_SCHEMA`, `search_path`); the walk can be slow, so consider its own
  marker kept out of the default run but inside the coverage run.

## B22. Add live tests against TMDB, TheTVDB, Brevo and Turnstile

**Added:** 2026-11-21 · Area: Tests
**Why:** `~/.claude/memory/feedback_tests.md` (checklist, "Live") wants a
`live` marker for tests against the real external APIs, kept out of the
default run but run before every version bump
(`~/.claude/memory/feedback_version_bump.md` step 2). The backend calls
four services (`tmdb/tmdb_http.py`, `tvdb/tvdb_http.py`,
`users/email_confirmation.py` for Brevo, `users/turnstile.py` for
Cloudflare Turnstile) and every test mocks them, so a changed response
shape or a retired endpoint only shows up in production.
**Goal:** `uv run pytest -m live` checks that each service still answers in
the shape the code parses.

### Notes
- Found by the standards audit (former item 38).
- Needs the API keys from `.env`; skip with a clear reason when a key is
  missing, never pass silently. Add `live` to `addopts`' exclusions and to
  `pyproject.toml`'s `markers`, and list the command in `README.md`'s Tests.
- Brevo: use its account/sender endpoint, not a real send. Turnstile: the
  documented always-pass test secret.

## B23. Add rendered browser tests for the admin panel

**Added:** 2026-11-21 · Area: Tests / Admin panel
**Why:** `~/.claude/memory/feedback_tests_rendered_ui.md` wants every UI
screen tested in the real running app (real clicks, pixel or DOM
assertions, reviewed baselines), and `feedback_ui_tests_hidden.md` wants
those runs headless by default with `<APP>_SHOW_TEST_WINDOW=1` to show
them. The admin panel (`routers/admin/`: dashboard, users, invites,
moderation, reports, premium, settings, periodic tasks, app releases,
server update, analytics, login) is server-rendered HTML with inline
JavaScript (the refresh button, the hostname and IP chip inputs in
`settings.py`, `confirm()` prompts), and is only tested as strings and
HTTP responses (`tests/test_admin.py`, `tests/test_admin_render.py`).
Nothing proves the page looks right or that its scripts work.
**Goal:** a Playwright suite (marker `ui`) logs in to the admin panel
against a throwaway DB, clicks through every page in light and narrow
widths, and compares each with a reviewed baseline.

### Notes
- Found by the standards audit (former item 38).
- Playwright is already used by renar-frontend (system Python; see the
  project memory `renar-frontend-ui-verification-workflow.md`).
- Headless by default (`RENAR_BACKEND_SHOW_TEST_WINDOW=1` for headed);
  never move the real mouse (`feedback_ui_tests_no_input_hijack.md`).
- Baselines must show only demo data (`feedback_tests_rendered_ui.md`,
  "Nothing personal on screen").
- The integration fixtures' live server (`_test_server.py`) can host it.

## B24. Fetch TMDB in parallel in the notifier checks and the translation warm-up

**Added:** 2026-11-21 · Area: Performance
**Why:** `~/.claude/memory/feedback_parallel_code.md` says independent I/O
runs concurrently through a bounded pool, and a sequential loop over it is
a defect. `social/notifier.py` fetches TMDB one title at a time in the
episode check (loop at line 84), the film check (line 179) and the
unmatched-title retry (line 302), and `tmdb/tmdb_store.py`'s
`warm_title_translations` (line 123) does the same per title. With a large
catalogue each check takes as long as the sum of its round trips.
**Goal:** these loops fan out through a bounded pool, keep their results in
order, log each failed title on its own, and finish in a fraction of the
time.

### Notes
- Found by the standards audit (former item 38).
- `_tmdb_metadata_resync_loop` paces itself on purpose (`time.sleep
  (pace_seconds)`, line 250, "no rate limiting in tmdb_http.py"); keep that
  one sequential and say why beside it. Size the pool under TMDB's rate
  limit and write the limit beside the cap.
- DB sessions are not thread-safe: fetch in the pool, write in one session
  afterwards (see the per-title session note in
  `docs/design-decisions.md`, "`warm_title_translations` opens one DB
  session per title").
- Tests: ordering, one failure among successes, the cap honoured.

## B25. Enforce the clean-code limits with ruff and a file-length check

**Added:** 2026-11-21 · Area: Code quality
**Why:** `~/.claude/memory/feedback_clean_code.md` (Enforcement) wants the
size and complexity limits checked by the linter, and
`~/.claude/memory/reference_lint_configs.md` gives the Python settings:
select `C901`, `PLR0911`-`PLR0917`, `PLR1702`, `RUF100`, `PGH004`, with
`max-complexity = 10`, `max-args = 4`, `max-positional-args = 3`,
`max-statements = 25`, `max-branches = 10`, `max-nested-blocks = 3`,
`max-locals = 10`, plus `pylint --disable=all --enable=C0302
--max-module-lines=500` for file length and a check that every `# noqa`
carries a reason. `pyproject.toml` selects only `E, F, I, B, UP, SIM`.
Run with those limits on 2026-11-21, ruff reports 330 findings in `src/`
(123 PLR0917, 57 PLR0913, 30 PLR1702, 30 PLR0915, 17 PLR0914, 16 C901,
14 PLR0912, 3 PLR0911, plus 40 boolean-flag FBT findings); 75 functions
are over 40 lines and 14 files over 500 lines.
**Goal:** `uv run ruff check` enforces the limits; every existing violation
is either fixed by items B26-B29 or carries a `# noqa: <CODE> <reason>`.

### Notes
- Found by the standards audit (former item 38).
- Land the config with per-file ignores for the files B26-B29 will split,
  and remove each ignore with its split, so the repo is never red.
- The two existing `# noqa: UP037` lines (`models.py` 885, `schemas.py`
  945) already carry reasons.

## B26. Split `users/tvtime_import.py` into a package by import stage

**Added:** 2026-11-21 · Area: Code structure
**Why:** `~/.claude/memory/feedback_clean_code.md` sets a hard stop at 500
lines per file and 40 lines per function. `users/tvtime_import.py` is 1651
lines; its `run` function is 744 lines, `_upsert_library_entry` 125 and
`_process_show` 99.
**Goal:** the TV Time import is a `users/tvtime_import/` package with one
module per stage (parsing the export, matching titles, writing the
library, lists, progress), each under 200 lines, with the same behaviour
and tests.

### Notes
- Found by the standards audit (former item 38). After B25.
- Tests: `tests/test_imports.py` (1395 lines) and
  `tests/test_tvtime_import_gaps.py` (2460 lines) pin it; split them along
  the same lines. Grep every importer of `tvtime_import` first
  (`routers/imports.py`).

## B27. Split the admin panel page modules

**Added:** 2026-11-21 · Area: Code structure / Admin panel
**Why:** `~/.claude/memory/feedback_clean_code.md` hard stops (500-line
files, 40-line functions). `routers/admin/users.py` is 1210 lines,
`invites.py` 834, `settings.py` 710, `_html.py` 636; the page renderers are
single functions of HTML f-strings: `_render_invites` 481 lines,
`_render_site_settings` 470, `_render_users` 237, `_render_user_detail`
104, `moderation._render_comments` 101. Handlers, queries and markup sit in
one file, against the rule's separation of concerns.
**Goal:** each admin page has its handlers, its queries and its markup in
separate modules (a template per page, or small render functions per
card), each file under 200 lines.

### Notes
- Found by the standards audit (former item 38). After B25; B23's rendered
  tests should exist first so the split can be checked visually.
- `docs/design-decisions.md`, "Admin panel: server-rendered HTML behind a
  login form + TOTP", keeps server-rendered HTML; a template engine
  (Jinja2) would be a new dependency, so record the choice there.

## B28. Split `models.py` and `schemas.py` by domain

**Added:** 2026-11-21 · Area: Code structure
**Why:** `~/.claude/memory/feedback_clean_code.md` hard stop of 500 lines
per file. `models.py` is 1534 lines and `schemas.py` 1258, each holding
every domain (users, titles, library, social, imports, admin, premium).
**Goal:** `models/` and `schemas/` packages with one module per domain,
each under 500 lines, and every import site updated.

### Notes
- Found by the standards audit (former item 38). After B25.
- No re-export shims: the rule forbids renaming re-exports and code in
  `__init__.py`, so every importer changes (grep `from .models import`,
  `from renar_backend.models import`, Alembic's `env.py`).
- `tests/test_normalization.py` and `tests/snapshots/*.json` must stay
  green unchanged; mutmut's `paths_to_mutate` in `pyproject.toml` names
  both files.

## B29. Split the remaining files over 500 lines

**Added:** 2026-11-21 · Area: Code structure
**Why:** `~/.claude/memory/feedback_clean_code.md` hard stop of 500 lines
per file, 40 per function. Besides B26-B28: `routers/media.py` 1504 lines
(`list_media` 101), `routers/auth.py` 781 (`register` 136),
`update_check.py` 616, `users/security.py` 603, `social/notifier.py` 557,
`users/renar_import.py` 550 (`_import_library` 101), `routers/tmdb.py`
509. Also over 40 lines: `_test_server.py::main` 171,
`routers/upcoming.py::get_upcoming_history` 126,
`catalog/titles.py::merge_titles` 117, `routers/stats.py::get_stats` 114.
**Goal:** each of these files is split by responsibility, under 500 lines,
and each listed function under 40, with behaviour unchanged.

### Notes
- Found by the standards audit (former item 38). After B25. Can be done one
  file per sitting; promote one file at a time.

## B30. Choose a source-tree skeleton for Python FastAPI backends and move to it

**Added:** 2026-11-21 · Area: Code structure
**Why:** `~/.claude/memory/feedback_source_organization.md` has an approved
skeleton only for Rust + gpui; for any other stack the rule is to propose
one (an instance of the base skeleton: `app/`, `model/<domain>/`, a
delivery layer such as `api/` in place of `ui/`, `platform/`, `tools/`,
build-enforced packages), get the user's approval and save it. This repo is
one package, `src/renar_backend/`, mixing top-level modules (`models.py`,
`schemas.py`, `update_check.py`, `self_update.py`, `db_triggers.py`) with
domain folders (`catalog/`, `media/`, `social/`, `users/`, `tmdb/`,
`tvdb/`, `routers/`). It has a generic name the rule forbids
(`media/image_utils.py`), and tests are flat in `tests/` instead of
mirroring `src/` (`~/.claude/memory/feedback_tests.md`, Framework).
**Goal:** an approved Python + FastAPI skeleton saved in the global memory,
and this repo moved to it, recorded in `docs/design-decisions.md`.

### Notes
- Found by the standards audit (former item 38). Needs the user's choice
  first (AskUserQuestion), so it can't start unattended.
- Do after B26-B29 or fold them in, so files move once.
- The self-update (`update_check.py`, `self_update.py`) and the hatch
  wheel config (`[tool.hatch.build.targets.wheel] packages`) depend on the
  package path.

## B31. Add the file header to the 48 files that lack it

**Added:** 2026-11-21 · Area: Code quality
**Why:** `~/.claude/memory/feedback_file_headers.md` and
`feedback_clean_code.md` ("Every source file: the `metadata` header, then
a module summary") want the `metadata` header on every `.py` file. 48 have
none: `src/renar_backend/events.py` (its docstring has Authors and Created
but no Revised), `src/renar_backend/routers/events.py`,
`tests/integration/__init__.py`, `tests/test_events.py`,
`tests/test_notifier_loops.py`, `tests/test_stale_prepared_plan.py`,
`tests/test_tvdb_http.py`, and 41 of the 87 migrations in
`alembic/versions/` (e.g. `e5ffb2678f36_initial_schema.py`).
**Goal:** every `.py` file in `src/`, `tests/` and `alembic/` starts with
the header, and a test fails when a new one doesn't.

### Notes
- Found by the standards audit (former item 38).
- `metadata -c` on a file that already has a docstring adds a second one:
  merge them by hand, then `metadata -m` (the rule's own warning).
  Migrations already have the E402 per-file ignore for the two-docstring
  layout.

## B32. Rename the default branch from `master` to `main` on every forge

**Added:** 2026-11-21 · Area: Repository
**Why:** `~/.claude/memory/feedback_git_remotes.md` says repositories use
`main`. This one uses `master` locally and on GitHub (`origin`), GitLab and
Codeberg, while `CONTRIBUTING.md` (lines 65 and 68) already tells
contributors to branch from and open pull requests against `main`. The
self-update's git mode hard-codes the branch: `update_check.py`
(`BRANCH = "master"`, line 62, and its docstring), and so do `README.md`
(lines 35, 38, 68, 245) and `docs/environment-variables.md`
(`UPDATE_RELEASE_URL` row).
**Goal:** `main` is the default branch everywhere, the self-update follows
`origin/main`, and no doc says `master`.

### Notes
- Found by the standards audit (former item 38).
- The dev PC's checkout self-updates in git mode; rename there and on the
  forges in one go, and change `BRANCH` in the same release, or the
  one-click update refuses. renar-frontend may need the same; check it.
- `docs/design-decisions.md` "Self-update: git checkouts fast-forward" says
  `origin/master` (lines 1155-1172).

## B33. Rewrite the README as a landing page

**Added:** 2026-11-21 · Area: Docs
**Why:** `~/.claude/memory/reference_readme_layout.md` sets the README
layout for every repo: a centred header with logo and tagline, a primary
call to action, a few badges, the main sections in public-first order
(adapted for a server: "Install on a server" in place of a download
table), technical material lower down, the License line with its version,
and Breren's original logo (`breren-logo.svg`) in the footer; every
`docs/*.md` starts with a links line to the others. `README.md` today
opens with `# Renar Backend` and goes straight into Setup, Run, HTTPS,
Endpoints (a long list), Tests and License, with no header block, badges,
FAQ, contents line or footer.
**Goal:** a README that tells a visitor what the Renar backend is and how
to run their own in its first screen, with the developer material kept
below and in `docs/`.

### Notes
- Found by the standards audit (former item 38).
- The rule is "on trial" (tested first on Orin); check it is still current
  before promoting.
- The Endpoints list can move to `docs/` (or the OpenAPI schema when
  `ENABLE_DOCS=true`).
- Copy `breren-logo.svg` unchanged from the `breren` repo's
  `public/icons/` into the repo's own assets.
