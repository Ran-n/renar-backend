[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/09 11:43:55.623794 )
[//]: # (+ Revised: 	2026/11/09 11:50:01.319096 )
[//]: # ( ---------------------------------------------------------------------- )

# TODO

The backlog. Each item is self-contained: reading it alone is enough to
implement it fully, without asking anything. Work top to bottom unless an item
says otherwise.

Every item carries a tag line: `[Blocking for 1.0]` or `[Future]`. "1.0"
means the next major version bump (first stable/public release), not the
next minor/patch. Done or dropped items are deleted, never marked done:
history lives in git, `CHANGELOG.md` and `docs/design-decisions.md`. Items
moved over from the old `docs/backlog.md` keep their original free-form
text; rewrite one into the template below before implementing it.

Next item number: 27

## Index

1. [Full test coverage across every test type, not just the modules that happen to have tests today](#1-full-test-coverage-across-every-test-type-not-just-the-modules-that-happen-to-have-tests-today)
2. [Set up WSL on the dev machine and actually run mutmut](#2-set-up-wsl-on-the-dev-machine-and-actually-run-mutmut)
3. [Minor: `_progress` entries are never pruned](#3-minor-_progress-entries-are-never-pruned)
4. [Planned: "watched on" (streaming source) import mapping](#4-planned-watched-on-streaming-source-import-mapping)
5. [Additional external rating sources (IMDb, Rotten Tomatoes, Metacritic) alongside TMDB's `vote_average`](#5-additional-external-rating-sources-imdb-rotten-tomatoes-metacritic-alongside-tmdbs-vote_average)
6. [Watched-on / streaming source tracking — user priority (2026-07-21)](#6-watched-on--streaming-source-tracking--user-priority-2026-07-21)
7. [Ranking only covers total overall watch time; no badges/achievements exist yet](#7-ranking-only-covers-total-overall-watch-time-no-badgesachievements-exist-yet)
8. [Registration-flow-around-the-toggle: two open product-policy questions remain, neither blocking](#8-registration-flow-around-the-toggle-two-open-product-policy-questions-remain-neither-blocking)
9. [Real phone number confirmation on registration](#9-real-phone-number-confirmation-on-registration)
10. [Diary endpoint — chronological watch/activity log](#10-diary-endpoint--chronological-watchactivity-log)
11. [Like/dislike (and share) support for Reviews](#11-likedislike-and-share-support-for-reviews)
12. [Chronological sort on comments](#12-chronological-sort-on-comments)
13. [Share — add a deep link once the frontend's share cards are ready for one](#13-share--add-a-deep-link-once-the-frontends-share-cards-are-ready-for-one)
14. [Per-season grading, once a season is fully watched](#14-per-season-grading-once-a-season-is-fully-watched)
15. [Social login: Continue with Google / Continue with Apple](#15-social-login-continue-with-google--continue-with-apple)
16. [Recommendation feed: infinite-scroll "what to watch next"](#16-recommendation-feed-infinite-scroll-what-to-watch-next)
17. [Push notifications (system notifications while the app is closed)](#17-push-notifications-system-notifications-while-the-app-is-closed)
18. [No human-facing mailbox on `breren.com` yet (e.g. `support@`/`hello@`)](#18-no-human-facing-mailbox-on-brerencom-yet-eg-supporthello)
19. [Admin/mod accounts still lack per-account roles](#19-adminmod-accounts-still-lack-per-account-roles)
20. [Log line formatting is hard to read](#20-log-line-formatting-is-hard-to-read)
21. [Production hosting isn't chosen or set up](#21-production-hosting-isnt-chosen-or-set-up)
22. [Privacy policy and Terms of Service are drafted but not published](#22-privacy-policy-and-terms-of-service-are-drafted-but-not-published)
23. [No payment integration wired to the app stores — and mobile can't just reuse a web payment flow](#23-no-payment-integration-wired-to-the-app-stores--and-mobile-cant-just-reuse-a-web-payment-flow)
24. [Host Android app releases for in-app updates](#24-host-android-app-releases-for-in-app-updates)
25. [Add a one-click backend update to the admin panel](#25-add-a-one-click-backend-update-to-the-admin-panel)
26. [Replace the admin panel's Basic-auth popup with a login page and authenticator-app codes](#26-replace-the-admin-panels-basic-auth-popup-with-a-login-page-and-authenticator-app-codes)

## Adding an item

- Write for someone who has never seen the conversation: what happens today,
  what should happen instead, and why each non-obvious decision was made.
- Be concrete: real file paths, names, sizes, colours, keys. No open "maybe";
  if the implementer must choose, say how to choose and how to check.
- Use the template below. Implementation is a numbered list of steps in the
  order to do them; Done when is a checklist.
- Number it with "Next item number" above, then increase that number.
- File order is priority: the first item is the next one to do.
- Numbers ascend in file order. Deleting leaves a gap; when adding at the top
  or moving an item breaks the order, renumber every item in file order (from
  the lowest number in use) and update every reference to them.
- Keep the Index in file order: one `<n>. [title](#anchor)` line per item;
  update it whenever an item is added, retitled, moved or deleted.
- Screenshots go in `docs/todo/<n>-<slug>.png`, linked from the item.
- Split anything bigger than one sitting into items that ship alone.

## Implementing an item

1. Read the whole item and every file it names; check `git status` first.
2. If the code has drifted from the item, adapt and note it; if the item
   contradicts a newer decision, ask before building.
3. Do the Implementation steps in order.
4. Write the listed tests, plus any others the change needs.
5. Lint, format, update file headers and run the full test suite until clean.
6. For visible changes, run the app and check it in the states the item names.
7. Update the listed docs; write the changelog line when committing.
8. Tick every Done when line, with evidence.
9. Delete the item, its Index line and its screenshots; add follow-up work as
   new items.

## Template

```markdown
## <n>. <short imperative title>

**Why:** what happens today and what is wrong with it.
**Goal:** the result, as the user will see it.

### Behaviour
- One bullet per case, edge cases included.

### Out of scope
- What this item deliberately doesn't change.

### Implementation
1. `<path>`: what changes and why.

### Tests
- `<test file>`: each case and what it proves.

### Docs
- `<doc file>`: what to change. Changelog: "<line>".

### Done when
- [ ] Checkable result.
```

---

## 1. Full test coverage across every test type, not just the modules that happen to have tests today

**[Blocking for 1.0]** · Area: Testing

The suite has every
commonly-recognized *category* of test set up (unit, integration, smoke,
regression, contract, property, snapshot, security, load, mutation
(config only — see the WSL entry below), fuzz), but having the category
doesn't mean coverage is complete within it. Two coverage pushes
(2026-09-03 and 2026-09-07) closed most of it and turned up nine real
production bugs along the way — the full writeups live in
`docs/design-decisions.md`'s Testing section. What is actually still
open:
- **Contract / response_model**: now **77/151** endpoints. The 74
  without one are almost entirely by design — 20 return
  `204 No Content`, 44 are the admin panel's server-rendered
  HTML/redirects (`include_in_schema=False`, audited 2026-09-03 and
  confirmed to need none), and the rest are non-JSON bodies (`/events`'
  SSE stream, the `/images`, `/tmdb/image` and `/export/data/download`
  binary responses) or one-line literals (`/`, `/health`). The genuine
  remaining gap is small and specific: `stats.py`'s three endpoints
  (`GET /stats`, `/stats/ranking`, `/stats/ranking/metrics`) and
  `GET /premium/palette`. `stats.py` is the awkward one — its response
  is assembled dict-by-dict across a long handler, so modelling it is a
  real shape-extraction job, not a decorator edit.
- **Unit/integration**: 96% branch coverage as of the 2026-09-02 pass
  (up from an 82% first baseline), measured with `pytest --cov` on the
  default marker set. Remaining real gaps: `catalog/titles.py` (86%),
  `_devserver.py` (54%, OS-level/subprocess code not reachable from
  in-process coverage), `_test_server.py` (0%, invoked only as a
  subprocess by `tests/integration/`, never measured by this
  instrumented run).
- **Mutation**: the one blocked item — `[tool.mutmut]` exists but has
  never run, and can't on this machine. Tracked separately in the WSL
  entry directly below, including widening `paths_to_mutate` beyond
  `models.py` + `schemas.py` once it can actually run.

Property/fuzz and load are done: fuzz now covers every endpoint with a
meaningful input surface, including `media.py`'s `CustomPosterSet`
binary-image endpoints and the admin sub-routers (2026-09-07), and
`tests/load/locustfile.py` covers reads plus weighted write tasks
(~27% of simulated traffic). renar-frontend's matching item closed
2026-09-07 — see its `docs/design-decisions.md`.

## 2. Set up WSL on the dev machine and actually run mutmut

**[Future]** · Area: Testing

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
verified for real instead of carrying the "unverified" caveat repeated
in the Testing item above and in `docs/design-decisions.md`, and
`paths_to_mutate` can be widened from `models.py` + `schemas.py` toward
the whole `src/` tree. As of 2026-09-07 this is the *only* remaining
blocked piece of that Testing item.

## 3. Minor: `_progress` entries are never pruned

**[Future]** · Area: Import system (`routers/imports.py`) / TV Time import

**Context:** Generalized from a single hardcoded TV Time importer to a registry of
pluggable importers (`users/tvtime_import.py`, `users/renar_import.py`, ...)
dispatched by auto-detecting the uploaded file's content — see
`routers/imports.py`'s module docstring for the registry shape. Old
endpoints `POST /import/tvtime` and `GET /import/tvtime/status` are now
`POST /import` (with an optional `claimed_kind` cross-checked against
detection) and `GET /import/status`; `GET /import/sources` is new, listing
every registered origin for the frontend's source picker
([import_view.py](../../renar-frontend/src/renar_frontend/views/profile/import_view.py)).
`ImportJob` (models.py) is now keyed by `(user_id, kind)` instead of just
`user_id` (migration `76058e1d65e8`), so an account's TV Time and Renar
import outcomes don't clobber each other.


A show with no TMDB match at all now falls all the way back to TheTVDB's
own data (poster, overview, episodes) instead of sitting fully blank —
tracked under `Title.tvdb_id`, upgraded to `tmdb_id` automatically the
moment that resolves. See design-decisions.md's "TheTVDB as a genuine
fallback identity, not just a name source".

Negligible memory; clears
on process restart. Not worth fixing unless it becomes visible.

## 4. Planned: "watched on" (streaming source) import mapping

**[Future]** · Area: Import system (`routers/imports.py`) / TV Time import

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

## 5. Additional external rating sources (IMDb, Rotten Tomatoes, Metacritic) alongside TMDB's `vote_average`

**[Future]** · Area: Features

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

## 6. Watched-on / streaming source tracking — user priority (2026-07-21)

**[Future]** · Area: Features

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

## 7. Ranking only covers total overall watch time; no badges/achievements exist yet

**[Future]** · Area: Features

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

## 8. Registration-flow-around-the-toggle: two open product-policy questions remain, neither blocking

**[Future]** · Area: Features

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

## 9. Real phone number confirmation on registration

**[Future]** · Area: Features

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

## 10. Diary endpoint — chronological watch/activity log

**[Future]** · Area: Features

New endpoint `GET /diary` returning the user's watch events in
reverse-chronological order, paginated. Should cover both film/show library
completions and individual episode watches. Response shape per entry:
`title_id`, `title` (display name), `poster_path`, `type` (`film`/`episode`),
`watched_at`, `rating` (nullable), `season`/`episode` (nullable, for episode
entries). Support query params: `page`, `type` filter, `from`/`to` date range.
Sources: `episode_watches` and `library_entries` (films and show-level
completions via `last_watched_at`). Prefer one unified endpoint over two
separate ones if the schema allows it cleanly.

## 11. Like/dislike (and share) support for Reviews

**[Future]** · Area: Features

`Review`
(`models.py:1138`) has no engagement columns, unlike comments' `CommentLike`
(`models.py:1251`, `comment_likes` table — one row per `(comment_id,
user_id)`, `value` +1/-1, reacting the other way flips the row instead of
adding a second one). Add the same shape for reviews: a `ReviewLike`
model/`review_likes` table keyed by `(review_id, user_id)`, plus like/
dislike endpoints on `routers/reviews.py` matching the comments router's
shape. Share doesn't need backend work —
renar-frontend's share cards are client-side image generation, no API
involved (see its `TODO.md`'s matching entry). See renar-frontend's
`TODO.md` for the frontend half (like/dislike row + share button
on each review tile).

## 12. Chronological sort on comments

**[Future]** · Area: Features

`GET /media/{id}/comments` currently returns comments in a fixed order.
Add a `?sort=asc|desc` query parameter so clients can request oldest-first
(chronological). Default remains the current behaviour; `asc` is the new
opt-in. Change goes in the comments query in `routers/comments.py` (or
wherever comments are fetched).

## 13. Share — add a deep link once the frontend's share cards are ready for one

**[Future]** · Area: Features

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

## 14. Per-season grading, once a season is fully watched

**[Future]** · Area: Features

No
season-level rating exists today — only `media_items.rating` (per
title) and `episode_watches.rating` (per episode); confirmed while
building the share-card mockups (see renar-frontend's `TODO.md`).
Wanted: let a user rate a season as a whole once they've finished every
aired episode in it (mirrors how a title itself gets rated only after
the user has actually watched it, not before). Needs a new rating fact
keyed on (user, title, season) — a season isn't its own row anywhere
today, so this likely means a new table rather than a column bolted onto
`episode_watches` (which is per-episode) or `media_items` (which is
per-title, no season dimension). Must stay BCNF; check
`test_normalization.py`. Open questions: enforce "fully watched" how (all
aired episodes checked off in that season, computed from
`episode_watches`), does the aggregate/Renar-average badge described in
the frontend backlog then read from this instead of leaving seasons
ungraded, and does this interact with the per-rewatch-ratings entry
above (a season rewatch re-rating too, or title/episode only). Not
scoped in detail — not blocking, no urgency signaled.

Rough API shape, so the frontend side (see renar-frontend's
`TODO.md`) has something concrete to wire the season-rate
prompt to: `set_episode`'s response should report whether that write
just completed the season (all aired episodes in `episode_watches` now
checked off for that (user, title, season)) — a `season_completed: bool`
flag alongside the existing response fields — so the frontend knows to
surface the rate prompt right after that call, without a separate
round-trip. Reads/writes of the rating itself go through their own new
endpoint (e.g. `PUT/GET /titles/{id}/seasons/{season}/rating`) rather
than being bolted onto `set_episode`, since the rating isn't tied to any
single episode write and needs to be independently re-readable/editable
later. Important: this flag must reflect *only* whether the season is
now fully watched, not carry or default to any episode's rating value —
the frontend backlog entry specifically calls out that the season
rating must not pre-fill from the last-watched episode's grade.

## 15. Social login: Continue with Google / Continue with Apple

**[Future]** · Area: Features

Not committed — revisit once real signup-funnel data shows password-registration
drop-off is a problem worth solving. Would need nullable `google_id`/`apple_id`
columns on `User` (with nullable `password_hash`), new Alembic migration, new
`/auth/google`/`/auth/apple` endpoints, `google-auth` + JWKS verification for
Apple, `GOOGLE_CLIENT_ID`/`APPLE_*` env vars. Apple requires an Apple Developer
account and is mandatory if Google sign-in is also offered on iOS. Decide on
native plugin bridge vs. OAuth web-redirect before scoping further.

## 16. Recommendation feed: infinite-scroll "what to watch next"

**[Future]** · Area: Features

Not committed — needs design work on what signals feed the taste model before
scoping endpoints. Would need a "taste inferer" (model/heuristic from watch
history, ratings, dwell time), new endpoint(s) in `routers/recommendations.py`,
implicit-signal recording (skip, completion, dwell), and cold-start handling
for new users. Open question: in-house collaborative/content-based filtering
vs. external recommendation service.

## 17. Push notifications (system notifications while the app is closed)

**[Future]** · Area: Features

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

## 18. No human-facing mailbox on `breren.com` yet (e.g. `support@`/`hello@`)

**[Future]** · Area: Infrastructure

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

## 19. Admin/mod accounts still lack per-account roles

**[Future]** · Area: Infrastructure

`routers/admin.py`
is a working operator dashboard (users, usage, comments, banned IPs)
gated by a single shared `HTTPBasic` credential pair
(`settings.admin_path`, admin.py:49) — good for one operator, not for
granting individual users admin/mod privileges. `models.py:111-151`
`User` has no `role`/`is_admin` field (only `banned`, `verified`,
`is_premium`). Needs a role field/table and auth checks gating
admin/mod-only actions per account if multiple privileged users are
wanted, distinct from the existing single-operator panel.

## 20. Log line formatting is hard to read

**[Future]** · Area: Infrastructure

Scheduled-job log output
(`social/notifier.py`'s cleanup/sync/check jobs, `catalog/titles.py`'s
unmatched-title retry, `tmdb/tmdb_store.py`'s fallback warnings, etc.) is
plain `logger.info`/`warning` text with no visual structure — scanning a
run's console output for the handful of lines that matter (warnings,
counts) among the routine ones is tedious. Worth a pass on the logging
setup (formatter, color/level distinction, consistent field ordering) to
make console output easier to skim at a glance. Not urgent — purely a
developer-experience/readability issue, no functional impact.

## 21. Production hosting isn't chosen or set up

**[Blocking for 1.0]** · Area: Publishing (app stores, web, going public)

**Context:** Not yet scheduled. Nothing here is started; capturing the shape of the work
before picking it up. Store-specific build steps (Android/iOS/web packaging)
are tracked in renar-frontend's `TODO.md`.

No Dockerfile/compose file
exists in either repo; the only thing running right now is a single
residential-machine deployment behind a router port-forward (`api.renar.app`,
see `docs/design-decisions.md`'s HTTPS entry), not a real host. Needs an
actual host (Fly.io/Railway/a VPS are all viable) running a persistent
Postgres (sqlite is fine locally, not for production) with a backup plan.

## 22. Privacy policy and Terms of Service are drafted but not published

**[Blocking for 1.0]** · Area: Publishing (app stores, web, going public)

`docs/privacy-policy.md` and `docs/terms-of-service.md` exist but are
both marked DRAFT: `[EFFECTIVE DATE]`, `[HOSTING PROVIDER]`, and
`[JURISDICTION]` are unfilled placeholders, and neither has had a legal
review. Both Apple and Google require a live, publicly hosted URL to a
privacy policy at submission time (Google also wants ToS since the app
has accounts and comments). Blocked on the app's subdomain being picked
to host the published pages on (`breren.com` itself is registered
already).

## 23. No payment integration wired to the app stores — and mobile can't just reuse a web payment flow

**[Future]** · Area: Publishing (app stores, web, going public)

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

## 24. Host Android app releases for in-app updates

**[Blocking for 1.0]**

**Why:** the user wants Renar to update itself with one button press. Today a
new frontend build only reaches a phone by hand: `uv run build apk --tg` in
renar-frontend sends the arm64 APK to Telegram, and the user installs it from
there. There is nowhere an installed app can ask "is there a newer version?",
and no forge release to fetch from: renar-frontend's GitHub repo is private
(`gh repo view` → `PRIVATE`) and no tags or releases exist on any forge, so an
unauthenticated phone can't download anything from it. The backend is the one
server every installed app already reaches, so it hosts the update channel.
This item is the server half; renar-frontend's `TODO.md` items 30 (publish
builds here) and 31 (the in-app Update button) build on it.

**Goal:** the backend stores uploaded APKs per ABI, any app can ask
`GET /app-releases/latest?platform=android-arm64-v8a` and download the file,
and the admin panel has an **App Releases** page listing every upload with a
delete button.

### Behaviour
- `GET /app-releases/latest?platform=<p>` (no auth) returns 200 with
  `{"id", "platform", "version", "size_bytes", "sha256", "blake3", "notes",
  "uploaded_at", "download_url"}` for the highest version of that platform.
  "Highest" compares `version` as an integer tuple (`0.10.0` > `0.9.9`), not
  as a string, so it never picks `0.9.9` over `0.10.0`.
- No release for that platform yet → 404 `{"detail": "No release for this platform"}`.
- `platform` not in `APP_RELEASE_PLATFORMS` → 422 (FastAPI validation via a
  `Literal`/enum query type), so a typo is never answered with a silent 404.
- `GET /app-releases/{id}/download` (no auth) streams the file with
  `Content-Type: application/vnd.android.package-archive`, `Content-Length`,
  and `Content-Disposition: attachment; filename="renar-<version>-<abi>.apk"`
  (every artifact filename carries the app version). Unknown id → 404. Row
  exists but file missing on disk → 500 logged at ERROR with the path, never a
  0-byte 200.
- `POST /admin/app-releases` (HTTP Basic admin auth, `users.auth.require_admin`,
  same as every other admin route) takes multipart `file`, `platform`,
  `version`, optional `notes` (max 2000 chars) and returns 201 with the same
  JSON as `latest`.
  - `version` must match `^\d+\.\d+\.\d+$` → else 422.
  - File must start with the ZIP magic bytes `PK\x03\x04` (an APK is a ZIP) → else 422 "Not an APK".
  - File larger than `APP_RELEASE_MAX_BYTES` (200 MiB; today's arm64 APK is
    well under Telegram's 50 MB cap, so 200 MiB leaves headroom) → 413, and the
    partial temp file is deleted.
  - Same `(platform, version)` already stored with the same BLAKE3 → 200 with
    the existing row (re-running a publish is idempotent).
  - Same `(platform, version)` with a different BLAKE3 → 409 "Version already
    published with different content; bump the version". Installed apps
    compare versions, so silently replacing a version's bytes would leave some
    phones on a build that no longer exists.
  - Wrong/missing admin credentials → 401, as everywhere else in `/admin`.
- Files are stored content-addressed under
  `<settings.media_dir>/app-releases/<blake3>.apk`, written to a `.part` temp
  file while hashing (BLAKE3 and SHA-256 in one streaming pass), then renamed
  atomically. SHA-256 is stored alongside BLAKE3 because the phone verifies
  with Python's stdlib `hashlib` (no extra native wheel on Android — see
  renar-frontend `TODO.md` item 31); BLAKE3 stays the project's canonical hash
  (`.b3` files, the media store).
- Admin page `GET /admin/app-releases`: one table per platform, newest version
  first, columns Version · Size (MB, 1 decimal) · Uploaded (UTC) · Notes ·
  BLAKE3 (first 12 hex chars, full value in `title`) · a red-outlined
  **Delete** button. The latest row per platform carries a green "Latest" pill.
  Empty state: "No releases uploaded yet. Publish one with
  `uv run build apk --split --publish` in renar-frontend."
- `POST /admin/app-releases/{id}/delete` removes the row and its file, then
  redirects back (303) to the page. File already missing → row still deleted,
  WARNING logged. Deleting the latest makes the next-highest the latest.
- The admin dashboard (`routers/admin/dashboard.py` `_SERVICES`) gets an
  **App Releases** tile, desc "Android builds served to in-app updates", with
  a package/box icon not used by any other tile (distinct icon per control).

### Out of scope
- Uploading from the admin page UI (uploads come from the build command,
  renar-frontend `TODO.md` item 30); the page is list + delete only.
- iOS, Windows, web and Play Store builds: Play builds must update through
  Play (Google Play policy forbids self-updating outside it), the others aren't
  shipped to users yet.
- A minimum-supported-version / forced-update flag.
- Forge (GitHub/GitLab/Codeberg) releases — separate release workflow.

### Implementation
1. `src/renar_backend/constants.py`: add `APP_RELEASE_PLATFORMS = ("android-arm64-v8a",
   "android-armeabi-v7a", "android-x86_64")` (the three ABIs
   renar-frontend's `launcher._ANDROID_ABIS` builds) and
   `APP_RELEASE_MAX_BYTES = 200 * 1024 * 1024`.
2. `src/renar_backend/models.py`: add `class AppRelease(Base)`, table
   `app_releases`: `id` PK, `platform` (String, not null), `version` (String,
   not null), `blake3` (String(64), unique, not null), `sha256` (String(64),
   unique, not null), `size_bytes` (BigInteger, not null), `notes` (Text,
   nullable), `uploaded_at` (DateTime tz, default `utcnow`). `UniqueConstraint
   ("platform", "version")`. BCNF: the candidate keys are `id`, `(platform,
   version)`, `blake3` and `sha256`; `size_bytes`/`notes`/`uploaded_at` depend
   only on those keys, and the file path is derived from `blake3` at runtime,
   never stored. No version-sort column: it would be derived from `version`.
3. `alembic/versions/<rev>_add_app_releases_table.py`: `uv run alembic revision
   --autogenerate -m "add app_releases table"`, review it, `upgrade head`.
4. `tests/test_normalization.py`: add `app_releases` to whatever per-table
   expectation it keeps (run it first; do not widen any allowlist — see the
   project's BCNF rule).
5. `src/renar_backend/schemas.py`: `AppReleaseOut` (the JSON above;
   `download_url` built as `/app-releases/{id}/download`).
6. `src/renar_backend/app_releases.py` (new, the service layer): `store_upload
   (db, upload_file, platform, version, notes) -> AppRelease` (stream to
   `.part` in 1 MiB chunks, hash with `blake3.blake3()` + `hashlib.sha256()`,
   enforce size and magic, dedupe/409 logic, atomic `os.replace`), `latest(db,
   platform)`, `file_path(release) -> Path`, `delete(db, release_id)`. Named
   logger `logging.getLogger(__name__)`; INFO on store/delete with platform,
   version, size; every failure raises `HTTPException` or logs at ERROR — no
   bare `except`.
7. `src/renar_backend/routers/app_releases.py` (new): the two public routes,
   thin, calling step 6.
8. `src/renar_backend/routers/admin/app_releases.py` (new): the JSON upload
   route, the HTML page (reuse `_html._BASE_CSS`, `_RESPONSIVE_CSS`, `_P`,
   `_FAVICON`, and the existing table/pill/button classes — copy the markup
   style of `periodic_tasks.py`), and the delete POST.
9. `src/renar_backend/routers/admin/__init__.py`: import and
   `include_router(app_releases.router)`; add it to the docstring's sub-module
   list.
10. `src/renar_backend/routers/admin/dashboard.py`: add the `_SERVICES` tile.
11. `src/renar_backend/main.py`: `app.include_router(app_releases.router)` next
    to the other public routers.
12. Check `AbuseGuardMiddleware`: a 404 from `/app-releases/latest` on a
    platform with no build yet is normal traffic from every installed app on
    every launch; make sure it never counts as a strike (exempt the path the
    same way existing benign 404s are exempted), and that any strike path
    still checks `site_settings.exempt_ips` first.
13. `ruff format` then `ruff check` (fix by hand, no `--fix`) on every edited
    `.py`; `metadata -c` on new files, `metadata -m` on edited ones.

### Tests
- `tests/test_app_releases.py` (new, real Postgres via the existing fixtures,
  a tmp `media_dir`):
  - `test_upload_stores_file_and_row`: 201, file at `app-releases/<blake3>.apk`, hashes correct.
  - `test_upload_same_content_is_idempotent`: second identical upload → 200, one row, one file.
  - `test_upload_same_version_different_content_conflicts`: 409, original untouched.
  - `test_upload_rejects_non_zip`, `test_upload_rejects_bad_version`,
    `test_upload_rejects_unknown_platform`: 422 each, no file left behind.
  - `test_upload_too_large_is_413_and_cleans_part_file` (monkeypatch the cap to 1 KiB).
  - `test_upload_requires_admin`: 401 without/with wrong Basic auth.
  - `test_latest_compares_versions_numerically`: `0.9.9` and `0.10.0` → `0.10.0`.
  - `test_latest_404_when_none` and `test_latest_is_per_platform`.
  - `test_download_streams_with_versioned_filename`: headers and bytes match.
  - `test_download_missing_file_is_500_and_logged` (caplog ERROR).
  - `test_delete_removes_row_and_file` and `test_delete_promotes_next_latest`.
  - `test_admin_page_lists_releases_and_empty_state`: HTML contains rows / empty text.
  - `test_latest_404_is_not_an_abuse_strike`: many 404s from one IP never ban it.
- `tests/test_property.py`: hypothesis property — for any set of valid
  versions, `latest` equals `max` by integer tuple.
- `tests/test_fuzz.py`: fuzz the upload form fields → never a 500.
- `tests/integration/test_smoke.py`: live server upload → latest → download → delete round trip.
- `tests/test_normalization.py` passes with the new table.

### Docs
- `docs/README.md`: API section — the three new routes and the admin page.
- `docs/design-decisions.md`: "App updates are served by the backend" (Why:
  frontend repo is private and has no releases; the backend is the one host
  every app reaches) and "Phones verify SHA-256, storage keyed by BLAKE3" (Why:
  stdlib only on Android).
- `CHANGELOG.md` `[Unreleased]`: "Added: app-release hosting for in-app updates
  (`/app-releases/latest`, download, admin upload and App Releases page)."

### Done when
- [ ] `uv run alembic upgrade head` creates `app_releases`; `test_normalization.py` passes.
- [ ] All tests above pass; full `uv run pytest` and `-m integration` green.
- [ ] A curl upload of a real APK shows up on `/admin/app-releases` (screenshot) and downloads with the versioned filename.
- [ ] Dashboard shows the App Releases tile with its own icon.
- [ ] Docs and changelog updated; ruff and metadata clean.

## 25. Add a one-click backend update to the admin panel

**[Blocking for 1.0]**

**Why:** updating the server today means going to the machine, stopping
`uv run be` in its console, `git pull`, `uv sync`, `uv run alembic upgrade
head`, and starting it again — five manual steps, any of which is easy to
forget (a skipped migration surfaces later as 500s). The user wants an
**Update** button in the admin panel that does all of it. Independent of
item 24; either can ship first.

**Goal:** a new **Server Update** page in the admin panel shows the running
version and commit, whether `origin/master` has newer commits (with their
one-line messages and the version they'd bring), and an **Update** button. One
press pulls, syncs dependencies, migrates, restarts the server, and the page
reports the outcome when the server is back.

### Behaviour
- `GET /admin/update` shows: running version (`main.backend_version()`),
  branch, short commit SHA, and the result of a fresh check: `git fetch origin
  master` (30 s timeout), then `git log --oneline HEAD..origin/master` and the
  `version` from `git show origin/master:pyproject.toml`.
- **Up to date** (0 commits behind): "Up to date" with a green pill; Update
  button disabled and visibly greyed out (dimmed background and label).
- **Update available**: list of incoming commits (max 50 shown, then "and N
  more"); enabled primary button "Update to <version>" (or "Update (N
  commits)" when the version didn't change).
- **Blocked** — button disabled with the reason shown right above it:
  - Working tree dirty (`git status --porcelain` not empty) → lists the dirty
    paths. Why: a second editor often has uncommitted work in this checkout; a
    pull would either fail or mix it with the update, and the rollback below
    relies on a clean tree.
  - Not on `master` → "Checked out on <branch>; switch to master to update."
  - Local commits not on origin (`git rev-list origin/master..HEAD` non-empty)
    → "Local commits not pushed; update would need a merge." Only
    fast-forwards are allowed so an update never creates a merge commit.
  - `git fetch` fails or times out → the error text, plus "Retry" link; never
    shown as "Up to date".
  - Another update already running (lock file present) → "An update is already in progress."
- Pressing **Update** asks `confirm("Update and restart the server? Connected
  apps reconnect automatically.")` (a decision dialog, so the browser's own
  is fine), then POSTs `/admin/update`. The server re-checks every blocking
  condition (the page may be stale), spawns the helper, answers 202, and the
  page switches to "Updating… the server restarts; this page reloads when it's
  back" with the custom spinner style used elsewhere in the admin panel (a CSS
  spinner, no browser default), polling `GET /` every 2 s.
- The helper (separate process, runs outside the project venv so `uv sync`
  can replace files the server has open — on Windows a loaded `.pyd` can't be
  overwritten):
  1. Writes `logs/self-update-last.json` `{"status": "running", ...}` and takes
     `logs/self-update.lock` (exclusive create; a lock older than 15 min is
     treated as stale and replaced, logged at WARNING).
  2. Waits for the server to stop gracefully: the worker, after sending the
     202, signals the uvicorn supervisor (Windows: `os.kill(0,
     signal.CTRL_C_EVENT)` — the helper is started with
     `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` so it doesn't receive it;
     POSIX: `os.kill(<supervisor pid>, signal.SIGINT)`). uvicorn's
     `timeout_graceful_shutdown=5` closes SSE streams. If the supervisor PID
     is still alive after 30 s, `taskkill /PID <pid> /T /F` (POSIX `SIGKILL`),
     logged at WARNING.
  3. `git pull --ff-only origin master` → `uv sync --locked` → `uv run alembic upgrade head`.
  4. Starts `uv run be` again (Windows: `CREATE_NEW_CONSOLE`, so the server gets
     its own console window like a hand start; POSIX: `start_new_session=True`,
     stdout/stderr appended to `logs/renar-backend.log`).
  5. Polls `https://127.0.0.1:8000/` (`ssl` context with hostname check off —
     loopback liveness only, `# nosec` with that reason) for up to 120 s until
     it answers with the expected new version.
  6. Writes the final `self-update-last.json`: `started_at`, `finished_at`,
     `from_sha`, `to_sha`, `from_version`, `to_version`, `status`
     (`ok`/`rolled_back`/`failed`), `failed_step`, `log_path`; removes the lock.
- Any step 3–5 failing → rollback: `git reset --hard <from_sha>` (safe: the
  tree was clean by precondition), `uv sync --locked`, start the old version,
  status `rolled_back` with the failing step. A failed `alembic upgrade`
  leaves the schema unchanged because `alembic/env.py` runs all pending
  revisions in one transaction (no `transaction_per_migration`) and Postgres
  DDL is transactional. If the rollback itself fails → status `failed` and
  the log path; the server may be down — say so on the page.
- Every command's full stdout/stderr goes to
  `logs/self-update-<YYYYmmdd-HHMMSS>.log`; the helper logs with the same
  `"%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"` format.
- After the server is back, `/admin/update` shows a result banner from
  `self-update-last.json`: green "Updated 0.19.8 → 0.20.0", amber "Update
  failed at <step>; rolled back to 0.19.8" with the log path, or red "Update
  failed and rollback failed" with the log path. Page times out after 180 s of
  polling → "Server didn't come back in 3 minutes; check `<log path>` on the
  host."
- The old console window (where the user ran `uv run be`) ends with uvicorn's
  normal shutdown lines; the new server runs in a new window. This is the one
  case where the backend restarts itself — the user still starts it by hand
  normally.

### Out of scope
- Updating renar-frontend (handled by its own in-app update, renar-frontend `TODO.md` item 31).
- Choosing a branch/commit or downgrading; it's always fast-forward to `origin/master`.
- Scheduled/automatic updates without a click.
- Running under a service manager (systemd/NSSM); the backend runs from a console today.

### Implementation
1. `src/renar_backend/__main__.py`: in `run()`, before `uvicorn.run`, write
   `os.getpid()` (the supervisor, since `reload=True` runs workers as its
   children) to `logs/be.pid`; delete it in a `finally`.
2. `src/renar_backend/self_update.py` (new, **stdlib only** — it runs under
   `uv run --no-project --isolated python -I`, outside the venv): the helper's
   steps 1–6 and rollback as functions (`stop_server`, `pull`, `sync`,
   `migrate`, `start_server`, `wait_healthy`, `rollback`, `write_status`) plus
   `main(argv)` taking `--repo`, `--pid`, `--from-sha`, `--expected-version`.
   One `_run(cmd, step)` wrapper that tees output to the log and raises
   `StepFailed(step)` on non-zero exit, so no step can fail silently.
3. `src/renar_backend/update_check.py` (new): `check() -> UpdateStatus`
   dataclass (`branch`, `head_sha`, `behind: list[str]`, `remote_version`,
   `blocked_reason: str | None`, `dirty_paths`), running git via
   `subprocess.run(..., timeout=30, check=False)` and turning each failure into
   a `blocked_reason`; `launch(status)` spawns step 2's helper with the right
   creation flags and returns; `last_result()` reads `self-update-last.json`
   (missing → `None`; corrupt → logged ERROR and shown as such).
4. `src/renar_backend/routers/admin/update.py` (new): `GET /update` (renders
   from `check()` + `last_result()`), `POST /update` (re-check → 409 with the
   reason if blocked → `launch` → 202 → `BackgroundTasks` callback that sends
   the stop signal after the response is flushed). Admin auth on both.
5. `src/renar_backend/routers/admin/__init__.py`: include the router; docstring entry.
6. `src/renar_backend/routers/admin/dashboard.py`: **Server Update** tile, desc
   "Pull the latest version and restart", a refresh/arrow-circle icon used by
   no other tile.
7. `src/renar_backend/routers/admin/_html.py`: add a disabled-button style
   (opacity 0.4 on background and label, `cursor: not-allowed`) if none
   exists, and the CSS spinner if none exists.
8. `ruff format` / `ruff check` on every edited `.py`; `metadata -c`/`-m`.

### Tests
- `tests/test_update_check.py` (new; each test builds a real throwaway git
  repo pair in `tmp_path` — a bare "origin" and a clone — so git behaviour is
  real, not mocked):
  - `test_up_to_date`, `test_behind_lists_commits_and_remote_version`,
    `test_dirty_tree_blocks_with_paths`, `test_wrong_branch_blocks`,
    `test_local_commits_block`, `test_fetch_failure_blocks_not_up_to_date`
    (origin path removed), `test_lock_blocks_second_update`,
    `test_stale_lock_is_replaced`.
- `tests/test_self_update.py` (new; same tmp repo pair, `uv`/server steps
  replaced by small fake scripts on `PATH` so the sequence is real):
  - `test_happy_path_writes_ok_status` (from/to sha and versions recorded).
  - `test_migrate_failure_rolls_back_to_from_sha` (HEAD back at `from_sha`, status `rolled_back`, `failed_step == "migrate"`).
  - `test_rollback_failure_reports_failed`.
  - `test_every_step_output_is_in_log`.
  - `test_helper_imports_only_stdlib` (parse the module's imports; it must run outside the venv).
- `tests/test_admin.py`: `test_update_page_requires_admin`,
  `test_update_page_renders_each_state` (monkeypatched `check()` per state:
  disabled button markup for up-to-date/blocked, enabled for available),
  `test_update_post_rechecks_and_409s_when_blocked`,
  `test_update_post_launches_and_returns_202` (launch monkeypatched),
  `test_update_page_shows_last_result_banner` for ok/rolled_back/failed/corrupt json.
- `tests/test_devserver.py` (or a new test next to it): `run()` writes and removes `logs/be.pid`.
- Manual, on the real host: one real update across a commit that adds a
  migration, and one with a deliberately failing migration on a scratch
  branch pushed to a scratch remote (then delete the scratch branch).

### Docs
- `docs/README.md`: "Updating the server" — the button, its preconditions, and the manual fallback commands.
- `README.md` run/deploy section: mention the admin update and that it restarts the server in a new console.
- `docs/design-decisions.md`: "Self-update runs in a helper outside the venv"
  (Why: Windows file locks on loaded `.pyd`s) and "Fast-forward only, clean
  tree only" (Why: safe rollback with `reset --hard`, concurrent editor's WIP).
- `CHANGELOG.md` `[Unreleased]`: "Added: one-click server update from the
  admin panel (pull, sync, migrate, restart, automatic rollback)."

### Done when
- [ ] All listed tests pass; full `uv run pytest` green.
- [ ] Screenshots of `/admin/update` in up-to-date, update-available and dirty-tree states.
- [ ] A real update on the host goes from one commit to the next and the page shows the green result banner.
- [ ] A forced migration failure ends `rolled_back` with the server running the old version.
- [ ] Docs and changelog updated; ruff and metadata clean.

## 26. Replace the admin panel's Basic-auth popup with a login page and authenticator-app codes

**[Blocking for 1.0]** · Area: Admin / security

**Why:** the admin panel is guarded only by HTTP Basic: `require_admin` in
`src/renar_backend/users/auth.py:30` compares one shared
`ADMIN_USERNAME`/`ADMIN_PASSWORD` pair from `.env`, and every admin route in
`routers/admin/*.py` depends on it (about 45 `Depends(_require_admin)` sites).
Opening `<ADMIN_PATH>` shows the browser's native grey credentials popup, there
is no way to log out short of closing the browser, and a leaked password alone
opens the panel. Prod now runs publicly on the Hetzner VPS, so one password
between the internet and user deletion, bans and settings is not enough for
1.0. A failed attempt is only logged (`auth.py:36`), never struck or banned,
so the password can be guessed at whatever rate the generic rate limiter
allows. The user asked for a "more classical" login with an OTP. The OTP is a
TOTP code from an authenticator app (Aegis, Google Authenticator, 1Password),
not an emailed code, because the admin is not a `User` row and has no email,
and TOTP keeps working when SMTP is down (chosen by the user on 2026-11-09).

**Goal:** opening `<ADMIN_PATH>` while logged out shows a renar-styled login
page (same Gruvbox look as the rest of the panel) with Username, Password and
a 6-digit "Authenticator code" field and a **Sign in** button. A correct
triple sets a session cookie and lands on the page that was requested; every
admin page's top bar gains a **Log out** button.

### Behaviour
- Not configured (any of `ADMIN_USERNAME`, `ADMIN_PASSWORD`,
  `ADMIN_TOTP_SECRET` empty): every admin route, the login page included,
  returns 503 "Admin panel not configured" as today. Why: keeps the existing
  "no way to expose it by accident" rule; TOTP is mandatory, not optional,
  otherwise the second factor is one missing line in `.env` away from gone.
- `ADMIN_TOTP_SECRET` set but not valid base32: the server refuses to start
  with a clear `ValueError` from the settings validator (fail loudly at boot,
  not with a 503 at login time).
- Logged out, `GET` on any admin page: `303` to
  `<ADMIN_PATH>/login?next=<original path+query>`. `next` is honoured only
  when it equals `<ADMIN_PATH>` or starts with `<ADMIN_PATH>/`; anything else
  (`//evil.com`, `https://…`) falls back to `<ADMIN_PATH>`. Why: open redirect.
- Logged out, `POST` on any admin action: `401` HTML "Session expired —
  sign in again" with a link to the login page, no redirect. Why: a redirect
  would silently drop the form data and make the action look done.
- `GET <ADMIN_PATH>/login` while already logged in: `303` to `<ADMIN_PATH>`.
- `POST <ADMIN_PATH>/login` (form fields `username`, `password`, `code`,
  `next`):
  - All three correct: set the cookie, `303` to `next`. Log
    `INFO admin login ok ip=<ip>`.
  - Any wrong: re-render the login page with HTTP 401 and one generic error
    "Wrong username, password or code." (never say which one was wrong), the
    username field kept, password and code cleared. Log
    `WARNING admin login failed ip=<ip> username=<repr>` and record a strike
    via `security.strike_and_maybe_ban(ip, "admin login failed")`, **unless
    the IP is in `site_settings.exempt_ips`** (check it first, exactly like
    the middleware at `users/security.py:418`; a missed check once nearly
    banned localhost on `/svc`). If the strike result calls for a temp ban or
    permaban, apply it the same way the middleware does.
  - Accepted codes: current 30 s step ±1 step (`valid_window=1`) to tolerate
    clock drift. Spaces are stripped ("123 456" works).
  - Replay: a code whose time step is ≤ the last successfully used step is
    rejected as wrong, even if otherwise valid. Keep the last used step in a
    module-level variable guarded by a `threading.Lock` (single uvicorn
    process; a restart forgetting it only re-opens a ≤90 s window).
- Session cookie `renar_admin`: a JWT signed with `settings.secret_key`
  (PyJWT, already a dependency), claims `sub=<admin username>`,
  `aud="renar-admin"` (so an app user's access token can never pass as an
  admin session, nor the reverse), `iat`, `exp=iat+8h`, and `cred` = first 16
  hex chars of `blake3(username + "\0" + password + "\0" + totp_secret)`.
  Each request recomputes `cred` from current settings; a mismatch counts as
  logged out. Why: rotating any admin credential in `.env` instantly ends
  every existing session without a session table. Cookie flags: `HttpOnly`,
  `SameSite=Strict`, `Path=<ADMIN_PATH>`, `Secure` when
  `request.url.scheme == "https"` (tests and plain-http local runs use http).
  No sliding renewal: 8 h after sign-in the next request redirects to login.
- **Log out**: a `POST <ADMIN_PATH>/logout` form button in every admin top
  bar, right of the existing "Admin" pill, styled like `.admin-pill`. It
  deletes the cookie and `303`s to the login page. POST, not GET, so a stray
  `<img src=…/logout>` can't log the admin out; `GET` answers 405.
- CSRF: the panel's form POSTs now ride a cookie, whereas today's
  bearer/Basic model made CSRF moot (see `OriginCheckMiddleware`'s docstring
  at `users/security.py:545`). `SameSite=Strict` plus the existing Origin
  check cover it; update that docstring to say so.
- Login page: no external assets (admin CSP is `default-src 'self'`), inline
  CSS from `_BASE_CSS`; `autocomplete="username"`, `"current-password"` and
  `"one-time-code"` with `inputmode="numeric" pattern="[0-9 ]{6,7}"` on the
  code field, so phones show the number pad and password managers autofill.
  Usable at 360 px width without horizontal scroll.
- Honeypot unchanged: with a renamed `ADMIN_PATH`, `/admin/login` is still
  under the bait prefix and permabans.

### Out of scope
- Per-account admin/mod roles (item 19): still one operator.
- Emailed OTP, recovery codes, WebAuthn/passkeys. Lost authenticator means
  generating a new secret with the script below and editing `.env` on the host.
- Any change to the app's own user login (`/auth/login`).

### Implementation
1. `pyproject.toml`: add `pyotp>=2.9` (TOTP) and `segno>=1.6` (terminal QR
   code, pure Python, no deps) with `uv add pyotp segno`; never hand-edit the
   lock. Add `admin-totp = "renar_backend.admin_totp:main"` under
   `[project.scripts]`.
2. `src/renar_backend/config.py`: add `admin_totp_secret: str = ""` next to
   `admin_password` (line 74) with a `field_validator` that, when non-empty,
   strips spaces, uppercases, and checks `base64.b32decode` succeeds, raising
   `ValueError("ADMIN_TOTP_SECRET is not valid base32")` otherwise.
3. `src/renar_backend/admin_totp.py` (new, header via `metadata -c`): `main()`
   generates `pyotp.random_base32()` and writes to stdout the secret, the
   `otpauth://totp/renar:<ADMIN_USERNAME or "admin">?secret=…&issuer=renar`
   URI, a terminal QR (`segno.make(uri).terminal(compact=True)`) and the
   `ADMIN_TOTP_SECRET=…` line to paste into `.env`. Output goes through
   `sys.stdout.write` because it is the command's result, not a log line;
   errors go through `logging`.
4. `src/renar_backend/users/admin_session.py` (new): the one module owning the
   admin session: `admin_configured()`, `verify_login(username, password,
   code) -> bool` (constant-time compares as today, TOTP, replay lock),
   `issue_session(username) -> str`, `read_session(token) -> str | None`
   (`None` on any `jwt.InvalidTokenError` or `cred` mismatch, logged at DEBUG
   because an expired cookie is normal), `_cred_fingerprint()` and
   `COOKIE_NAME`. Keeps `auth.py` about app users (single responsibility).
5. `src/renar_backend/users/auth.py`: rewrite `require_admin(request)` to read
   the cookie through `admin_session.read_session`: 503 when not configured;
   logged out raises a small `AdminLoginRequired` exception carrying method
   and path. Remove `HTTPBasic`/`_basic`. Keep the name and the return value
   (admin username) so the ~45 `Depends(_require_admin)` call sites and their
   `admin_user` audit logging stay untouched.
6. `src/renar_backend/main.py`: register an exception handler for
   `AdminLoginRequired` returning the `303` (GET/HEAD) or `401` (other
   methods) described above.
7. `src/renar_backend/routers/admin/login.py` (new): `GET /login`,
   `POST /login`, `POST /logout`, the safe-`next` helper and the strike logic
   (exempt-IP check first; client IP from the same helper the middleware
   uses). Login HTML built from the `_html` constants.
8. `src/renar_backend/routers/admin/__init__.py`: include `login.router` and
   add it to the docstring's sub-module layout.
9. `src/renar_backend/routers/admin/_html.py`: add `_logout_button()` returning
   the `<form method="post" action="{_P}/logout">` button and use it in
   `_usage_page`'s top bar. Add it to every other hand-built top bar too:
   `dashboard.py:202`, `invites.py:325`, `moderation.py:118` and `:201`,
   `periodic_tasks.py`, `premium.py`, `settings.py`, `users.py` (two); find
   them with `grep -n 'class="topbar"' src/renar_backend/routers/admin/*.py`
   (10 today). Include item 25's update page if it landed first.
10. `src/renar_backend/users/security.py`: update `OriginCheckMiddleware`'s
    docstring (line ~545) for the cookie session.
11. `tests/conftest.py`: `ADMIN_BASIC` becomes `ADMIN_CREDS`; `admin_enabled`
    also sets `settings.admin_totp_secret` to a fixed test secret and resets
    the replay state; new fixture `admin_session(client, admin_enabled)` posts
    a valid login (code from `pyotp.TOTP(secret).now()`) so the client's
    cookie jar holds the session.
12. Replace every `auth=BASIC` with the `admin_session` fixture in
    `tests/test_admin.py`, `test_account_deletion.py`,
    `test_email_confirmation.py`, `test_fuzz.py`, `test_premium.py`,
    `test_ranking.py`, `test_reviews.py`, `test_security.py`, `test_usage.py`
    (`grep -rn "auth=BASIC\|ADMIN_BASIC" tests`). Two logins inside one test
    need a fresh time step because of replay protection: patch `time.time`
    in the replay tests only.
13. `ruff format` then `ruff check` on every edited `.py` (fix by hand, never
    `--fix`); `metadata -m` on edited files, `-c` on the three new ones.

### Tests
- `tests/test_admin_login.py` (new, on the real Postgres test schema):
  - `test_unconfigured_returns_503`: each of the three settings empty in turn gives 503 on `/admin` and `/admin/login`.
  - `test_get_redirects_to_login_with_next`: `/admin/users?q=a` gives 303 to `/admin/login?next=%2Fadmin%2Fusers%3Fq%3Da`.
  - `test_post_without_session_is_401`: logged-out `POST /admin/users/<id>/delete` gives 401 and the user still exists.
  - `test_login_success_sets_cookie_and_redirects`: cookie is HttpOnly, SameSite=Strict, Path=/admin; lands on `next`.
  - `test_wrong_password`, `test_wrong_username`, `test_wrong_code`: 401, same generic message, no cookie.
  - `test_code_with_space_accepted`, `test_code_previous_step_accepted` (drift window).
  - `test_code_two_steps_old_rejected`.
  - `test_code_replay_rejected`: the same code twice, second fails.
  - `test_unsafe_next_ignored`: `next=//evil.com` and `next=https://evil.com` redirect to `/admin`.
  - `test_failed_login_records_strike` and `test_failed_login_exempt_ip_no_strike` (IP in `exempt_ips` leaves no `Strike` row).
  - `test_expired_session_redirects`: `exp` in the past gives 303 to login.
  - `test_rotated_password_kills_session`: changing `settings.admin_password` makes the next request redirect.
  - `test_user_access_token_not_admin_session`: an app JWT in the `renar_admin` cookie redirects (audience check).
  - `test_logout_clears_cookie`: POST logout clears the cookie and `/admin` then redirects; `GET /admin/logout` gives 405.
  - `test_logged_in_get_login_redirects_home`.
  - `test_every_admin_page_has_logout_button`: GET each admin page and assert the logout form is present.
- Settings test (existing config tests, or a new `tests/test_config.py`): invalid base32 `ADMIN_TOTP_SECRET` raises `ValueError`.
- `tests/test_security.py`: `/admin/login` still permabans when `ADMIN_PATH` is renamed.
- Existing admin tests (step 12) all pass through the new fixture, proving no route lost its guard.
- `tests/test_zzz_render_check.py`: if it renders admin pages, add the login page.
- Rendered check: run `uv run be`, open `<ADMIN_PATH>` in Playwright, screenshot the login page at 1280 px and 360 px, the error state, and the dashboard with Log out; review by eye.

### Docs
- `docs/environment-variables.md` "Admin panel" table: rewrite the
  `ADMIN_USERNAME` / `ADMIN_PASSWORD` row (login page, not HTTP Basic) and add
  an `ADMIN_TOTP_SECRET` row (required, base32, generate with
  `uv run admin-totp`, rotating it logs every session out).
- `README.md` line ~134: "`GET /admin` — HTML admin panel behind a login page
  (password + authenticator code); 503 until `ADMIN_USERNAME`,
  `ADMIN_PASSWORD` and `ADMIN_TOTP_SECRET` are set". Add a short "Setting up
  admin 2FA" note with the `uv run admin-totp` command.
- `docs/design-decisions.md`: retitle "Admin panel: server-rendered HTML behind
  HTTP Basic, not a JSON API + SPA" (line 892) to say login form + TOTP, and
  add "Admin session: stateless JWT cookie bound to a credential fingerprint"
  with the Why lines above (no session table, rotation revokes, `aud`
  separation, TOTP over emailed code).
- `docs/anti-abuse.md`: failed admin logins now strike (exempt IPs skipped).
- `.env` on both hosts (dev PC and the Hetzner VPS): add `ADMIN_TOTP_SECRET`
  before deploying, or the panel goes 503.
- Changelog: "Admin panel: classic sign-in page with authenticator-app (TOTP) codes, session cookie and Log out button, replacing the HTTP Basic popup."

### Done when
- [ ] Logged out, `<ADMIN_PATH>` shows the login page, not the browser popup (screenshot).
- [ ] Sign-in needs username + password + a live authenticator code; every wrong one gives the same generic error and a strike (none for exempt IPs).
- [ ] Reused and two-step-old codes are rejected.
- [ ] Log out button on every admin page; afterwards `<ADMIN_PATH>` redirects to login.
- [ ] Changing any of the three admin env values logs existing sessions out.
- [ ] `uv run admin-totp` prints a secret, URI and scannable QR; scanning it in an authenticator app yields codes the login accepts.
- [ ] All listed tests pass; full `uv run pytest` green; ruff and metadata clean.
- [ ] Docs and changelog updated; `ADMIN_TOTP_SECRET` set on the dev and prod hosts.
