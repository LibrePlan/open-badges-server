# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""Configuration, loaded from the process environment.

Every value has a safe default except ``SECRET_KEY`` and ``EXTERNAL_URL``,
which are mandatory in a non-testing run (see :func:`Config.validate`).
"""

from __future__ import annotations

import os


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


class Config:
    """Application configuration derived from environment variables."""

    def __init__(self, data_dir: str) -> None:
        self.DATA_DIR = data_dir
        self.UPLOAD_DIR = os.path.join(data_dir, "uploads")

        self.SECRET_KEY = os.environ.get("SECRET_KEY", "")
        # Public origin the badges are served from, e.g. https://badges.example.org
        self.EXTERNAL_URL = os.environ.get("EXTERNAL_URL", "").rstrip("/")

        self.SQLALCHEMY_DATABASE_URI = os.environ.get(
            "DATABASE_URL", f"sqlite:///{os.path.join(data_dir, 'badges.sqlite')}"
        )
        self.SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

        # Behind a TLS-terminating reverse proxy by default.
        self.PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")
        self.SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"

        # Number of trusted proxy hops in front of the app.
        self.PROXY_FIX_HOPS = _int("PROXY_FIX_HOPS", 1)

        self.RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
        self.RATELIMIT_LOGIN = os.environ.get("RATELIMIT_LOGIN", "5 per minute; 30 per hour")

        self.MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_BYTES", 3 * 1024 * 1024)
        self.BADGE_IMAGE_SIZE = _int("BADGE_IMAGE_SIZE", 512)
        self.CSV_AWARD_MAX_ROWS = _int("CSV_AWARD_MAX_ROWS", 200)

        # E-mail / SMTP
        self.MAIL_ENABLED = _bool("MAIL_ENABLED", False)
        self.SMTP_HOST = os.environ.get("SMTP_HOST", "")
        self.SMTP_PORT = _int("SMTP_PORT", 587)
        self.SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls").strip().lower()
        self.SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
        self.SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
        self.SMTP_TIMEOUT = _int("SMTP_TIMEOUT", 15)
        self.MAIL_FROM = os.environ.get("MAIL_FROM", "")
        self.MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")

        self.SITE_TITLE = os.environ.get("SITE_TITLE", "Open Badges")

    def as_dict(self) -> dict:
        return {k: v for k, v in vars(self).items() if k.isupper()}

    def validate(self) -> None:
        missing = [k for k in ("SECRET_KEY", "EXTERNAL_URL") if not getattr(self, k)]
        if missing:
            raise RuntimeError(
                "Missing required configuration: "
                + ", ".join(missing)
                + ". Set them in the environment (see deploy/badges.env.example)."
            )
        if not self.EXTERNAL_URL.startswith(("http://", "https://")):
            raise RuntimeError("EXTERNAL_URL must be an absolute http(s) URL.")
        if self.SMTP_SECURITY not in {"none", "starttls", "ssl"}:
            raise RuntimeError("SMTP_SECURITY must be one of: none, starttls, ssl.")
