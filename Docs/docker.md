<!--
SPDX-License-Identifier: AGPL-3.0-or-later
SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
-->

# Running badgeserver with Docker

The image (`Dockerfile`) is a `debian:trixie-slim` base with the runtime
dependencies from apt — the exact set in `requirements-apt.txt`, no pip. The
compiled translation catalogs are committed, so there is no build step beyond
copying the source in. `docker-compose.yml` builds it, runs `gunicorn` on port
4000, and keeps the data in a named volume.

Debian trixie is the tested base. `ubuntu:24.04` has compatible package
versions too (its `requests` is a little old, so the `/verify` DNS-pinning
falls back to the plain SSRF screen — no crash). `ubuntu:22.04` is too old:
its Flask-Babel, WTForms, email-validator and Flask-SQLAlchemy predate what
the code uses.

## First run

```sh
cp deploy/badges.env.example badges.env
$EDITOR badges.env
docker compose up -d --build
docker compose exec badgeserver flask create-admin <username>
docker compose exec badgeserver flask set-issuer \
  --name "Your Org" --url https://your.org --email badges@your.org
```

Open `http://localhost:4000/` (or your `EXTERNAL_URL`).

`set-issuer` fills in the issuer profile — the organisation that issues the
badges. `--url` is that organisation's homepage, not this server (the server's
address is already recorded as the issuer id). `flask set-issuer --help` and
[`INSTALL.md`](INSTALL.md#what-set-issuer-configures) explain each field; you
can also edit it later at **Admin → Issuer**.

### `badges.env`

Same `KEY=VALUE` format as `deploy/badges.env.example`; Compose loads it as the
container's environment. Set at least:

| Key | Value |
| --- | --- |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `EXTERNAL_URL` | the exact public origin, e.g. `https://badges.example.org` or `http://host.lan:4000` |
| `SMTP_*` / `MAIL_FROM` | your mail relay, if award e-mails are wanted |

The example ships with `MAIL_ENABLED=true` and the LibrePlan relay — set
`MAIL_ENABLED=false` (or your own `SMTP_HOST` / `MAIL_FROM`) unless you want
award e-mails. Self-service badge claiming needs a working relay.

`EXTERNAL_URL` is baked into every badge and assertion URL — pick it carefully,
don't change it after issuing badges. `BIND` and `BADGESERVER_DATA_DIR` are
fixed by the compose file; leave them out of `badges.env`.

Change the published port with `HOST_PORT` (host side only):
`HOST_PORT=8080 docker compose up -d`.

## Admin CLI

Any `flask` subcommand runs in the container:

```sh
docker compose exec badgeserver flask reset-password <username>
docker compose exec badgeserver flask send-test-email you@example.org
```

`flask init-db` runs automatically on every start; it is idempotent and also
applies schema upgrades (add-column migrations, the duplicate-award index).

## Data, backup, restore

Everything mutable is in the `data` volume: `badges.sqlite` and `uploads/`.

```sh
# backup
docker compose exec -T badgeserver tar -C /data -cz . > badgeserver-backup.tgz

# restore (into a stopped stack)
docker compose down
docker volume rm badgeserver_data
docker compose run --rm -T badgeserver sh -c 'tar -C /data -xz' < badgeserver-backup.tgz
docker compose up -d
```

To use a host directory instead of the named volume, replace `data:/data` with
`./data:/data` in `docker-compose.yml` and `chown -R 10001:10001 ./data` (the
`badges` user in the image is uid 10001).

## Upgrades

```sh
git pull
docker compose up -d --build
```

The new container rebuilds, runs `flask init-db` (migrations), and restarts.

## Reverse proxy / TLS

Terminate TLS in front (nginx, Caddy, Traefik, …), proxy to
`http://badgeserver:4000` (or the published `HOST_PORT`), and in `badges.env`:

```
EXTERNAL_URL=https://badges.example.org
PROXY_FIX_HOPS=1
```

`PROXY_FIX_HOPS` is the number of proxies you control — it makes the app trust
`X-Forwarded-*`; never set it higher than the real hop count.

## Rate limits across workers

Gunicorn runs 3 workers by default and rate limits are counted per worker
unless a shared store is set. For exact limits, start the bundled Redis and
point the app at it:

```sh
docker compose --profile with-redis up -d --build
# in badges.env:
RATELIMIT_STORAGE_URI=redis://redis:6379/0
```

Or just run one worker: `WEB_CONCURRENCY=1` in `badges.env`.

## Health

`GET /healthz` returns `{"status": "ok"}` after checking the database; the
compose healthcheck uses it. `docker compose ps` shows the status.
