# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""A small self-hosted Open Badges 2.0 issuer."""

from __future__ import annotations

import os

from flask import Flask, render_template
from flask_talisman import Talisman
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, limiter, login_manager

__all__ = ["create_app"]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CSP = {
    "default-src": "'self'",
    "img-src": ["'self'", "data:"],
    "style-src": "'self'",
    "script-src": "'self'",
    "base-uri": "'self'",
    "form-action": "'self'",
    "frame-ancestors": "'none'",
}


def _resolve_data_dir(override: str | None) -> str:
    data_dir = (
        override
        or os.environ.get("BADGESERVER_DATA_DIR")
        or os.path.join(_REPO_ROOT, "instance")
    )
    return os.path.abspath(data_dir)


def create_app(config_overrides: dict | None = None, *, data_dir: str | None = None) -> Flask:
    resolved = _resolve_data_dir(data_dir)
    os.makedirs(resolved, exist_ok=True)

    app = Flask(__name__, instance_path=resolved)

    config = Config(resolved)
    app.config.from_mapping(config.as_dict())
    if config_overrides:
        app.config.update(config_overrides)

    if not app.config.get("TESTING"):
        config.validate()

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    hops = int(app.config.get("PROXY_FIX_HOPS", 1))
    if hops > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops, x_port=hops
        )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    Talisman(
        app,
        force_https=False,
        strict_transport_security=True,
        session_cookie_secure=app.config["SESSION_COOKIE_SECURE"],
        frame_options="DENY",
        referrer_policy="same-origin",
        content_security_policy=_CSP,
    )

    from .models import AdminUser

    @login_manager.user_loader
    def _load_user(user_id: str):
        return db.session.get(AdminUser, int(user_id))

    from .admin import bp as admin_bp
    from .public import bp as public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from . import cli

    cli.register(app)

    @app.errorhandler(404)
    def _not_found(err):  # noqa: ANN001
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def _server_error(err):  # noqa: ANN001
        return render_template("500.html"), 500

    @app.context_processor
    def _inject_globals():
        return {"site_title": app.config["SITE_TITLE"]}

    return app
