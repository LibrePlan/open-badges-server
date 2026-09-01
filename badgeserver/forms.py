# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Flask-WTF forms. CSRF protection is applied globally via ``CSRFProtect``."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    IntegerRangeField,
    PasswordField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    URL,
    DataRequired,
    Email,
    EqualTo,
    Length,
    NumberRange,
    Optional,
    Regexp,
)
from wtforms.widgets import RangeInput

from .models import BadgeClass

_IMAGE_EXT = ["png", "jpg", "jpeg", "webp", "gif"]
_LOGO_EXT = [*_IMAGE_EXT, "svg"]
_HEX_COLOUR = Regexp(
    r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$", message="Use a hex colour like #2b6cb0."
)


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Sign in")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired()])
    new_password = PasswordField(
        "New password", validators=[DataRequired(), Length(min=10, max=255)]
    )
    confirm = PasswordField(
        "Repeat new password",
        validators=[DataRequired(), EqualTo("new_password", "Passwords do not match.")],
    )
    submit = SubmitField("Change password")


class IssuerForm(FlaskForm):
    slug = StringField("Slug", validators=[Optional(), Length(max=64)])
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    url = StringField("Website URL", validators=[DataRequired(), URL(), Length(max=255)])
    email = StringField("Contact e-mail", validators=[DataRequired(), Email(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=4000)])
    image = FileField("Logo (optional)", validators=[FileAllowed(_IMAGE_EXT, "Images only.")])
    submit = SubmitField("Save issuer")


class BadgeClassForm(FlaskForm):
    slug = StringField("Slug", validators=[Optional(), Length(max=64)])
    name = StringField("Name", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField(
        "Description", validators=[DataRequired(), Length(max=4000)]
    )
    criteria_narrative = TextAreaField(
        "Criteria (what it is awarded for)", validators=[Optional(), Length(max=4000)]
    )
    criteria_url = StringField(
        "Criteria URL (optional)", validators=[Optional(), URL(), Length(max=255)]
    )
    tags = StringField("Tags (comma separated)", validators=[Optional(), Length(max=512)])

    art_mode = RadioField(
        "Badge image",
        choices=[("upload", "Upload a finished image"), ("compose", "Compose from a logo")],
        default="upload",
    )
    # used when art_mode == "upload"
    image = FileField(
        "Finished badge image", validators=[FileAllowed(_LOGO_EXT, "Images only.")]
    )
    # used when art_mode == "compose"
    logo = FileField("Logo", validators=[FileAllowed(_LOGO_EXT, "Images only.")])
    art_shape = SelectField(
        "Shape",
        choices=[(s, s.title()) for s in BadgeClass.ART_SHAPES],
        default="octagon",
    )
    art_bg = StringField(
        "Background colour", default=BadgeClass.ART_BG_DEFAULT, validators=[Optional(), _HEX_COLOUR]
    )
    art_accent = StringField(
        "Ring colour", default=BadgeClass.ART_ACCENT_DEFAULT, validators=[Optional(), _HEX_COLOUR]
    )
    art_logo_scale = IntegerRangeField(
        "Logo size",
        default=100,
        widget=RangeInput(step=5),
        validators=[Optional(), NumberRange(*BadgeClass.ART_LOGO_SCALE_RANGE)],
    )
    art_border_width = IntegerRangeField(
        "Border width",
        default=8,
        widget=RangeInput(step=1),
        validators=[Optional(), NumberRange(*BadgeClass.ART_BORDER_WIDTH_RANGE)],
    )
    art_logo_offset = IntegerRangeField(
        "Logo position",
        default=0,
        widget=RangeInput(step=1),
        validators=[Optional(), NumberRange(*BadgeClass.ART_LOGO_OFFSET_RANGE)],
    )
    art_title_offset = IntegerRangeField(
        "Title position",
        default=0,
        widget=RangeInput(step=1),
        validators=[Optional(), NumberRange(*BadgeClass.ART_TITLE_OFFSET_RANGE)],
    )

    submit = SubmitField("Save badge")


class NewBadgeClassForm(BadgeClassForm):
    """Same fields; on creation the view requires an image or a logo per mode."""


class AwardForm(FlaskForm):
    recipient_email = StringField(
        "Recipient e-mail", validators=[DataRequired(), Email(), Length(max=255)]
    )
    issued_on = DateField("Issued on", validators=[Optional()])
    evidence_url = StringField(
        "Evidence URL (optional)", validators=[Optional(), URL(), Length(max=255)]
    )
    narrative = TextAreaField("Note (optional)", validators=[Optional(), Length(max=4000)])
    send_email = BooleanField("Send an e-mail notification", default=True)
    submit = SubmitField("Award badge")


class AwardCsvForm(FlaskForm):
    file = FileField(
        "CSV file",
        validators=[FileRequired("Choose a CSV file."), FileAllowed(["csv", "txt"], "CSV only.")],
    )
    send_email = BooleanField("Send an e-mail notification to each recipient", default=True)
    submit = SubmitField("Award to all rows")


class RevokeForm(FlaskForm):
    reason = StringField("Reason", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Revoke")


class ConfirmForm(FlaskForm):
    """A bare form carrying only the CSRF token, for one-click POST actions."""

    submit = SubmitField("Confirm")
