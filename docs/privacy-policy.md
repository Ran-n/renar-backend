[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/16 09:19:09.907159 )
[//]: # (+ Revised: 	2026/11/15 11:56:16.380726 )
[//]: # ( ---------------------------------------------------------------------- )

# Privacy Policy — Renar

Published at <https://renar.app/privacy>. This file is the source; the
page is `renar-frontend/landing/privacy/index.html` and must be updated in
the same change. Not yet reviewed by a lawyer.

_Last updated: 15 November 2026_

## Who we are

Renar ("Renar", "we", "us") is a personal media tracker for films and TV
shows, operated by Breren. This policy covers
the Renar mobile apps, web app, and backend service, and is incorporated
by reference into our Terms of Service. If you have
questions about this policy or your data, contact us at
privacy@renar.app.

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
scripted registration spam).
We also record login timestamps and coarse, aggregated request counts per
endpoint to keep the service running reliably; this is operational
telemetry, not behavioral tracking, and is not shared with or sold to
anyone.

**Content you post publicly.** Your username, avatar, profile, reviews,
comments, lists, ratings and the people you follow are visible to other
Renar users. Don't post anything there you want to keep private.

**Blocks and reports.** If you block another user, we store that you
blocked them and when, so their content stays hidden from you (and yours
from them) until you unblock them. If you report a comment, review or
profile, we store who reported what, when, and any reason you typed, so a
moderator can look into it. Neither is shown to other users: the person
you block or report is not told.

**What we don't collect.** We don't use advertising SDKs, third-party
analytics/tracking pixels, or sell your data to anyone. There is no ad
network integrated into Renar.

## Service providers that process data for us

- **Hetzner Online GmbH** (Germany) — hosts the server and database where
  your account and library data are stored.
- **Cloudflare, Inc.** — all traffic to Renar passes through Cloudflare's
  network (DNS, TLS, DDoS protection), so Cloudflare sees your IP address
  and request metadata. Registration and login use **Cloudflare
  Turnstile**, a bot check that processes your IP address and browser
  signals to tell humans from bots.
- **Brevo (Sendinblue SAS)** (France) — sends account email such as
  confirmation codes. It receives your email address and the message.

We don't sell your data or share it with anyone else, except where the
law requires us to.

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
Deleting your account (in-app, or via a request to privacy@renar.app) removes
your user record and all associated library entries, watch history,
reviews, comments, lists, blocks, reports, images, and preferences. Self-service
deletion takes effect after a 30-day grace period; logging back in
during that window cancels it. Data exports you request are deleted
automatically after a short time. IP-based security logs (login attempts, rate-limit strikes)
are kept only as long as needed for abuse detection and are not tied to
your account identity beyond that window.

## Your rights

Depending on where you live (including under the GDPR if you're in the
EU/EEA/UK), you may have the right to:

- **Access** the personal data we hold about you
- **Correct** inaccurate data (most of this you can already edit directly
  in your profile settings)
- **Delete** your account and associated data — available directly in the
  app, or by contacting privacy@renar.app
- **Export** your data in a portable format (available in the app)
- **Object to or restrict** certain processing

To exercise any of these, use the in-app options where available or
contact us at privacy@renar.app. We'll respond within the timeframe required
by applicable law. You also have the right to complain to the data
protection authority in your country.

## Children's privacy

Renar is not directed at children under 13 (or the minimum age required
by your local law, e.g. 16 in some EU member states), and we do not
knowingly collect personal information from children under that age. If
you believe a child has created an account, contact us at
privacy@renar.app and we'll remove it.

## Data storage and security

Passwords are stored as salted hashes, never in plaintext. Authentication
uses short-lived signed tokens (JWT). Uploaded images and account data are
stored on servers operated by Hetzner Online GmbH in Germany (EU). We use
HTTPS to encrypt data in transit.

No method of storage or transmission is 100% secure; we can't guarantee
absolute security, but we take reasonable measures to protect your data,
including rate limiting, brute-force lockouts, and IP banning for abusive
traffic.

## International data transfers

Your account and library data are stored in the EU. Cloudflare runs a
global network, so your requests may be processed in data centres
outside your country, including outside the EU/EEA. Cloudflare covers
those transfers with the EU Standard Contractual Clauses and the EU–US
Data Privacy Framework. We process your data under the EU General Data
Protection Regulation (GDPR).

## Changes to this policy

We may update this policy as the app changes. Material changes will be
noted with an updated "Last updated" date above; where required by law,
we'll provide additional notice (e.g. in-app).

## Contact

Questions, requests, or complaints about this policy or your data:
privacy@renar.app.
