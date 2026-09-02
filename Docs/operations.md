# Operations

First-time installation is in [`INSTALL.md`](INSTALL.md). This document covers
running the service afterwards.

## Layout on the host

| Path | Purpose |
| --- | --- |
| the repository checkout | the code (path is pinned only in the systemd unit's `WorkingDirectory`) |
| `/var/lib/badgeserver` | data directory (owned by the `badges` user) |
| `/var/lib/badgeserver/badges.env` | configuration + secrets, mode `0640 root:badges` |
| `/var/lib/badgeserver/badges.sqlite` | the database |
| `/var/lib/badgeserver/uploads/` | badge / issuer images and baked PNGs |
| `/etc/systemd/system/badgeserver.service` | the service unit |

The service runs as `User=badges`. Administration commands are run with
`sudo ./deploy/badgectl <command>`, which loads `badges.env` and re-executes
`flask` as that user.

## First steps

Everything below happens in the web UI. The address is your `EXTERNAL_URL`
(e.g. `http://badges.dsg.lan:4000`).

### 1. Sign in

Go to `/admin`. Sign in with the username you passed to
`badgectl create-admin` and its password. You land on the **Dashboard** (badge
and assertion counts, recent awards). The left nav has: Dashboard, Issuer,
Badges, Assertions, Password.

Change the bootstrap password now if it was typed on a shared terminal:
**Password** in the nav, or `sudo ./deploy/badgectl reset-password <username>`.

### 2. Polish the issuer profile

**Issuer** in the nav. This is the Open Badges `Issuer` / `Profile` object — it
identifies *who* issues the badges (your organisation), separate from the
server that hosts them. `badgectl set-issuer` created it; here you edit:

| Field | Meaning |
| --- | --- |
| Name | Display name of the issuing organisation. Shown everywhere as *"Issued by \<name\>"*. |
| Website URL | The **organisation's public homepage**, e.g. `https://example.org`. A human link shown by wallets and validators so a badge holder can find out who the issuer is. Point it at the organisation, **not** at this badge server (see below). |
| Contact e-mail | Public address, embedded in the issuer JSON — visible to anyone who verifies a badge. |
| Description | Optional blurb about the issuer. |
| Logo | Square PNG/JPEG/WEBP/GIF, normalised to a 512 px PNG. Appears on the issuer JSON and next to the badge on verification pages. |

The **slug** is fixed once set — it is part of `/issuer/<slug>.json`, which is
referenced by every badge.

The server derives the rest from `EXTERNAL_URL` and never asks you for it: the
issuer's machine-readable **`id`** (`{EXTERNAL_URL}/issuer/<slug>.json`) and the
URLs of every badge class and assertion.

**Website URL — organisation, not server.** The badge server's host is already
in the badge data twice over (the issuer `id`, and the host of every assertion
JSON). The *Website URL* is the one human-facing link in the profile, so it
should go to a page that says who the issuer is — the organisation's site, not
a bare badge host. Using the organisation's parent domain also keeps the issuer
`id` host and the assertion host on a related domain, which some external
validators check for consistency. This server's own `/verify` only checks that
the issuer `id` and the assertion share a domain, so the Website URL never
affects verification here.

This profile is published at `/issuer/<slug>.json`.

### 3. Create a badge class

A *badge class* is the definition of an award (its name, image, criteria). You
issue *assertions* of it to people.

**Badges → New badge**. Fill in:

| Field | Notes |
| --- | --- |
| Name | e.g. "First Commit". The slug is derived from it and then fixed. |
| Description | One or two sentences shown on the badge page and in the JSON. |
| Criteria | Plain text: what someone did to earn it. |
| Criteria URL | Optional link to a fuller policy/page. |
| Tags | Comma-separated, for grouping on the public page. |
| Badge image | Choose one of the two modes below. |

**Badge image** has two modes:

- **Upload a finished image** — PNG / JPEG / WEBP / GIF / SVG; it is made square
  and resized to 512 px and used as-is.
- **Compose from a logo** — upload just a logo (SVG works well), pick a shape
  (octagon / circle / hexagon / shield / crest) and background + ring colours, then
  fine-tune with sliders: **Logo size** (40–200 %), **Border width** (0–30 px,
  0 = no border), **Logo position** and **Title position** (nudge each up or
  down). The **live preview** beside the form updates as you change any of
  these or the title. The server draws the badge with the logo on top and the
  title wrapped underneath, re-rendering it on every save. Text colour
  auto-contrasts with the background.

Save. The badge now appears on the public home page and at `/b/<slug>`.

### 4. Award it

From **Badges**, use **Award** on the row (or open the badge and award from
there):

- **Recipient e-mail** — the identity the badge is bound to. It is stored
  server-side but only ever published as a salted SHA-256 hash.
- **Issued on** — defaults to today.
- **Evidence URL** / **Note** — optional, both appear in the assertion.
- **Send an e-mail notification** — on by default (hidden if SMTP is not
  configured). The recipient gets a message with a link to their badge.

On save you get the **assertion page**. Each assertion has a unique URL
(`/a/<uuid>`) and:

- `/a/<uuid>.json` — the Open Badges 2.0 assertion, i.e. the verifiable proof;
- `/a/<uuid>/badge.png` — the badge image with that assertion URL baked in;
- `/a/<uuid>/qr.png` — a QR code to the assertion page.

To award the same badge to many people at once, use **CSV**: upload a file with
one e-mail address per line (other columns are ignored). Duplicates and people
who already hold the badge are skipped; you get a per-row result. Capped at
`CSV_AWARD_MAX_ROWS` (default 200).

### 5. What the recipient does

The recipient opens their assertion page and can:

- download the **baked PNG** and use it anywhere (it carries its own proof);
- import the badge into an Open Badges backpack / wallet by giving it either the
  baked PNG or the `/a/<uuid>.json` URL;
- share the assertion page link.

Anyone can verify a badge by fetching its `.json` and following `badge` →
`issuer`; all three URLs are public and send `Access-Control-Allow-Origin: *`.

### 6. Manage awards

**Assertions** in the nav lists everything issued, with filters by badge,
recipient e-mail and status. Open one to:

- **Revoke** it (with a reason) — `/a/<uuid>.json` then returns
  `"revoked": true` and the recipient's page shows it as revoked. **Re-instate**
  undoes this.
- **Re-send** the notification e-mail (e.g. after a delivery failure — the
  detail page shows the last e-mail status).

**Archive** a badge class (Badges list) to hide it from the public home page
without touching any assertions already issued.

## Verifying a badge

`/verify` (also in the admin menu, and the public site header) checks whether a
badge is legitimate. Paste any of:

- a badge page / assertion-JSON URL, or a baked badge PNG URL;
- the assertion JSON itself;
- a signed-badge (JWS) token.

Badges issued by **this** server are checked against the database directly.
Anything else is fetched and validated as an Open Badges 2.0 badge: the
assertion must be published at its own `id`, the badge class and issuer are
fetched and checked, `revoked` is honoured, and **signed badges have their
signature cryptographically verified** against the issuer's published key.
Add the recipient's e-mail to also confirm who the badge was issued to.

The result is `valid` / `revoked` / `expired` / `not verified` / `not checked`
(Open Badges 3.0 and pre-2.0 are recognised but not verified), with a checklist
of every check performed.

The page is public and rate-limited (`RATELIMIT_VERIFY`, default
`12/minute; 80/hour`) — the limit applies to `GET /verify?url=…` too, not only
the form POST. Outbound fetches are screened so they cannot reach private,
loopback or link-local addresses, each fetch connects to the exact IP that was
screened (no DNS-rebinding window), and one verification is capped at a dozen
requests and two levels of baked-PNG indirection.

## Self-service badges

Tick **Let anyone claim this badge** on a badge (Badges → edit) to open it for
public self-claiming — a "fan" badge, an event badge, etc. On the badge's public
page a visitor enters their e-mail and gets a **confirmation link**; following it
opens a page with a single button, and the badge is issued only when they press
it (link valid `CLAIM_EXPIRY_HOURS`, default 24).

- E-mail (SMTP) must be configured — the confirmation link is the whole point.
- Self-service badges show a *claimable* marker on the home page and in the
  admin badge list.
- The claim endpoint is rate-limited (`RATELIMIT_CLAIM`, default
  `4/minute; 15/hour; 40/day`).
- Turn the whole feature off with `SELF_SERVICE_ENABLED=false` in `badges.env`
  (the per-badge tick is then ignored).

Claimed badges are ordinary assertions — revoke them from **Assertions** like
any other.

## Languages

The interface ships in **English** (source), **Spanish**, **German**,
**French** and **Dutch**.

- **Visitors** switch with the links in the page header. The choice is kept in
  their session and travels as `?lang=<code>` on links. With no choice made,
  the browser's `Accept-Language` decides, then `BABEL_DEFAULT_LOCALE`.
- **Notification e-mails** follow the language in effect when they are sent:
  a self-service confirmation is in the visitor's language; an admin-issued
  award notice is in the language the admin had selected.
- `LANGUAGES` (in `badges.env`, default `en,es,de,fr,nl`) sets which languages
  are offered — drop codes to hide them. The header switcher disappears when
  only one language is listed.

### Editing the translations

Catalogs live in `badgeserver/translations/<code>/LC_MESSAGES/messages.po`.
The compiled `.mo` files are committed, so deployments need no build step.
`contrib/i18n.sh` wraps `pybabel` (from `python3-babel`):

```sh
contrib/i18n.sh extract      # rescan the code + templates into messages.pot
contrib/i18n.sh update       # merge new/changed strings into every .po
# ...edit the msgstr entries in the .po files...
contrib/i18n.sh compile      # rebuild the .mo files
```

Commit the changed `.po` **and** `.mo` files. To add a language:
`contrib/i18n.sh init <code>`, translate it, `compile`, then add the code to
`LANGUAGES` and to `LANGUAGE_NAMES` in `badgeserver/i18n.py`.

## Security notes

- **Rate limits and multiple workers.** Limits are counted in each gunicorn
  worker's own memory by default, so with `WEB_CONCURRENCY=3` the effective
  limit is roughly three times the configured value and it resets whenever a
  worker recycles. For exact enforcement set `RATELIMIT_STORAGE_URI` to a shared
  store, e.g. `redis://127.0.0.1:6379/0`, or run a single worker.
- **Reverse proxy and client IPs.** Rate limits key on the client IP. Behind a
  proxy, set `PROXY_FIX_HOPS` to the number of proxies you control so the real
  client IP is used — and never set it higher than that, or a client could spoof
  `X-Forwarded-For` to dodge the limit.
- **Recipient e-mail privacy.** A published assertion JSON contains the salted
  SHA-256 of the recipient's e-mail plus the salt (required by Open Badges 2.0
  hosted verification). E-mail addresses are low-entropy, so a determined party
  with the assertion can brute-force the address offline. This is a property of
  the badge format, not of this server; treat "who holds badge X" as
  semi-public.

## Quick reference

| Task | Where |
| --- | --- |
| Award a badge | Badges → *Award* (or *CSV* for a list) |
| Revoke / re-instate | Assertions → open one → *Revoke* / *Re-instate* |
| Re-send a notification | assertion detail → *Re-send e-mail* |
| Hide a badge from the public page | Badges → *Archive* (assertions keep working) |
| Reset a lost admin password | `sudo ./deploy/badgectl reset-password <username>` |
| Add another admin | `sudo ./deploy/badgectl create-admin <username>` |

## Service control

```sh
sudo systemctl status badgeserver
sudo systemctl restart badgeserver
journalctl -u badgeserver -f
sudo systemctl reload badgeserver     # graceful worker reload after a code update
```

## Updating the code

```sh
cd "$(systemctl show -p WorkingDirectory --value badgeserver)"
git pull
sudo ./deploy/badgectl init-db        # picks up any new columns; safe to re-run
sudo systemctl restart badgeserver
```

If you moved the checkout, re-generate the unit:
`sudo sed "s#__REPO__#$PWD#" deploy/badgeserver.service | sudo tee /etc/systemd/system/badgeserver.service`
then `sudo systemctl daemon-reload && sudo systemctl restart badgeserver`.

`init-db` creates missing tables and adds missing columns (`ALTER TABLE ADD
COLUMN`, SQLite) — it is idempotent. There is no down-migration or column
removal; take a backup before an upgrade if in doubt.

## Backup

Everything that matters is under `/var/lib/badgeserver`:

```sh
sudo systemctl stop badgeserver
sudo tar czf /root/badgeserver-$(date +%F).tgz -C /var/lib badgeserver
sudo systemctl start badgeserver
```

For an online snapshot of just the database:

```sh
sudo -u badges sqlite3 /var/lib/badgeserver/badges.sqlite ".backup '/var/lib/badgeserver/backup.sqlite'"
```

## Restore

```sh
sudo systemctl stop badgeserver
sudo tar xzf /root/badgeserver-YYYY-MM-DD.tgz -C /var/lib
sudo chown -R badges:badges /var/lib/badgeserver
sudo systemctl start badgeserver
```

## Reverse proxy (optional)

The server runs fine on plain HTTP with `BIND=0.0.0.0:4000` and no proxy. To
put TLS in front of it, set `BIND=127.0.0.1:4000`, `PROXY_FIX_HOPS=1` and an
`https://` `EXTERNAL_URL`, then restart. Worked examples:
[`deploy/apache-badges.conf.example`](../deploy/apache-badges.conf.example) and
[`deploy/nginx-badges.conf.example`](../deploy/nginx-badges.conf.example). Any
proxy works as long as it forwards the original `Host`, sets
`X-Forwarded-Proto`, and passes `X-Forwarded-For`, with `PROXY_FIX_HOPS`
matching the number of proxies you control. Full steps (Apache modules, certs)
in [`INSTALL.md`](INSTALL.md) section 6b.

## Health

`GET /healthz` returns `{"status":"ok"}` and touches the database. Point the
proxy or an external monitor at it.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Service won't start, `Missing required configuration` | `SECRET_KEY` / `EXTERNAL_URL` in `badges.env` |
| Service won't start, `WorkingDirectory ... not absolute` | the unit still has `__REPO__`; re-run the `sed` install step |
| `badgectl` / service fails: `badges` user can't read the checkout, or `dotenv ... Starting path not found` | the checkout is under a private `/home`; relocate it (`sudo rsync -a --delete <checkout>/ /opt/badgeserver/`), redo the `sed` install step |
| Badge JSON has the wrong scheme/host | `EXTERNAL_URL` must be the exact public origin; behind a proxy also set `PROXY_FIX_HOPS=1` |
| Apache: `Invalid command 'RequestHeader'` | `sudo a2enmod headers && sudo systemctl restart apache2` |
| Apache: `AH01144: No protocol handler was valid for the URL / (scheme 'http')` | `mod_proxy_http` not loaded: `sudo a2enmod proxy_http && sudo systemctl restart apache2` |
| Login works but redirects to `http://` / drops the session | proxy isn't sending `X-Forwarded-Proto: https`, or `PROXY_FIX_HOPS` is 0 |
| Login fails with `The CSRF session token is missing` | `SESSION_COOKIE_SECURE=true` in `badges.env` while serving over `http://` — the browser drops the cookie. Remove that line (it defaults correctly from `EXTERNAL_URL`) and restart. The service now refuses to start in this state. |
| Login always fails right after deploy | run `create-admin`; check the clock (session protection) |
| `429 Too Many Requests` on login | rate limit hit; wait, or adjust `RATELIMIT_LOGIN` |
| Award e-mail fails | `sudo ./deploy/badgectl send-test-email …`; check `SMTP_*` |
| Image upload rejected | must be PNG/JPEG/WEBP/GIF and under `MAX_UPLOAD_BYTES` |
