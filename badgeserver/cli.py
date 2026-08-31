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


@click.command("init-db")
@with_appcontext
def init_db() -> None:
    """Create any missing database tables."""
    db.create_all()
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
    _send(address)
    click.echo(f"Test message sent to {address}.")
