# Installation

Target: **Debian 13 (trixie)**, system Python 3.13, all dependencies from `apt`.

The app is a Flask WSGI application served by gunicorn on port **4000**. A
reverse proxy is **optional** — it can serve plain HTTP directly on the LAN, or
sit behind nginx/apache for TLS. Both modes are covered below.

There is a scripted version of all of this in
[`contrib/setup.sh`](../contrib/setup.sh); this document is the annotated walk-through.

---

## 0. Where the repository lives

The service runs as the unprivileged `badges` user, so **the checkout must be
readable by that user**. A private home directory (`/home/you`, mode `0700`) is
not — put the code somewhere world-traversable. `/opt/badgeserver` is the
recommended location; `/srv/badgeserver` is fine too. The data directory is
always `/var/lib/badgeserver`, separate from the code.

```sh
sudo rsync -a --delete /path/to/your/checkout/ /opt/badgeserver/
cd /opt/badgeserver
REPO_DIR="$PWD"
```

Keep the checkout owned by your normal user (so `git pull` works); it only
needs to be *readable* by others, which `/opt` already allows. The single place
the path is pinned is the systemd unit's `WorkingDirectory`, and step 5
substitutes it automatically. If you later move the checkout, redo step 5.

> Staying under `/home` is possible but requires opening it up
> (`sudo setfacl -m u:badges:x /home/you && sudo setfacl -R -m u:badges:rX /path/to/checkout`).
> Relocating to `/opt` is cleaner.

## 1. Runtime packages

```sh
sudo apt install python3-flask python3-flask-sqlalchemy python3-flask-login \
  python3-flaskext.wtf python3-wtforms python3-email-validator \
  python3-flask-talisman python3-flask-limiter python3-pil python3-qrcode \
  python3-gunicorn fonts-dejavu-core python3-cairosvg rsync
```

`fonts-dejavu-core` is the font for composed badge titles; `python3-cairosvg`
rasterises SVG uploads (omit it and SVG uploads are rejected with a clear
message — everything else still works).

Optional, for the test suite: `sudo apt install python3-pytest`.

Verify the imports resolve to the apt location:

```sh
python3 -c "import flask, sqlalchemy, email_validator; print(flask.__file__)"
# -> /usr/lib/python3/dist-packages/flask/__init__.py
```

## 2. Service user and data directory

```sh
sudo adduser --system --group --home /var/lib/badgeserver --no-create-home badges
sudo install -d -o badges -g badges -m 0750 /var/lib/badgeserver
```

`systemd`'s `StateDirectory=badgeserver` also creates/owns this directory at
service start; the explicit `install -d` just lets the CLI run before the
service exists.

## 3. Configuration

```sh
sudo install -o root -g badges -m 0640 deploy/badges.env.example /var/lib/badgeserver/badges.env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # -> SECRET_KEY
sudoedit /var/lib/badgeserver/badges.env
```

Minimum to set:

| Key | Value |
| --- | --- |
| `SECRET_KEY` | the random string just generated |
| `EXTERNAL_URL` | the exact public origin, e.g. `http://badges.dsg.lan:4000` |
| `BIND` | `0.0.0.0:4000` for direct access, `127.0.0.1:4000` behind a proxy |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_SECURITY` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `MAIL_FROM` | your mail relay |

`EXTERNAL_URL` is baked into every badge URL. Changing it later rewrites all
badge/assertion URLs and breaks already-issued badges — pick it carefully.

`SESSION_COOKIE_SECURE` and `PROXY_FIX_HOPS` default themselves from the
`EXTERNAL_URL` scheme (`http://` → insecure cookie, no proxy trust;
`https://` → secure cookie). Only set them by hand for an unusual setup.

## 4. Bootstrap the database

`deploy/badgectl` runs the `flask` CLI as the `badges` user with `badges.env`
loaded. It finds the repo from its own location, so it works from any checkout path.

```sh
sudo ./deploy/badgectl init-db
sudo ./deploy/badgectl create-admin admin
sudo ./deploy/badgectl set-issuer --slug main \
  --name "LibrePlan Badges" --url https://libreplan.dev --email jeroen@libreplan.dev
sudo ./deploy/badgectl send-test-email jeroen@libreplan.dev
```

The `send-test-email` step should land a message in your inbox. If it errors,
fix the `SMTP_*` values and retry — nothing else depends on it.

## 5. Install and start the service

```sh
sudo sed "s#__REPO__#$REPO_DIR#" deploy/badgeserver.service \
  | sudo tee /etc/systemd/system/badgeserver.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now badgeserver

curl -fsS http://127.0.0.1:4000/healthz && echo
journalctl -u badgeserver -n 20 --no-pager
```

If you ever move the checkout, re-run the `sed | tee` line with the new
`$REPO_DIR` and `systemctl daemon-reload && systemctl restart badgeserver`.

## 6a. Direct HTTP (no reverse proxy)

With `BIND=0.0.0.0:4000` and `EXTERNAL_URL=http://badges.dsg.lan:4000`, the
server is already reachable at `http://badges.dsg.lan:4000/`. Open the firewall
if one is active:

```sh
sudo ufw allow 4000/tcp        # or: firewall-cmd --add-port=4000/tcp --permanent
```

Make sure `badges.dsg.lan` resolves to this host (DNS or `/etc/hosts` on the
clients). That is the whole setup for this mode.

## 6b. Behind a reverse proxy (TLS)

Set in `badges.env`: `BIND=127.0.0.1:4000`, `PROXY_FIX_HOPS=1`,
`EXTERNAL_URL=https://badges.example.org`, then
`sudo systemctl restart badgeserver`.

An Apache vhost is in [`deploy/apache-badges.conf.example`](../deploy/apache-badges.conf.example):

```sh
sudo a2enmod proxy proxy_http headers ssl
sudo cp deploy/apache-badges.conf.example /etc/apache2/sites-available/badges.conf
sudoedit /etc/apache2/sites-available/badges.conf     # ServerName + cert paths
sudo a2ensite badges && sudo systemctl reload apache2
```

The proxy must forward the original `Host` and set `X-Forwarded-Proto: https`.

## 7. End-to-end check

```sh
BASE=http://badges.dsg.lan:4000      # or your https origin

curl -s "$BASE/issuer/main.json" | python3 -m json.tool
```

Then in a browser: sign in at `$BASE/admin`, create a badge class with a PNG,
award it to yourself with the notification box ticked. On the assertion page:

- the `assertion JSON` link returns Open Badges 2.0 with
  `"verification": {"type": "hosted"}` and a `sha256$…` recipient identity;
- the baked PNG download carries the assertion URL:
  `python3 -c "from PIL import Image,sys; print(Image.open(sys.argv[1]).text['openbadges'])" badge.png`
- the notification e-mail arrives with a working link.

Revoke it from the admin page and confirm the JSON now shows
`"revoked": true`.

Once reachable from the internet (proxy mode), run a public assertion URL
through an external Open Badges validator as the final confirmation.

## Upgrades, backup, restore, troubleshooting

See [`operations.md`](operations.md).
