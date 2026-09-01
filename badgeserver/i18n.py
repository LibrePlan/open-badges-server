# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Locale selection and the header language switcher."""

from __future__ import annotations

from urllib.parse import urlencode

from flask import current_app, has_request_context, request, session

#: language code -> name shown in the switcher (in that language)
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Español",
    "de": "Deutsch",
    "fr": "Français",
    "nl": "Nederlands",
}


def languages() -> dict[str, str]:
    return {code: LANGUAGE_NAMES.get(code, code) for code in current_app.config["LANGUAGES"]}


def select_locale() -> str:
    codes = current_app.config["LANGUAGES"]
    default = current_app.config["BABEL_DEFAULT_LOCALE"]
    if not has_request_context():
        return default
    chosen = session.get("lang")
    if chosen in codes:
        return chosen
    return request.accept_languages.best_match(codes) or default


def remember_locale() -> None:
    """`before_request` hook: honour and persist a ``?lang=`` choice."""
    lang = request.args.get("lang")
    if lang and lang in current_app.config["LANGUAGES"] and session.get("lang") != lang:
        session["lang"] = lang


def switch_url(code: str) -> str:
    """The current page's URL with ``lang=code`` set in the query string."""
    args = request.args.to_dict(flat=True)
    args["lang"] = code
    return f"{request.path}?{urlencode(args)}"
