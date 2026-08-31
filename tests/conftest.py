# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>

from __future__ import annotations

import pytest

from badgeserver import create_app
from badgeserver.extensions import db
from badgeserver.models import AdminUser, Issuer


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "EXTERNAL_URL": "https://badges.test",
            "WTF_CSRF_ENABLED": False,
            "SESSION_COOKIE_SECURE": False,
            "MAIL_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        },
        data_dir=str(tmp_path),
    )
    with application.app_context():
        db.create_all()
        issuer = Issuer(
            slug="main",
            name="Test Org",
            url="https://example.com",
            email="badges@example.com",
        )
        admin = AdminUser(username="admin")
        admin.set_password("correct-horse-battery")
        db.session.add_all([issuer, admin])
        db.session.commit()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app):
    c = app.test_client()
    c.post("/admin/login", data={"username": "admin", "password": "correct-horse-battery"})
    return c


@pytest.fixture
def sample_png():
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", (200, 200), (40, 120, 200, 255)).save(buf, "PNG")
    buf.seek(0)
    return buf
