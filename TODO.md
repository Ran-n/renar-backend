[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/09 11:43:55.623794 )
[//]: # (+ Revised: 	2026/11/24 10:57:01.332150 )
[//]: # ( ---------------------------------------------------------------------- )

# TODO

The planned work: everything here blocks 1.0. Each item is self-contained:
reading it alone is enough to implement it fully, without asking anything.
Work top to bottom unless an item says otherwise.

Every item here blocks 1.0 and carries the tag line `[Blocking for 1.0]`, or
`[Pending manual review]` when its code is done and tested and only a
one-time human action is left (buying an account, safeguarding a
credential). "1.0" means the next major version bump (first stable/public
release), not the next minor/patch. Anything that doesn't block 1.0 lives
in `BACKLOG.md` as a light `B<n>` item and is promoted here when it is
planned. Done or dropped items are deleted, never marked done:
history lives in git, `CHANGELOG.md` and `docs/design-decisions.md`. Items
moved over from the old `docs/backlog.md` keep their original free-form
text; rewrite one into the template below before implementing it.

| To do | Backlog |
|:-----:|:-------:|
| **17** | **32** |

Next item number: 55

## Index

- [22. Publish the Terms of Service](#22-publish-the-terms-of-service)
- [27. Turn on admin sign-in and the one-click update on the dev PC and the Hetzner VPS](#27-turn-on-admin-sign-in-and-the-one-click-update-on-the-dev-pc-and-the-hetzner-vps)
- [29. Switch prod to the hashed admin password and lock `.env` to the service user](#29-switch-prod-to-the-hashed-admin-password-and-lock-env-to-the-service-user)
- [30. Put the prod admin panel behind Cloudflare Access](#30-put-the-prod-admin-panel-behind-cloudflare-access)
- [31. Turn on the Cloudflare Access header check on prod](#31-turn-on-the-cloudflare-access-header-check-on-prod)
- [39. Name the license version in every mention of the license](#39-name-the-license-version-in-every-mention-of-the-license)
- [44. Keep asking for the reload while a self-update waits](#44-keep-asking-for-the-reload-while-a-self-update-waits)
- [45. Cap the library page size by plan on the server](#45-cap-the-library-page-size-by-plan-on-the-server)
- [46. Store admin accounts and grant them from the server shell](#46-store-admin-accounts-and-grant-them-from-the-server-shell)
- [47. Sign in to the admin panel with a renar account](#47-sign-in-to-the-admin-panel-with-a-renar-account)
- [48. Recovery codes for admin accounts](#48-recovery-codes-for-admin-accounts)
- [49. Limit what moderators can open in the panel](#49-limit-what-moderators-can-open-in-the-panel)
- [50. Remove the shared admin login from `.env`](#50-remove-the-shared-admin-login-from-env)
- [51. Pair a phone with an admin account](#51-pair-a-phone-with-an-admin-account)
- [52. Build the Android admin app](#52-build-the-android-admin-app)
- [53. Release and update the Android admin app](#53-release-and-update-the-android-admin-app)
- [54. Let the certificate renewal restart the backend](#54-let-the-certificate-renewal-restart-the-backend)

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
- Keep the Index in file order: one `- [<n>. title](#anchor)` line per item;
  update it whenever an item is added, retitled, moved or deleted.
- Keep the count table above the Index equal to the items here and in
  `BACKLOG.md`, in both files; update it whenever an item is added, deleted,
  promoted or parked.
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
   new items (here if it's planned, in `BACKLOG.md` if not).

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

## 22. Publish the Terms of Service

**[Blocking for 1.0]** · Area: Publishing (app stores, web, going public)

**Why:** Google wants terms for an app with accounts and comments. They went
live on 2026-11-23 with backend 0.24.0: <https://renar.app/terms/>,
<https://renar.app/privacy/> and their Spanish versions under `/es/` answer
200, dated that day. The provider is named by trade name only (Breren, the
trade name of an individual): the owner chose on 2026-11-23 to leave the legal
name out. What's left is checking the two places that link to them.
**Goal:** the app and the Play listing lead to the published terms.

### Implementation
1. On a phone with 0.25.1 or later, open Profile → Legal → Terms of Service,
   in English and in Spanish: the matching page opens in the browser.
2. If the Play Console listing has a terms field, give it
   <https://renar.app/terms/>.

### Done when
- [ ] The app's Terms of Service row opens the page in both languages.
- [ ] The Play Console field has the URL, or there is no such field.

## 27. Turn on admin sign-in and the one-click update on the dev PC and the Hetzner VPS

**[Blocking for 1.0]** · Area: Operations

**Why:** the admin panel now signs in with a password plus an authenticator
code and has a Server Update page, but both need one-time setup on each host
that only the operator can do. Until `ADMIN_TOTP_SECRET` is set, the panel
answers 503; and the Update page needs the server able to write its own
project directory.
**Status (2026-11-21):** prod already has `ADMIN_TOTP_SECRET`,
`ADMIN_API_TOKEN` and `ADMIN_PASSWORD_HASH` in `.env`, and its systemd unit
has `ReadWritePaths=/opt/renar-backend` (step 4 is done). The dev PC's
`.env` still has neither `ADMIN_TOTP_SECRET` nor `ADMIN_API_TOKEN`; the owner
does step 1 later. Steps 3, 5 and 6 are still open.

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
1. Dev PC (`ADMIN_PASSWORD_HASH` is already in `.env`; `uv run
   admin-password` makes a new one): `uv run admin-totp`, scan the QR
   (entry "renar (dev)"), put `ADMIN_TOTP_SECRET=…` and a new
   `ADMIN_API_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")`
   in `.env`, restart `uv run be`, sign in at `<ADMIN_PATH>`.
2. Prod, over SSH: 0.20.0 is deployed (by tarball) and `.env` already has an
   `ADMIN_API_TOKEN`. Run `sudo -u renar /opt/renar-backend/.local/bin/uv run admin-totp`
   in `/opt/renar-backend`, add `ADMIN_TOTP_SECRET=…` to `.env`,
   `sudo systemctl restart renar-backend`, sign in. From the release
   that hashes the admin password on, `.env` also needs
   `ADMIN_PASSWORD_HASH` (item 29 step 2) before that restart.
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

## 29. Switch prod to the hashed admin password and lock `.env` to the service user

**[Pending manual review]** · Area: Admin panel / Security

**Why:** the server now only accepts an Argon2id hash of the admin password
(`ADMIN_PASSWORD_HASH`, made by `uv run admin-password`) and refuses to boot
while a plain `ADMIN_PASSWORD` is in `.env`. The dev PC's `.env` was
converted on 2026-11-15. Prod still runs the old release with the plain
password, and on the VPS nothing restricts `.env` beyond the `renar` user
owning `/opt/renar-backend`.
**Goal:** prod signs in against the hash, a leaked `.env` no longer gives
the password, and `.env` and the Cloudflare credentials file are readable
only by `renar`.

**Status (2026-11-21):** steps 2 and 3 are done. Prod's `.env` has
`ADMIN_PASSWORD_HASH` and no `ADMIN_PASSWORD` (the hash was made during the
0.23.0 deploy on 2026-11-16). `.env` and `cloudflare.ini` are
`renar:renar 600`, and `/root/renar-backups` is `700`. Left: step 1 (sign in
on the dev PC, which needs the owner's password) and step 4 (the owner
first saves the password in KeePass).

### Behaviour
- The release that carries this change will not start on prod until its
  `.env` has `ADMIN_PASSWORD_HASH` and no `ADMIN_PASSWORD`: do step 2 as
  part of that deploy, before the restart.

### Implementation
1. Dev PC: restart `uv run be` and sign in at `<ADMIN_PATH>` with the usual
   password, to confirm the converted `.env` works.
2. VPS, while deploying the release:
   `sudo -u renar HOME=/opt/renar-backend /opt/renar-backend/.local/bin/uv run --no-dev admin-password`,
   paste the printed line (with its single quotes) into `.env`, delete the
   `ADMIN_PASSWORD` line.
3. VPS: `chown renar:renar /opt/renar-backend/.env /opt/renar-backend/.secrets/cloudflare.ini`,
   `chmod 600` both, `chmod 700 /root/renar-backups`,
   `systemctl restart renar-backend`, sign in.
4. Delete `D:\tmp\renar_db_pw.txt` (the prod database password, written
   during the VPS migration) once its value is in a password manager.

### Done when
- [ ] `grep ADMIN_PASSWORD= .env` is empty on the VPS, and sign-in works on
      both hosts.
- [ ] `stat -c '%U:%G %a'` shows `renar:renar 600` for `.env` and
      `cloudflare.ini` on the VPS, and `700` for `/root/renar-backups`.
- [ ] `D:\tmp\renar_db_pw.txt` no longer exists.

## 30. Put the prod admin panel behind Cloudflare Access

**[Blocking for 1.0]** · Area: Admin panel / Security

**Why:** anyone on the internet who learns `ADMIN_PATH` (from browser
history, a screenshot, a log line) reaches the prod sign-in page; only the
password and TOTP code stand between them and the panel. Prod
(`api.renar.app`, Hetzner VPS) already accepts traffic only from
Cloudflare's IP ranges (ufw rules), so Cloudflare can check who someone is
before a request ever reaches the server. The code side is done:
renar-frontend's `--publish` sends an Access service token when one is in
the keyring (README "Build"). What is left is in Cloudflare's dashboard,
which only the operator can do. After item 29.
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
  1 year).
- Everything outside the admin path (the app API, `/app-releases/latest`, the
  APK download, `/health`, `/robots.txt`, the `/admin` honeypot) is untouched.
- Dev (`api.dev.renar.app`) is out: its DNS record is unproxied (DNS only),
  so Cloudflare never sees that traffic; it keeps `ADMIN_PATH` + password +
  TOTP.

### Out of scope
- Proxying the dev host through Cloudflare.
- Access in front of anything but the admin path.

### Implementation
1. Cloudflare dashboard → Zero Trust: create the team if none exists, keep
   One-time PIN as the login method, create service token
   `renar-apk-publish` (copy the id and secret once; the secret isn't shown
   again), create the application and both policies above. Dashboard only:
   the zone-scoped DNS token can't manage Access, and the work is one-off.
2. Build PC: store the two values with
   `uv run python -c "import keyring; keyring.set_password('renar-backend-admin', 'api.renar.app:cf_access_client_id', '<id>')"`
   and the same for `:cf_access_client_secret`.
3. Check by hand: a private browser window on `https://api.renar.app/<ADMIN_PATH>`
   shows Cloudflare's code prompt; after the code, renar's sign-in; `curl -I`
   without headers gets 302/403; `uv run build apk --split --publish` of a
   test version uploads (then delete that test release from the App Releases
   page).
4. Add a calendar reminder 11 months out to rotate the service token (it
   expires after a year and publishing would then fail with "Cloudflare
   Access blocked the upload").
5. Then do item 31.

### Done when
- [ ] Private window on the prod admin path shows Cloudflare's code prompt
      first (screenshot).
- [ ] `curl -I https://api.renar.app/<ADMIN_PATH>/login` without headers →
      302 or 403.
- [ ] A test `--publish` to prod succeeds with the token, and fails with the
      friendly message with the token removed from the keyring.
- [ ] Rotation reminder set.

## 31. Turn on the Cloudflare Access header check on prod

**[Blocking for 1.0]** · Area: Admin panel / Security

**Why:** after item 30, Cloudflare Access protects prod's admin path, but
allowing only Cloudflare's IP ranges doesn't prove a request went through
*your* zone and its Access policy: anyone with their own Cloudflare account
can point a proxied record at the VPS IP and reach the origin from a
Cloudflare IP, skipping Access. The server can now check the signed header
Access adds (`users/cf_access.py`, see `docs/anti-abuse.md` "Cloudflare
Access in front of the admin path"), but the check is off until its two
settings are in prod's `.env`. After item 30, and after the release with
the check is deployed.
**Goal:** on prod, a request to the admin path without a valid Access token
gets the same 404 an unknown path gets.

### Implementation
1. VPS `.env`: `CF_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com` and
   `CF_ACCESS_AUD=<the application's Audience tag>` (Zero Trust → Access →
   Applications → renar admin (prod) → Overview). Setting only one stops
   the server at boot.
2. `systemctl restart renar-backend`.

### Done when
- [ ] On prod, the admin path works in the browser after the Cloudflare code
      and `--publish` still uploads.
- [ ] A request that reaches the origin without the header gets 404: from
      the VPS itself,
      `curl -k -H "Host: api.renar.app" https://127.0.0.1:8000/<ADMIN_PATH>/login`.

## 39. Name the license version in every mention of the license

**[Blocking for 1.0]** · Area: Docs / Legal

**Why:** `LICENSE` is the PayBack License v2.0 (its second line reads
`Version 2.0`), but the two places that name it leave the version out:
`README.md` line 326 (`[PayBack License (PBL)](LICENSE)`, under "License")
and `CONTRIBUTING.md` line 105 ("This project is licensed under the
[PayBack License (PBL)](LICENSE). …"). PBL v1 and v2 are legally different
licenses, so a public 1.0 that only says "PBL" leaves open which terms
apply. The global rule `~/.claude/memory/reference_license.md` says every
mention of a license names its version, read from the `LICENSE` file's
"Version X.Y" line, as `[PayBack License (PBL) vX.Y](LICENSE)`. Found by
the standards audit (former item 38). `CONTRIBUTORS` already says
"Governed by the PayBack License (PBL) v2.0" and needs no change.
**Goal:** every mention of the license in this repository says "PayBack
License (PBL) v2.0", and a test fails if a mention without the version, or
with a version other than `LICENSE`'s, is ever added.

### Behaviour
- `README.md` "License" section: `[PayBack License (PBL) v2.0](LICENSE)`
  followed by its terms in plain words on the same line: "Free for personal
  and non-commercial use; commercial use needs a revenue-share agreement
  with the founder." (the README layout rule,
  `~/.claude/memory/reference_readme_layout.md` section 17, wants the terms
  beside the link).
- `CONTRIBUTING.md` "License" section: the same link text with `v2.0`; the
  rest of the paragraph stays.
- When `LICENSE` moves to a new version, the test below fails until every
  mention is updated, so the version can never silently go stale.

### Out of scope
- Changing the license itself or copying a newer `LICENSE` from
  `sw\doc\LICENSE` (never read or edit `LICENSE` by hand;
  the rule says it is only ever copied with the shell).
- The README's wider layout (backlog item B33).

### Implementation
1. `README.md`, "License" section (line 326): replace the line with
   `[PayBack License (PBL) v2.0](LICENSE). Free for personal and
   non-commercial use; commercial use needs a revenue-share agreement with
   the founder.`
2. `CONTRIBUTING.md`, "License" section (line 105): change the link text to
   `PayBack License (PBL) v2.0`.
3. `tests/test_license_mentions.py` (new, with the `metadata -c` header and
   a module docstring saying what it guards): read the version from
   `LICENSE`'s `Version X.Y` line with a regex (not a hard-coded `2.0`),
   then scan `README.md`, `CONTRIBUTING.md`, `CONTRIBUTORS` and every
   `docs/*.md` for `PayBack License (PBL)` and assert each occurrence is
   followed by ` v<that version>`.
4. `uv run ruff format` then `uv run ruff check` on the new test file (fix
   by hand, never `--fix`); `metadata -m` on `README.md`,
   `CONTRIBUTING.md`; `metadata -c` on the new test.

### Tests
- `tests/test_license_mentions.py::test_every_license_mention_names_the_license_file_version`:
  passes after steps 1-2, and fails if either file is put back (check once
  by reverting step 1 locally, then restore).
- `tests/test_license_mentions.py::test_license_file_declares_a_version`:
  `LICENSE` has a `Version X.Y` line, so the first test can't pass
  vacuously.
- Full suite with coverage, `uv run pytest -m "not security" --cov`, stays
  at the 100 % gate.

### Docs
- `README.md`, `CONTRIBUTING.md`: as above. Changelog (under `### Changed`):
  "Named the license version (PayBack License v2.0) in the README and the
  contributing guide".

### Done when
- [ ] `README.md` and `CONTRIBUTING.md` both say `PayBack License (PBL) v2.0`.
- [ ] `tests/test_license_mentions.py` passes, and was seen failing with
      the old README line.
- [ ] `uv run ruff check` and `uv run ruff format --check` are clean.
- [ ] The full suite passes with the coverage gate.

## 44. Keep asking for the reload while a self-update waits

**Why:** on 2026-11-23 the first 0.23.0 -> 0.24.0 update on prod rolled
itself back after 120 s with "verify: no new worker started", and the same
update run again two minutes later worked. The updater renames the new
`src/renar_backend` into place and touches `__init__.py` once, right after
(`Updater.touch_reload`, called by `swap`). The reloader (watchfiles) has
to start watching the renamed-in folder first; when the touch comes before
that, it's missed and nothing reloads. Evidence in `renar-backend.log`:
"2 changes detected" and no reload in the failed run, "3 changes detected"
and "WatchFiles detected changes in 'src/renar_backend/__init__.py'" in the
runs that worked (2026-11-11 and the second one on 2026-11-23). The
rollback itself worked: code, dependencies and schema were back on 0.23.0.
**Goal:** a missed touch costs a few seconds, never the update.

### Behaviour
- While the old worker keeps answering, the updater touches
  `src/renar_backend/__init__.py` again every 10 s until a new worker
  starts or the 120 s run out.
- A server that doesn't answer (it's restarting) is not touched again: a
  second reload then would only delay it.
- A server that answers from a new worker, whatever its version, is not
  touched again.
- A failing touch is the same failed step as today, so the update rolls
  back.
- `since` stays the time of the first touch. A worker started by any later
  touch is newer, so the check still holds.
- The rollback's own verify step gets the same, since it waits in the same
  function.

### Out of scope
- The rename-based swap, the 120 s limit and git mode's merge.

### Implementation
1. `src/renar_backend/self_update.py`: add `RETOUCH_SECONDS = 10` next to
   `HEALTH_TIMEOUT_SECONDS`, with a comment giving the race above as the
   reason.
2. `wait_healthy`, branch "the old worker answered"
   (`started is None or started < since`): when `RETOUCH_SECONDS` have
   passed since the last touch (`time.monotonic()`, started at the top of
   the function), call `self.touch_reload(step)` and remember the time.
   Move the one-probe part into a helper if the function goes over 40 code
   lines or complexity 10.
3. `uv run ruff format` and `uv run ruff check` on the edited files (fix by
   hand, never `--fix`), `metadata -m` on each.

### Tests
- `tests/test_self_update_edges.py`, next to
  `test_wait_healthy_ignores_the_old_worker_answering`:
  - the old worker keeps answering for 25 s (fake clock): `touch_reload` is
    called twice, and the step still fails at the limit.
  - a new worker appears after the first re-touch: no more touches, the
    step passes.
  - the server doesn't answer: no touches.
  - the re-touch fails: `StepFailed` with the step's name.
- `tests/test_self_update.py`: an update whose first touch is dropped (patch
  `touch_reload` to skip its first call) ends "ok" and not "rolled_back".
- Full suite with coverage, `uv run pytest -m "not security" --cov`, stays
  at the 100 % gate.

### Docs
- `docs/design-decisions.md`, "Self-update reloads in place; the helper runs
  outside the venv": add the race and the repeated touch.
- `CHANGELOG.md` under `### Fixed`: "The self-update no longer rolls back
  when the server misses the first reload request; it asks again every 10
  seconds".

### Done when
- [ ] The tests above pass, and the dropped-touch one was seen failing on
      the old code.
- [ ] Lint is clean and the full suite passes with the coverage gate.

## 45. Cap the library page size by plan on the server

**Why:** choosing the library page size is a premium setting, but only the
app enforces it: Profile's "Library page size" row is locked for free
accounts, which always ask for 60 (`views/library/page_size.py`,
renar-frontend). `GET /media` (`routers/media.py`, `list_media`) takes
`limit` up to 2000 from anyone, so a script with a free account can make the
server build 2000 full entries per request. Free accounts will be the
majority, and the server has 1 GB of RAM.
**Goal:** one request returns at most 60 entries to a free account and 240
to a premium one, whatever it asks for, and no app version loses entries.

### Behaviour
- Free: at most 60. Premium (`user.is_premium`): at most 240, the largest
  size the app offers. Below the cap, `limit` works as today; without
  `limit` the default stays 60.
- Asking for more than the cap is answered with the capped page, not with
  an error, so older apps and scripts keep working. `limit` above 2000 or
  below 1 stays a 422.
- Every `GET /media` answer carries `X-Page-Size: <entries allowed on this
  page>` (the limit after the cap). It is needed because the app decides
  "there is more" by comparing the number of entries with the size it asked
  for: an app that still believes it is premium and asks for 240 would get
  60 and stop paging, silently hiding the rest of the library.
- The app uses that header for "there is more", and its own size when the
  header is missing (an older server).
- Premium ending between two pages is safe: paging is by `offset`, and the
  app advances it by the entries it received.

### Out of scope
- `GET /media/keys` (deliberately unbounded and light), exports, the diary
  and social lists, which have their own limits.
- The sizes offered in Profile.

### Implementation
1. `src/renar_backend/routers/media.py`: constants `_FREE_PAGE_CAP = 60`
   and `_PREMIUM_PAGE_CAP = 240`, with a comment giving the reason above.
   `_DEFAULT_LIST_LIMIT` stays 60. `list_media` gets a `response: Response`
   parameter, sets `limit = min(limit, cap)` and the header.
2. Add `X-Page-Size` to the CORS `expose_headers` (grep `CORSMiddleware` in
   `main.py`), or the web app can't read it.
3. renar-frontend `api_client.py`: `list_media` returns only the JSON today.
   Add `list_media_page(...) -> tuple[list[dict], int]` (entries and the
   allowed size) sharing its parameter building, and keep `list_media` for
   Home, which asks for 20 at most.
4. renar-frontend `views/library/library_view.py`: `fetch_page` uses
   `list_media_page`; both `has_more` comparisons use the returned size, and
   the offset advances by the entries received (check it does today).
5. `uv run ruff format` and `uv run ruff check` on the edited files (by
   hand, never `--fix`), `metadata -m` on each.

### Tests
- `tests/test_media.py`, next to the limit tests: free asking 61 and 2000
  gets 60 and header 60; asking 10 gets 10 and header 10; premium asking
  240 gets 240 and 2000 gets 240; lapsed premium is free; 2001 and 0 stay
  422; paging a 130-entry library through capped pages yields every entry
  once. Existing tests that list more than 60 entries in one call (grep
  `"limit"` in `tests/`) are adjusted to page.
- renar-frontend `tests/test_api_client.py`: the header is read, and a
  missing header falls back to the asked size. Library view tests: a page
  shorter than asked but equal to the header keeps paging.
- renar-frontend `tests/integration/test_api_live.py`: a free account asking
  240 pages through its whole library against the real server.
- Both full suites, with the backend's coverage gate.

### Docs
- Backend `README.md` (`GET /media` line) and `docs/design-decisions.md`:
  the caps, the header and why it isn't an error. Frontend
  `docs/design-decisions.md`, "Library page size is a premium preference
  kept on the device": the server enforces the cap. Changelogs, under
  `### Changed`: "`GET /media` returns at most 60 entries per request to
  free accounts and 240 to premium ones" and "The library keeps loading
  when the server gives smaller pages than asked for".

### Done when
- [ ] A free account asking for 2000 gets 60 and the header.
- [ ] The app shows a whole 130-entry library for a free account and for one
      whose premium has just ended.
- [ ] Both suites pass.

## 46. Store admin accounts and grant them from the server shell

**Why:** the panel has one shared login in `.env` (`ADMIN_USERNAME`,
`ADMIN_PASSWORD_HASH`, `ADMIN_TOTP_SECRET`, checked in
`users/admin_session.py`). It can't give a second person access, take it
away from one person, or tell from the logs who did what. Admin becomes a
role on ordinary renar accounts. First of items 46 to 50, which replace that
login; then come the phone app's sign-in (51) and the app (52, 53). This
item adds the storage and the commands; nothing signs in with them yet.
**Goal:** `uv run admin-grant <username> admin|moderator` on the server
gives an account a role, `uv run admin-revoke <username>` takes it away, and
`uv run admin-list` shows who has one.

### Behaviour
- Roles: `admin` (everything) and `moderator` (item 49). One per account at
  most; none means an ordinary user. Granting the same role again says so;
  granting the other one changes it.
- Each command refuses, with a one-line reason and exit code 1: an unknown
  username, a banned account, one pending deletion, and (revoke, or admin to
  moderator) the last `admin`.
- Deleting an account deletes its role. Deleting the last `admin` account is
  refused, in the app and in the panel, with a message saying to grant
  another admin first.
- The authenticator secret is stored encrypted (AES-256-GCM, the user id as
  associated data so a row can't be copied onto another account). The key is
  a 32-byte file outside the database, so a database dump alone can't make
  codes: `ADMIN_KEY_FILE`, default `admin.key` next to `.env`, created on
  first use with mode 0600. A missing key while encrypted secrets exist is
  an error naming the file, never a silently created new key.

### Out of scope
- Any change to sign-in. Granting roles from the panel.

### Implementation
1. `models.py`: `AdminAccount` (`admin_accounts`): `user_id` primary key and
   foreign key to `users` (cascade), `role` (checked text),
   `totp_secret_enc` (nullable bytes, nonce first), `totp_version` (int, 0),
   `totp_last_step` (nullable bigint: the replay guard, stored so a restart
   doesn't forget it), `granted_at`. Every column depends on `user_id` only,
   so it is BCNF; add it to `tests/test_normalization.py`.
2. Alembic migration for it, with a working downgrade.
3. New `users/admin_crypto.py`: load or create the key, encrypt, decrypt
   (`cryptography`, already installed for Cloudflare Access's RS256).
4. New `users/admin_accounts.py`: grant, revoke, list, "is the last admin",
   raising one exception type with the reason; log each change at WARNING
   with the target username.
5. `admin_cli.py` + `[project.scripts]`: the three commands, thin over 4.
6. Account deletion (`DELETE /auth/me` and the panel's delete): the
   last-admin refusal. Grep every caller of the deletion helpers first.
7. `config.py` and `.env.example`: `ADMIN_KEY_FILE`; `.gitignore`:
   `admin.key`. The self-updater must leave the file alone: add it to the
   kept-files test in `tests/test_self_update.py`. Because 0.24.0 rejects
   unknown `.env` keys, nobody should set the variable before updating: say
   so in the changelog.
8. Lint, `metadata -c` on new files, `-m` on edited ones.

### Tests
- New `tests/test_admin_accounts.py`: each command's success and each
  refusal; role change; cascade; last-admin refusals including two
  concurrent revokes of the last two admins (one must fail; lock the rows).
- New `tests/test_admin_crypto.py`: round trip, another user id refused,
  tampered bytes refused, key created once with 0600 (POSIX), missing key
  with secrets present refused.
- `tests/test_migrations.py` covers up and down; `tests/test_admin_cli.py`
  the entry points. Full suite with coverage.

### Docs
- `README.md` "Setting up admin sign-in", `docs/design-decisions.md` (roles
  on accounts, key outside the database). Changelog, `### Added`: "Admin and
  moderator roles on accounts (`uv run admin-grant`, `admin-revoke`,
  `admin-list`); the panel doesn't use them yet".

### Done when
- [ ] The three commands work on the dev server and refuse what they should.
- [ ] A dump of the database holds no readable authenticator secret.
- [ ] The suite passes with the coverage gate.

## 47. Sign in to the admin panel with a renar account

**Why:** after item 46 accounts can have a role, but the panel still only
knows the shared `.env` login. During this item both work, so nobody is
locked out; item 50 removes the shared one.
**Goal:** an admin signs in with their own renar username, password and
authenticator code, after enrolling the authenticator once.

### Behaviour
- The sign-in page stays as it is (username, password, code). The username
  is tried as an account with a role; if it isn't one, as the `.env` login.
- An account without an authenticator signs in with username and password
  only and lands on "Set up your authenticator" (QR, the secret as text, a
  code field). It can reach nothing else until a correct code is entered.
- Revoked, banned and pending-deletion accounts can't sign in. Every refusal
  shows the same "Wrong username, password or code." and takes the same
  time (always verify a password hash, a dummy one when there's no account).
- Strikes, backoff and Exempt IPs behave as today. A used code's time step
  is refused again, also after a restart (`totp_last_step`, updated under a
  row lock).
- Sessions last 8 hours. The cookie holds the account id and a fingerprint
  of role, `totp_version`, password hash and secret key, so a revoke, role
  change, re-enrolment or password change ends that account's sessions on
  the next request.
- `uv run admin-reset-totp <username>` clears the authenticator (lost
  phone): the account enrols again at the next sign-in.
- The panel's logs and stored `created_by`-like fields show the account's
  username.

### Out of scope
- Recovery codes (48), what a moderator may see (49), changing how users
  sign in to the app.

### Implementation
1. `users/admin_session.py`: split first, it would pass 200 lines: keep
   cookies in it, move credential checks to a new `users/admin_login.py`.
   `read_session` takes a database session and returns a small `AdminUser`
   (id or None for the `.env` login, username, role, how it signed in).
2. `users/auth.py`: `require_admin` depends on `get_db` and returns
   `AdminUser`. Every admin page uses `admin_user: str`; grep
   `_require_admin` in `routers/admin/` and update each call site, reading
   `.username` where the name is stored or logged.
   `require_admin_or_api_token` keeps `"api-token"` as the username.
3. `routers/admin/login.py`: the new flow; new `routers/admin/enrol.py` for
   the QR page (reuse the QR code of `admin-totp` in `admin_cli.py`).
4. `admin_cli.py`: `admin-reset-totp`.
5. Lint, headers.

### Tests
- `tests/test_admin_login.py`: every Behaviour line: both logins, enrolment
  (wrong code, right code, nothing else reachable before it), replay across
  a restart, two sign-ins with the same code at once (one wins), revoked,
  banned, role changed, password changed, `.env` login unaffected.
- `tests/test_admin_render.py`: the enrolment page, light and dark.
- `tests/test_security.py`: an app token is not an admin session, and the
  reverse. Full suite with coverage; `-m security`.

### Docs
- `README.md` "Setting up admin sign-in", `docs/anti-abuse.md`,
  `docs/design-decisions.md` "Admin session". Changelog, `### Added`: "The
  admin panel accepts renar accounts with an admin role, each with its own
  authenticator".

### Done when
- [ ] On dev, an account granted `admin` enrols, signs in and is signed out
      at once by `admin-revoke`.
- [ ] The suite passes with the coverage gate.

## 48. Recovery codes for admin accounts

**Why:** after item 47 a lost phone locks an admin out until someone runs
`admin-reset-totp` over SSH. After item 47.
**Goal:** an admin with a lost authenticator signs in with a one-time
recovery code.

### Behaviour
- Enrolment ends by showing ten codes once (`xxxx-xxxx-xxxx`, 60 random bits
  each), with "I saved them" before going on.
- The code field on the sign-in page takes a recovery code too. A used code
  never works again; signing in with one logs a WARNING and shows how many
  are left.
- "New recovery codes" in the panel (asks for a current authenticator code)
  replaces all of them. `admin-reset-totp` and `admin-revoke` delete them.
- Wrong recovery codes count as failed sign-ins (strikes).

### Out of scope
- E-mailing codes or any reset without one of the two factors.

### Implementation
1. `models.py` + migration: `AdminRecoveryCode` (`id`, `user_id` foreign key
   to `admin_accounts` with cascade, `code_hash` BLAKE3, unique with
   `user_id`, `used_at`). BLAKE3 is enough because the codes are random, not
   chosen by people.
2. `users/admin_login.py`: accept them, marking one used with
   `UPDATE … WHERE used_at IS NULL` so two requests can't share it.
3. `routers/admin/enrol.py`: show them; a "Security" page with the count and
   "New recovery codes".

### Tests
- `tests/test_admin_login.py`: works once; two at once, one wins; wrong code
  strikes; replaced and deleted codes refused; the count shown.
- `tests/test_normalization.py`, migrations, render test; full suite.

### Docs
- `README.md`, `docs/design-decisions.md`. Changelog, `### Added`: "Recovery
  codes for admin accounts".

### Done when
- [ ] A recovery code signs in once on dev and is refused the second time.
- [ ] The suite passes with the coverage gate.

## 49. Limit what moderators can open in the panel

**Why:** item 46 adds the `moderator` role, but every page still asks only
for "an admin". After item 47; until it's done, granting `moderator` gives
full access, so don't grant it.
**Goal:** a moderator sees only Moderation, Reports, Moderation Decisions
and Users; everything else is hidden and refused.

### Behaviour
- Moderator: the pages in `routers/admin/` `moderation`, `reports`,
  `decisions`, `account_moderation` and `users`, except: resetting a user's
  password, changing e-mail, granting premium, hard-deleting an account, and
  any action on an account that has a role.
- Admin: everything.
- A refused page answers 403 with a page saying it's admins only. The
  dashboard and navigation don't show what can't be opened.
- A new admin route with no role rule fails a test, so a page can't be open
  by accident. Default: admins only.

### Out of scope
- Finer permissions than the two roles.

### Implementation
1. `users/auth.py`: `require_role("admin")` and `require_role("moderator")`
   (admins pass both), built on `require_admin`.
2. Each `routers/admin/*.py`: use the right one; `dashboard.py` and
   `_html.py`: hide links by role.
3. `routers/admin/users.py`: list every POST, mark each per the Behaviour.

### Tests
- New `tests/test_admin_roles.py`: walks every route under `ADMIN_PATH` as
  admin, moderator and signed out against an explicit table; a route missing
  from the table fails. A moderator acting on an admin account is refused.
- `tests/test_admin_render.py`: the moderator's dashboard. Full suite.

### Docs
- `README.md`, `docs/design-decisions.md`. Changelog, `### Added`:
  "Moderators can open only the moderation and user pages".

### Done when
- [ ] The route table test covers every admin route.
- [ ] The suite passes with the coverage gate.

## 50. Remove the shared admin login from `.env`

**Why:** with items 46 to 49 done, the shared login is one more way in that
can't be revoked per person. After item 48, and after the owner has signed
in with their own account on both hosts. Do it together with checking items
27 and 29, which describe the shared login.
**Goal:** `.env` holds no admin login; only accounts with a role get in.

### Behaviour
- Boot refuses `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` or
  `ADMIN_TOTP_SECRET` in `.env`, saying to run `admin-grant` and delete
  them, the way a leftover `ADMIN_PASSWORD` is refused today.
- Boot also refuses to continue when no account is `admin` and one of the
  three was set, so an update can't lock the owner out: grant first.
- With no admin account at all, the panel answers 503 naming `admin-grant`.
- `ADMIN_API_TOKEN` stays, for scripts such as the APK upload.

### Implementation
1. `config.py`: the three become refused leftovers; `users/admin_login.py`,
   `admin_session.py`, `auth.py`: remove the `.env` path and
   `admin_configured`'s old meaning.
2. `admin_cli.py`: remove `admin-totp` and `admin-password` and their script
   entries; `.env.example`, `README.md`.
3. Prod: this release removes `.env` keys, so it needs the same one-restart
   swap as 0.23.0 (grant the account first, then delete the keys and install
   the release in one go), not the Update button.

### Tests
- `tests/test_config.py`: each leftover refused with its message.
- `tests/test_admin_login.py`, `test_admin_cli.py`: the old path's tests go,
  the 503 stays. `tests/integration/conftest.py` and `_test_server.py`: the
  test server grants an account instead of setting `.env`; update
  renar-frontend's tests that sign in to the panel (grep `ADMIN_USERNAME`).

### Docs
- `README.md`, `docs/design-decisions.md`, `docs/anti-abuse.md`; items 27
  and 29 of this file. Changelog, `### Removed`, marked breaking.

### Done when
- [ ] Both hosts run without the three keys and the owner signs in.
- [ ] Both suites pass.

## 51. Pair a phone with an admin account

**Why:** the owner wants to open the panel from the phone with the sign-in
saved. Today that takes username, password and code every 8 hours.
Items 46 to 50 decide who may enter; this one adds how a phone proves it's
that person's, without a saved password: each phone has its own key, and any
phone can be cut off alone. The app itself is items 52 and 53. After item
47; best after 50, so pairing is never tied to the shared login.
**Goal:** from the panel an admin pairs a phone by scanning a QR code, sees
the paired phones and can remove one; a paired phone gets a panel session by
signing a challenge with its own key.

### Behaviour
- "Phones" page: name, paired on, last used, Remove. "Pair a phone" asks for
  a current authenticator code, then shows a QR valid for 5 minutes and one
  use, holding the panel's address and a 128-bit pairing code.
- The phone sends the pairing code, its name and its public key (P-256). The
  key was made inside the phone's secure hardware and never leaves it.
- To sign in, the phone asks for a challenge (32 random bytes, 60 seconds,
  one use), signs it together with the host name and the phone's id, and
  gets the same 8-hour session cookie as a normal sign-in. The host name is
  signed so a fake server can't relay the challenge.
- A phone's session can do all its role can, except pair phones, change the
  authenticator or recovery codes: those need password + code.
- Removing a phone ends its sessions at once. Revoking the role, banning or
  deleting the account, or changing its password removes all its phones.
  Re-enrolling the authenticator keeps them.
- At most 5 phones per account. Wrong codes and signatures count as failed
  sign-ins, with the same answer whatever was wrong.
- Pairing and each new phone sign-in are logged with account and phone name;
  the dashboard shows "New phone paired" for 7 days.
- Behind Cloudflare Access (item 30) the phone needs a way past Cloudflare's
  e-mail code: a service token of its own, `renar-admin-phone`, in a second
  Service Auth policy, with `CF_ACCESS_PHONE_CLIENT_ID` and
  `CF_ACCESS_PHONE_CLIENT_SECRET` in `.env`, put in the QR when both are set.
  It only opens Cloudflare's door; the phone's own key is still needed.

### Out of scope
- The app; pairing for ordinary users; passkeys in the browser.

### Implementation
1. `models.py` + migration: `AdminDevice` (`id`, `user_id` foreign key to
   `admin_accounts` with cascade, `name`, `public_key`, `created_at`,
   `last_used_at`). Removing deletes the row.
2. New `users/admin_devices.py`: pairing codes and challenges in memory (one
   worker; a restart only means scanning again), verification with
   `cryptography`, all bounded in size and age.
3. `users/admin_session.py`: the cookie carries the device id and how the
   session started; a missing device ends it. `AdminUser` gets
   `strong: bool` (password + code); `require_strong` guards the excluded
   actions.
4. New `routers/admin/devices.py`: the page, `POST devices/pair`,
   `POST devices/challenge`, `POST devices/session` (JSON). They're under
   `ADMIN_PATH`, so Cloudflare Access covers them.
5. `config.py`, `.env.example`: the two optional keys, both or neither.

### Tests
- New `tests/test_admin_devices.py`: pair and sign in; code expired, used
  twice, two phones at once; challenge expired, reused, for another phone,
  signed for another host, wrong key, malformed key; removed phone, revoked
  role, banned account, changed password; phone session refused on each
  excluded action; the limit of 5; strikes; nothing secret in the logs.
- `tests/test_fuzz.py`: the three JSON routes. Normalization, migrations,
  render (light and dark), the role table of item 49. Full suite with
  coverage; `-m security`.

### Docs
- `README.md`, `docs/anti-abuse.md`, `docs/design-decisions.md` (why a key
  per phone and not a long session or a saved password); item 30 (the second
  policy). Changelog, `### Added`: "Pair a phone with an admin account".

### Done when
- [ ] A test client pairs, signs in and is cut off by Remove.
- [ ] The suite passes with the coverage gate.

## 52. Build the Android admin app

**Why:** the owner wants to manage the server from the phone with the
sign-in saved, at any time. The panel's pages already work at phone width,
so the app shows them instead of building every page again; what it adds is
the saved sign-in from item 51. It's separate from the renar app so that
nothing about the panel ships to users. After item 51.
**Goal:** open the app, touch the fingerprint sensor, and the panel is
there, signed in.

### Behaviour
- First start: "Scan the code from the panel's Phones page". It makes its
  key, pairs, and opens the panel. A failed pairing says why and lets one
  scan again.
- Every later start: fingerprint, face or the phone's screen lock, then the
  panel. When the 8-hour session ends while open, it asks again and returns
  to the same page.
- Leaving the app for more than 5 minutes locks it. A lock clears the
  session cookie.
- Several servers (prod and dev) can be paired; a switch at the top shows
  which one is open, in a different colour for dev, so a change never lands
  on the wrong one.
- A removed phone sees "This phone was removed. Pair it again". A new
  fingerprint enrolled on the phone invalidates the key (Android's own
  rule), and asks to pair again.
- No network, server down and certificate errors each get their own message
  with Retry; a certificate error can never be skipped.
- Only the paired server's `ADMIN_PATH` opens inside; any other link opens
  in the browser. File upload (App Releases) and downloads work.
- Back goes to the previous page, then asks before closing. Light and dark
  follow the phone. English and Spanish.
- The screen isn't shown in screenshots or the recent-apps list, and nothing
  is included in Android backups.
- About: name, version and build, author, Breren with its original logo,
  license, links.

### Out of scope
- iOS, a store listing, push notifications, native versions of the pages.

### Implementation
1. Kotlin, no cross-platform toolkit: the secure key store, biometric prompt
   and web view are Android's own, and the app has no interface of its own
   to share. There is no approved source layout for Kotlin yet: research one
   per the source-organisation rule, propose it with AskUserQuestion, and
   save the approved one before writing code.
2. New repo `renar-admin` next to `renar-backend` (branch `main`; LICENSE,
   CHANGELOG, CONTRIBUTING, README, CONTRIBUTORS, TODO, BACKLOG per the
   new-repo rules; remotes created at the first push, asking for the
   visibility). Application id `com.breren.renar.admin`, minimum Android 9.
3. `keys`: P-256 key in the Android Keystore (StrongBox when there is one),
   user authentication required, invalidated by new biometrics.
4. `pairing` (QR with ML Kit's bundled scanner, so no Google service is
   asked), `session` (challenge, sign, cookie), `servers` (the list, in
   encrypted storage), `panel` (the web view with the rules above), `lock`,
   `about`.
5. The web view: JavaScript on (the panel uses it), file access, content
   access and mixed content off, no JavaScript bridge, Cloudflare's headers
   only sent to the paired host.
6. Structured logging, with nothing secret in it; ktlint and detekt with the
   clean-code numbers.

### Tests
- Unit: pairing data, the signed bytes against the backend's test vector,
  which links stay inside, lock timing, each error message.
- Instrumented on the emulator: pairing and sign-in against the backend's
  test server, removed phone, expired session, rotation, process death, back
  button, light and dark screenshots with reviewed baselines, both languages.
- Security: the manifest (no backup, only the main screen exported), no
  cleartext, no secret in logcat.
- By hand on the owner's phone: real fingerprint, real prod panel.

### Docs
- The new repo's README (pairing, removing a phone) and design decisions;
  backend `README.md`: a line pointing at the app.

### Done when
- [ ] On a real phone: pair once, close, open with the fingerprint, change a
      setting on dev, remove the phone in the panel and see it locked out.
- [ ] All test groups pass.

## 53. Release and update the Android admin app

**Why:** item 52 builds the app; without releases each change needs a cable.
After item 52.
**Goal:** a version tag produces a signed APK on the three forges, and the
app installs new versions itself after checking them.

### Behaviour
- The app looks for a newer release on GitHub and then GitLab when opened
  and from About, as the in-app updater rule describes: signature
  (minisign) and BLAKE3 are checked before installing, and a failed check
  says so and installs nothing.
- Files are `renar-admin-<version>-android-universal-portable.apk` (no
  installer exists apart from the APK itself), each with `.b3` and
  `.minisig`.
- If the repo is private, anonymous update checks can't work; then the
  backend serves the APK to paired phones the way it serves the renar app's
  updates (`routers/admin/app_releases.py`). Choose by the visibility the
  owner picks in item 52.

### Implementation
1. A new signing keystore and minisign key, kept as the release-key rule
   says (`~/.release-keys`, backup in the owner's KeePass); the public keys
   in the README and in the app.
2. The updater module and the tag-driven draft release per the build-matrix
   rule.

### Tests
- Unit: version comparison, wrong signature, wrong checksum, truncated
  download, no network, older version offered (refused).
- On the emulator: version N updates itself to N+1.

### Docs
- README (download, keys), changelog of the new repo.

### Done when
- [ ] Version N on the owner's phone updates itself to N+1.
- [ ] The release is on the three forges with its `.b3` and `.minisig`.

## 54. Let the certificate renewal restart the backend

**Why:** on prod `certbot-renar.service` has ended in failure every night since at least 2026-11-10. The renewal
itself works ("not yet due"), but its last step, `ExecStartPost=/bin/systemctl restart renar-backend`, runs as
`User=renar`, who may not restart services ("Access denied", status 4). Two things are wrong: a failed unit every
day hides a real failure, and after the next renewal (due about 8 January 2027; the certificate ends on
7 February 2027) the backend keeps serving the old one until something else restarts it. As written it would also
restart the backend every night even when nothing was renewed.
**Goal:** the unit succeeds every night, and the backend restarts only on a night it got a new certificate.

### Behaviour
- Nothing renewed: no restart, the unit succeeds.
- Renewed: the backend restarts once and serves the new certificate.
- The renewal fails: the unit fails and the backend keeps running.

### Out of scope
- Who issues the certificate and the DNS method.

### Implementation
1. New `scripts/deploy/certbot-renar.service` in the repo: the unit as it is on prod
   (`/etc/systemd/system/certbot-renar.service`), so it stops living only on the server. `ExecStart` gets
   `--deploy-hook "touch /opt/renar-backend/certs/renewed"` (certbot runs it only after a renewal), and
   `ExecStartPost=` becomes
   `+/bin/sh -c 'if [ -e /opt/renar-backend/certs/renewed ]; then rm /opt/renar-backend/certs/renewed && systemctl restart renar-backend; fi'`.
   The `+` runs that one step as root while the renewal stays with `renar`.
2. Copy it to prod, `systemctl daemon-reload`, `systemctl reset-failed certbot-renar.service`.
3. `docs/design-decisions.md`, the certificate section (about line 1235): where the unit lives and why the restart
   step needs the `+`.

### Tests
- `tests/test_deploy_units.py` (new): the unit file keeps `User=renar`, its restart step starts with `+` and only
  runs when the marker exists.
- On prod: `systemctl start certbot-renar.service` ends in success and the backend's start time doesn't change;
  with the marker created by hand it restarts once and the marker is gone.

### Docs
- Step 3. Changelog: "Fixed: a renewed certificate was not picked up until the next restart".

### Done when
- [ ] Both prod checks above, with `systemctl status` output.
- [ ] The whole suite passes.
