# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""``flask`` command-line administration."""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db
from .models import AdminUser, Issuer, slugify


def register(app: Flask) -> None:
    app.cli.add_command(init_db)
    app.cli.add_command(create_admin)
    app.cli.add_command(reset_password)
    app.cli.add_command(set_issuer)
    app.cli.add_command(send_test_email)


# Columns added after 1.0. `init-db` is safe to re-run on an existing database
# and applies these with ALTER TABLE ADD COLUMN (SQLite).
_ADDED_COLUMNS = {
    "badge_class": {
        "logo_path": "VARCHAR(255)",
        "art_shape": "VARCHAR(16) NOT NULL DEFAULT 'octagon'",
        "art_bg": "VARCHAR(7) NOT NULL DEFAULT ''",
        "art_accent": "VARCHAR(7) NOT NULL DEFAULT ''",
        "art_logo_scale": "INTEGER NOT NULL DEFAULT 100",
        "art_border_width": "INTEGER NOT NULL DEFAULT 8",
        "art_logo_offset": "INTEGER NOT NULL DEFAULT 0",
        "art_title_offset": "INTEGER NOT NULL DEFAULT 0",
        "self_service": "BOOLEAN NOT NULL DEFAULT 0",
    },
}


def _sync_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    with db.engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    click.echo(f"added {table}.{name}")


@click.command("init-db")
@with_appcontext
def init_db() -> None:
    """Create missing tables and add any missing columns (safe to re-run)."""
    db.create_all()
    _sync_columns()
    click.echo(f"Database ready: {db.engine.url}")


@click.command("create-admin")
@click.argument("username")
@click.password_option(confirmation_prompt=True)
@with_appcontext
def create_admin(username: str, password: str) -> None:
    """Create the admin account USERNAME."""
    if AdminUser.query.filter_by(username=username).first():
        raise click.ClickException(f"User {username!r} already exists (use reset-password).")
    user = AdminUser(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"Created admin user {username!r}.")


@click.command("reset-password")
@click.argument("username")
@click.password_option(confirmation_prompt=True)
@with_appcontext
def reset_password(username: str, password: str) -> None:
    """Set a new password for USERNAME."""
    user = AdminUser.query.filter_by(username=username).first()
    if user is None:
        raise click.ClickException(f"No such user {username!r}.")
    user.set_password(password)
    db.session.commit()
    click.echo(f"Password updated for {username!r}.")


@click.command("set-issuer")
@click.option("--slug", default="", help="Identifier in URLs (default: derived from the name).")
@click.option("--name", required=True)
@click.option("--url", "url", required=True, help="Issuer website URL.")
@click.option("--email", required=True)
@click.option("--description", default="")
@with_appcontext
def set_issuer(slug: str, name: str, url: str, email: str, description: str) -> None:
    """Create or update the issuer profile."""
    existing = Issuer.query.order_by(Issuer.created_on).first()
    if existing is None:
        existing = Issuer(slug=slugify(slug or name))
        db.session.add(existing)
        action = "Created"
    else:
        action = "Updated"
        if slug and slug != existing.slug:
            click.echo(
                f"Note: keeping existing slug {existing.slug!r}; "
                f"badge URLs must stay stable."
            )
    existing.name = name
    existing.url = url
    existing.email = email
    existing.description = description
    db.session.commit()
    click.echo(f"{action} issuer {existing.slug!r} ({existing.name}).")


@click.command("send-test-email")
@click.argument("address")
@with_appcontext
def send_test_email(address: str) -> None:
    """Send a test message to ADDRESS to verify SMTP settings."""
    from .mail import mail_configured
    from .mail import send_test_email as _send

    if not mail_configured():
        raise click.ClickException(
            "SMTP is not configured (need MAIL_ENABLED, SMTP_HOST, MAIL_FROM)."
        )
    try:
        _send(address)
    except Exception as exc:  # noqa: BLE001 - report cleanly, no traceback
        raise click.ClickException(f"SMTP test failed: {exc}") from exc
    click.echo(f"Test message sent to {address}.")
