# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""Public, unauthenticated views: browse pages, Open Badges JSON, images."""

from __future__ import annotations

import io
import os

import qrcode
from flask import Blueprint, Response, abort, current_app, json, render_template, send_from_directory

from .extensions import db, limiter
from .models import Assertion, BadgeClass, Issuer
from .openbadges import assertion_json, badgeclass_json, issuer_json

bp = Blueprint("public", __name__)
limiter.exempt(bp)


def _json(payload: dict, status: int = 200) -> Response:
    resp = current_app.response_class(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        status=status,
        mimetype="application/json",
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


def _uploads_dir() -> str:
    return current_app.config["UPLOAD_DIR"]


def _get_badge_or_404(slug: str) -> BadgeClass:
    badge = db.session.get(BadgeClass, slug)
    if badge is None:
        abort(404)
    return badge


def _get_assertion_or_404(uuid: str) -> Assertion:
    assertion = db.session.get(Assertion, uuid)
    if assertion is None:
        abort(404)
    return assertion


@bp.get("/")
def index():
    issuer = Issuer.query.order_by(Issuer.created_on).first()
    badges = (
        BadgeClass.query.filter_by(archived=False).order_by(BadgeClass.name).all()
        if issuer
        else []
    )
    return render_template("index.html", issuer=issuer, badges=badges)


@bp.get("/healthz")
def healthz():
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}


# --- Issuer -----------------------------------------------------------------


@bp.get("/issuer/<slug>.json")
def issuer_doc(slug: str):
    issuer = db.session.get(Issuer, slug)
    if issuer is None:
        abort(404)
    return _json(issuer_json(issuer))


@bp.get("/issuer/<slug>/image")
def issuer_image(slug: str):
    issuer = db.session.get(Issuer, slug)
    if issuer is None or not issuer.image_path:
        abort(404)
    return send_from_directory(_uploads_dir(), issuer.image_path, max_age=3600)


# --- Badge classes --------------------------------------------------------


@bp.get("/b/<slug>.json")
def badge_doc(slug: str):
    return _json(badgeclass_json(_get_badge_or_404(slug)))


@bp.get("/b/<slug>/image")
def badge_image(slug: str):
    badge = _get_badge_or_404(slug)
    return send_from_directory(_uploads_dir(), badge.image_path, max_age=3600)


@bp.get("/b/<slug>")
def badge_page(slug: str):
    badge = _get_badge_or_404(slug)
    awarded = badge.assertions.filter_by(revoked=False).count()
    return render_template("badge.html", badge=badge, awarded=awarded)


# --- Assertions ---------------------------------------------------------


@bp.get("/a/<uuid>.json")
def assertion_doc(uuid: str):
    return _json(assertion_json(_get_assertion_or_404(uuid)))


@bp.get("/a/<uuid>/badge.png")
def assertion_badge_png(uuid: str):
    assertion = _get_assertion_or_404(uuid)
    if not assertion.baked_png_path or not os.path.exists(
        os.path.join(_uploads_dir(), assertion.baked_png_path)
    ):
        # Fall back to the unbaked badge-class image.
        return send_from_directory(_uploads_dir(), assertion.badge.image_path, max_age=0)
    return send_from_directory(
        _uploads_dir(),
        assertion.baked_png_path,
        max_age=3600,
        download_name=f"{assertion.badge_slug}.png",
    )


@bp.get("/a/<uuid>/qr.png")
def assertion_qr(uuid: str):
    _get_assertion_or_404(uuid)
    from .openbadges import assertion_id

    target = assertion_id(uuid).removesuffix(".json")
    img = qrcode.make(target, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype="image/png")


@bp.get("/a/<uuid>")
def assertion_page(uuid: str):
    assertion = _get_assertion_or_404(uuid)
    return render_template("assertion.html", assertion=assertion, badge=assertion.badge)
