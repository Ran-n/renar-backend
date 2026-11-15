[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/11/09 11:43:55.623794 )
[//]: # (+ Revised: 	2026/11/15 22:47:21.252869 )
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

Next item number: 39

## Index

- [21. Back up the production database](#21-back-up-the-production-database)
- [22. Publish the Terms of Service](#22-publish-the-terms-of-service)
- [27. Turn on admin sign-in and the one-click update on the dev PC and the Hetzner VPS](#27-turn-on-admin-sign-in-and-the-one-click-update-on-the-dev-pc-and-the-hetzner-vps)
- [29. Switch prod to the hashed admin password and lock `.env` to the service user](#29-switch-prod-to-the-hashed-admin-password-and-lock-env-to-the-service-user)
- [30. Put the prod admin panel behind Cloudflare Access](#30-put-the-prod-admin-panel-behind-cloudflare-access)
- [31. Turn on the Cloudflare Access header check on prod](#31-turn-on-the-cloudflare-access-header-check-on-prod)
- [37. Audit the whole history for leaked secrets and personal data](#37-audit-the-whole-history-for-leaked-secrets-and-personal-data)
- [38. Check the project against the global standards and file the gaps](#38-check-the-project-against-the-global-standards-and-file-the-gaps)

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

## 21. Back up the production database

**[Blocking for 1.0]** · Area: Publishing (app stores, web, going public)

**Why:** production runs on the Hetzner VPS since 2026-11-09 (systemd
`renar-backend.service`, Postgres 17 on the same machine, database `renar`),
so a host is chosen and set up. Nothing backs the database up: a dead disk,
a bad migration or a deleted server loses every account and library.
`/root/renar-backups/` only holds pre-deploy code tarballs, on the same disk.
**Goal:** a dump of the database is taken every night, kept for 14 days,
copied off the VPS, and a restore from it has been done once.

### Behaviour
- A systemd timer on the VPS runs nightly at 03:30 UTC:
  `pg_dump -F c renar` as the `postgres` user into
  `/var/backups/renar/renar-<YYYY-MM-DD>.dump` (directory `postgres:postgres`,
  mode `0700`), then deletes dumps older than 14 days.
- The same unit then copies the new dump off the machine. Where to is the
  owner's choice, because it costs money or needs an account: a Hetzner
  Storage Box (same provider, cheapest) or any `rclone` remote. Pick one
  before starting; without an off-host copy the item is not done.
- The uploaded images (`/opt/renar-backend/media`) go to the same
  destination with `rsync`/`rclone sync` in the same unit.
- A failed run shows as a failed unit (`systemctl --failed`); nothing mails.

### Out of scope
- Point-in-time recovery (WAL archiving) and a standby server.
- Dev PC backups.

### Implementation
1. Choose the off-host destination and create its credentials.
2. VPS: `/usr/local/bin/renar-backup` (the dump, the prune, the copy),
   `renar-backup.service` (oneshot) and `renar-backup.timer`; enable the timer.
3. Run it once by hand; check the dump exists in both places.
4. Restore test: `pg_restore --no-owner -d renar_restore_test` into a scratch
   database on the VPS, compare `SELECT count(*) FROM users` with prod, drop
   the scratch database.
5. `README.md`: a "Backups" section under the deployment notes: where the
   dumps are, how to restore one, how to check the timer.

### Tests
- None automated; step 4 is the test.

### Docs
- `README.md` as in step 5. `docs/design-decisions.md`: entry "Nightly
  `pg_dump` plus an off-host copy" (why a dump and not WAL archiving at this
  size). Changelog: none (no code).

### Done when
- [ ] `systemctl list-timers renar-backup.timer` shows the next run.
- [ ] A dump from last night exists on the VPS and off it.
- [ ] The restore test's user count matched prod's.
- [ ] README section in place.

## 22. Publish the Terms of Service

**[Blocking for 1.0]** · Area: Publishing (app stores, web, going public)

**Why:** Google wants terms for an app with accounts and comments. The text
is written (`docs/terms-of-service.md`: Spanish law, EU consumer protections
kept, Hetzner named as host, EU Digital Services Act for takedown notices),
its page is built (`renar-frontend/landing/terms/index.html`) and the app's
Profile → Legal → Terms of Service row already opens
<https://renar.app/terms/>, but that URL answers 404: the site hasn't been
deployed since. Neither the terms nor the privacy policy has had a legal
review.
**Goal:** <https://renar.app/terms/> shows the terms, dated the day they
went live.

### Implementation
1. Decide whether a lawyer reads both documents first; apply their changes
   to the `.md` source and regenerate the page (same HTML shell as
   `landing/privacy/index.html`; the two must say the same thing).
2. Set "Last updated" in `docs/terms-of-service.md` and
   `landing/terms/index.html` to the day of the deploy.
3. Deploy `landing/` (Cloudflare Pages project `renar-site`). This is the
   same deploy as renar-frontend TODO item 25 step 3, which waits for the
   backend release that carries blocking.
4. If the Play Console listing has a terms field, give it the URL.

### Done when
- [ ] `curl -I https://renar.app/terms/` answers 200.
- [ ] The app's Terms of Service row opens the page.

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

**[Blocking for 1.0]** · Area: Admin panel / Security

**Why:** the server now only accepts an Argon2id hash of the admin password
(`ADMIN_PASSWORD_HASH`, made by `uv run admin-password`) and refuses to boot
while a plain `ADMIN_PASSWORD` is in `.env`. The dev PC's `.env` was
converted on 2026-11-15. Prod still runs the old release with the plain
password, and on the VPS nothing restricts `.env` beyond the `renar` user
owning `/opt/renar-backend`.
**Goal:** prod signs in against the hash, a leaked `.env` no longer gives
the password, and `.env` and the Cloudflare credentials file are readable
only by `renar`.

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

## 37. Audit the whole history for leaked secrets and personal data

**Why:** on 2026-11-15 an audit of bounty_board found, in commits already pushed: a real Clavren licence key in a
test file (`tests/licence_fakes.py`), from where it had been copied into vitralis, a public repo; the licence key the
user handed to an avalio-lite session, committed into its tests (whole, and half of it in another test); two
screenshots under `docs/todo/` showing the user's own player card (full name, e-mail, phone, birth date, player ID)
and their local stores, which gives away where they live; real names, a username, a player ID and a Telegram chat ID
used as test data; and the Windows user folder in paths written into `TODO.md`. The leak-scan git hooks only see new
commits, and no text scanner reads pixels, so none of this was caught. This repo has never been audited the same way.

**Goal:** no commit, tag, branch or release file of this repo, on any forge, holds a secret (key, token, password,
private key, licence key, chat or account ID) or the user's personal data (legal name outside `CONTRIBUTORS`,
e-mail, phone, birth date, address or anything that locates their home, player or account IDs, the Windows user
folder name). Anything found is gone from history, rotated if it was a secret, and purged from the forges.

### Behaviour
- The audit covers every branch and tag, every file type (images and PDFs looked at by eye) and every release asset
  built from the tree (source archives such as `.tar.gz` ship the tests).
- A finding that is a false positive is recorded, not deleted: a gitleaks fingerprint in `.gitleaksignore` with a
  comment saying what it is, or a `!regex` line in the ```` ```leak ```` block of
  `~/.claude/memory/reference_leak_terms_private.md` (then `python ~/.claude/bin/secrets.py seal`) when the same
  harmless value recurs across projects.
- A real finding in the current files is replaced by a fake that keeps the tests meaningful: licence keys by
  Clavren's published test vector `BRN-79YN-44XQ-W025-377Z` or `BRN-2222-3333-4444-5555`; names, usernames and IDs
  by made-up ones (`Alba`, `Lago Abad`, `·Estrela·`, `0000123456`); e-mails by `@example.com` or `.test`
  addresses; user paths by `~\...`; screenshots retaken with demo data.
- A real finding in history is rewritten out (step 8), so it was never committed as far as anyone can see.
- A leaked secret is also rotated: replaced at its service and the old one revoked. Personal data can't be rotated,
  so the forges must purge it before the repo is (or stays) public.
- Nothing personal of the user's is ever sent to an outside service while doing this, except the support requests
  of step 12, which name only the repo and commit hashes.

### Out of scope
- Fixing anything that isn't a leak (other items cover code quality and standards).
- Other repositories: each has its own copy of this item. Work inside this repo only.

### Implementation
1. Note each remote's visibility: `gh repo view Ran-n/<repo> --json visibility`, `glab api projects/Ran-n%2F<repo>`
   (`visibility`), and Codeberg's `GET /api/v1/repos/ran-n/<repo>` (`private`; token in
   `~/.claude/memory/reference_codeberg_token.md`). A public repo makes every finding urgent.
2. Scan all history with the hook's own checks (its rules, the personal terms and gitleaks):
   `python ~/.claude/bin/leak_history.py` from the repo root. It lists each distinct finding with its first
   commit, then every image path ever committed.
3. Scan the current files too, including uncommitted ones:
   `gitleaks dir <folder> --config ~/.claude/hooks/gitleaks.toml --redact` for each source, test, docs and script
   folder (not `.venv`, `build`, `target`, `node_modules`, which are ignored).
4. Look at every image, PDF and other binary ever committed, every version: list them with
   `git rev-list --all --objects`, write each blob out with `git cat-file blob <id> > <scratch file>` into the
   session scratchpad, and open it. Flag real names, e-mails, phones, IDs, chat IDs, tokens, addresses, a map or a
   list of nearby places centred on home, file paths with the user folder, and window titles or notifications
   showing accounts. Delete the scratch copies afterwards.
5. Grep the history for the shapes no rule knows, from the repo root:
   `git log --all -p | grep -E "BRN-[0-9A-Z]{4}-|chat_id|user_id|bandai|@gmail|C:\\\\Users\\\\"`, and for any real key in
   `~/.claude/memory` or `~/.claude/project-memory` (the sealed `reference_*` files), check that no part of it
   (any two consecutive groups) appears: a test of a "mistyped" key once held half a real one.
6. Check the release assets on every forge (`gh release download`, `glab release download`, Codeberg's release
   API) the same way: unpack each source archive and grep it; binaries without tests need no check.
7. Triage every finding into false positive or real, with the reason, and record the false positives as the
   Behaviour section says. Commit nothing yet.
8. For real findings in history: rewrite it on a copy, never in the working clone.
   a. Ask any other Claude session working in this repo (`ListAgents`, then `SendMessage`) to pause commits and
      pushes, and wait for its reply.
   b. Make a fresh bare copy: `git init --bare -b main <scratch>/orig.git`, copy `.git/objects` into it
      (`robocopy <repo>\.git\objects <scratch>\orig.git\objects /E /MT:16`, much faster than a clone on a slow
      disk), and point `main`, the other branches to publish and every tag at the clone's values with
      `git update-ref`. Leave tool refs such as `refs/codex/...` out. Copy it again to `<scratch>/new.git`.
   c. In `new.git`, run `git filter-repo --replace-text <file>` (lines `<real>==><fake>`; for one line that must
      stay, swap it to a placeholder first and back last) and/or `--strip-blobs-with-ids <file>` for images. An
      image can sit under several names: strip it by blob id, not by path.
   d. `python ~/.claude/bin/resign_rewritten.py <scratch>/new.git <scratch>/orig.git main [other branches]`: commits
      the filter didn't change stay the original objects with their original signatures (even ones made with an
      older GPG key); changed ones are re-made with the same dates and messages and signed only if they were
      signed. Then `git -C new.git repack -a -d`, delete `new.git/objects/info/alternates`,
      `git reflog expire --expire=now --all` and `git gc --prune=now`.
   e. Verify before pushing: the finding is gone (`git log --all -S<value>` is empty; `git rev-list --all
      --objects` has no stripped blob); `git log --format='%G?|%GK|%an|%ae|%ad|%cn|%ce|%cd|%B' --date=raw` is
      identical between orig and new once hashes are masked; tags' tagger, date and message are identical;
      `git diff --stat <orig main> <new main>` (with `GIT_ALTERNATE_OBJECT_DIRECTORIES` pointing at orig) shows only
      the scrubbed lines; `python ~/.claude/bin/leak_history.py` inside `new.git` is clean.
   f. Check every remote still has the `main` you copied (`git ls-remote`); if one moved, start again from b.
   g. GitLab protects `main` against force pushes: `glab api -X PATCH projects/Ran-n%2F<repo>/protected_branches/main
      -f allow_force_push=true`, push, then the same call with `false`. Push from `new.git` to every remote:
      `git push --force <url> refs/heads/main 'refs/tags/*'` (the global hooks scan the push; never bypass them).
      Check with `git ls-remote` that each forge now matches.
   h. Move the working clone onto the new history without touching uncommitted work:
      `git fetch <scratch>/new.git '+refs/heads/main:refs/rewritten/main' '+refs/tags/*:refs/tags/*'`,
      `git reset --mixed <new main>`, `git checkout -- <each file the rewrite changed and you didn't edit>`, update
      every `refs/remotes/<remote>/main`, delete `refs/rewritten/main`, then `git reflog expire --expire=now --all`
      and `git gc --prune=now`. Tell the paused session it can resume and that every hash after the first changed
      commit is new.
9. Rebuild every release asset that was built from an old tree and held a finding (source archives:
   `git archive <tag> | tar -x`, then the project's build, e.g. `uv build --sdist`), write its `.b3`, and replace
   the file on every forge without touching the release's date or notes: `gh release upload <tag> --clobber`;
   GitLab: upload with `curl -H "Authorization: Bearer $(glab config get token --host gitlab.com)" -F file=@...`
   to `projects/<id>/uploads`, swap the release link, then delete the old upload
   (`DELETE projects/<id>/uploads/<secret>/<filename>`); Codeberg: delete the asset, upload it again under the
   same name.
10. Rotate each leaked secret at its service (a Clavren licence key: revoke it and issue a new one in the Clavren
    dashboard, which only the user can sign in to, so ask them) and seal the new one in this project's memory
    (a `reference_*_keys.md` or `*_secret.md` file, sealed with `python ~/.claude/bin/secrets.py seal`).
11. GitLab keeps the old objects: delete the scrubbed blobs with the GraphQL mutation
    `projectBlobsRemove(input: {projectPath: "Ran-n/<repo>", blobOids: [...]})` (the ids are every blob in the old
    history that the new one lacks), delete the pipelines of old commits
    (`DELETE projects/<id>/pipelines/<id>`, they pin old commits), then
    `POST projects/<id>/housekeeping?task=prune`. Check a removed blob with `GET projects/<id>/repository/blobs/<id>`;
    if it is still served a day later, add GitLab to step 12.
12. GitHub and Codeberg (and GitLab if needed) keep serving the old commits by hash: write a support request
    naming the repo, its visibility, the current `main`, the old heads and the scrubbed blob ids, asking them to
    purge cached views and unreachable objects; the user sends it from their account.
13. Record the outcome in this project's memory (`project_history_rewrite.md`, indexed in its `MEMORY.md`): what was
    found, where, what replaced it, the new `main`, and what is still pending.

### Tests
- No code changes, so no unit tests. Each check is evidence instead:
  - `python ~/.claude/bin/leak_history.py` exits 0 on the final history.
  - `gitleaks dir` reports nothing on every folder.
  - Every committed image has been opened and noted as clean or removed.
- If the rewrite changed test files, run the project's full test suite on the new working tree: green.

### Docs
- `CHANGELOG.md` under `[Unreleased]`, **Security**: "Removed leaked <kind> from the repository history" (no value).
- `.gitleaksignore` comments for each false positive.

### Done when
- [ ] Every remote's visibility is noted.
- [ ] `leak_history.py`, `gitleaks dir` and the grep of step 5 report no real finding; false positives are recorded
      with a reason.
- [ ] Every image and PDF ever committed was looked at.
- [ ] Every real finding is gone from history on every forge (`git ls-remote` matches the new history) and from
      the release assets, with dates, messages, tags and signatures as before.
- [ ] Every leaked secret is rotated (or the user has been asked to), and the new one is sealed.
- [ ] GitLab's old blobs are deleted or a request is written; GitHub's and Codeberg's support requests are written.
- [ ] The working clone sits on the new history with uncommitted work intact; other sessions were told.
- [ ] The project memory records the result.

## 38. Check the project against the global standards and file the gaps

**Why:** the global rules in `~/.claude/memory/` (indexed in `~/.claude/memory/MEMORY.md`) have grown: every app
now needs an in-app updater with signed releases, an About section, a portable build and an installer for each
platform, a README laid out as a landing page, and code that follows SOLID and the design patterns. Projects
written before a rule existed don't follow it: Orin, for one, wasn't following the design patterns. This repo has
not been checked against the current rules, so its gaps are unknown. Do this after item 37, so no work starts on a
history that may still be rewritten.

**Goal:** a written verdict for every global rule (follows it, not applicable and why, or a gap), and every gap
filed as its own item in this `TODO.md`, each small enough to ship alone, ordered by importance. This item only
audits and files; the filed items do the work.

### Behaviour
- Each rule is judged against the code as it is now: read the code, run the app or the tests where that is the only
  way to know.
- A rule that doesn't fit this kind of project (a library has no updater, a docs or assets repo has no build) is
  marked not applicable, with the reason.
- When this project deliberately differs from a rule, and the project spec (`project_spec.md` in its memory) or a
  decision records why, that is a documented exception, not a gap; when nothing records it, ask the user with
  AskUserQuestion whether it is an exception or a gap.
- Each gap becomes one item written by the `/todo` writing rules (Why, Goal, Behaviour, Out of scope,
  Implementation, Tests, Docs, Done when), with the rule's file named in its Why.

### Out of scope
- Fixing the gaps here: each filed item fixes its own.
- Changing a global rule. If a rule looks wrong for this project, raise it with the user instead of bending it.
- Other repositories: each has its own copy of this item.

### Implementation
1. Read `~/.claude/memory/MEMORY.md` and every rule file it lists under Session Behaviour, Git & Version Control,
   Python Projects (when this is a Python project), Repository Setup, Code Quality, API Design (when it has an
   API) and UI (when it has a UI), plus this project's `project_spec.md`.
2. Check the project, rule by rule, and write the verdict in a table in this item's working notes (not committed):
   - **App standards:** `feedback_app_consistency.md`, `feedback_universal_behaviours.md` (clean shutdown on every
     quit path), `feedback_about_section.md`, `feedback_in_app_updater.md` (GitHub + GitLab check, Ed25519 +
     BLAKE3 proof before download, self-replace, restart, signing tool, tests, bridge from an older updater),
     `feedback_build_matrix.md` (portable + installer per platform, names `<app>-<version>-<target>-portable|setup`,
     `.b3` + `.sig`, tag-driven draft release, per-user installer and its test),
     `feedback_versioned_build_filenames.md`, `feedback_releases.md`, `feedback_persist_all_settings.md`.
   - **Repository:** `feedback_new_repo_scaffold.md`, `reference_license.md` (PayBack License, never MIT or Apache),
     `reference_readme_layout.md`, `reference_contributing_layout.md`, `reference_contributors_layout.md`,
     `feedback_changelog.md`, `feedback_site_organization.md`, `feedback_git_remotes.md` (`main`, all three forges
     over SSH).
   - **Code:** `feedback_clean_code.md` (SOLID, GoF patterns where they fit, DRY, files under about 200 lines,
     functions under about 20; list the worst offenders with their sizes), `feedback_source_organization.md`,
     `feedback_logging.md`, `feedback_no_silent_failure.md` (grep for bare `except`, swallowed errors),
     `feedback_parallel_code.md`, `feedback_regression_safety.md`, `feedback_database_bcnf.md`,
     `feedback_no_future_imports.md`, `feedback_file_headers.md`, `feedback_python_projects.md` and
     `reference_pyproject_scaffold.md` (ruff, line length 120), `reference_preferred_stack.md`.
   - **Tests:** `feedback_tests.md` (every type in its checklist, coverage gate), `feedback_tests_rendered_ui.md`,
     `feedback_ui_tests_no_input_hijack.md`, `feedback_ui_tests_hidden.md`; run the suite with coverage and note
     the figure.
   - **UI and text:** `feedback_i18n_completeness.md`, `feedback_ui_inline_editing.md`,
     `feedback_ui_disabled_buttons.md`, `feedback_ui_cta_hierarchy.md`.
3. For each gap, add an item at the end of this file with `/todo` (one rule per item, or one area of the code per
   item for a large refactor), in this order: security and data loss first, then the updater and releases, then
   tests, then code structure, then docs and layout. Put the rule file in each item's Why.
4. Reply to the user with the table's gaps and the new item numbers.

### Tests
- None for this item: it changes no code. Each filed item lists its own tests.

### Docs
- None for this item. Changelog: none (an audit changes nothing).

### Done when
- [ ] Every rule file in the groups of step 2 has a verdict: follows, not applicable (with reason), exception (with
      where it is recorded) or gap.
- [ ] Every gap is filed as its own item in this `TODO.md`, in the order of step 3, with the Index updated.
- [ ] The test suite's coverage figure is noted.
- [ ] The user has the list of gaps and item numbers.
