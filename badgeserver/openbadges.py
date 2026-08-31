# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jbaten@coderial.com>
"""Open Badges 2.0 JSON serialisers.

Reference: IMS Open Badges v2.0 (``https://w3id.org/openbadges/v2``).
Only the hosted-verification profile is produced.
"""

from __future__ import annotations

from flask import current_app

from .models import Assertion, BadgeClass, Issuer

CONTEXT = "https://w3id.org/openbadges/v2"


def base_url() -> str:
    return current_app.config["EXTERNAL_URL"].rstrip("/")


def issuer_id(slug: str) -> str:
    return f"{base_url()}/issuer/{slug}.json"


def badgeclass_id(slug: str) -> str:
    return f"{base_url()}/b/{slug}.json"


def assertion_id(uuid: str) -> str:
    return f"{base_url()}/a/{uuid}.json"


def issuer_json(issuer: Issuer) -> dict:
    data = {
        "@context": CONTEXT,
        "type": "Issuer",
        "id": issuer_id(issuer.slug),
        "name": issuer.name,
        "url": issuer.url,
        "email": issuer.email,
    }
    if issuer.description:
        data["description"] = issuer.description
    if issuer.image_path:
        data["image"] = f"{base_url()}/issuer/{issuer.slug}/image"
    return data


def badgeclass_json(badge: BadgeClass) -> dict:
    criteria: dict = {}
    if badge.criteria_narrative:
        criteria["narrative"] = badge.criteria_narrative
    if badge.criteria_url:
        criteria["id"] = badge.criteria_url
    if not criteria:
        criteria["narrative"] = f"Awarded at the discretion of {badge.issuer.name}."

    data = {
        "@context": CONTEXT,
        "type": "BadgeClass",
        "id": badgeclass_id(badge.slug),
        "name": badge.name,
        "description": badge.description,
        "image": f"{base_url()}/b/{badge.slug}/image",
        "criteria": criteria,
        "issuer": issuer_id(badge.issuer_slug),
    }
    if badge.tag_list:
        data["tags"] = badge.tag_list
    return data


def assertion_json(assertion: Assertion) -> dict:
    data = {
        "@context": CONTEXT,
        "type": "Assertion",
        "id": assertion_id(assertion.uuid),
        "recipient": {
            "type": "email",
            "hashed": True,
            "salt": assertion.salt,
            "identity": assertion.identity_hash(),
        },
        "badge": badgeclass_id(assertion.badge_slug),
        "issuedOn": assertion.issued_on_utc().isoformat(),
        "verification": {"type": "hosted"},
    }
    if assertion.evidence_url:
        data["evidence"] = assertion.evidence_url
    if assertion.narrative:
        data["narrative"] = assertion.narrative
    if assertion.revoked:
        data["revoked"] = True
        data["revocationReason"] = assertion.revocation_reason or "Revoked."
    return data
