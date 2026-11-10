[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/09 11:43:55.623794 )
[//]: # (+ Revised: 	2026/11/10 15:58:25.933242 )
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

Next item number: 32

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
27. [Turn on admin sign-in and the one-click update on the dev PC and the Hetzner VPS](#27-turn-on-admin-sign-in-and-the-one-click-update-on-the-dev-pc-and-the-hetzner-vps)
28. [Show the renar logo as the api.renar.app favicon and on the admin sign-in page](#28-show-the-renar-logo-as-the-apirenarapp-favicon-and-on-the-admin-sign-in-page)
29. [Store the admin password as an Argon2id hash and lock `.env` to the service user](#29-store-the-admin-password-as-an-argon2id-hash-and-lock-env-to-the-service-user)
30. [Put the prod admin panel behind Cloudflare Access](#30-put-the-prod-admin-panel-behind-cloudflare-access)
31. [Make the backend verify Cloudflare Access's signed header on admin routes](#31-make-the-backend-verify-cloudflare-accesss-signed-header-on-admin-routes)

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

**Why:** the admin panel has one shared login: `ADMIN_USERNAME`,
`ADMIN_PASSWORD_HASH` (after item 29) and `ADMIN_TOTP_SECRET` in `.env`,
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

### Behaviour
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

### Out of scope
- A UI for granting roles (CLI only at first).
- Finer permissions than the two roles.
- Changing how app users sign in.

### Implementation
Split into items before building (it's more than one sitting): (a) schema
and key file, (b) sign-in and sessions on accounts, (c) TOTP enrolment and
recovery codes, (d) moderator restrictions per page, (e) removing the `.env`
login. Each needs its own Implementation, Tests and Docs per the template;
`role` lives in its own table keyed by `user_id` if that keeps the schema
BCNF (run `tests/test_normalization.py`).

### Tests
- Defined per split item; at minimum: role checks on every admin route
  (moderator 403 on admin-only pages), revoke kills sessions, encrypted TOTP
  round trip, missing key file stops boot, recovery code single use.

### Docs
- `docs/design-decisions.md`: "Admin is a role on renar accounts, not a
  separate account system" with the clavren comparison above.
- `docs/environment-variables.md`: remove the three variables, add
  `ADMIN_KEY_FILE`.

### Done when
- [ ] The split items above exist in this file and this item is deleted.

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

## 27. Turn on admin sign-in and the one-click update on the dev PC and the Hetzner VPS

**[Blocking for 1.0]** · Area: Operations

**Why:** the admin panel now signs in with a password plus an authenticator
code and has a Server Update page, but both need one-time setup on each host
that only the operator can do. Until `ADMIN_TOTP_SECRET` is set, the panel
answers 503; and the Update page needs the server able to write its own
project directory.
**Goal:** on both hosts the admin can sign in with an authenticator code,
`uv run build apk --split --publish` uploads with the API token, and the
Update button updates and rolls back for real.

### Behaviour
- Dev PC (`api.dev.renar.app`, the renar-backend checkout there) and
  prod (`api.renar.app`, Hetzner VPS `/opt/renar-backend`, systemd
  `renar-backend.service` as user `renar`) each get their own
  `ADMIN_TOTP_SECRET` and `ADMIN_API_TOKEN`.
- The operator's own public IP is in Exempt IPs (`<ADMIN_PATH>/settings`) on
  both, so failed sign-ins never ban it. If it changes and a ban happens:
  `ssh` to the host, `uv run admin-unban <ip>`, then restart the service.

### Out of scope
- Any code change, unless a step below finds a bug (then add an item for it).

### Implementation
1. Dev PC: `uv run admin-totp`, scan the QR (entry "renar (dev)"), put
   `ADMIN_TOTP_SECRET=…` and a new
   `ADMIN_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")`
   in `.env`, restart `uv run be`, sign in at `<ADMIN_PATH>`.
2. Prod, over SSH: 0.20.0 is deployed (by tarball) and `.env` already has an
   `ADMIN_API_TOKEN`. Run `sudo -u renar /opt/renar-backend/.local/bin/uv run admin-totp`
   in `/opt/renar-backend`, add `ADMIN_TOTP_SECRET=…` to `.env`,
   `sudo systemctl restart renar-backend`, sign in.
3. Both panels: add the operator's public IP to Exempt IPs.
4. Prod, so the Update button works: systemd's `ReadWritePaths` must cover
   `/opt/renar-backend` itself (the update renames `src/`, `alembic/`,
   `pyproject.toml`… and writes `.self-update/`, not only `media`, `logs`,
   `certs`, `.cache`); `systemctl daemon-reload` and restart. Prod stays a
   tarball deploy (no git): the page installs release tarballs. The first
   release with the tarball updater has to be deployed by hand, since 0.20.0
   still carries the git-based one.
5. Build PC: store the publish credentials per README "Build" (renar-frontend)
   for `api.dev.renar.app` (`api.renar.app` is stored): `<host>:api_token`
   and `<host>:admin_path`.
6. One real update on prod across a release that adds a migration; one with
   a deliberately failing migration, from a scratch release on a fork, with
   `UPDATE_RELEASE_URL` pointed at it for the test and restored after. On
   the dev PC (a git checkout, so it follows `origin/master`): one real
   update across a commit that adds a migration, and one forced failure from
   a scratch remote's `master`.

### Tests
- None new; this is configuration. The code is covered by
  `tests/test_admin_login.py`, `test_admin_cli.py`, `test_update_check.py`,
  `test_self_update.py` and `test_admin_update.py`.

### Docs
- None, unless a step differs from README "Setting up admin sign-in" /
  "Updating the server": then fix the README.

### Done when
- [ ] Both panels show the login page, and a live authenticator code signs in.
- [ ] Operator IP in Exempt IPs on both.
- [ ] `uv run build apk --split --publish` uploads to prod with the token.
- [ ] Prod's Update page shows "Up to date" (not Blocked) on the latest release.
- [ ] A real update ends with the green "Updated A → B" banner; a forced migration failure ends "rolled back" with the old version running.

## 28. Show the renar logo as the api.renar.app favicon and on the admin sign-in page

**[Blocking for 1.0]** · Area: Admin panel / Branding

**Why:** today every admin page's browser tab shows a 🛠 emoji: `_FAVICON` in
`src/renar_backend/routers/admin/_html.py` is a `data:image/svg+xml` URI
drawing that emoji, and every admin page links it. The panel's CSP
(`default-src 'self'`, set in `SecurityHeadersMiddleware` in
`src/renar_backend/users/security.py`) doesn't allow `data:`, so browsers
that apply CSP to favicons (Firefox) block that icon outright. Opening
`https://api.renar.app/` directly (the `GET /` JSON reply, `home()` in
`main.py`) shows the browser's blank-page icon, because `/favicon.ico` has no
route: it 404s, and since it matches no route, `AbuseGuardMiddleware` counts
each automatic browser fetch as a scanner probe toward
`PROBE_BAN_THRESHOLD`. The sign-in page (`routers/admin/login.py` `_page()`)
shows a generic padlock in the topbar instead of the product's mark, so
nothing tells the operator this is renar's server.
**Goal:** every page on `api.renar.app` and `api.dev.renar.app` (the JSON
root, every admin page) shows the renar mark in the browser tab, as the same
dark rounded tile the web app uses, and the sign-in and session-expired
pages show the renar mark in the topbar where the padlock is now.

### Behaviour
- `GET /favicon.ico` returns 200, `Content-Type: image/x-icon`, a multi-size
  ICO (16, 32, 48, 64 px) of the dark tile: mark `#e9e5da`, dot `#c99b6c`,
  rings `rgba(111,163,145,.5)` on `#17191a`, rounded corners. These are the
  frontend's app-icon colours (`renar-frontend/branding-tools/gen_logo.py`
  `MARK`, `DOT`, `RING`, `INK_BG`); a dark tile reads on both light and dark
  tab strips, which is why the frontend uses it too.
- The response carries `Cache-Control: public, max-age=86400` (a day: the
  icon almost never changes, and without it browsers re-fetch it often).
- `/favicon.ico` never counts toward the rate limit or probe detection: it is
  added to `_UNCOUNTED_PATHS` next to `/health` and `/robots.txt`. It is
  already in `users/usage.py` `_UNTRACKED_PATHS`, so usage stats don't change.
- Every admin page's `<link rel="icon">` points at `/favicon.ico` (same
  origin, so the admin CSP `default-src 'self'` allows it; no CSP change).
  Changing the `_FAVICON` constant is enough: every page in
  `routers/admin/` (`app_releases`, `dashboard`, `invites`, `login`,
  `moderation`, `periodic_tasks`, `premium`, `settings`, `update`, `users`,
  and `_html._usage_page`) already links `{_FAVICON}`.
- The sign-in page (`login._page()`) topbar shows the renar mark at 30×30 px
  in place of the padlock SVG inside `.logo`, with no yellow/orange gradient
  box behind it (the mark has its own rings; the gradient would clash). The
  mark is an inline `<svg>` (inline markup isn't a fetch, so CSP doesn't
  apply), in the dark palette above on a transparent background, so it sits
  on the topbar's `--surface` (`#3c3836`).
- `session_expired_page()` has no topbar today; it gets the same topbar as
  `_page()` (mark + "Admin" / "renar"), so both sign-in screens match.
- Every other admin page keeps its own topbar icon (dashboard tiles, 📦 on
  Invites, …): those icons say which page you're on.
- If the ICO or SVG file is missing from the install (a packaging bug), the
  app fails at import with a `FileNotFoundError` naming the path, rather than
  serving a broken icon: both files are read once at import.

### Out of scope
- The frontend's own favicon (`renar-frontend/src/renar_frontend/assets/`)
  and the app icons: unchanged.
- A light favicon variant or `prefers-color-scheme` switching: the dark tile
  works on both tab strips.
- `apple-touch-icon` and a web manifest: the API isn't installed as a web app.
- Topbar icons on the other admin pages.

### Implementation
1. `src/renar_backend/static/favicon.ico` (new folder and file): generate it
   from `renar-frontend/branding-tools/logo_out/icon-ico-base.png` (256 px
   dark rounded tile) with Pillow:
   `Image.open(p).save("favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])`,
   run once from the scratchpad (no committed script). Don't copy the
   frontend's `icon.ico`: it carries 128 and 256 px layers (≈62 KB) that a
   tab never uses. Check the result lists exactly those four sizes
   (`Image.open(...).info["sizes"]`).
2. `src/renar_backend/static/renar-mark-dark.svg` (new): copy
   `renar-frontend/branding-tools/renar-mark.svg`, drop the `<title>` and the
   `width`/`height` attributes (keep `viewBox="0 0 512 512"`), and recolour:
   both ring circles `stroke="#6fa391" stroke-opacity="0.5"`, the path
   `fill="#e9e5da"`, the dot `fill="#c99b6c"`. Render it to PNG at 30 px and
   60 px (LANCZOS, never NEAREST) on a `#3c3836` background and look at it
   before going on: rings, spiral and dot must all be visible and not muddy.
3. `src/renar_backend/routers/admin/_html.py`: replace the `_FAVICON`
   data-URI with `_FAVICON = "/favicon.ico"`; add
   `_STATIC = Path(__file__).resolve().parents[2] / "static"` and
   `_LOGO_MARK_SVG = (_STATIC / "renar-mark-dark.svg").read_text(encoding="utf-8")`;
   add `.logo.mark { background: none; }` and
   `.logo.mark svg { width: 30px; height: 30px; stroke: none; }` to
   `_BASE_CSS` (the existing `.logo svg` rule sets 16 px and
   `stroke: var(--bg)`, which would shrink the mark and outline its filled
   shapes; the ring circles keep their own `stroke` attribute, which a CSS
   `stroke: none` on the `<svg>` element doesn't override because it only
   inherits).
4. `src/renar_backend/routers/admin/login.py`: add a `_topbar()` helper
   returning the `<header class="topbar">` block with
   `<div class="logo mark" aria-hidden="true">{_LOGO_MARK_SVG}</div>` and the
   existing brand spans; use it in `_page()` (replacing the padlock header)
   and in `session_expired_page()` (new, before `<main>`). One helper, so the
   two screens can't drift (DRY).
5. `src/renar_backend/main.py`: add
   `@app.get("/favicon.ico", include_in_schema=False)` next to `home()`,
   returning `Response(_FAVICON_BYTES, media_type="image/x-icon",
   headers={"Cache-Control": "public, max-age=86400"})`, with
   `_FAVICON_BYTES = (Path(__file__).parent / "static" / "favicon.ico").read_bytes()`
   at module level.
6. `src/renar_backend/users/security.py`: add `"/favicon.ico"` to
   `_UNCOUNTED_PATHS` and extend its comment ("…and the browser's automatic
   favicon fetch").
7. Packaging: hatch ships every non-ignored file under `src/renar_backend`,
   so `static/` should be in the wheel. Confirm with `uv build --wheel` and
   `python -m zipfile -l dist/<wheel>` (both files listed), then delete the
   `dist/` output.
8. `metadata -m` on every edited file; `ruff format` then `ruff check` on the
   edited `.py` files, fixing by hand (never `--fix`).

### Tests
- `tests/test_security.py`:
  - `test_favicon_served`: `GET /favicon.ico` → 200, `image/x-icon`,
    `Cache-Control` contains `max-age=86400`, body opens with Pillow and its
    `info["sizes"]` is exactly {16, 32, 48, 64}.
  - `test_favicon_never_counts_as_probe`: fetch `/favicon.ico`
    `probe_ban_threshold + 5` times from one client, then `GET /` is still
    200 (not 403): the browser's repeated fetches can't ban anyone.
  - `test_favicon_not_rate_limited`: lower `rate_limit_per_minute` to 3 with
    the site-settings override pattern this file already uses, fetch the
    icon 10 times, all 200.
- `tests/test_admin_login.py`:
  - extend `test_login_page_renders_form`: the page contains
    `href="/favicon.ico"`, `class="logo mark"` and the mark's
    `viewBox="0 0 512 512"`, and no longer contains the padlock path
    `M7 11V7a5 5 0 0 1 10 0v4`.
  - `test_session_expired_page_has_logo_topbar`: get the session-expired
    page the way the existing expired-session tests reach it and assert the
    same topbar markup.
  - `test_every_admin_page_uses_served_favicon`: walk the same page list as
    `test_every_admin_page_has_logout_button`; each has
    `href="/favicon.ico"` and none contains `data:image/svg+xml`.
- Rendered UI check: start the backend (`uv run be`), open
  `<ADMIN_PATH>/login` with Playwright in Chromium and Firefox, screenshot
  the topbar and assert the 30×30 `.logo` box isn't one flat colour (mark
  pixels present); check `/favicon.ico` loads (200) in both. Firefox matters
  because it's the browser that blocked the old data-URI icon. Screenshot
  the session-expired page too.
- Full suite: `uv run pytest` green.

### Docs
- `docs/design-decisions.md`, section "Admin panel colors mirror the app's
  Gruvbox palette": add a paragraph: the favicon and sign-in mark are the
  app's dark icon tile (`#17191a`, mark `#e9e5da`, dot `#c99b6c`), served
  from `/favicon.ico` rather than a data URI because the admin CSP is
  `default-src 'self'`.
- `docs/anti-abuse.md`, "3. Rate limiting — throttle first, ban only for
  floods": one sentence that `/health`, `/robots.txt` and `/favicon.ico`
  never count; "2. Probe detection": the favicon is a real route, so
  browsers fetching it never count as probes.
- Changelog under `[Unreleased]`: `### Added` "Serve the renar logo as
  `/favicon.ico` on every page, and show it on the admin sign-in page.";
  `### Fixed` "Browsers fetching the favicon no longer count as scanner
  probes."

### Done when
- [ ] `curl -I https://api.dev.renar.app/favicon.ico` → 200 `image/x-icon`.
- [ ] The browser tab on `/` and on every admin page shows the renar tile in
      Chromium and Firefox (screenshots).
- [ ] Sign-in and session-expired pages show the mark in the topbar, with no
      padlock and no gradient box (screenshots).
- [ ] Repeated `/favicon.ico` fetches never ban or throttle (tests green).
- [ ] The wheel contains `renar_backend/static/favicon.ico` and
      `renar_backend/static/renar-mark-dark.svg`.
- [ ] New tests and the full suite pass; ruff clean; headers updated.
- [ ] Docs and CHANGELOG lines in place.

## 29. Store the admin password as an Argon2id hash and lock `.env` to the service user

**[Blocking for 1.0]** · Area: Admin panel / Security

**Why:** the admin password sits in `.env` in plain text (`ADMIN_PASSWORD`,
`config.py` `admin_password`) and `users/admin_session.py` compares it
directly (`secrets.compare_digest(password.encode(),
settings.admin_password.encode())`). Anyone who reads `.env`, a pre-deploy
backup of it (prod keeps code tarballs with `.env` in `/root/renar-backups/`)
or a copy on the dev PC gets the password outright. The TOTP secret is in the
same file, so one leaked file is a full admin login. On the VPS nothing
restricts the file beyond the `renar` user owning `/opt/renar-backend`.
**Goal:** `.env` holds only an Argon2id hash of the admin password
(`ADMIN_PASSWORD_HASH`). A leaked `.env` gives the TOTP secret but not the
password, so it can't sign in alone. On the VPS `.env` and the Cloudflare
credentials file are readable only by `renar`.

### Behaviour
- `uv run admin-password` asks for the password twice (hidden, `getpass`),
  refuses an empty one, one under 12 characters, or two that differ (exit 1,
  a one-line reason, nothing printed), and otherwise prints
  `ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$…'` plus "Put this
  line in .env and restart the server. This signs out every current admin
  session." The single quotes matter: python-dotenv doesn't interpolate inside
  single quotes, so the `$` signs survive.
- Hashing uses `argon2-cffi`'s `PasswordHasher()` defaults (RFC 9106
  low-memory profile: 64 MiB, 3 passes, 4 lanes). One sign-in costs about
  50 ms and 64 MiB on the 1 GB VPS, which is fine because sign-ins are rare
  and already rate-limited.
- Sign-in verifies with `PasswordHasher().verify(hash, password)`;
  `VerifyMismatchError` means a wrong password (same response and strike as
  today). The password is always verified, even when the username is wrong,
  so response time doesn't reveal which half was wrong (the current code
  also always runs both comparisons).
- Boot checks, in `config.py` validators, each stopping the server with a
  one-line message (same pattern as the existing `admin_totp_secret`
  validator):
  - a non-empty `ADMIN_PASSWORD` → "ADMIN_PASSWORD is no longer read: run
    `uv run admin-password` and set ADMIN_PASSWORD_HASH instead" (so an old
    `.env` can't silently leave the panel unconfigured or the plain password
    in place);
  - a non-empty `ADMIN_PASSWORD_HASH` that doesn't start with `$argon2id$`
    → "ADMIN_PASSWORD_HASH is not an Argon2id hash".
- `admin_configured()` needs `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` and
  `ADMIN_TOTP_SECRET`; the 503 detail names `ADMIN_PASSWORD_HASH`.
- Changing the password changes the hash, which is part of the session
  fingerprint, so every admin session is signed out (as today).
- VPS: `/opt/renar-backend/.env` and `/opt/renar-backend/.secrets/cloudflare.ini`
  are `renar:renar` mode `0600`; `/root/renar-backups/` is mode `0700`.
  The local leftover `D:\tmp\renar_db_pw.txt` (prod DB password written
  during the VPS migration) is deleted once its value is in a password
  manager.

### Out of scope
- Admin accounts in the database and per-account roles (item 19).
- Moving `ADMIN_TOTP_SECRET` or `ADMIN_API_TOKEN` out of `.env`.
- Rehashing on parameter change (`check_needs_rehash`): one operator re-runs
  `admin-password` instead.
- App users' bcrypt hashes (`users/auth.py`): unchanged.

### Implementation
1. `pyproject.toml`: add `argon2-cffi>=23.1` to `dependencies` with
   `uv add`, and the script `admin-password` (entry point `renar_backend.admin_cli:password`)
   next to `admin-totp`.
2. `src/renar_backend/config.py`: add `admin_password_hash: str = ""`; keep
   `admin_password: str = ""` only so a field validator can reject a non-empty
   value with the message above; add the `$argon2id$` prefix validator.
3. `src/renar_backend/users/admin_session.py`: module-level
   `_HASHER = PasswordHasher()`; `admin_configured()` and
   `_cred_fingerprint()` use `settings.admin_password_hash`; the credential
   check calls `_HASHER.verify(...)`, catching `VerifyMismatchError` as a
   wrong password. Any other `argon2.exceptions.VerificationError` /
   `InvalidHashError` is logged at `error` with `exc_info` (named logger
   already in the module) and treated as a failed sign-in, never a 500 and
   never silent.
4. `src/renar_backend/admin_cli.py`: `password_main(argv)` (argparse,
   `getpass.getpass` twice, checks above, prints the line) and a `password()`
   entry point, mirroring `totp_main`/`totp`.
5. `src/renar_backend/routers/admin/login.py:109` and
   `src/renar_backend/users/auth.py:42`: the 503 detail says
   `ADMIN_PASSWORD_HASH`.
6. `src/renar_backend/_test_server.py:67`: set `ADMIN_PASSWORD_HASH = ""`
   instead of `ADMIN_PASSWORD`.
7. `.env.example`: replace `ADMIN_PASSWORD=` with `ADMIN_PASSWORD_HASH=` and
   a comment "generate with `uv run admin-password`".
8. Dev PC: `uv run admin-password`, replace the `ADMIN_PASSWORD` line in
   `.env`, restart `uv run be`, sign in.
9. VPS (after deploying the release with this change):
   `sudo -u renar HOME=/opt/renar-backend /opt/renar-backend/.local/bin/uv run --no-dev admin-password`,
   edit `.env`, then `chown renar:renar /opt/renar-backend/.env /opt/renar-backend/.secrets/cloudflare.ini`,
   `chmod 600` both, `chmod 700 /root/renar-backups`,
   `systemctl restart renar-backend`, sign in. If item 27 is still open,
   add `admin-password` to its setup steps for both hosts.
10. `ruff format` then `ruff check` on edited `.py` files (fix by hand);
    `metadata -m` on every edited file.

### Tests
- `tests/conftest.py`: `ADMIN_PASSWORD_HASH = PasswordHasher().hash(ADMIN_CREDS[1])`
  computed once at import; the admin fixture sets `settings.admin_password_hash`;
  env reset uses `ADMIN_PASSWORD_HASH`.
- `tests/test_admin_login.py`: the two parametrized lists
  (`test_unconfigured_returns_503`, `test_rotated_credential_kills_session`)
  use `admin_password_hash`; new `test_wrong_password_with_hash_is_rejected`
  (strike recorded), `test_wrong_username_still_verifies_password` (patch
  `_HASHER.verify` with a spy, assert it ran), and
  `test_corrupt_hash_fails_closed_and_logs` (hash replaced by
  `$argon2id$garbage` after boot → sign-in refused, `caplog` has an error).
- `tests/test_config.py` (or wherever the `admin_totp_secret` validator is
  tested): plain `ADMIN_PASSWORD` set → `ValidationError` with the message;
  non-Argon2 hash → `ValidationError`; empty both → loads.
- `tests/test_admin_cli.py`: `password_main` with patched `getpass` — happy
  path prints a line that `PasswordHasher().verify` accepts; mismatch, empty
  and 11-character inputs exit 1 and print no hash.
- Full suite `uv run pytest` green.

### Docs
- `docs/environment-variables.md`, "Admin panel": replace the
  `ADMIN_USERNAME` / `ADMIN_PASSWORD` row with `ADMIN_USERNAME` and
  `ADMIN_PASSWORD_HASH` (generate with `uv run admin-password`, single-quoted,
  boot refuses a plain `ADMIN_PASSWORD`).
- `docs/design-decisions.md`: new entry "Admin password stored as an Argon2id
  hash": why (a leaked `.env` no longer gives the password; the TOTP secret
  alone can't sign in), why Argon2id over the bcrypt app users use (memory-hard,
  current OWASP first choice, no 72-byte limit), why defaults.
- `README.md`: wherever admin setup is described, the `admin-password` step.
- Changelog `[Unreleased]`: `### Changed` "The admin password is stored as an
  Argon2id hash (`ADMIN_PASSWORD_HASH`, made with `uv run admin-password`);
  a plain `ADMIN_PASSWORD` stops the server at boot."

### Done when
- [ ] `grep ADMIN_PASSWORD= .env` is empty on the dev PC and the VPS, and
      sign-in works on both.
- [ ] A plain `ADMIN_PASSWORD` in `.env` stops the server with the message.
- [ ] `stat -c '%U:%G %a'` shows `renar:renar 600` for `.env` and
      `cloudflare.ini` on the VPS, and `700` for `/root/renar-backups`.
- [ ] `D:\tmp\renar_db_pw.txt` no longer exists.
- [ ] New tests and the full suite pass; ruff clean; headers updated.
- [ ] Docs and CHANGELOG lines in place.

## 30. Put the prod admin panel behind Cloudflare Access

**[Blocking for 1.0]** · Area: Admin panel / Security

**Why:** anyone on the internet who learns `ADMIN_PATH` (from browser
history, a screenshot, a log line) reaches the prod sign-in page; only the
password and TOTP code stand between them and the panel. `ADMIN_PATH` hides
the page from scanners but is itself a secret that can leak. Prod
(`api.renar.app`, Hetzner VPS) already accepts traffic only from
Cloudflare's IP ranges (ufw rules), so Cloudflare can check who someone is
before a request ever reaches the server. After item 29, so the password is
hashed before this goes live.
**Goal:** opening `https://api.renar.app/<ADMIN_PATH>` first shows
Cloudflare's sign-in (a one-time code mailed to the operator's address); only
then does renar's own sign-in page appear. `uv run build apk --split --publish`
keeps uploading to prod without a browser.

### Behaviour
- Cloudflare Zero Trust (free plan, up to 50 users) has one self-hosted
  application "renar admin (prod)": domain `api.renar.app`, path
  `<ADMIN_PATH without the leading slash>` (Access matches the path and
  everything under it), session duration 24 hours.
- Policy 1 "operator", action Allow: include Emails = the operator's own
  address; login method One-time PIN.
- Policy 2 "apk publish", action Service Auth: include Service Token =
  `renar-apk-publish` (created under Access → Service credentials, duration
  1 year). Non-browser clients send `CF-Access-Client-Id` and
  `CF-Access-Client-Secret` headers instead of signing in.
- Everything outside the admin path (the app API, `/app-releases/latest`, the
  APK download, `/health`, `/robots.txt`, the `/admin` honeypot) is untouched.
- renar-frontend's publish (`launcher.py`, `_publish_credentials` and the
  upload loop): reads two optional keyring entries in the existing
  `renar-backend-admin` service, `api.renar.app:cf_access_client_id` and
  `api.renar.app:cf_access_client_secret`. If both are set, every upload
  sends them as the two headers; if neither is, nothing changes (dev). If
  only one is set, it stops with "--publish: set both cf_access_client_id
  and cf_access_client_secret for <host>, or neither".
- Publish when Access blocks the upload (missing/expired token): Cloudflare
  answers 302 to its login page or 403. The upload loop turns both into
  "--publish: Cloudflare Access blocked the upload to <host> (HTTP <code>);
  store the service token in the keyring (see README Build)", not the
  generic "answered HTTP …" with a page of HTML.
- Dev (`api.dev.renar.app`) is out: its DNS record is unproxied (DNS only),
  so Cloudflare never sees that traffic; it keeps `ADMIN_PATH` + password +
  TOTP.

### Out of scope
- Making renar itself verify Cloudflare's signed header (item 31).
- Proxying the dev host through Cloudflare.
- Access in front of anything but the admin path.

### Implementation
1. renar-frontend `src/renar_frontend/launcher.py`: add
   `cf_access_client_id: str | None` and `cf_access_client_secret: str | None`
   to `PublishTarget`; read them in `_publish_credentials` (both-or-neither
   check above); in the upload loop build `headers` from the bearer token plus
   the two Access headers when present; add the 302/403 branch with the
   message above. Logging stays on the module's `_log`; never log the secret.
2. Ship that frontend change (commit; no app release needed, it's build
   tooling) before step 3, or publishing breaks the moment Access goes on.
3. Cloudflare dashboard → Zero Trust: create the team if none exists, keep
   One-time PIN as the login method, create service token
   `renar-apk-publish` (copy the id and secret once; the secret isn't shown
   again), create the application and both policies above. Dashboard only:
   the zone-scoped DNS token can't manage Access, and the work is one-off.
4. Build PC: store the two values with
   `uv run python -c "import keyring; keyring.set_password('renar-backend-admin', 'api.renar.app:cf_access_client_id', '<id>')"`
   and the same for `:cf_access_client_secret`.
5. Check by hand: a private browser window on `https://api.renar.app/<ADMIN_PATH>`
   shows Cloudflare's code prompt; after the code, renar's sign-in; `curl -I`
   without headers gets 302/403; `uv run build apk --split --publish` of a
   test version uploads (then delete that test release from the App Releases
   page).
6. Add a calendar reminder 11 months out to rotate the service token (it
   expires after a year and publishing would then fail with the 403 message).

### Tests
- renar-frontend `tests/test_launcher_build_tooling.py`:
  - `test_publish_credentials_reads_cf_access_pair`: both keyring entries set
    → `PublishTarget` carries them.
  - `test_publish_credentials_rejects_half_cf_access_pair`: only one set →
    `SystemExit` with the message.
  - `test_publish_sends_cf_access_headers` (with the injectable `client`, an
    `httpx.MockTransport`): headers present on every upload; absent when the
    pair is unset.
  - `test_publish_access_block_message` for 302 and 403: the friendly message,
    and `already published` lists earlier ABIs.
- Full renar-frontend suite green. The Cloudflare side is checked by step 5
  (no automated test can reach Zero Trust).

### Docs
- renar-frontend `README.md`, "Build": the two optional keyring commands and
  when they're needed (prod behind Access).
- renar-backend `docs/design-decisions.md`, next to "`ADMIN_PATH` is
  configurable…": entry "Prod admin panel behind Cloudflare Access": why
  (identity check before the origin; `ADMIN_PATH` stays as a second layer),
  why a service token for publish, why dev isn't covered.
- renar-backend `docs/anti-abuse.md` or the deployment doc that covers the
  VPS: where the Access app lives and how to rotate the service token.
- Changelogs: renar-frontend `### Added` "`--publish` sends a Cloudflare
  Access service token when one is stored for the target host."

### Done when
- [ ] Private window on the prod admin path shows Cloudflare's code prompt
      first (screenshot).
- [ ] `curl -I https://api.renar.app/<ADMIN_PATH>/login` without headers →
      302 or 403.
- [ ] A test `--publish` to prod succeeds with the token, and fails with the
      friendly message with the token removed from the keyring.
- [ ] Rotation reminder set.
- [ ] Frontend tests pass; docs and changelog lines in place.

## 31. Make the backend verify Cloudflare Access's signed header on admin routes

**[Blocking for 1.0]** · Area: Admin panel / Security

**Why:** after item 30, Cloudflare Access protects prod's admin path, but
renar doesn't know that: the server would serve the admin path to any request
that arrives from a Cloudflare IP. Allowing only Cloudflare's IP ranges
doesn't prove the request went through *your* Cloudflare zone and its Access
policy: anyone with their own Cloudflare account can point a proxied record
at the VPS IP (`<VPS IP>`) and reach the origin from a Cloudflare IP,
skipping Access entirely. Cloudflare adds a signed JWT
(`Cf-Access-Jwt-Assertion` header) to every request it lets through;
checking it closes that gap. After item 30.
**Goal:** when Access is configured for a host, a request to the admin path
without a valid Access token gets the same 404 an unknown path gets, before
any renar sign-in code runs.

### Behaviour
- Two new settings: `CF_ACCESS_TEAM_DOMAIN` (e.g. `renar.cloudflareaccess.com`)
  and `CF_ACCESS_AUD` (the application's Audience tag, Zero Trust → Access →
  Applications → renar admin (prod) → Overview). Both empty (default, and on
  dev) → no check at all. Only one set → boot stops with
  "set both CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD, or neither".
- Both set → every request whose path starts with the admin path (including
  `/login`, the API-token upload route and static admin pages) must carry
  `Cf-Access-Jwt-Assertion`, an RS256 JWT whose signature checks against
  `https://<team>/cdn-cgi/access/certs`, with `aud` containing
  `CF_ACCESS_AUD`, `iss` = `https://<team>`, and `exp` in the future (PyJWT
  default 0 s leeway; add 60 s for clock skew). Browser sign-ins and the
  service-token publish both carry this header.
- Missing or invalid token → 404 `{"detail": "Not Found"}` (indistinguishable
  from a nonexistent path), logged at `warning` with the client IP and the
  reason (missing / bad signature / wrong aud / expired), never the token.
  It does not add an abuse strike: a stale browser tab must not get the
  operator banned.
- Signing keys are fetched with `jwt.PyJWKClient` (cached, `lifespan=3600`).
  If the certs URL can't be fetched and no cached key matches → 503 "Admin
  access check unavailable", logged at `error` with `exc_info`; never fail
  open.
- The `/admin` honeypot keeps working as before (it isn't the admin path once
  `ADMIN_PATH` is moved).

### Out of scope
- Using the Access identity (email) as renar's admin identity; renar's own
  sign-in stays.
- Any non-admin route.

### Implementation
1. `pyproject.toml`: change `PyJWT>=2.9` to `PyJWT[crypto]>=2.9` (`uv add`),
   which pulls in `cryptography` for RS256.
2. `src/renar_backend/config.py`: `cf_access_team_domain: str = ""`,
   `cf_access_aud: str = ""`, and a model validator for the both-or-neither
   rule.
3. New `src/renar_backend/users/cf_access.py`: `verify_access_jwt(token) -> None`
   raising a small `AccessDenied(reason)` exception, with the module-level
   `PyJWKClient` built lazily from the setting; named logger `_log`.
4. `src/renar_backend/users/security.py`: in `SecurityHeadersMiddleware`'s
   neighbour (or a new `CloudflareAccessMiddleware` registered right after
   `AbuseGuardMiddleware` in `main.py`, so bans still apply first), run the
   check for admin-path requests when both settings are set, returning the
   404/503 above. One middleware, not a dependency on each admin router, so
   no admin route can be missed.
5. VPS `.env`: set both values, restart, check (Done when).
6. `ruff format` then `ruff check`; `metadata -c` on the new module,
   `metadata -m` on edited files.

### Tests
- `tests/test_cf_access.py` (new), with an RSA key generated in the test and
  `PyJWKClient.get_signing_key_from_jwt` patched to return it:
  - settings unset → admin path works without a header (dev unchanged);
  - valid token → admin login page 200;
  - missing header, wrong `aud`, wrong `iss`, expired, signed by another key
    → 404 each, a warning logged with the reason, no strike row written;
  - key fetch raises `PyJWKClientError` → 503, error logged;
  - non-admin path (`/health`, `/app-releases/latest`) never checked;
  - config: only one of the two set → `ValidationError`.
- `tests/test_admin_login.py`: one test that the upload route with a valid
  bearer token but no Access header gets 404 when Access is configured.
- Full suite green.

### Docs
- `docs/environment-variables.md`, "Admin panel": rows for
  `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` (where to find each, empty on
  dev).
- `docs/design-decisions.md`: extend item 30's entry with why the origin
  checks the JWT (Cloudflare-IP allowlisting alone can be bypassed through
  another Cloudflare account) and why failures are a 404 without a strike.
- Changelog `[Unreleased]` `### Security`: "When Cloudflare Access is
  configured, admin routes require its signed header; requests that bypass
  Access get a 404."

### Done when
- [ ] On prod, the admin path works in the browser after the Cloudflare code
      and `--publish` still uploads.
- [ ] `curl -H "Host: api.renar.app" https://<VPS IP>/<ADMIN_PATH>/login --resolve …`
      style request without the header (from a Cloudflare-proxied test
      record on another zone, or by temporarily allowing your IP in ufw) → 404.
- [ ] New tests and the full suite pass; ruff clean; headers updated.
- [ ] Docs and CHANGELOG lines in place.
