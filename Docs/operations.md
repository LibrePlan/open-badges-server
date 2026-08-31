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

**Issuer** in the nav. `badgectl set-issuer` already created it; here you can
edit the name, website URL, contact e-mail and description, and upload a
**logo** (square PNG/JPEG/WEBP/GIF; it is normalised to a 512 px PNG). The
issuer's `slug` is fixed — it is part of every badge URL.

This profile is published at `/issuer/<slug>.json` and is what validators read
to identify who issued a badge.

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
| Badge image | **Required.** A square PNG works best; it is padded to square and resized to 512 px, and becomes the artwork that gets "baked". |

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
sudo systemctl restart badgeserver
```

If you moved the checkout, re-generate the unit:
`sudo sed "s#__REPO__#$PWD#" deploy/badgeserver.service | sudo tee /etc/systemd/system/badgeserver.service`
then `sudo systemctl daemon-reload && sudo systemctl restart badgeserver`.

There are no schema migrations in v1. If a future change adds columns,
`sudo ./deploy/badgectl init-db` creates *new* tables only — an added column
needs a manual `ALTER TABLE` or a one-off script. Take a backup first.

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
`https://` `EXTERNAL_URL`, then restart. `deploy/apache-badges.conf.example` is
a working Apache vhost; any proxy works as long as it forwards the original
`Host` and sets `X-Forwarded-Proto`, with `PROXY_FIX_HOPS` matching the number
of proxies. See [`INSTALL.md`](INSTALL.md) section 6b.

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
| Login fails with `The CSRF session token is missing` | `SESSION_COOKIE_SECURE=true` in `badges.env` while serving over `http://` — the browser drops the cookie. Remove that line (it defaults correctly from `EXTERNAL_URL`) and restart. The service now refuses to start in this state. |
| Login always fails right after deploy | run `create-admin`; check the clock (session protection) |
| `429 Too Many Requests` on login | rate limit hit; wait, or adjust `RATELIMIT_LOGIN` |
| Award e-mail fails | `sudo ./deploy/badgectl send-test-email …`; check `SMTP_*` |
| Image upload rejected | must be PNG/JPEG/WEBP/GIF and under `MAX_UPLOAD_BYTES` |
