# badgeserver

A small self-hosted **Open Badges 2.0** issuer.

- Issues badges with **hosted verification** — the assertion JSON URL is the proof.
- One **local admin** account (username + password). No external identity provider.
- Single **SQLite** database plus an uploads directory.
- Server-rendered Flask app, runs under **gunicorn on `127.0.0.1:4000`** behind a
  reverse proxy that terminates TLS.
- Emails recipients (optional) when a badge is awarded.

Licence: **AGPL-3.0-or-later** (see `LICENSE`).

The full design is in [`Docs/badges-server-v2-build-plan-v1.md`](Docs/badges-server-v2-build-plan-v1.md);
operational procedures are in [`Docs/operations.md`](Docs/operations.md).

## What it serves

| URL | Content |
| --- | --- |
| `/` | public browse page (issuer + active badges) |
| `/b/<slug>` , `/b/<slug>.json` | badge class (human page / `BadgeClass` JSON) |
| `/a/<uuid>` , `/a/<uuid>.json` | assertion (human page / `Assertion` JSON — the hosted proof) |
| `/a/<uuid>/badge.png` | the badge image with the assertion URL baked in |
| `/a/<uuid>/qr.png` | QR code linking to the assertion page |
| `/issuer/<slug>.json` | `Issuer` / `Profile` JSON |
| `/admin` | login-protected administration |
| `/healthz` | health check for the proxy |

## Install (Debian 13)

```sh
sudo apt install python3-flask python3-flask-sqlalchemy python3-flask-login \
  python3-flaskext.wtf python3-wtforms python3-email-validator \
  python3-flask-talisman python3-flask-limiter python3-pil python3-qrcode \
  python3-gunicorn

sudo adduser --system --group --home /var/lib/badgeserver --no-create-home badges
```

Then create the config and bootstrap the database:

```sh
sudo install -o root -g badges -m 0640 deploy/badges.env.example /var/lib/badgeserver/badges.env
sudoedit /var/lib/badgeserver/badges.env      # set SECRET_KEY, EXTERNAL_URL, SMTP_*

sudo ./deploy/badgectl init-db
sudo ./deploy/badgectl create-admin admin
sudo ./deploy/badgectl set-issuer --slug main --name "Your Org" --url https://your.org --email badges@your.org
sudo ./deploy/badgectl send-test-email you@your.org      # verify SMTP
```

Install and start the service:

```sh
sudo cp deploy/badgeserver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now badgeserver
curl -s localhost:4000/healthz
```

Put a reverse proxy in front of `127.0.0.1:4000`
(see `deploy/apache-badges.conf.example`), matching `EXTERNAL_URL`.

## Local development

```sh
export SECRET_KEY=dev-only EXTERNAL_URL=http://localhost:4000 \
       SESSION_COOKIE_SECURE=false MAIL_ENABLED=false
python3 -m flask --app wsgi.py init-db
python3 -m flask --app wsgi.py create-admin admin
python3 -m flask --app wsgi.py run --port 4000
```

Data goes to `./instance/` in this mode.

## Tests

```sh
sudo apt install python3-pytest
python3 -m pytest -q
```
