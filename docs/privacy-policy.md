[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/16 09:19:09.907159 )
[//]: # (+ Revised: 	2026/07/18 19:33:27.690167 )
[//]: # ( ---------------------------------------------------------------------- )

[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ DRAFT — not yet published. Needs: effective date, hosting provider/  )
[//]: # (+ jurisdiction, and a legal review before this goes live or gets       )
[//]: # (+ linked from any app store listing.                                   )
[//]: # ( ---------------------------------------------------------------------- )

# Privacy Policy — Renar

**Status: DRAFT.** Company is set (Breren); domain/contact are scoped under
the app name (renar.breren.com, privacy@renar.breren.com).
Still open: `[EFFECTIVE DATE]`, `[HOSTING PROVIDER]`, `[JURISDICTION]` —
fill in once hosting is chosen (see `docs/backlog.md`, Infrastructure /
Publishing sections). Have a lawyer review before publishing or linking
this from a store listing — this draft reflects what the app actually does
today, but isn't a substitute for legal sign-off.

_Last updated: [EFFECTIVE DATE]_

## Who we are

Renar ("Renar", "we", "us") is a personal media tracker for films and TV
shows, operated by Breren. This policy covers
the Renar mobile apps, web app, and backend service. If you have
questions about this policy or your data, contact us at
privacy@renar.breren.com.

## What we collect

**Account information.** Username, email address, and password (stored
only as a salted hash — we never store or can recover your plaintext
password). Optionally: a profile avatar and background image you upload.

**Library data.** The titles you track, their watch/read status, your
ratings and notes, favorites, rewatch history, and per-episode progress.
If you set a custom poster or backdrop image on an entry (a premium
feature), that image is stored too.

**Preferences.** Display language, theme, and other in-app settings
(e.g. whether original titles are shown, home-screen layout choices).
These are stored so they follow your account across devices.

**Technical and security data.** Your IP address is logged briefly to
enforce rate limits and detect abuse (e.g. brute-force login attempts,
scripted registration spam) — see `docs/anti-abuse.md` for the mechanism.
We also record login timestamps and coarse, aggregated request counts per
endpoint to keep the service running reliably; this is operational
telemetry, not behavioral tracking, and is not shared with or sold to
anyone.

**What we don't collect.** We don't use advertising SDKs, third-party
analytics/tracking pixels, or sell your data to anyone. There is no ad
network integrated into Renar.

## Third-party services we use to fetch content metadata

To show posters, titles, episode lists, and other metadata for the movies
and shows you track, Renar queries:

- **The Movie Database (TMDB)**
- **TheVDB (TVDB)** — used only as a fallback to resolve titles TMDB can't
  match during TV Time imports

These lookups are by title/ID, not by your personal account information —
we don't send your email, username, or password to these services. Their
own privacy policies govern how they handle the requests we send them.

## Why we process this data

- **To provide the service** — your account, library, and preferences
  exist so the app can function; this is the core contractual basis for
  processing.
- **To keep the service secure and available** — IP-based rate limiting
  and abuse detection, a legitimate interest in preventing account
  takeover, spam, and denial-of-service against other users.
- **To improve reliability** — aggregated, non-identifying request/error
  counts used to find and fix performance problems.

We do not process your data for advertising, profiling, or any purpose
beyond running and securing the app.

## How long we keep it

Account and library data is kept for as long as your account exists.
Deleting your account (in-app, or via a request to privacy@renar.breren.com) removes
your user record and all associated library entries, images, and
preferences. IP-based security logs (login attempts, rate-limit strikes)
are kept only as long as needed for abuse detection and are not tied to
your account identity beyond that window.

## Your rights

Depending on where you live (including under the GDPR if you're in the
EU/EEA/UK), you may have the right to:

- **Access** the personal data we hold about you
- **Correct** inaccurate data (most of this you can already edit directly
  in your profile settings)
- **Delete** your account and associated data — available directly in the
  app, or by contacting privacy@renar.breren.com
- **Export** your data in a portable format
- **Object to or restrict** certain processing

To exercise any of these, use the in-app options where available or
contact us at privacy@renar.breren.com. We'll respond within the timeframe required
by applicable law.

## Children's privacy

Renar is not directed at children under 13 (or the minimum age required
by your local law, e.g. 16 in some EU member states), and we do not
knowingly collect personal information from children under that age. If
you believe a child has created an account, contact us at
privacy@renar.breren.com and we'll remove it.

## Data storage and security

Passwords are stored as salted hashes, never in plaintext. Authentication
uses short-lived signed tokens (JWT). Uploaded images and account data are
stored on infrastructure operated by Breren / [HOSTING PROVIDER],
located in [JURISDICTION]. We use HTTPS to encrypt data in transit.

No method of storage or transmission is 100% secure; we can't guarantee
absolute security, but we take reasonable measures to protect your data,
including rate limiting, brute-force lockouts, and IP banning for abusive
traffic (see `docs/anti-abuse.md`).

## International data transfers

[Fill in once hosting region is chosen: state whether data is processed
outside the user's country/region, and under what safeguard (e.g. Standard
Contractual Clauses) if applicable.]

## Changes to this policy

We may update this policy as the app changes. Material changes will be
noted with an updated "Last updated" date above; where required by law,
we'll provide additional notice (e.g. in-app).

## Contact

Questions, requests, or complaints about this policy or your data:
privacy@renar.breren.com.
