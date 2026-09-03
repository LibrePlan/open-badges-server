# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Self-service badge claiming (public, e-mail-confirmed)."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    url_for,
)
from flask_babel import gettext as _

from .extensions import db, limiter
from .forms import ClaimForm, ConfirmForm
from .issuing import AlreadyAwarded, award_badge, resend_email
from .mail import mail_configured, send_claim_confirmation
from .models import Assertion, BadgeClaim, BadgeClass

bp = Blueprint("claim", __name__)


def _claimable_or_404(slug: str) -> BadgeClass:
    if not current_app.config["SELF_SERVICE_ENABLED"]:
        abort(404)
    badge = db.session.get(BadgeClass, slug)
    if badge is None or not badge.self_service or badge.archived:
        abort(404)
    return badge


@bp.post("/b/<slug>/claim")
@limiter.limit(lambda: current_app.config["RATELIMIT_CLAIM"])
def claim(slug: str):
    badge = _claimable_or_404(slug)
    badge_page = url_for("public.badge_page", slug=slug)

    if not mail_configured():
        flash(_("Claiming this badge is unavailable right now."), "error")
        return redirect(badge_page)

    form = ClaimForm()
    if not form.validate_on_submit():
        for errors in form.errors.values():
            for err in errors:
                flash(err, "error")
        return redirect(badge_page)

    email = form.email.data.strip()
    # Everyone gets the same "check your e-mail" response, whether or not this
    # address already holds the badge -- so an anonymous visitor cannot use the
    # claim form to test who has a badge. A repeat holder simply lands back on
    # their existing assertion when they follow the link (award_badge raises
    # AlreadyAwarded, which the confirm step handles).
    now = datetime.now(timezone.utc)
    BadgeClaim.query.filter(
        BadgeClaim.confirmed_on.is_(None), BadgeClaim.expires_on < now
    ).delete(synchronize_session=False)
    BadgeClaim.query.filter_by(
        badge_slug=slug, email=email, confirmed_on=None
    ).delete(synchronize_session=False)

    entry = BadgeClaim.make(slug, email, current_app.config["CLAIM_EXPIRY_HOURS"])
    db.session.add(entry)
    db.session.commit()

    try:
        send_claim_confirmation(
            entry, url_for("claim.confirm", token=entry.token, _external=True)
        )
    except Exception as exc:  # noqa: BLE001 - report cleanly
        db.session.delete(entry)
        db.session.commit()
        current_app.logger.warning("Claim confirmation e-mail failed: %s", exc)
        flash(
            _("We could not send the confirmation e-mail. Please try again later."),
            "error",
        )
        return redirect(badge_page)

    return render_template(
        "claim_result.html", status="sent", badge=badge, email=_mask(email)
    )


def _pending_claim_or_response(token: str):
    """Return ``(entry, badge)`` for a still-pending claim, or a ready response.

    Handles the not-found / already-confirmed / expired / not-claimable cases
    the same way for both the GET landing page and the POST that awards.
    """
    entry = db.session.get(BadgeClaim, token)
    if entry is None:
        abort(404)
    if entry.confirmed_on and entry.assertion_uuid:
        return None, _no_store(
            redirect(url_for("public.assertion_page", uuid=entry.assertion_uuid))
        )
    if entry.expired:
        return None, _no_store(
            render_template("claim_result.html", status="expired", badge=entry.badge)
        )
    badge = entry.badge
    if badge is None or not badge.self_service:
        abort(404)
    return (entry, badge), None


@bp.get("/claim/<token>")
@limiter.limit("30 per minute")
def confirm(token: str):
    pending, response = _pending_claim_or_response(token)
    if response is not None:
        return response
    _entry, badge = pending
    return _no_store(
        render_template(
            "claim_confirm.html", badge=badge, token=token, form=ConfirmForm()
        )
    )


@bp.post("/claim/<token>")
@limiter.limit("20 per minute")
def confirm_submit(token: str):
    pending, response = _pending_claim_or_response(token)
    if response is not None:
        return response
    entry, badge = pending

    if not ConfirmForm().validate_on_submit():
        return _no_store(
            render_template(
                "claim_confirm.html", badge=badge, token=token, form=ConfirmForm()
            )
        )

    already_had = False
    try:
        assertion = award_badge(badge, entry.email, send_email=True).assertion
    except AlreadyAwarded as exc:
        assertion = exc.assertion
        already_had = True

    entry.confirmed_on = datetime.now(timezone.utc)
    entry.assertion_uuid = assertion.uuid
    db.session.commit()

    if already_had:
        # They had it already -- show when, and offer to re-send the notice.
        # This is only reachable via the confirmation link, so no address is
        # confirmed to anyone who does not already own the inbox.
        return _no_store(
            render_template(
                "claim_result.html", status="already", badge=badge,
                assertion=assertion, token=token, form=ConfirmForm(),
            )
        )

    flash(_("Badge confirmed — here it is."), "ok")
    return _no_store(redirect(url_for("public.assertion_page", uuid=assertion.uuid)))


@bp.post("/claim/<token>/resend")
@limiter.limit("5 per minute")
def confirm_resend(token: str):
    entry = db.session.get(BadgeClaim, token)
    if entry is None or not entry.assertion_uuid:
        abort(404)
    assertion = db.session.get(Assertion, entry.assertion_uuid)
    if (
        assertion is None
        or assertion.revoked
        or assertion.recipient_email != entry.email
    ):
        abort(404)
    if not ConfirmForm().validate_on_submit():
        abort(400)

    if not mail_configured():
        flash(_("E-mail is not configured on this server."), "error")
    else:
        try:
            resend_email(assertion)
            flash(_("Notification e-mail re-sent."), "ok")
        except Exception as exc:  # noqa: BLE001 - report cleanly
            current_app.logger.warning("Claim resend failed: %s", exc)
            flash(_("We could not send the e-mail. Please try again later."), "error")

    return _no_store(redirect(url_for("public.assertion_page", uuid=assertion.uuid)))


def _mask(email: str) -> str:
    local, sep, domain = email.partition("@")
    return f"{local[:1]}…@{domain}" if sep else "…"


def _no_store(response):
    response = make_response(response)
    response.headers["Cache-Control"] = "no-store"
    return response
