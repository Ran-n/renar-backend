[//]: # ( ---------------------------------------------------------------------- )
[//]: # (+ Authors: 	Ran# <ran.hash@proton.me> )
[//]: # (+ Created: 	2026/07/16 09:19:09.907159 )
[//]: # (+ Revised: 	2026/11/23 21:05:51.393584 )
[//]: # ( ---------------------------------------------------------------------- )

# Privacy Policy — Renar

Published at <https://renar.app/privacy>. This file is the source; the
page is `renar-frontend/landing/privacy/index.html` and must be updated in
the same change. Reviewed on 21–22 November 2026 in a lawyer-role review,
which the owner accepted as the legal review.

_Last updated: 22 November 2026_

This document is also available in Spanish. Both versions have the same value; if they differ, the one more favourable to you applies.

## Who we are

Renar ("Renar", "we", "us") is a personal tracker for films, series and
anime, run by an individual under the trade name Breren. This policy
covers the Renar mobile apps, web app, and backend service, and gives you
the information required by articles 13 and 14 of the EU General Data
Protection Regulation (GDPR) and the Spanish data protection law (Ley
Orgánica 3/2018, LOPDGDD). It is information for you, not a contract.

**Controller:** Breren, the trade name of an individual in Spain.
Contact for anything
about your data: privacy@renar.app. We have not appointed a data
protection officer, as the law doesn't require one for a service of our
size and kind.

## What we collect

**Account information.** Username, email address (and, while you change
it, the new address awaiting confirmation), and password, stored only as
a salted bcrypt hash: we never store or can recover your plaintext
password. The one-time codes we email you are also stored only as hashes
and expire after 15 minutes. We also keep your account's creation date,
when you ticked the sign-up box accepting the Terms of Service and this
policy and confirming you're 14 or older, and, if you create invite
codes, which codes you created. Optionally: a
profile avatar and background image you upload. Every uploaded image is
re-encoded on our server, which removes embedded metadata such as camera
details or location.

**Library data.** The titles you track, their watch status, your ratings
(including per-season and per-episode ratings), notes, an optional link
you attach to an entry, favorites, per-episode progress, and your watch
and rewatch history with dates. If you set a custom poster, backdrop or
episode image (a premium feature), that image is stored too. Also your
lists, and the in-app notifications we create about new episodes and
releases of titles you track.

**Imports.** If you import a TV Time export or a Renar export, we read the
file to create your library entries, lists and comments, and don't keep
the file itself. To match titles, we send the show and film names or IDs
in the file (never your account details) to TMDB and TheTVDB.

**Preferences.** Display language, theme, and other in-app settings
(e.g. whether original titles are shown, home-screen layout choices,
colors). These are stored so they follow your account across devices.

**Usage and security data.**

- Your IP address is processed for every request to enforce rate limits
  and detect abuse (e.g. brute-force login attempts, scripted registration
  spam). Only IP addresses that sent abusive traffic are stored, with the
  number of offences and the reason; some of them are banned.
- We record the time of each login and of your last activity, and keep
  per-account counters of how many requests your account made to each
  part of the service and on each day. These are linked to your account;
  we use them to run, secure and size the service, never for advertising
  or profiling.
- Our server writes technical log files (date and time, IP address,
  requested address and result, and error details, which may include your
  username or user ID) to find faults and investigate abuse.

**Content visible to other users.** Other signed-in Renar users can see:
your profile (username, avatar, background, badge, join date, number of
followers, people followed, tracked titles and total watch time); your
library (your most recent entries with status, rating and progress; the
notes and the link you attach to an entry are visible only to you); your
library activity, shown in the feeds
of your followers; your reviews and comments; and who you follow and who
follows you. Your lists are private. Don't put anything in these fields
you want to keep private.

**Blocks and reports.** If you block another user, we store that you
blocked them and when, so their content stays hidden from you (and yours
from them) until you unblock them. If you report a comment, review or
profile, we store who reported what, when, and any reason you typed, so a
moderator can look into it. Neither is shown to other users: the person
you block or report is not told. If we moderate content or an account, we
e-mail the user concerned, and everyone who reported it, the decision and
its reasons, and keep a record of the decision, its reason, a copy of any
removed text cut to 300 characters, and any complaint about it.

**What we don't collect.** We don't use advertising SDKs, third-party
analytics or tracking pixels, and we don't collect your location,
contacts or advertising ID. We don't sell your data to anyone.

**Cookies and device storage.** We use no tracking cookies. The app keeps
your login token and some settings on your device so you stay signed in;
this is strictly necessary for the service you asked for. Cloudflare may
set strictly necessary security cookies.

## Why we process this data, and on what legal basis

- **To provide the service** (your account, email confirmation, library,
  lists, social features, imports, exports, notifications, premium
  features and preferences): necessary to perform our contract with you
  (article 6(1)(b) GDPR).
- **To keep the service secure and available** (rate limits, the
  registration bot check, IP bans, login records, log files, backups,
  stopping a deleted account's username from being taken over at once):
  our legitimate interest in protecting you, other users and the service
  from account takeover, spam and attacks (article 6(1)(f) GDPR).
- **To run and improve the service** (per-account usage counters and
  error logs used to find and fix problems and plan capacity): our
  legitimate interest in a working, reliable service (article 6(1)(f)
  GDPR).
- **To moderate content and handle reports, complaints and notices of
  illegal content**: our legal obligations under the EU Digital Services
  Act (article 6(1)(c) GDPR) and our legitimate interest in a safe
  community (article 6(1)(f) GDPR).
- **To comply with the law** (e.g. answering a valid order from a court or
  authority, keeping records we must keep): legal obligation (article
  6(1)(c) GDPR).

You can object to processing based on legitimate interest (see "Your
rights"). Giving us your username, email address and password is required
to create an account; without them we can't provide the service.
Everything else is optional. We don't make decisions about you based
solely on automated processing that have legal or similarly significant
effects; automatic IP blocks act on abusive traffic, are limited in time
unless the abuse continues, and can be reviewed by a person on request.

## Who receives your data

Service providers that process data on our behalf, under data processing
agreements (article 28 GDPR):

- **Hetzner Online GmbH** (Germany) — hosts the server and database where
  your account and library data are stored.
- **Cloudflare, Inc.** (USA) — all traffic to Renar passes through
  Cloudflare's network (DNS, TLS, DDoS protection), so Cloudflare sees
  your IP address and request metadata. Registration uses **Cloudflare
  Turnstile**, a bot check that processes your IP address and browser or
  device signals to tell humans from bots.
- **Brevo (Sendinblue SAS)** (France) — sends account email such as
  confirmation codes. It receives your email address and the message.

**Google** distributes the Android app through Google Play and processes
data about your download and device under its own privacy policy, as an
independent controller.

**Other users** see the content described under "Content visible to other
users". **Courts and authorities** receive data only when the law requires
us to share it. We don't sell your data or share it with anyone else.

## Third-party services we use to fetch content metadata

To show posters, titles, episode lists, and other metadata for the movies
and shows you track, our server queries:

- **The Movie Database (TMDB)**
- **TheTVDB** — used only as a fallback to resolve titles TMDB can't
  match, mostly during TV Time imports

These lookups are by title/ID, not by your personal account information:
we don't send your email, username, or password to these services, and
images are fetched by our server, so your device doesn't contact them.
Their own privacy policies govern how they handle the requests we send
them.

## How long we keep it

- **Account, library, social content and preferences:** as long as your
  account exists. Deleting your account (in the app, on our web
  account-deletion page, or via a request to privacy@renar.app) starts a
  30-day grace period, during which your account stays active and visible
  to others and logging back in cancels the deletion. After it, we delete
  your user record and all associated library entries, watch history,
  ratings, reviews, comments (with the replies under them), lists,
  follows, blocks, reports by and about you, notifications, login and
  usage records, images and preferences.
- **Unconfirmed accounts:** deleted after 14 days if the email address is
  never confirmed.
- **Data exports** you request: deleted automatically after 7 days (1 day
  for premium accounts).
- **Reports:** until the reporter withdraws them, the reported content is
  removed, or either account is deleted.
- **Moderation records** (decisions, reasons, removed text, complaints): as long as the
  measure applies and for up to 6 months after, so that it can be
  contested, or longer if needed for a legal claim.
- **Abuse records about IP addresses:** offence counters are deleted 30
  days after the last offence; permanent bans last until we lift them.
- **Server log files:** a new file each day, deleted after 30 days.
- **Backups:** daily database backups are kept for 14 days, on the server
  and in a copy under our own control in the EU, so deleted data
  disappears from them within 14 days.
- **Released usernames:** when an account is deleted, we keep only its
  former username and the date for the username cooldown (30 days unless
  we change it), so nobody else can register it straight away. Nothing else about the account is kept.

## Your rights

Under the GDPR you have the right to:

- **Access** the personal data we hold about you
- **Correct** inaccurate data (most of this you can already edit directly
  in your profile settings)
- **Delete** your account and associated data — available directly in the
  app, on our web account-deletion page, or by contacting
  privacy@renar.app
- **Export** your data in a portable format (available in the app)
- **Restrict** processing in the cases the law provides
- **Object** to processing based on our legitimate interest, on grounds
  relating to your particular situation

To exercise any of these, use the in-app options where available or
contact us at privacy@renar.app. We reply within one month, which can be
extended by two more months for complex requests (we'll tell you if so),
and we may ask you to confirm you own the account. Exercising your rights
is free.

You have the right to lodge a complaint with a data protection authority:
in Spain, the Agencia Española de Protección de Datos (AEPD,
<https://www.aepd.es>, C/ Jorge Juan 6, 28001 Madrid), or the authority of
the EU country where you live or work. We'd appreciate the chance to sort
it out with you first at privacy@renar.app.

## Children

You must be at least 14 years old to use Renar, the age at which Spanish
law (article 7 LOPDGDD) lets you decide about your own data, or older if
the law of your country sets a higher age. We do not knowingly collect
personal data from children under that age. If you believe a child under
the minimum age has created an account, contact us at privacy@renar.app
and we'll delete it.

## Data storage and security

Passwords are stored as salted hashes, never in plaintext. Authentication
uses signed login tokens (JWT) that expire after one week and stop working
as soon as you change your password. Uploaded images and account data are
stored on servers operated by Hetzner Online GmbH in Germany (EU). We use
HTTPS to encrypt data in transit.

No method of storage or transmission is 100% secure; we can't guarantee
absolute security, but we take reasonable measures to protect your data,
including rate limiting, brute-force lockouts, and IP banning for abusive
traffic. If a breach puts your data at risk, we will notify the AEPD and,
where required, you (articles 33 and 34 GDPR).

## International data transfers

Your account and library data are stored in the EU. Cloudflare, Inc. is a
US company and runs a global network, so your requests may be processed in
data centres outside the EU/EEA. Transfers to Cloudflare rely on the
EU–US Data Privacy Framework, under which Cloudflare is certified (the
European Commission's adequacy decision of 10 July 2023, article 45 GDPR),
and on the European Commission's Standard Contractual Clauses in
Cloudflare's data processing agreement (article 46 GDPR). You can ask us
at privacy@renar.app for more information about these safeguards.

## Changes to this policy

We may update this policy as the app changes. Material changes will be
noted with an updated "Last updated" date above, and we'll tell you in the
app or by email before they take effect.

## Contact

Questions, requests, or complaints about this policy or your data:
privacy@renar.app.
