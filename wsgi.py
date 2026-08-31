# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""WSGI entry point for gunicorn and the ``flask`` CLI."""

from badgeserver import create_app

application = create_app()
app = application
