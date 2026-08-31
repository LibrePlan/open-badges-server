# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""The award-a-badge workflow: create the assertion, bake the PNG, notify."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import current_app

from .baking import bake_png
from .extensions import db
from .mail import mail_configured, send_award_email
from .models import Assertion, BadgeClass, new_salt, new_uuid
from .openbadges import assertion_id


@dataclass
class AwardResult:
    assertion: Assertion
    email_attempted: bool
    email_ok: bool
    email_error: str = ""


class AlreadyAwarded(Exception):
    def __init__(self, assertion: Assertion) -> None:
        super().__init__("This recipient already holds this badge.")
        self.assertion = assertion


def find_existing(badge: BadgeClass, email: str) -> Assertion | None:
    return badge.assertions.filter_by(recipient_email=email, revoked=False).first()


def _bake(assertion: Assertion) -> None:
    badge = assertion.badge
    src = os.path.join(current_app.config["UPLOAD_DIR"], badge.image_path)
    out_name = f"baked-{assertion.uuid}.png"
    out_path = os.path.join(current_app.config["UPLOAD_DIR"], out_name)
    bake_png(src, assertion_id(assertion.uuid), out_path)
    assertion.baked_png_path = out_name


def award_badge(
    badge: BadgeClass,
    email: str,
    *,
    issued_on: datetime | None = None,
    evidence_url: str = "",
    narrative: str = "",
    send_email: bool = True,
    allow_duplicate: bool = False,
) -> AwardResult:
    email = email.strip()
    if not allow_duplicate:
        existing = find_existing(badge, email)
        if existing is not None:
            raise AlreadyAwarded(existing)

    assertion = Assertion(
        uuid=new_uuid(),
        badge_slug=badge.slug,
        recipient_email=email,
        salt=new_salt(),
        issued_on=issued_on or datetime.now(timezone.utc),
        evidence_url=evidence_url.strip(),
        narrative=narrative.strip(),
    )
    db.session.add(assertion)
    db.session.flush()  # assign relationships / uuid before baking

    try:
        _bake(assertion)
    except Exception:  # noqa: BLE001 - baking must not lose the award
        current_app.logger.exception("Failed to bake PNG for assertion %s", assertion.uuid)

    db.session.commit()

    attempted = bool(send_email and mail_configured())
    ok = False
    err = ""
    if attempted:
        try:
            send_award_email(assertion)
            ok = True
            assertion.email_sent = True
            assertion.email_sent_at = datetime.now(timezone.utc)
            assertion.email_error = ""
        except Exception as exc:  # noqa: BLE001 - e-mail is best-effort
            err = f"{type(exc).__name__}: {exc}"
            assertion.email_error = err
            current_app.logger.warning(
                "Award e-mail to %s failed: %s", assertion.recipient_email, err
            )
        db.session.commit()

    return AwardResult(assertion=assertion, email_attempted=attempted, email_ok=ok, email_error=err)


def resend_email(assertion: Assertion) -> None:
    """Re-send the notification for an existing assertion. Raises on failure."""
    send_award_email(assertion)
    assertion.email_sent = True
    assertion.email_sent_at = datetime.now(timezone.utc)
    assertion.email_error = ""
    db.session.commit()
