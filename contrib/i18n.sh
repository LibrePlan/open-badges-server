#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
#
# Translation catalog helper. Wraps pybabel (package: python3-babel).
#
#   contrib/i18n.sh extract          rebuild badgeserver/translations/messages.pot
#   contrib/i18n.sh update           merge the .pot into every existing .po
#   contrib/i18n.sh init <locale>    create a new badgeserver/translations/<locale>
#   contrib/i18n.sh compile          compile every .po to its .mo (commit both)
#
# The usual loop after changing a user-facing string:
#   contrib/i18n.sh extract && contrib/i18n.sh update
#   # ...translate the new entries in the .po files...
#   contrib/i18n.sh compile

set -eu

cd "$(dirname "$0")/.."

POT=badgeserver/translations/messages.pot
DOMAIN=messages
DIR=badgeserver/translations

case "${1:-}" in
  extract)
    pybabel extract -F babel.cfg -k _l -k lazy_gettext \
      -o "$POT" --project="Open Badges Server" --version="" \
      --copyright-holder="Jeroen Baten" .
    echo "wrote $POT"
    ;;
  update)
    pybabel update -i "$POT" -d "$DIR" -D "$DOMAIN" --no-fuzzy-matching
    ;;
  init)
    [ $# -eq 2 ] || { echo "usage: $0 init <locale>" >&2; exit 2; }
    pybabel init -i "$POT" -d "$DIR" -D "$DOMAIN" -l "$2"
    ;;
  compile)
    pybabel compile -d "$DIR" -D "$DOMAIN" --statistics
    ;;
  *)
    sed -n '4,20p' "$0"
    exit 2
    ;;
esac
