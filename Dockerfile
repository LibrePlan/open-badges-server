# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
#
# Runtime dependencies come from Debian apt (the python3-* packages), never
# pip -- the same set as requirements-apt.txt. The compiled translation
# catalogs are committed, so there is no build step.

FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-flask python3-flask-sqlalchemy python3-flask-login \
      python3-flaskext.wtf python3-wtforms python3-email-validator \
      python3-flask-talisman python3-flask-limiter python3-flask-babel \
      python3-pil python3-qrcode \
      python3-gunicorn fonts-dejavu-core python3-cairosvg \
      python3-requests python3-jwt python3-cryptography \
      python3-redis \
 && rm -rf /var/lib/apt/lists/*
# python3-redis is used only when RATELIMIT_STORAGE_URI points at a redis:// URL.

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin badges

WORKDIR /app
COPY . /app
RUN install -d -o badges -g badges /data

# The image has no .git, so the footer version comes from this build arg:
#   BADGESERVER_VERSION="$(contrib/version.sh)" docker compose build
ARG BADGESERVER_VERSION=""

ENV BADGESERVER_DATA_DIR=/data \
    BIND=0.0.0.0:4000 \
    FLASK_APP=/app/wsgi.py \
    FLASK_SKIP_DOTENV=1 \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    BADGESERVER_VERSION=$BADGESERVER_VERSION

USER badges
EXPOSE 4000
VOLUME ["/data"]

ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["gunicorn"]
