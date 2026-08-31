#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
#
# One-shot host bootstrap. Run from a checkout of this repository:
#   sudo ./contrib/setup.sh
# then edit /var/lib/badgeserver/badges.env and re-run the badgectl steps.
# See Docs/INSTALL.md for the annotated version.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# 1. runtime packages (Debian 13)
sudo apt install -y python3-flask python3-flask-sqlalchemy python3-flask-login \
  python3-flaskext.wtf python3-wtforms python3-email-validator \
  python3-flask-talisman python3-flask-limiter python3-pil python3-qrcode \
  python3-gunicorn

# 2. dedicated service user + data dir
sudo adduser --system --group --home /var/lib/badgeserver --no-create-home badges || true
sudo install -d -o badges -g badges -m 0750 /var/lib/badgeserver

# 3. config file (edit it before continuing)
if [ ! -e /var/lib/badgeserver/badges.env ]; then
  sudo install -o root -g badges -m 0640 deploy/badges.env.example /var/lib/badgeserver/badges.env
  echo
  echo ">>> Edit /var/lib/badgeserver/badges.env now:"
  echo ">>>   SECRET_KEY   = $(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  echo ">>>   EXTERNAL_URL = http://badges.dsg.lan:4000   (your real origin)"
  echo ">>>   SMTP_* / MAIL_FROM"
  echo ">>> then re-run this script to finish."
  exit 0
fi

# 4. database + admin + issuer
sudo ./deploy/badgectl init-db
sudo ./deploy/badgectl create-admin admin
sudo ./deploy/badgectl set-issuer --slug main --name "LibrePlan Badges" \
  --url https://libreplan.dev --email jeroen@libreplan.dev
sudo ./deploy/badgectl send-test-email jeroen@libreplan.dev || \
  echo "(SMTP test failed -- fix SMTP_* in badges.env, then: sudo ./deploy/badgectl send-test-email jeroen@libreplan.dev)"

# 5. systemd service (substitutes this checkout's path)
sudo sed "s#__REPO__#$REPO_DIR#" deploy/badgeserver.service \
  | sudo tee /etc/systemd/system/badgeserver.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now badgeserver
sleep 2
curl -fsS http://127.0.0.1:4000/healthz && echo
sudo systemctl --no-pager status badgeserver | head -n 5
