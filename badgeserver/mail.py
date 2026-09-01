# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""SMTP e-mail sending, using only the Python standard library."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from urllib.parse import urlsplit

from flask import current_app, render_template

from .models import Assertion
from .openbadges import assertion_id


def mail_configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("MAIL_ENABLED") and cfg.get("SMTP_HOST") and cfg.get("MAIL_FROM"))


def _send(msg: EmailMessage) -> None:
    cfg = current_app.config
    host = cfg["SMTP_HOST"]
    port = int(cfg["SMTP_PORT"])
    security = cfg["SMTP_SECURITY"]
    timeout = int(cfg["SMTP_TIMEOUT"])
    context = ssl.create_default_context()

    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)

    with server:
        server.ehlo()
        if security == "starttls":
            if not server.has_extn("starttls"):
                raise RuntimeError(
                    f"{host}:{port} does not offer STARTTLS; "
                    f"set SMTP_SECURITY to 'none' or 'ssl'."
                )
            server.starttls(context=context)
            server.ehlo()
        username = cfg.get("SMTP_USERNAME")
        if username:
            if not server.has_extn("auth"):
                raise RuntimeError(
                    f"{host}:{port} does not offer SMTP AUTH. If the relay accepts "
                    f"mail from this host without a login, leave SMTP_USERNAME and "
                    f"SMTP_PASSWORD blank."
                )
            server.login(username, cfg.get("SMTP_PASSWORD", ""))
        server.send_message(msg)


def _sender_domain() -> str:
    cfg = current_app.config
    _name, addr = parseaddr(cfg.get("MAIL_FROM", ""))
    if "@" in addr:
        return addr.rsplit("@", 1)[1]
    host = urlsplit(cfg.get("EXTERNAL_URL", "")).hostname
    return host or "localhost"


def _base_message(to_addr: str, subject: str) -> EmailMessage:
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    # Date and Message-ID are required by RFC 5322 and expected by most
    # filters; EmailMessage/smtplib do not add them.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_sender_domain())
    if cfg.get("MAIL_REPLY_TO"):
        msg["Reply-To"] = cfg["MAIL_REPLY_TO"]
    return msg


def send_test_email(to_addr: str) -> None:
    msg = _base_message(to_addr, "Badge server SMTP test")
    msg.set_content(
        "This is a test message from the badge server. "
        "If you received it, SMTP delivery works."
    )
    _send(msg)


def send_award_email(assertion: Assertion) -> None:
    """Send the award notification. Raises on any SMTP failure."""
    badge = assertion.badge
    ctx = {
        "badge": badge,
        "issuer": badge.issuer,
        "assertion": assertion,
        "assertion_url": assertion_id(assertion.uuid).removesuffix(".json"),
        "assertion_json_url": assertion_id(assertion.uuid),
        "badge_png_url": assertion_id(assertion.uuid).removesuffix(".json") + "/badge.png",
        "site_title": current_app.config["SITE_TITLE"],
    }
    msg = _base_message(
        assertion.recipient_email, f"You have been awarded: {badge.name}"
    )
    msg.set_content(render_template("email/award.txt", **ctx))
    msg.add_alternative(render_template("email/award.html", **ctx), subtype="html")
    _send(msg)


def send_claim_confirmation(claim, confirm_url: str) -> None:
    """Send the 'confirm your badge' link for a self-service claim. Raises on failure."""
    badge = claim.badge
    ctx = {
        "badge": badge,
        "issuer": badge.issuer,
        "confirm_url": confirm_url,
        "expires_hours": current_app.config["CLAIM_EXPIRY_HOURS"],
        "site_title": current_app.config["SITE_TITLE"],
    }
    msg = _base_message(claim.email, f"Confirm your {badge.name} badge")
    msg.set_content(render_template("email/claim.txt", **ctx))
    msg.add_alternative(render_template("email/claim.html", **ctx), subtype="html")
    _send(msg)
