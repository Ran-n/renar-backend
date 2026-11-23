[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/09 11:43:55.623794 )
[//]: # (+ Revised: 	2026/11/23 21:05:51.864949 )
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
| **6** | **32** |

Next item number: 44

## Index

- [22. Publish the Terms of Service](#22-publish-the-terms-of-service)
- [27. Turn on admin sign-in and the one-click update on the dev PC and the Hetzner VPS](#27-turn-on-admin-sign-in-and-the-one-click-update-on-the-dev-pc-and-the-hetzner-vps)
- [29. Switch prod to the hashed admin password and lock `.env` to the service user](#29-switch-prod-to-the-hashed-admin-password-and-lock-env-to-the-service-user)
- [30. Put the prod admin panel behind Cloudflare Access](#30-put-the-prod-admin-panel-behind-cloudflare-access)
- [31. Turn on the Cloudflare Access header check on prod](#31-turn-on-the-cloudflare-access-header-check-on-prod)
- [39. Name the license version in every mention of the license](#39-name-the-license-version-in-every-mention-of-the-license)

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

**Why:** Google wants terms for an app with accounts and comments. The text
is written (`docs/terms-of-service.md`: Spanish law, EU consumer protections
kept, Hetzner named as host, EU Digital Services Act for takedown notices),
its page is built (`renar-frontend/landing/terms/index.html`) and the app's
Profile → Legal → Terms of Service row already opens
<https://renar.app/terms/>, but that URL answers 404: the site hasn't been
deployed since.
**Goal:** <https://renar.app/terms/> shows the terms, dated the day they
went live.

**Status (2026-11-22):** the owner made the lawyer-role review the legal
review, so steps 1 and 2 are done. The provider is named by trade name only
(Breren, the trade name of an individual): the owner chose on 2026-11-23 to
leave the legal name out. There is no NIF or postal address, because Renar is
free with no advertising or income, so LSSI-CE art. 10 doesn't apply; the
Terms promise to add both before charging for anything. The commitments
stand: contact in English and Spanish, 30 days' notice, 6 months to
contest, backups in the EU. "Last updated" is 22 November 2026, and Spanish
versions exist (`docs/*.es.md`, `landing/es/`). The code the texts promise
is built: owner-only notes, the username purge, 30-day logs, moderation
decisions with e-mails, and the sign-up checkbox (renar-frontend). What's
left is the deploy. It waits for the backend and app releases that carry
that code, because publishing first would promise things users can't see
yet.

### Implementation
1. Release the backend and the app that carry the sign-up checkbox and the
   moderation decisions, and deploy the backend to prod.
2. If either text changed after 22 November 2026, set "Last updated" in
   all eight files (two `.md` and two `.es.md` sources, four pages) to the
   deploy day.
3. Deploy `landing/` (Cloudflare Pages project `renar-site`). This is the
   same deploy as renar-frontend TODO item 25 step 3.
4. If the Play Console listing has a terms field, give it the URL.

### Done when
- [ ] `curl -I https://renar.app/terms/` and `https://renar.app/es/terms/`
      answer 200.
- [ ] The app's Terms of Service row opens the page.

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
