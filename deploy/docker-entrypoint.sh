#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
#
# Container entrypoint.
#   (no args) / "gunicorn"  -> apply DB migrations, then run the app
#   anything else           -> exec it (e.g. `flask create-admin alice`)
set -eu

if [ "${1:-gunicorn}" = "gunicorn" ]; then
    echo "badgeserver: preparing the database in ${BADGESERVER_DATA_DIR} ..."
    python3 -m flask init-db
    echo "badgeserver: starting gunicorn on ${BIND}"
    exec python3 -m gunicorn -c deploy/gunicorn.conf.py wsgi:application
fi

exec "$@"
