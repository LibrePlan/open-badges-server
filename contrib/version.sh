#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
#
# Print the app version:  <most recent tag> (<short commit>)
# or just  (<short commit>)  while there is no tag.
#
# Use it to feed BADGESERVER_VERSION where there is no git checkout at runtime
# (the container, or a hardened systemd unit):
#   BADGESERVER_VERSION="$(contrib/version.sh)" docker compose build
#   echo "BADGESERVER_VERSION=$(contrib/version.sh)" >> /var/lib/badgeserver/badges.env
set -eu

cd "$(dirname "$0")/.."

short=$(git rev-parse --short HEAD 2>/dev/null) || { echo "unknown"; exit 0; }
tag=$(git describe --tags --abbrev=0 2>/dev/null || true)

if [ -n "$tag" ]; then
    echo "$tag ($short)"
else
    echo "($short)"
fi
