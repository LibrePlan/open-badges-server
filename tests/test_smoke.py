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


# --- composed badges -------------------------------------------------------


def _png_bytes(w=120, h=90):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", (w, h), (200, 80, 40, 255)).save(buf, "PNG")
    buf.seek(0)
    return buf


def _compose(auth_client, **overrides):
    data = {
        "name": "Release Manager",
        "description": "Ships releases.",
        "art_mode": "compose",
        "art_shape": "shield",
        "art_bg": "#1f6f43",
        "art_accent": "#d4af37",
        "logo": (_png_bytes(), "logo.png"),
        "submit": "Save badge",
    }
    data.update(overrides)
    return auth_client.post(
        "/admin/badges/new", data=data, content_type="multipart/form-data",
        follow_redirects=True,
    )


def test_compose_badge(app, auth_client):
    assert _compose(auth_client, art_shape="hexagon").status_code == 200
    with app.app_context():
        badge = db.session.get(BadgeClass, "release-manager")
        assert badge.composed and badge.art_shape == "hexagon"
        assert badge.art_bg == "#1f6f43" and badge.logo_path

    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(auth_client.get("/b/release-manager/image").data))
    assert img.format == "PNG" and img.size == (app.config["BADGE_IMAGE_SIZE"],) * 2
    assert auth_client.get("/b/release-manager/logo").status_code == 200


def test_compose_rerenders_on_rename(app, auth_client):
    _compose(auth_client)
    import os

    path = os.path.join(app.config["UPLOAD_DIR"], "badge-release-manager.png")
    before = open(path, "rb").read()
    r = auth_client.post(
        "/admin/badges/release-manager/edit",
        data={
            "name": "Release Wrangler", "description": "Ships releases.",
            "art_mode": "compose", "art_shape": "octagon",
            "art_bg": "#1f6f43", "art_accent": "#d4af37", "submit": "Save badge",
        },
        content_type="multipart/form-data", follow_redirects=True,
    )
    assert r.status_code == 200
    assert open(path, "rb").read() != before


def test_compose_to_upload_switch_clears_logo(app, auth_client):
    _compose(auth_client)
    auth_client.post(
        "/admin/badges/release-manager/edit",
        data={
            "name": "Release Manager", "description": "d", "art_mode": "upload",
            "art_bg": "#1f6f43", "art_accent": "#d4af37",
            "image": (_png_bytes(256, 256), "final.png"), "submit": "Save badge",
        },
        content_type="multipart/form-data", follow_redirects=True,
    )
    with app.app_context():
        badge = db.session.get(BadgeClass, "release-manager")
        assert not badge.composed and badge.logo_path is None


def test_award_composed_badge_bakes(app, auth_client):
    _compose(auth_client)
    with app.app_context():
        from badgeserver.issuing import award_badge

        badge = db.session.get(BadgeClass, "release-manager")
        uuid = award_badge(badge, "r@example.com", send_email=False).assertion.uuid

    from io import BytesIO

    from PIL import Image

    png = auth_client.get(f"/a/{uuid}/badge.png").data
    with Image.open(BytesIO(png)) as img:
        assert img.text["openbadges"] == f"https://badges.test/a/{uuid}.json"


def test_logo_scale_changes_image(app, auth_client):
    import os

    _compose(auth_client, name="Small", art_shape="octagon", art_logo_scale="60")
    _compose(auth_client, name="Big", art_shape="octagon", art_logo_scale="150")
    updir = app.config["UPLOAD_DIR"]
    small = open(os.path.join(updir, "badge-small.png"), "rb").read()
    big = open(os.path.join(updir, "badge-big.png"), "rb").read()
    assert small != big
    with app.app_context():
        assert db.session.get(BadgeClass, "small").art_logo_scale == 60


def test_border_width_changes_image(app, auth_client):
    import os

    _compose(auth_client, name="Thin", art_shape="octagon", art_border_width="0")
    _compose(auth_client, name="Thick", art_shape="octagon", art_border_width="30")
    updir = app.config["UPLOAD_DIR"]
    thin = open(os.path.join(updir, "badge-thin.png"), "rb").read()
    thick = open(os.path.join(updir, "badge-thick.png"), "rb").read()
    assert thin != thick
    with app.app_context():
        assert db.session.get(BadgeClass, "thin").art_border_width == 0
        assert db.session.get(BadgeClass, "thick").art_border_width == 30


def test_position_offsets_change_image(app, auth_client):
    import os

    _compose(auth_client, name="Centered", art_shape="octagon")
    _compose(
        auth_client, name="Shifted", art_shape="octagon",
        art_logo_offset="15", art_title_offset="-15", art_logo_scale="200",
    )
    updir = app.config["UPLOAD_DIR"]
    a = open(os.path.join(updir, "badge-centered.png"), "rb").read()
    b = open(os.path.join(updir, "badge-shifted.png"), "rb").read()
    assert a != b
    with app.app_context():
        s = db.session.get(BadgeClass, "shifted")
        assert (s.art_logo_offset, s.art_title_offset, s.art_logo_scale) == (15, -15, 200)


def test_preview_endpoint(app, auth_client, client):
    r = auth_client.post(
        "/admin/badges/preview",
        data={
            "name": "Preview", "art_shape": "shield", "art_bg": "#1f6f43",
            "art_accent": "#d4af37", "art_logo_scale": "120",
            "logo": (_png_bytes(), "logo.png"),
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png" and len(r.data) > 500

    # not logged in -> redirected to login
    assert client.post(
        "/admin/badges/preview", data={"name": "x"}, content_type="multipart/form-data"
    ).status_code == 302


def test_preview_falls_back_to_stored_logo(app, auth_client):
    _compose(auth_client, name="Stored")
    r = auth_client.post(
        "/admin/badges/preview",
        data={
            "name": "Stored", "slug": "stored", "art_shape": "circle",
            "art_bg": "#2b6cb0", "art_accent": "#b0872b", "art_logo_scale": "100",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/png"


def test_svg_finished_upload(app, auth_client):
    import pytest

    pytest.importorskip("cairosvg")
    svg = (
        b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
        b'width="100" height="100"><circle cx="50" cy="50" r="40" fill="#369"/></svg>'
    )
    from io import BytesIO

    r = auth_client.post(
        "/admin/badges/new",
        data={
            "name": "Vector Badge", "description": "d", "art_mode": "upload",
            "image": (BytesIO(svg), "art.svg"), "submit": "Save badge",
        },
        content_type="multipart/form-data", follow_redirects=True,
    )
    assert r.status_code == 200
    from PIL import Image

    img = Image.open(BytesIO(auth_client.get("/b/vector-badge/image").data))
    assert img.format == "PNG"


# --- badge verification --------------------------------------------------


def _award_local(app, auth_client, email="alice@example.com"):
    _compose(auth_client, name="Verified", art_shape="circle")
    with app.app_context():
        from badgeserver.issuing import award_badge

        badge = db.session.get(BadgeClass, "verified")
        return award_badge(badge, email, send_email=False).assertion.uuid


def test_verify_local_valid(app, auth_client):
    uuid = _award_local(app, auth_client)
    with app.app_context():
        from badgeserver.verify import verify

        r = verify(f"{app.config['EXTERNAL_URL']}/a/{uuid}")
        assert r.verdict == "valid" and r.issued_by_us
        assert r.badge["name"] == "Verified"
        assert verify(f"{app.config['EXTERNAL_URL']}/a/{uuid}", "alice@example.com").recipient_match is True
        assert verify(f"{app.config['EXTERNAL_URL']}/a/{uuid}", "bob@example.com").recipient_match is False


def test_verify_local_revoked_and_unknown(app, auth_client):
    uuid = _award_local(app, auth_client)
    with app.app_context():
        from badgeserver.verify import verify

        db.session.get(Assertion, uuid).revoked = True
        db.session.commit()
        assert verify(f"{app.config['EXTERNAL_URL']}/a/{uuid}").verdict == "revoked"
        assert verify(f"{app.config['EXTERNAL_URL']}/a/00000000-0000-0000-0000-000000000000").verdict == "invalid"


def test_verify_ssrf_and_garbage(app):
    with app.app_context():
        from badgeserver.verify import VerifyError, check_url_allowed, verify

        for bad in ("http://127.0.0.1/", "http://169.254.169.254/", "http://[::1]/", "file:///etc/passwd"):
            try:
                check_url_allowed(bad)
                raise AssertionError(f"{bad} should be blocked")
            except VerifyError:
                pass
        assert verify("hello world").verdict == "invalid"
        assert verify("").verdict == "invalid"
        assert verify(
            '{"@context":"https://www.w3.org/ns/credentials/v2",'
            '"type":["VerifiableCredential","OpenBadgeCredential"]}'
        ).verdict == "unsupported"


def test_verify_external_hosted(app, monkeypatch):
    import json

    import badgeserver.verify as V

    docs = {
        "https://acme.test/i.json": {
            "@context": V_CONTEXT, "type": "Issuer", "id": "https://acme.test/i.json",
            "name": "Acme", "url": "https://acme.test", "email": "b@acme.test",
        },
        "https://acme.test/b.json": {
            "@context": V_CONTEXT, "type": "BadgeClass", "id": "https://acme.test/b.json",
            "name": "Widget Master", "description": "d", "image": "https://acme.test/b.png",
            "issuer": "https://acme.test/i.json",
        },
        "https://acme.test/a/1.json": {
            "@context": V_CONTEXT, "type": "Assertion", "id": "https://acme.test/a/1.json",
            "recipient": {"type": "email", "hashed": False, "identity": "u@acme.test"},
            "badge": "https://acme.test/b.json", "issuedOn": "2026-01-02T00:00:00+00:00",
            "verification": {"type": "hosted"},
        },
    }
    monkeypatch.setattr(V, "check_url_allowed", lambda u: None)
    monkeypatch.setattr(V, "_fetch", lambda url, *, max_bytes: (json.dumps(docs[url]).encode(), "application/json"))
    with app.app_context():
        r = V.verify("https://acme.test/a/1.json")
        assert r.verdict == "valid" and not r.issued_by_us and r.issuer["name"] == "Acme"
        assert V.verify("https://acme.test/a/1.json", "u@acme.test").recipient_match is True
        # served from a URL that isn't its id
        docs["https://evil.test/x.json"] = docs["https://acme.test/a/1.json"]
        assert V.verify("https://evil.test/x.json").verdict == "invalid"


def test_verify_signed(app, monkeypatch):
    import json

    pytest = __import__("pytest")
    jwt = pytest.importorskip("jwt")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    import badgeserver.verify as V

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    payload = {
        "@context": V_CONTEXT, "type": "Assertion", "id": "urn:uuid:sig1",
        "recipient": {"type": "email", "hashed": False, "identity": "z@acme.test"},
        "badge": "https://acme.test/b.json", "issuedOn": "2026-03-01T00:00:00+00:00",
        "verification": {"type": "signed", "creator": "https://acme.test/key.json"},
    }
    token = jwt.PyJWS().encode(json.dumps(payload).encode(), key, algorithm="RS256")
    docs = {
        "https://acme.test/key.json": {
            "type": "CryptographicKey", "id": "https://acme.test/key.json",
            "owner": "https://acme.test/i.json", "publicKeyPem": pem,
        },
        "https://acme.test/i.json": {
            "@context": V_CONTEXT, "type": "Issuer", "id": "https://acme.test/i.json",
            "name": "Acme", "url": "https://acme.test", "email": "b@acme.test",
            "publicKey": "https://acme.test/key.json",
            "revocationList": "https://acme.test/rl.json",
        },
        "https://acme.test/b.json": {
            "@context": V_CONTEXT, "type": "BadgeClass", "id": "https://acme.test/b.json",
            "name": "Signed Badge", "description": "d", "issuer": "https://acme.test/i.json",
        },
        "https://acme.test/rl.json": {"revokedAssertions": []},
    }
    monkeypatch.setattr(V, "check_url_allowed", lambda u: None)
    monkeypatch.setattr(V, "_fetch", lambda url, *, max_bytes: (json.dumps(docs[url]).encode(), "application/json"))
    with app.app_context():
        r = V.verify(token)
        assert r.verdict == "valid"
        assert any("Signature verified" in c.label and c.status == "pass" for c in r.checks)
        assert V.verify(token[:-6] + "AAAAAA").verdict == "invalid"
        docs["https://acme.test/rl.json"] = {"revokedAssertions": ["urn:uuid:sig1"]}
        assert V.verify(token).verdict == "revoked"


def test_verify_page(app, client, auth_client):
    uuid = _award_local(app, auth_client)
    assert client.get("/verify").status_code == 200
    r = client.get(f"/verify?url={app.config['EXTERNAL_URL']}/a/{uuid}")
    assert r.status_code == 200 and b"Valid badge" in r.data
    # admin nav links to it
    assert b'href="/verify"' in auth_client.get("/admin/").data


V_CONTEXT = "https://w3id.org/openbadges/v2"
