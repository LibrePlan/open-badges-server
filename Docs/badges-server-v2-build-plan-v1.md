# Badge server v2 — build plan (v1)

## Context

The Fedora **Tahrir** stack is not optimal for our usecase: its
latest PyPI releases (`tahrir` 2.1.0 + `tahrir-api` 1.5.6) are mutually
incompatible (leaderboard API renamed, badge tags moved to a separate table,
WTForms / flask-admin break), it is hard-wired to a Fedora OpenID Connect
provider, and even a version-pinned fork would still emit the obsolete Open
Badges 0.5/1.0 assertion format that nothing verifies today.

This project replaces it with a small, purpose-built Flask application that:

- issues **Open Badges 2.0** with **hosted verification** — the format current
  validators and backpacks accept;
- has **one local admin** (username + password), no external identity provider;
- stores everything in a single SQLite file plus an uploads directory;
- runs under **gunicorn on `127.0.0.1:4000`**, behind a reverse proxy added
  separately;
- is small enough to read end-to-end and keep stable long term.

Constraints baked into this plan:

- Prefer **Debian `apt` packages** for all runtime dependencies.
- The service listens on **port 4000** only; TLS is terminated by the proxy.
- Recipients are **emailed** when a badge is awarded (SMTP).
- The service runs as a dedicated **`badges` system user**; its data lives in
  `/var/lib/badgeserver`, outside the repository.
- Licence: **AGPL-3.0-or-later**, with SPDX headers on every source file.

## Runtime environment

Debian 13 (trixie), system Python 3.13. Every dependency is available from
`apt`:

| Package | Provides |
|---|---|
| `python3-flask` | Flask 3.1 |
| `python3-flask-sqlalchemy` | ORM session / teardown wiring |
| `python3-flask-login` | admin session management |
| `python3-flaskext.wtf` | Flask-WTF 1.2 (`flask_wtf`) — forms + CSRF |
| `python3-wtforms` | WTForms 3.2 |
| `python3-email-validator` | e-mail syntax validation for forms |
| `python3-flask-talisman` | security headers / CSP |
| `python3-flask-limiter` | login brute-force rate limiting |
| `python3-pil` | Pillow — image validation + PNG baking |
| `python3-qrcode` | QR image for the assertion URL |
| `python3-gunicorn` | WSGI server (run as `python3 -m gunicorn`) |

Password hashing uses Werkzeug's built-in `generate_password_hash`
(`pbkdf2:sha256`). E-mail sending uses the Python standard library
(`smtplib` + `email.message`). Neither needs an extra package.

### One-time host setup (operator)

```
sudo apt install python3-flask python3-flask-sqlalchemy python3-flask-login \
  python3-flaskext.wtf python3-wtforms python3-email-validator \
  python3-flask-talisman python3-flask-limiter python3-pil python3-qrcode python3-gunicorn

sudo adduser --system --group --home /var/lib/badgeserver --no-create-home badges
```

After the apt install, `python3 -c "import flask, sqlalchemy; print(flask.__file__)"`
must print a path under `/usr/lib/python3/`.

## Open Badges 2.0 shapes

`@context` is always `"https://w3id.org/openbadges/v2"`. Every `id` / `image` /
`issuer` / `badge` value is an **absolute URL** built from the configured
`EXTERNAL_URL`.

- **Issuer / Profile** — `GET /issuer/<slug>.json`
  `{ @context, type: "Issuer", id, name, url, email, description?, image? }`
- **BadgeClass** — `GET /b/<slug>.json`
  `{ @context, type: "BadgeClass", id, name, description, image,
     criteria: { narrative, id? }, issuer, tags? }`
- **Assertion** — `GET /a/<uuid>.json` (this URL is both the `id` and the
  hosted proof)
  `{ @context, type: "Assertion", id,
     recipient: { type: "email", hashed: true, salt, identity: "sha256$<hex>" },
     badge: <BadgeClass URL>, issuedOn: <ISO 8601>,
     verification: { type: "hosted" }, evidence?, narrative? }`
  A revoked assertion returns HTTP 200 with
  `{ …, "revoked": true, "revocationReason": "<text>" }`.

`identity = "sha256$" + sha256((recipient_email + salt).encode()).hexdigest()`.

## Data model (`badgeserver/models.py`)

- **AdminUser**: `id`, `username` (unique), `password_hash`, `created_on`.
- **Issuer**: `slug` (PK), `name`, `url`, `email`, `description`, `image_path`.
- **BadgeClass**: `slug` (PK), `issuer_slug` (FK), `name`, `description`,
  `image_path`, `criteria_narrative`, `criteria_url`, `tags` (comma string),
  `created_on`, `archived` (bool).
- **Assertion**: `uuid` (PK), `badge_slug` (FK), `recipient_email` (plaintext,
  server-side only — needed for management and revocation), `salt`, `issued_on`,
  `evidence_url`, `narrative`, `revoked` (bool), `revocation_reason`,
  `baked_png_path`, `created_on`, `email_sent` (bool), `email_sent_at`,
  `email_error`.

Schema is created with `db.create_all()` via `flask init-db`. Alembic is out of
scope for v1 and can be added later without rework.

## Project layout

```
badges/
├── Docs/
│   ├── badges-server-v2-build-plan-v1.md   (this file)
│   └── operations.md                       bootstrap / backup / restore / upgrade
├── badgeserver/
│   ├── __init__.py        app factory: config, extensions, ProxyFix, Talisman,
│   │                      blueprint + CLI registration
│   ├── config.py          configuration loaded from the environment
│   ├── extensions.py      db / login_manager / limiter / csrf singletons
│   ├── models.py
│   ├── openbadges.py      OB 2.0 JSON serialisers + recipient hashing
│   ├── issuing.py         award-a-badge service (salt, bake, e-mail, persist)
│   ├── images.py          validate an upload, normalise to a square PNG
│   ├── baking.py          embed the assertion URL in a PNG "openbadges" iTXt chunk
│   ├── mail.py            stdlib SMTP sender + award-notification helper
│   ├── public.py          blueprint: browse pages, *.json, images, QR, baked PNG
│   ├── admin.py           blueprint: login, dashboard, issuer / badge / assertion admin
│   ├── forms.py           Flask-WTF forms
│   ├── cli.py             init-db / create-admin / reset-password / set-issuer / send-test-email
│   ├── templates/         base, index, badge, assertion, errors, admin/*, email/*
│   └── static/            style.css, favicon (no external CDN)
├── deploy/
│   ├── badgeserver.service        systemd unit (gunicorn, 127.0.0.1:4000, User=badges)
│   ├── gunicorn.conf.py
│   ├── badgectl                   run the flask CLI as the badges user with badges.env
│   ├── badges.env.example         template for /var/lib/badgeserver/badges.env
│   └── apache-badges.conf.example  reverse-proxy vhost example (commented)
├── tests/                 pytest smoke tests
├── wsgi.py                application = create_app()
├── instance/              local-dev data dir (gitignored)
├── .gitignore
├── LICENSE                AGPL-3.0
├── README.md
└── requirements-apt.txt   documents the apt package list
```

## Routes

Public — no authentication; the `*.json` endpoints send
`Access-Control-Allow-Origin: *`:

| Route | Purpose |
|---|---|
| `GET /` | issuer summary + list of active badge classes |
| `GET /b/<slug>` | human page for a badge class |
| `GET /a/<uuid>` | human page for an assertion (masked recipient, date, verify link, downloads) |
| `GET /issuer/<slug>.json` | Issuer JSON |
| `GET /b/<slug>.json` | BadgeClass JSON |
| `GET /a/<uuid>.json` | Assertion JSON (hosted proof) |
| `GET /issuer/<slug>/image` | issuer logo |
| `GET /b/<slug>/image` | badge-class PNG |
| `GET /a/<uuid>/badge.png` | baked PNG |
| `GET /a/<uuid>/qr.png` | QR code of the assertion page |
| `GET /healthz` | health check for the proxy |

Admin (`/admin`, login required, CSRF on every POST):

`login` (rate-limited) · `logout` · dashboard · issuer edit + logo upload ·
badge classes list / new / edit / archive · award (single) · award-csv (bulk) ·
assertions list + filter · revoke / unrevoke · resend notification ·
change password.

The award forms carry a "send e-mail notification" checkbox (on by default,
disabled when SMTP is not configured).

## PNG baking (`badgeserver/baking.py`)

Pure Pillow, no ImageMagick:

```python
from PIL import Image, PngImagePlugin
img = Image.open(badge_class_png).convert("RGBA")
meta = PngImagePlugin.PngInfo()
meta.add_itxt("openbadges", assertion_json_url)   # standard bakery keyword
img.save(out_path, "PNG", pnginfo=meta)
```

Uploaded badge art is validated and re-saved as a 512×512 PNG by `images.py`.
SVG is not supported in v1.

## E-mail notifications (`badgeserver/mail.py`)

Standard-library `smtplib` / `email.message.EmailMessage`. Config keys (in
`badges.env`): `MAIL_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`
(`none` | `starttls` | `ssl`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM`,
`MAIL_REPLY_TO` (optional).

- On award, if requested and SMTP is configured, send a text + HTML message
  from `templates/email/award.*` containing the assertion page URL and the
  baked-PNG link.
- Sending is **synchronous** and **best-effort**: failure never rolls back the
  award. Success records `email_sent` / `email_sent_at`; failure records
  `email_error`. The admin assertion view shows the status and a **Resend**
  button.
- CSV bulk award is capped at 200 rows (sending happens in-request) and reports
  a per-row result summary.
- `flask send-test-email <addr>` checks SMTP without issuing a badge.

## Security posture (internet-facing)

- `werkzeug.middleware.proxy_fix.ProxyFix` (one hop) so the forwarded protocol,
  host and client IP from the reverse proxy are honoured.
- Flask-Talisman: HSTS, `X-Content-Type-Options=nosniff`, frame-deny,
  `referrer-policy=same-origin`, CSP `default-src 'self'` (server-rendered, no
  inline scripts). `force_https` is off (the proxy terminates TLS) but HSTS is
  still emitted.
- Session cookie `Secure` + `HttpOnly` + `SameSite=Lax`.
- Flask-Limiter on `/admin/login` — `5/minute; 30/hour` per IP.
- CSRF on every state-changing form.
- Public JSON never contains the plaintext recipient e-mail — only the salted
  SHA-256 identity.
- No self-service registration or password reset; recovery is the
  `flask reset-password` CLI command (local shell only).
- `SECRET_KEY` and `EXTERNAL_URL` are required — the app refuses to start
  without them. `SECRET_KEY` and `SMTP_PASSWORD` live only in
  `/var/lib/badgeserver/badges.env` (mode 0640, `root:badges`).

## systemd unit (`deploy/badgeserver.service`)

Runs `/usr/bin/gunicorn -c deploy/gunicorn.conf.py wsgi:application`
(`bind = "127.0.0.1:4000"`, 3 workers, logs to the journal).

- `User=badges`, `Group=badges`
- `WorkingDirectory=/home/jeroen/badges`
- `StateDirectory=badgeserver` → `/var/lib/badgeserver` (auto-created, `badges`-owned)
- `EnvironmentFile=/var/lib/badgeserver/badges.env`
- Hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
  `ProtectHome=read-only`, `ReadWritePaths=/var/lib/badgeserver`,
  `ProtectKernelTunables`, `ProtectControlGroups`,
  `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `LockPersonality`,
  `MemoryDenyWriteExecute`, `SystemCallFilter=@system-service`.

CLI admin commands run through `deploy/badgectl`, which sources `badges.env`
and re-executes `flask` as the `badges` user, e.g.
`sudo ./deploy/badgectl create-admin admin`.

## Verification (end-to-end)

1. apt install + `adduser badges` + pip cleanup done; `flask.__file__` under
   `/usr/lib/python3`.
2. Write `/var/lib/badgeserver/badges.env` from `deploy/badges.env.example`.
3. `sudo ./deploy/badgectl init-db`
4. `sudo ./deploy/badgectl create-admin admin`
5. `sudo ./deploy/badgectl set-issuer --slug main --name "…" --url "…" --email "…"`
6. `sudo ./deploy/badgectl send-test-email you@example.org`
7. `sudo systemctl enable --now badgeserver`
8. `curl -s localhost:4000/issuer/main.json | python3 -m json.tool` — check
   `@context`, `type`, required fields.
9. Log into `/admin`, create a badge class with a PNG, award it to
   `test@example.com` with notification on.
10. `curl -s localhost:4000/a/<uuid>.json` — verify
    `recipient.identity == "sha256$" + sha256(b"test@example.com" + salt)`;
    confirm the e-mail arrived with the correct assertion URL.
11. `curl -so out.png localhost:4000/a/<uuid>/badge.png` then
    `python3 -c "from PIL import Image; print(Image.open('out.png').text['openbadges'])"`
    — equals the assertion `.json` URL.
12. Revoke via admin; re-fetch `.json` — `revoked: true` + reason.
13. CSRF rejection (POST with no token → 400) and login rate limit
    (6th bad login in a minute → 429).
14. `pytest -q`.
15. Once the reverse proxy is live: run the public assertion URL through an
    external Open Badges validator.

## Out of scope for v1

Open Badges 3.0 / Verifiable Credentials; signed (non-hosted) verification;
multiple admin users; SVG badge art; Alembic migrations; a background job queue
for e-mail (sending is synchronous and resendable); any message bus.
