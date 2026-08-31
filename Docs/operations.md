# Operations

## Layout on the host

| Path | Purpose |
| --- | --- |
| `/home/jeroen/badges` | the code (this repository) |
| `/var/lib/badgeserver` | data directory (owned by the `badges` user) |
| `/var/lib/badgeserver/badges.env` | configuration + secrets, mode `0640 root:badges` |
| `/var/lib/badgeserver/badges.sqlite` | the database |
| `/var/lib/badgeserver/uploads/` | badge / issuer images and baked PNGs |
| `/etc/systemd/system/badgeserver.service` | the service unit |

The service runs as `User=badges`. Administration commands are run with
`sudo ./deploy/badgectl <command>`, which loads `badges.env` and re-executes
`flask` as that user.

## First-time bootstrap

```sh
sudo apt install python3-flask python3-flask-sqlalchemy python3-flask-login \
  python3-flaskext.wtf python3-wtforms python3-email-validator \
  python3-flask-talisman python3-flask-limiter python3-pil python3-qrcode python3-gunicorn
sudo adduser --system --group --home /var/lib/badgeserver --no-create-home badges

sudo install -o root -g badges -m 0640 deploy/badges.env.example /var/lib/badgeserver/badges.env
sudoedit /var/lib/badgeserver/badges.env

sudo ./deploy/badgectl init-db
sudo ./deploy/badgectl create-admin admin
sudo ./deploy/badgectl set-issuer --name "Your Org" --url https://your.org --email badges@your.org
sudo ./deploy/badgectl send-test-email you@your.org

sudo cp deploy/badgeserver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now badgeserver
```

`SECRET_KEY`: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.

`EXTERNAL_URL` must be the exact public origin (scheme + host, no trailing
slash) that recipients and validators reach through the reverse proxy. Changing
it later changes every badge URL and invalidates already-issued assertions.

## Day-to-day

- **Award a badge**: `/admin` → Badges → *Award*. Or bulk from a CSV/text file
  of e-mail addresses (*CSV*, capped at `CSV_AWARD_MAX_ROWS`, default 200).
- **Revoke**: open the assertion → *Revoke* with a reason. The public
  `/a/<uuid>.json` then returns `"revoked": true`. Use *Re-instate* to undo.
- **Resend a notification**: assertion page → *Re-send e-mail*.
- **Archive a badge**: hides it from the public browse page; existing
  assertions and JSON keep working.

## Service control

```sh
sudo systemctl status badgeserver
sudo systemctl restart badgeserver
journalctl -u badgeserver -f
sudo systemctl reload badgeserver     # graceful worker reload after a code update
```

## Updating the code

```sh
cd /home/jeroen/badges
git pull
sudo systemctl restart badgeserver
```

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

## Reverse proxy

The app listens on `127.0.0.1:4000` and expects TLS to be terminated in front
of it. `deploy/apache-badges.conf.example` is a working Apache vhost; any proxy
works as long as it forwards `X-Forwarded-Proto` and the original `Host`, and
`PROXY_FIX_HOPS` matches the number of proxies.

## Health

`GET /healthz` returns `{"status":"ok"}` and touches the database. Point the
proxy or an external monitor at it.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Service won't start, `Missing required configuration` | `SECRET_KEY` / `EXTERNAL_URL` in `badges.env` |
| Badge JSON has `http://` or wrong host | `EXTERNAL_URL`, and that the proxy sets `X-Forwarded-Proto` |
| Login always fails right after deploy | run `create-admin`; check the clock (session protection) |
| `429 Too Many Requests` on login | rate limit hit; wait, or adjust `RATELIMIT_LOGIN` |
| Award e-mail fails | `sudo ./deploy/badgectl send-test-email …`; check `SMTP_*` |
| Image upload rejected | must be PNG/JPEG/WEBP/GIF and under `MAX_UPLOAD_BYTES` |
