# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>

from __future__ import annotations

import hashlib

from badgeserver.extensions import db
from badgeserver.models import Assertion, BadgeClass


def _make_badge(app):
    with app.app_context():
        badge = BadgeClass(
            slug="tester",
            issuer_slug="main",
            name="Tester",
            description="For testing.",
            image_path="badge-tester.png",
            criteria_narrative="Run the tests.",
        )
        db.session.add(badge)
        db.session.commit()
        # a real image so baking works
        from PIL import Image

        import os

        Image.new("RGBA", (64, 64), (10, 10, 10, 255)).save(
            os.path.join(app.config["UPLOAD_DIR"], "badge-tester.png"), "PNG"
        )


def test_public_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/nope").status_code == 404


def test_issuer_json(client):
    doc = client.get("/issuer/main.json").get_json()
    assert doc["@context"] == "https://w3id.org/openbadges/v2"
    assert doc["type"] == "Issuer"
    assert doc["id"] == "https://badges.test/issuer/main.json"
    assert doc["email"] == "badges@example.com"


def test_badgeclass_json(app, client):
    _make_badge(app)
    doc = client.get("/b/tester.json").get_json()
    assert doc["type"] == "BadgeClass"
    assert doc["id"] == "https://badges.test/b/tester.json"
    assert doc["issuer"] == "https://badges.test/issuer/main.json"
    assert doc["image"] == "https://badges.test/b/tester/image"


def test_award_flow_and_hash(app):
    _make_badge(app)
    with app.app_context():
        from badgeserver.issuing import award_badge

        badge = db.session.get(BadgeClass, "tester")
        result = award_badge(badge, "person@example.com", send_email=False)
        uuid = result.assertion.uuid
        salt = result.assertion.salt

    doc = app.test_client().get(f"/a/{uuid}.json").get_json()
    assert doc["type"] == "Assertion"
    assert doc["verification"] == {"type": "hosted"}
    assert doc["badge"] == "https://badges.test/b/tester.json"
    expected = "sha256$" + hashlib.sha256(f"person@example.com{salt}".encode()).hexdigest()
    assert doc["recipient"]["identity"] == expected
    assert doc["recipient"]["hashed"] is True
    assert "person@example.com" not in app.test_client().get(f"/a/{uuid}.json").text


def test_revocation(app, auth_client):
    _make_badge(app)
    with app.app_context():
        from badgeserver.issuing import award_badge

        badge = db.session.get(BadgeClass, "tester")
        uuid = award_badge(badge, "revoke@example.com", send_email=False).assertion.uuid

    r = auth_client.post(f"/admin/assertions/{uuid}/revoke", data={"reason": "mistake"})
    assert r.status_code in (302, 200)
    doc = auth_client.get(f"/a/{uuid}.json").get_json()
    assert doc["revoked"] is True
    assert doc["revocationReason"] == "mistake"


def test_baked_png_contains_url(app):
    _make_badge(app)
    with app.app_context():
        from badgeserver.issuing import award_badge

        badge = db.session.get(BadgeClass, "tester")
        uuid = award_badge(badge, "bake@example.com", send_email=False).assertion.uuid

    png = app.test_client().get(f"/a/{uuid}/badge.png").data
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(png)) as img:
        assert img.text["openbadges"] == f"https://badges.test/a/{uuid}.json"


def test_admin_requires_login(client):
    r = client.get("/admin/", follow_redirects=False)
    assert r.status_code == 302
    assert "/admin/login" in r.headers["Location"]


def test_login_and_dashboard(auth_client):
    assert auth_client.get("/admin/").status_code == 200


def test_csrf_enforced(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    c.post("/admin/login", data={"username": "admin", "password": "correct-horse-battery"})
    # no token -> rejected
    r = c.post("/admin/change-password", data={})
    assert r.status_code == 400
