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
| Can't sign in over plain HTTP | `SESSION_COOKIE_SECURE` should be false for an `http://` `EXTERNAL_URL` (it defaults that way) |
| Login always fails right after deploy | run `create-admin`; check the clock (session protection) |
| `429 Too Many Requests` on login | rate limit hit; wait, or adjust `RATELIMIT_LOGIN` |
| Award e-mail fails | `sudo ./deploy/badgectl send-test-email …`; check `SMTP_*` |
| Image upload rejected | must be PNG/JPEG/WEBP/GIF and under `MAX_UPLOAD_BYTES` |
