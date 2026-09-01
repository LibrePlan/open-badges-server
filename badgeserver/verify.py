# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
"""Verify an Open Badges 2.0 assertion.

Given a URL (assertion page / JSON / baked PNG), the assertion JSON itself, or a
signed-badge JWS token, decide whether it is a legitimately issued badge and, if
an e-mail address is supplied, whether it was issued to that recipient.

Badges issued by this server are checked against the database directly. Anything
else is fetched over HTTP; every outbound request is screened so it cannot reach
a private / loopback / link-local address (basic SSRF protection -- the
DNS-rebinding TOCTOU window is accepted for this low-frequency tool).
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from flask import current_app
from flask_babel import gettext as _

from .baking import read_baked_from_bytes
from .extensions import db
from .models import Assertion, Issuer
from .openbadges import assertion_id as ob_assertion_id
from .openbadges import assertion_json
from .openbadges import badgeclass_id as ob_badgeclass_id
from .openbadges import issuer_id as ob_issuer_id

_UA = "badgeserver-verifier/1.0 (+Open Badges verification)"
_MAX_JSON = 512 * 1024
_MAX_IMAGE = 3 * 1024 * 1024
_TIMEOUT = (4, 8)
_JWS_RE = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}$")
_SIG_ALGS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]
_EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
]


class VerifyError(Exception):
    """A problem that stops verification (bad input, unreachable, disallowed)."""


@dataclass
class Check:
    label: str
    status: str  # "pass" | "warn" | "fail"
    detail: str = ""


@dataclass
class Result:
    verdict: str | None = None  # valid | revoked | expired | invalid | unsupported
    format: str = "unknown"  # ob2-hosted | ob2-signed | ob2-legacy | ob3 | unknown
    issued_by_us: bool = False
    issuer: dict | None = None
    badge: dict | None = None
    assertion: dict | None = None
    recipient_match: bool | None = None
    checks: list[Check] = field(default_factory=list)
    raw: dict | None = None
    error: str | None = None

    def add(self, label: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(label, status, detail))


# --------------------------------------------------------------------------- #
# outbound fetch + SSRF screen
# --------------------------------------------------------------------------- #


def _ip_blocked(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    return any(ip in net for net in _EXTRA_BLOCKED)


def check_url_allowed(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise VerifyError(_("Only http(s) URLs can be verified."))
    host = parts.hostname
    if not host:
        raise VerifyError(_("That URL has no host name."))
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise VerifyError(_("Could not resolve %(host)r.", host=host))
    for info in infos:
        if _ip_blocked(info[4][0]):
            raise VerifyError(_("The address behind %(host)r is not allowed.", host=host))


def _fetch(url: str, *, max_bytes: int) -> tuple[bytes, str]:
    for _hop in range(5):
        check_url_allowed(url)
        resp = requests.get(
            url,
            stream=True,
            allow_redirects=False,
            timeout=_TIMEOUT,
            headers={
                "User-Agent": _UA,
                "Accept": "application/ld+json, application/json, image/png, text/plain, */*",
            },
        )
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                target = resp.headers.get("Location")
                if not target:
                    raise VerifyError(_("Got a redirect with no target."))
                url = urljoin(url, target)
                continue
            if resp.status_code != 200:
                raise VerifyError(
                    _(
                        "%(url)s returned HTTP %(code)s.",
                        url=url,
                        code=resp.status_code,
                    )
                )
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            body = bytearray()
            for chunk in resp.iter_content(16384):
                body += chunk
                if len(body) > max_bytes:
                    raise VerifyError(_("The response is larger than allowed."))
            return bytes(body), ctype
        finally:
            resp.close()
    raise VerifyError(_("Too many redirects."))


def _fetch_json(url: str) -> dict:
    body, _ctype = _fetch(url, max_bytes=_MAX_JSON)
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise VerifyError(_("%(url)s did not return JSON.", url=url)) from exc
    if not isinstance(data, dict):
        raise VerifyError(_("%(url)s returned JSON that is not an object.", url=url))
    return data


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _norm_url(url: str) -> str:
    p = urlsplit(url)
    path = p.path.rstrip("/") or "/"
    return f"{p.scheme.lower()}://{(p.hostname or '').lower()}{'' if p.port in (None, 80, 443) else ':' + str(p.port)}{path}"


def _host_key(url: str) -> tuple:
    p = urlsplit(url)
    return (p.scheme.lower(), (p.hostname or "").lower(), p.port)


def _is_local(url: str) -> bool:
    external = current_app.config.get("EXTERNAL_URL", "")
    return bool(external) and isinstance(url, str) and _host_key(url) == _host_key(external)


def _local_uuid(url: str) -> str | None:
    if not _is_local(url):
        return None
    m = re.match(
        r"^/a/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
        r"(?:\.json|/badge\.png|/qr\.png|/)?$",
        urlsplit(url).path,
    )
    return m.group(1) if m else None


def _parse_when(value) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None


def _as_types(value) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value is not None else []


def _recipient_match(recipient: dict, email: str) -> bool | None:
    if not isinstance(recipient, dict) or recipient.get("type") not in ("email", None):
        return None
    identity = recipient.get("identity", "")
    email = email.strip()
    if recipient.get("hashed"):
        algo, _, digest = identity.partition("$")
        salt = recipient.get("salt", "")
        try:
            h = hashlib.new(algo)
        except ValueError:
            return None
        h.update((email + salt).encode("utf-8"))
        if h.hexdigest().lower() == digest.lower():
            return True
        h2 = hashlib.new(algo)
        h2.update((email.lower() + salt).encode("utf-8"))
        return h2.hexdigest().lower() == digest.lower()
    return identity.strip().lower() == email.lower()


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def verify(source: str, recipient: str | None = None) -> Result:
    source = (source or "").strip()
    recipient = (recipient or "").strip() or None
    result = Result()
    try:
        if not source:
            raise VerifyError(
                _("Paste a badge URL, its assertion JSON, or a signed badge token.")
            )
        if _JWS_RE.match(source):
            _verify_signed(source, recipient, result)
        elif source.startswith("{"):
            try:
                doc = json.loads(source)
            except ValueError as exc:
                raise VerifyError(_("That does not look like valid JSON.")) from exc
            _dispatch_doc(doc, fetched_from=None, recipient=recipient, result=result)
        elif re.match(r"^https?://", source, re.I):
            _verify_url(source, recipient, result)
        else:
            raise VerifyError(
                _("Paste an http(s) URL, the assertion JSON, or a signed badge token.")
            )
    except VerifyError as exc:
        result.verdict = result.verdict or "invalid"
        result.error = str(exc)
    except Exception:  # noqa: BLE001 - the verifier must never 500
        current_app.logger.exception("Badge verification crashed")
        result.verdict = "invalid"
        result.error = _("The badge data could not be processed.")
    if result.verdict is None:
        result.verdict = "invalid" if any(c.status == "fail" for c in result.checks) else "valid"
    return result


def _verify_url(url: str, recipient: str | None, result: Result) -> None:
    # Our own badges are answered from the database -- no network, no SSRF check.
    local = _local_uuid(url)
    if local is not None:
        _verify_local(local, recipient, result)
        return

    check_url_allowed(url)
    max_bytes = _MAX_IMAGE if url.lower().endswith(".png") else _MAX_JSON
    body, ctype = _fetch(url, max_bytes=max_bytes)
    if ctype == "image/png" or body[:8] == b"\x89PNG\r\n\x1a\n":
        inner = read_baked_from_bytes(body)
        if not inner:
            raise VerifyError(_("That PNG has no Open Badges data baked into it."))
        result.add(
            _("Baked PNG"), "pass", _("read the assertion reference from the image")
        )
        sub = verify(inner, recipient)
        sub.checks[:0] = result.checks
        result.__dict__.update(sub.__dict__)
        return

    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise VerifyError(
            _(
                "That URL did not return badge data. Use the assertion JSON URL "
                "(often ends in .json) or the badge PNG."
            )
        ) from exc
    if not isinstance(doc, dict):
        raise VerifyError(_("That URL returned JSON that is not an object."))
    _dispatch_doc(doc, fetched_from=url, recipient=recipient, result=result)


# --------------------------------------------------------------------------- #
# local (issued by us)
# --------------------------------------------------------------------------- #


def _verify_local(uuid: str, recipient: str | None, result: Result) -> None:
    result.format = "ob2-hosted"
    result.issued_by_us = True
    assertion = db.session.get(Assertion, uuid)
    if assertion is None:
        result.verdict = "invalid"
        result.error = _(
            "No badge with that identifier has been issued by this server."
        )
        result.add(_("Assertion exists on this server"), "fail", uuid)
        return

    result.add(_("Assertion exists on this server"), "pass", "")
    badge = assertion.badge
    result.add(_("Linked badge class"), "pass", badge.name)

    issuer = Issuer.query.order_by(Issuer.created_on).first()
    result.issuer = (
        {"name": issuer.name, "url": issuer.url, "email": issuer.email, "id": ob_issuer_id(issuer.slug)}
        if issuer
        else None
    )
    result.add(
        _("Issuer profile"),
        "pass" if issuer else "warn",
        issuer.name if issuer else _("missing"),
    )

    base = current_app.config["EXTERNAL_URL"].rstrip("/")
    try:
        version = int(os.path.getmtime(os.path.join(current_app.config["UPLOAD_DIR"], badge.image_path)))
    except OSError:
        version = 0
    result.badge = {
        "name": badge.name,
        "description": badge.description,
        "image": f"{base}/b/{badge.slug}/image?v={version}",
        "id": ob_badgeclass_id(badge.slug),
    }
    result.assertion = {
        "id": ob_assertion_id(assertion.uuid),
        "issued_on": assertion.issued_on_utc().date().isoformat(),
        "recipient": assertion.masked_recipient,
    }
    result.raw = assertion_json(assertion)

    if assertion.revoked:
        result.verdict = "revoked"
        result.add(
            _("Not revoked"), "fail", assertion.revocation_reason or _("revoked")
        )
    else:
        result.verdict = "valid"
        result.add(_("Not revoked"), "pass", "")

    if recipient:
        ok = recipient.strip().lower() == assertion.recipient_email.lower()
        result.recipient_match = ok
        result.add(
            _("Recipient e-mail matches"),
            "pass" if ok else "fail",
            "" if ok else _("this badge was issued to a different address"),
        )


# --------------------------------------------------------------------------- #
# external OB 2.0 documents
# --------------------------------------------------------------------------- #


def _dispatch_doc(doc: dict, *, fetched_from: str | None, recipient: str | None, result: Result) -> None:
    context = doc.get("@context", "")
    context_s = " ".join(context) if isinstance(context, list) else str(context)
    all_types = _as_types(doc.get("type"))

    if "w3.org/ns/credentials" in context_s or "OpenBadgeCredential" in all_types:
        result.format = "ob3"
        result.verdict = "unsupported"
        result.error = _(
            "This is an Open Badges 3.0 / Verifiable Credential. "
            "This tool verifies Open Badges 2.0 badges."
        )
        result.raw = doc
        return

    # If it names one of our own assertions, answer from the database.
    local = _local_uuid(doc.get("id") or "")
    if local is not None:
        _verify_local(local, recipient, result)
        return

    verification = doc.get("verification") or {}
    verify_1x = doc.get("verify") or {}
    if _as_types(verification.get("type")) and "signed" in " ".join(
        _as_types(verification.get("type"))
    ).lower():
        result.format = "ob2-signed"
        result.raw = doc
        result.add(
            _("Signed badge"),
            "warn",
            _(
                "provide the signed token or the baked PNG so the signature "
                "can be checked"
            ),
        )
        _resolve_badge_and_issuer(doc, result)
        _finish_common(doc, recipient, result)
        return

    result.format = "ob2-legacy" if verify_1x and not verification else "ob2-hosted"
    _verify_hosted(doc, fetched_from, recipient, result)


def _verify_hosted(doc: dict, fetched_from: str | None, recipient: str | None, result: Result) -> None:
    result.raw = doc
    assertion_id = doc.get("id") or (doc.get("verify") or {}).get("url")

    if "Assertion" not in _as_types(doc.get("type")) and "assertion" not in str(doc.get("type", "")).lower():
        result.add(_("Document type is Assertion"), "warn", f"type = {doc.get('type')!r}")
    else:
        result.add(_("Document type is Assertion"), "pass", "")

    for field_name in ("recipient", "badge"):
        if field_name not in doc:
            result.add(_("Has %(field)s", field=field_name), "fail", _("missing"))
        else:
            result.add(_("Has %(field)s", field=field_name), "pass", "")

    # Hosted authenticity: the assertion must be served from its own id.
    if assertion_id:
        if fetched_from is None:
            try:
                check_url_allowed(assertion_id)
                hosted = _fetch_json(assertion_id)
                same = hosted.get("id") == doc.get("id")
                result.add(
                    _("Assertion is published at its own URL"),
                    "pass" if same else "fail",
                    "" if same else _("the copy at that URL has a different id"),
                )
            except VerifyError as exc:
                result.add(
                    _("Assertion is published at its own URL"), "warn", str(exc)
                )
        else:
            same = _norm_url(fetched_from) == _norm_url(assertion_id)
            result.add(
                _("Assertion is published at its own URL"),
                "pass" if same else "fail",
                "" if same else f"served from {fetched_from} but claims id {assertion_id}",
            )
    else:
        result.add(_("Assertion has an id"), "fail", _("missing"))

    _resolve_badge_and_issuer(doc, result)
    _finish_common(doc, recipient, result)


def _resolve_ref(ref, kind: str, result: Result) -> dict | None:
    """Resolve a badge/issuer reference: inline object, our DB, or an HTTP fetch."""
    if isinstance(ref, dict):
        return ref
    if not isinstance(ref, str):
        return None
    if _is_local(ref):
        slug_m = re.match(rf"^/{'b' if kind == 'badge' else 'issuer'}/([^/.]+)", urlsplit(ref).path)
        if slug_m:
            from .models import BadgeClass
            from .openbadges import badgeclass_json, issuer_json

            slug = slug_m.group(1)
            if kind == "badge":
                obj = db.session.get(BadgeClass, slug)
                return badgeclass_json(obj) if obj else None
            obj = db.session.get(Issuer, slug)
            return issuer_json(obj) if obj else None
    try:
        check_url_allowed(ref)
        return _fetch_json(ref)
    except VerifyError as exc:
        result.add(_("%(kind)s fetched", kind=kind.title()), "warn", str(exc))
        return None


def _resolve_badge_and_issuer(doc: dict, result: Result) -> None:
    badge_doc = _resolve_ref(doc.get("badge"), "badge", result)

    if badge_doc:
        is_bc = "BadgeClass" in _as_types(badge_doc.get("type"))
        result.add(_("Badge class is well-formed"), "pass" if is_bc else "warn",
                   "" if is_bc else f"type = {badge_doc.get('type')!r}")
        image = badge_doc.get("image")
        result.badge = {
            "name": badge_doc.get("name", ""),
            "description": badge_doc.get("description", ""),
            "image": image if isinstance(image, str) else (image or {}).get("id", ""),
            "id": badge_doc.get("id", ""),
        }
        issuer_ref = badge_doc.get("issuer")
    else:
        issuer_ref = None

    issuer_doc = _resolve_ref(issuer_ref, "issuer", result)
    if issuer_doc:
        ok_type = bool({"Issuer", "Profile"} & set(_as_types(issuer_doc.get("type"))))
        result.add(_("Issuer profile is well-formed"), "pass" if ok_type else "warn",
                   "" if ok_type else f"type = {issuer_doc.get('type')!r}")
        result.issuer = {
            "name": issuer_doc.get("name", ""),
            "url": issuer_doc.get("url", ""),
            "email": issuer_doc.get("email", ""),
            "id": issuer_doc.get("id", ""),
        }
        result.issuer_raw = issuer_doc  # type: ignore[attr-defined]
        aid = doc.get("id") or ""
        if aid and result.issuer["id"]:
            same_host = _host_key(aid)[1] == _host_key(result.issuer["id"])[1]
            result.add(
                _("Issuer and assertion share a domain"),
                "pass" if same_host else "warn",
                "" if same_host else _("the issuer is hosted on a different domain"),
            )
    # is this us?
    external = current_app.config.get("EXTERNAL_URL", "")
    if result.issuer and external and _host_key(result.issuer.get("id", ""))[1] == _host_key(external)[1]:
        result.issued_by_us = True


def _finish_common(doc: dict, recipient: str | None, result: Result) -> None:
    if doc.get("revoked") is True:
        result.verdict = "revoked"
        result.add(
            _("Not revoked"),
            "fail",
            str(doc.get("revocationReason") or _("revoked")),
        )
    else:
        result.add(_("Not revoked"), "pass", "")

    issued = _parse_when(doc.get("issuedOn"))
    result.add(_("Issue date is valid"), "pass" if issued else "warn",
               issued.date().isoformat() if issued else str(doc.get("issuedOn")))
    expires = _parse_when(doc.get("expires") or doc.get("expiresOn"))
    if expires:
        past = expires < datetime.now(timezone.utc)
        result.add(_("Not expired"), "fail" if past else "pass", expires.date().isoformat())
        if past and result.verdict is None:
            result.verdict = "expired"

    result.assertion = {
        "id": doc.get("id", ""),
        "issued_on": issued.date().isoformat() if issued else "",
        "recipient": _describe_recipient(doc.get("recipient")),
    }

    if recipient and isinstance(doc.get("recipient"), dict):
        match = _recipient_match(doc["recipient"], recipient)
        result.recipient_match = match
        if match is not None:
            result.add(
                _("Recipient e-mail matches"),
                "pass" if match else "fail",
                "" if match else _("this badge was issued to a different address"),
            )


def _describe_recipient(recipient) -> str:
    if isinstance(recipient, dict):
        if recipient.get("hashed"):
            return f"{recipient.get('type', 'identity')} (hashed)"
        ident = str(recipient.get("identity", ""))
        local, sep, domain = ident.partition("@")
        return f"{local[:1]}***@{domain}" if sep else "identity"
    return "identity (hashed)" if isinstance(recipient, str) else "unknown"


# --------------------------------------------------------------------------- #
# signed badges (JWS)
# --------------------------------------------------------------------------- #


def _verify_signed(token: str, recipient: str | None, result: Result) -> None:
    try:
        import jwt as pyjwt
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise VerifyError(
            _(
                "Signed-badge verification needs the python3-jwt and "
                "python3-cryptography packages."
            )
        ) from exc

    result.format = "ob2-signed"
    parts = token.split(".")
    try:
        header = json.loads(base64.urlsafe_b64decode(parts[0] + "=="))
        doc = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    except Exception as exc:  # noqa: BLE001
        raise VerifyError(_("Could not decode that signed badge token.")) from exc
    if not isinstance(doc, dict):
        raise VerifyError(
            _("The signed token payload is not an Open Badges assertion.")
        )
    result.raw = doc
    result.add(
        _("Signed badge token decoded"),
        "pass",
        f"algorithm {header.get('alg', '?')}",
    )

    verification = doc.get("verification") or doc.get("verify") or {}
    creator = verification.get("creator") or verification.get("url")
    if not creator:
        raise VerifyError(
            _(
                "The signed badge does not reference a public key "
                "(verification.creator)."
            )
        )

    check_url_allowed(creator)
    key_doc = _fetch_json(creator)
    pem = key_doc.get("publicKeyPem")
    if not pem:
        raise VerifyError(_("The referenced key document has no publicKeyPem."))

    try:
        public_key = load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)
        pyjwt.PyJWS().decode(token, key=public_key, algorithms=_SIG_ALGS)
        result.add(_("Signature verified with the issuer's key"), "pass", "")
    except Exception as exc:  # noqa: BLE001
        result.verdict = "invalid"
        result.add(
            _("Signature verified with the issuer's key"),
            "fail",
            type(exc).__name__,
        )

    _resolve_badge_and_issuer(doc, result)

    issuer_raw = getattr(result, "issuer_raw", {})
    owner = key_doc.get("owner")
    issuer_id_val = (result.issuer or {}).get("id")
    if owner and issuer_id_val:
        result.add(
            _("Key belongs to the issuer"),
            "pass" if owner == issuer_id_val else "fail",
            "" if owner == issuer_id_val else f"key owner {owner} != issuer {issuer_id_val}",
        )
    declared = issuer_raw.get("publicKey")
    declared_ids = _as_types(declared) if not isinstance(declared, list) else [
        (d.get("id") if isinstance(d, dict) else str(d)) for d in declared
    ]
    if key_doc.get("id"):
        listed = key_doc["id"] in declared_ids
        result.add(
            _("Issuer lists this key"),
            "pass" if listed else "warn",
            "" if listed else _("the issuer profile does not reference this key"),
        )

    _check_revocation_list(doc, issuer_raw, result)
    _finish_common(doc, recipient, result)


def _check_revocation_list(doc: dict, issuer_raw: dict, result: Result) -> None:
    rl_url = issuer_raw.get("revocationList")
    if not rl_url or not isinstance(rl_url, str):
        return
    try:
        check_url_allowed(rl_url)
        rl = _fetch_json(rl_url)
    except VerifyError as exc:
        result.add(_("Checked the issuer revocation list"), "warn", str(exc))
        return
    revoked = rl.get("revokedAssertions") or []
    aid = doc.get("id")
    auid = doc.get("uid")
    hit = None
    for entry in revoked:
        if isinstance(entry, str) and entry in (aid, auid):
            hit = {}
        elif isinstance(entry, dict) and entry.get("id") in (aid, auid):
            hit = entry
    if hit is not None:
        result.verdict = "revoked"
        result.add(
            _("Not on the revocation list"),
            "fail",
            str(hit.get("revocationReason") or _("revoked")),
        )
    else:
        result.add(_("Not on the revocation list"), "pass", "")
