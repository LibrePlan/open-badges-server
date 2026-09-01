# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Authenticated admin views."""

from __future__ import annotations

import csv as csvmod
import io
import os
from datetime import datetime, time, timezone

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db, limiter
from .forms import (
    AwardCsvForm,
    AwardForm,
    BadgeClassForm,
    ChangePasswordForm,
    ConfirmForm,
    IssuerForm,
    LoginForm,
    NewBadgeClassForm,
    RevokeForm,
)
from . import images
from .badgeart import compose_badge
from .images import ImageError, save_square_png
from .issuing import AlreadyAwarded, award_badge, resend_email
from .mail import mail_configured
from .models import AdminUser, Assertion, BadgeClass, Issuer, slugify
from .openbadges import assertion_id as assertion_public_id

bp = Blueprint("admin", __name__)


@bp.before_request
def _require_login():
    if request.endpoint in {"admin.login", "admin.static"}:
        return None
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    return None


# --- helpers --------------------------------------------------------------


def _unique_slug(model, desired: str, *, current: str | None = None) -> str:
    base = slugify(desired)
    candidate = base
    n = 2
    while candidate != current and db.session.get(model, candidate) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _sole_issuer() -> Issuer | None:
    return Issuer.query.order_by(Issuer.created_on).first()


def _upload_dir() -> str:
    return current_app.config["UPLOAD_DIR"]


def _image_size() -> int:
    return current_app.config["BADGE_IMAGE_SIZE"]


def _write_upload(data: bytes, filename: str) -> str:
    with open(os.path.join(_upload_dir(), filename), "wb") as fh:
        fh.write(data)
    return filename


def _store_image(file_storage, filename: str) -> str:
    raw = file_storage.read()
    if not raw:
        raise ImageError("The uploaded file is empty.")
    save_square_png(raw, os.path.join(_upload_dir(), filename), size=_image_size())
    return filename


def _as_utc_datetime(d) -> datetime | None:
    if not d:
        return None
    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)


# --- auth ----------------------------------------------------------------


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["RATELIMIT_LOGIN"], methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(username=form.username.data.strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            current_app.logger.info("Admin %s signed in", user.username)
            nxt = request.args.get("next", "")
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("admin.dashboard"))
        flash("Incorrect username or password.", "error")
    return render_template("admin/login.html", form=form)


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "ok")
    return redirect(url_for("public.index"))


# --- dashboard ---------------------------------------------------------


@bp.get("/")
def dashboard():
    stats = {
        "badges": BadgeClass.query.count(),
        "active_badges": BadgeClass.query.filter_by(archived=False).count(),
        "assertions": Assertion.query.filter_by(revoked=False).count(),
        "revoked": Assertion.query.filter_by(revoked=True).count(),
    }
    recent = Assertion.query.order_by(Assertion.created_on.desc()).limit(10).all()
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent=recent,
        issuer=_sole_issuer(),
        mail_ready=mail_configured(),
    )


# --- issuer ----------------------------------------------------------


@bp.route("/issuer", methods=["GET", "POST"])
def issuer():
    obj = _sole_issuer()
    form = IssuerForm(obj=obj)
    if form.validate_on_submit():
        try:
            if obj is None:
                slug = _unique_slug(Issuer, form.slug.data or form.name.data)
                obj = Issuer(slug=slug)
                db.session.add(obj)
            obj.name = form.name.data.strip()
            obj.url = form.url.data.strip()
            obj.email = form.email.data.strip()
            obj.description = (form.description.data or "").strip()
            if form.image.data:
                obj.image_path = _store_image(form.image.data, f"issuer-{obj.slug}.png")
            db.session.commit()
            flash("Issuer saved.", "ok")
            return redirect(url_for("admin.issuer"))
        except ImageError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/issuer.html", form=form, issuer=obj)


# --- badge classes -------------------------------------------------


@bp.get("/badges")
def badges():
    items = BadgeClass.query.order_by(BadgeClass.archived, BadgeClass.name).all()
    return render_template("admin/badges.html", badges=items)


@bp.route("/badges/new", methods=["GET", "POST"])
def badge_new():
    if _sole_issuer() is None:
        flash("Create the issuer profile first.", "error")
        return redirect(url_for("admin.issuer"))
    form = NewBadgeClassForm()
    if form.validate_on_submit():
        try:
            slug = _unique_slug(BadgeClass, form.slug.data or form.name.data)
            badge = BadgeClass(slug=slug, issuer_slug=_sole_issuer().slug)
            _apply_badge_form(badge, form, image_required=True)
            db.session.add(badge)
            db.session.commit()
            flash(f"Badge “{badge.name}” created.", "ok")
            return redirect(url_for("admin.badges"))
        except ImageError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/badge_form.html", form=form, badge=None)


@bp.route("/badges/<slug>/edit", methods=["GET", "POST"])
def badge_edit(slug: str):
    badge = db.session.get(BadgeClass, slug) or abort(404)
    form = BadgeClassForm(obj=badge)
    if request.method == "GET":
        form.tags.data = badge.tags
        form.art_mode.data = "compose" if badge.composed else "upload"
        form.art_bg.data = badge.art_bg or BadgeClass.ART_BG_DEFAULT
        form.art_accent.data = badge.art_accent or BadgeClass.ART_ACCENT_DEFAULT
        form.art_logo_scale.data = badge.art_logo_scale
        form.art_border_width.data = badge.art_border_width
        form.art_logo_offset.data = badge.art_logo_offset
        form.art_title_offset.data = badge.art_title_offset
    if form.validate_on_submit():
        try:
            _apply_badge_form(badge, form, image_required=False)
            db.session.commit()
            flash("Badge updated.", "ok")
            return redirect(url_for("admin.badges"))
        except ImageError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("admin/badge_form.html", form=form, badge=badge)


def _apply_badge_form(badge: BadgeClass, form: BadgeClassForm, *, image_required: bool) -> None:
    badge.name = form.name.data.strip()
    badge.description = form.description.data.strip()
    badge.criteria_narrative = (form.criteria_narrative.data or "").strip()
    badge.criteria_url = (form.criteria_url.data or "").strip()
    badge.tags = BadgeClass.normalise_tags(form.tags.data or "")

    if form.art_mode.data == "compose":
        _apply_compose(badge, form)
    else:
        if form.image.data:
            badge.image_path = _store_image(form.image.data, f"badge-{badge.slug}.png")
        elif image_required and not badge.image_path:
            raise ImageError("A badge image is required.")
        badge.logo_path = None
        badge.art_bg = badge.art_accent = ""


def _apply_compose(badge: BadgeClass, form: BadgeClassForm) -> None:
    size = _image_size()
    if form.logo.data:
        png = images.rasterize_to_png(form.logo.data.read(), size)
        badge.logo_path = _write_upload(png, f"logo-{badge.slug}.png")
    if not badge.logo_path:
        raise ImageError("Upload a logo to compose a badge.")

    badge.art_shape = (
        form.art_shape.data if form.art_shape.data in BadgeClass.ART_SHAPES else "octagon"
    )
    badge.art_bg = (form.art_bg.data or BadgeClass.ART_BG_DEFAULT).strip()
    badge.art_accent = (form.art_accent.data or BadgeClass.ART_ACCENT_DEFAULT).strip()
    badge.art_logo_scale = _clamp(
        form.art_logo_scale.data, BadgeClass.ART_LOGO_SCALE_RANGE, 100
    )
    badge.art_border_width = _clamp(
        form.art_border_width.data, BadgeClass.ART_BORDER_WIDTH_RANGE, 8
    )
    badge.art_logo_offset = _clamp(
        form.art_logo_offset.data, BadgeClass.ART_LOGO_OFFSET_RANGE, 0
    )
    badge.art_title_offset = _clamp(
        form.art_title_offset.data, BadgeClass.ART_TITLE_OFFSET_RANGE, 0
    )

    with open(os.path.join(_upload_dir(), badge.logo_path), "rb") as fh:
        logo_png = fh.read()
    compose_badge(
        logo_png,
        badge.name,
        shape=badge.art_shape,
        bg=badge.art_bg,
        accent=badge.art_accent,
        size=size,
        dest_path=os.path.join(_upload_dir(), f"badge-{badge.slug}.png"),
        logo_scale=badge.art_logo_scale / 100,
        border_width=badge.art_border_width,
        logo_offset=badge.art_logo_offset,
        title_offset=badge.art_title_offset,
    )
    badge.image_path = f"badge-{badge.slug}.png"


def _clamp(value, bounds: tuple[int, int], default: int) -> int:
    lo, hi = bounds
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _placeholder_logo() -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [24, 24, 216, 216], radius=28, fill=(255, 255, 255, 90)
    )
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@bp.post("/badges/preview")
def badge_preview():
    """Render a composed badge for the live form preview. Saves nothing."""
    from io import BytesIO

    from .badgeart import render_badge

    data = request.form
    scale = _clamp(data.get("art_logo_scale"), BadgeClass.ART_LOGO_SCALE_RANGE, 100)
    border = _clamp(data.get("art_border_width"), BadgeClass.ART_BORDER_WIDTH_RANGE, 8)
    logo_off = _clamp(data.get("art_logo_offset"), BadgeClass.ART_LOGO_OFFSET_RANGE, 0)
    title_off = _clamp(data.get("art_title_offset"), BadgeClass.ART_TITLE_OFFSET_RANGE, 0)

    logo_png = None
    upload = request.files.get("logo")
    if upload and upload.filename:
        try:
            logo_png = images.rasterize_to_png(upload.read(), 320)
        except ImageError:
            logo_png = None
    if logo_png is None and data.get("slug", "").strip():
        badge = db.session.get(BadgeClass, data["slug"].strip())
        if badge and badge.logo_path:
            path = os.path.join(_upload_dir(), badge.logo_path)
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    logo_png = fh.read()
    if logo_png is None:
        logo_png = _placeholder_logo()

    try:
        image = render_badge(
            logo_png,
            data.get("name", ""),
            shape=data.get("art_shape", "octagon"),
            bg=data.get("art_bg") or BadgeClass.ART_BG_DEFAULT,
            accent=data.get("art_accent") or BadgeClass.ART_ACCENT_DEFAULT,
            size=320,
            logo_scale=scale / 100,
            border_width=border,
            logo_offset=logo_off,
            title_offset=title_off,
        )
    except Exception:  # noqa: BLE001 - preview must never 500
        return Response("preview unavailable", status=422, mimetype="text/plain")

    buf = BytesIO()
    image.save(buf, "PNG")
    resp = Response(buf.getvalue(), mimetype="image/png")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/badges/<slug>/archive")
def badge_archive(slug: str):
    badge = db.session.get(BadgeClass, slug) or abort(404)
    badge.archived = not badge.archived
    db.session.commit()
    flash(("Badge archived." if badge.archived else "Badge un-archived."), "ok")
    return redirect(url_for("admin.badges"))


# --- awarding --------------------------------------------------------


@bp.route("/badges/<slug>/award", methods=["GET", "POST"])
def award(slug: str):
    badge = db.session.get(BadgeClass, slug) or abort(404)
    form = AwardForm()
    if form.validate_on_submit():
        try:
            result = award_badge(
                badge,
                form.recipient_email.data,
                issued_on=_as_utc_datetime(form.issued_on.data),
                evidence_url=form.evidence_url.data or "",
                narrative=form.narrative.data or "",
                send_email=form.send_email.data,
            )
        except AlreadyAwarded as exc:
            flash(
                f"That recipient already holds this badge "
                f"(assertion {exc.assertion.uuid}).",
                "error",
            )
            return redirect(url_for("admin.award", slug=slug))
        msg = f"Badge awarded to {result.assertion.recipient_email}."
        category = "ok"
        if result.email_attempted and result.email_ok:
            msg += " Notification e-mail sent."
        elif result.email_attempted:
            msg += f" Notification e-mail failed: {result.email_error}"
            category = "error"
        flash(msg, category)
        return redirect(url_for("admin.assertion_detail", uuid=result.assertion.uuid))
    return render_template(
        "admin/award.html", form=form, badge=badge, mail_ready=mail_configured()
    )


@bp.route("/badges/<slug>/award-csv", methods=["GET", "POST"])
def award_csv(slug: str):
    badge = db.session.get(BadgeClass, slug) or abort(404)
    form = AwardCsvForm()
    results: list[dict] = []
    if form.validate_on_submit():
        raw = form.file.data.read().decode("utf-8-sig", errors="replace")
        emails = _extract_emails(raw)
        cap = current_app.config["CSV_AWARD_MAX_ROWS"]
        if len(emails) > cap:
            flash(f"CSV has {len(emails)} addresses; the limit is {cap}.", "error")
        else:
            for email in emails:
                results.append(_award_one_csv_row(badge, email, form.send_email.data))
            ok = sum(1 for r in results if r["status"] == "awarded")
            flash(f"Processed {len(results)} rows: {ok} awarded.", "ok")
    return render_template(
        "admin/award_csv.html",
        form=form,
        badge=badge,
        results=results,
        mail_ready=mail_configured(),
    )


def _extract_emails(text: str) -> list[str]:
    out: list[str] = []
    for row in csvmod.reader(io.StringIO(text)):
        for cell in row:
            cell = cell.strip()
            if "@" in cell and "." in cell.split("@")[-1]:
                out.append(cell)
                break
    # de-duplicate, preserve order
    seen: set[str] = set()
    return [e for e in out if not (e.lower() in seen or seen.add(e.lower()))]


def _award_one_csv_row(badge: BadgeClass, email: str, send_email: bool) -> dict:
    try:
        result = award_badge(badge, email, send_email=send_email)
    except AlreadyAwarded:
        return {"email": email, "status": "skipped", "detail": "already holds this badge"}
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        return {"email": email, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}
    detail = ""
    if result.email_attempted and not result.email_ok:
        detail = f"awarded, e-mail failed: {result.email_error}"
    elif result.email_attempted:
        detail = "awarded, e-mail sent"
    else:
        detail = "awarded"
    return {"email": email, "status": "awarded", "detail": detail, "uuid": result.assertion.uuid}


# --- assertions ------------------------------------------------------


@bp.get("/assertions")
def assertions():
    q = Assertion.query
    badge_slug = request.args.get("badge", "").strip()
    email = request.args.get("email", "").strip()
    status = request.args.get("status", "").strip()
    if badge_slug:
        q = q.filter_by(badge_slug=badge_slug)
    if email:
        q = q.filter(Assertion.recipient_email.ilike(f"%{email}%"))
    if status == "revoked":
        q = q.filter_by(revoked=True)
    elif status == "active":
        q = q.filter_by(revoked=False)
    items = q.order_by(Assertion.created_on.desc()).limit(500).all()
    return render_template(
        "admin/assertions.html",
        items=items,
        all_badges=BadgeClass.query.order_by(BadgeClass.name).all(),
        filters={"badge": badge_slug, "email": email, "status": status},
    )


@bp.get("/assertions/<uuid>")
def assertion_detail(uuid: str):
    assertion = db.session.get(Assertion, uuid) or abort(404)
    json_url = assertion_public_id(assertion.uuid)
    return render_template(
        "admin/assertion_detail.html",
        assertion=assertion,
        badge=assertion.badge,
        json_url=json_url,
        page_url=json_url.removesuffix(".json"),
        revoke_form=RevokeForm(),
        confirm_form=ConfirmForm(),
        mail_ready=mail_configured(),
    )


@bp.post("/assertions/<uuid>/revoke")
def assertion_revoke(uuid: str):
    assertion = db.session.get(Assertion, uuid) or abort(404)
    form = RevokeForm()
    if form.validate_on_submit():
        assertion.revoked = True
        assertion.revocation_reason = form.reason.data.strip()
        db.session.commit()
        flash("Assertion revoked.", "ok")
    else:
        flash("A reason is required to revoke.", "error")
    return redirect(url_for("admin.assertion_detail", uuid=uuid))


@bp.post("/assertions/<uuid>/unrevoke")
def assertion_unrevoke(uuid: str):
    assertion = db.session.get(Assertion, uuid) or abort(404)
    assertion.revoked = False
    assertion.revocation_reason = ""
    db.session.commit()
    flash("Assertion re-instated.", "ok")
    return redirect(url_for("admin.assertion_detail", uuid=uuid))


@bp.post("/assertions/<uuid>/resend-email")
def assertion_resend(uuid: str):
    assertion = db.session.get(Assertion, uuid) or abort(404)
    if not mail_configured():
        flash("SMTP is not configured.", "error")
    else:
        try:
            resend_email(assertion)
            flash("Notification e-mail re-sent.", "ok")
        except Exception as exc:  # noqa: BLE001
            assertion.email_error = f"{type(exc).__name__}: {exc}"
            db.session.commit()
            flash(f"Re-send failed: {assertion.email_error}", "error")
    return redirect(url_for("admin.assertion_detail", uuid=uuid))


# --- account --------------------------------------------------------


@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("Current password is incorrect.", "error")
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            flash("Password changed.", "ok")
            return redirect(url_for("admin.dashboard"))
    return render_template("admin/change_password.html", form=form)
