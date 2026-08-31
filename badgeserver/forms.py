# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""Flask-WTF forms. CSRF protection is applied globally via ``CSRFProtect``."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    PasswordField,
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
    Optional,
)

_IMAGE_EXT = ["png", "jpg", "jpeg", "webp", "gif"]


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
    image = FileField("Badge image", validators=[FileAllowed(_IMAGE_EXT, "Images only.")])
    submit = SubmitField("Save badge")


class NewBadgeClassForm(BadgeClassForm):
    image = FileField(
        "Badge image",
        validators=[FileRequired("A badge image is required."), FileAllowed(_IMAGE_EXT, "Images only.")],
    )


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
