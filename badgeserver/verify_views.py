# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Public badge-verification page."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template, request

from .extensions import limiter
from .forms import VerifyForm
from .verify import verify

bp = Blueprint("verify", __name__)


@bp.route("/verify", methods=["GET", "POST"])
@limiter.limit(
    lambda: current_app.config.get("RATELIMIT_VERIFY", "12 per minute; 80 per hour"),
    # A bare GET only renders the form; a GET with ?url= runs the full check
    # (outbound fetches), so it is rate-limited exactly like the POST.
    exempt_when=lambda: request.method == "GET" and not request.args.get("url"),
)
def index():
    form = VerifyForm()
    result = None

    # A GET with ?url= pre-fills and runs the check (so links can be shared).
    prefill = request.args.get("url", "").strip()
    if request.method == "GET" and prefill:
        form.source.data = prefill
        result = verify(prefill, request.args.get("recipient"))
    elif form.validate_on_submit():
        result = verify(form.source.data, form.recipient.data)

    return render_template("verify.html", form=form, result=result)
