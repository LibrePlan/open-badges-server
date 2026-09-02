<!--
SPDX-License-Identifier: AGPL-3.0-or-later
SPDX-FileCopyrightText: 2026 Jeroen Baten <jeroen@libreplan.dev>
-->

# Open Badges 2.0 vs 3.0, and what 3.0 support would take

## The core shift

**OB 2.0 is a bespoke JSON-LD format. OB 3.0 is a W3C Verifiable Credential.**
That single change drags everything else with it: identifiers, verification,
revocation, key management, and how a badge gets to a person.

OB 2.0's trust model is *"this badge is genuine because it's served from the
issuer's own domain"* (hosted verification) with an optional JWS signature.
OB 3.0's is *"this badge is genuine because it carries a cryptographic proof
that chains to the issuer's public key/DID"* — hosting becomes optional.

## Field-level mapping

| Concept | OB 2.0 (what this server emits) | OB 3.0 |
|---|---|---|
| `@context` | `https://w3id.org/openbadges/v2` | `https://www.w3.org/ns/credentials/v2` + `…/spec/ob/v3p0/context-3.0.3.json` |
| Top object | `Assertion` | `AchievementCredential` (`type: [VerifiableCredential, AchievementCredential]`) |
| Badge definition | `BadgeClass` (own URL) | `Achievement`, usually embedded under `credentialSubject.achievement` |
| Recipient | `recipient`: `{hashed, salt, identity: "sha256$…"}` | `credentialSubject.id` = a **DID** (holder-bound), or `identifier: [IdentityObject]` with the same hashed-email fallback |
| Dates | `issuedOn`, `expires` | `validFrom`, `validUntil` |
| Verification | `verification: {type: hosted}` or a JWS | `proof` — either **Data Integrity** (Ed25519 + RDF canonicalization) or **VC-JWT** (JOSE, like OB2's signed badges) |
| Issuer keys | `CryptographicKey` with `publicKeyPem` | **DID documents** (`did:web`, `did:key`, `did:jwk`) or a hosted JWKS |
| Revocation | assertion URL returns `revoked:true`, or issuer `revocationList` | `credentialStatus` → **Bitstring Status List** (itself a signed VC) |
| Delivery | host JSON at a URL, email the link | wallet flows (OID4VCI), or just hand over a JWT/JSON file; baking still supported |

Baking into PNG/SVG survives in 3.0 (keyword `openbadgecredential`, payload is
the credential or a URL to it).

The practical consequence of the recipient change: OB 2.0's *"email a link, the
recipient does nothing"* doesn't map onto 3.0's holder-binding model. You either
keep using the weak hashed-email `IdentityObject` (allowed, but the credential
isn't bound to a key the recipient controls) or you implement a wallet issuance
protocol so the recipient can present a DID.

## How hard is 3.0 for *this* server

It splits into tiers. The feasibility hinge is that **`python3-cryptography` and
`python3-jwt` are already installed**, so Ed25519 signing + JOSE need no new
packages — *if* we commit to the VC-JWT proof format and skip Data Integrity.

### Tier 1 — issue OB 3.0 credentials (VC-JWT + `did:web`) · ~2–4 days

Reuses the existing DB models, `Assertion.identity_hash()`, and the JWS code in
`verify.py` (signing is its inverse).

- **Key + identity**: generate an Ed25519 keypair, private key from a file/env
  (mode 0600), publish it at `/.well-known/did.json` as `did:web:<host>`.
  New config: `OB3_ENABLED`, `OB3_PRIVATE_KEY_PATH`. ~40 lines.
- **Serializer** `openbadges3.py` (parallel to the 96-line `openbadges.py`): map
  `Issuer`/`BadgeClass`/`Assertion` into an `AchievementCredential` dict.
  ~100 lines, mechanical but version-sensitive.
- **Proof**: `jwt.encode(payload, key, algorithm="EdDSA", headers={"typ":"vc+jwt","kid":…})`.
  ~15 lines.
- **Serving**: content-negotiate the existing `/a/<uuid>` (`Accept:
  application/vc+jwt` → JWT), serve `/.well-known/did.json`. ~40 lines in
  `public.py`.
- **Baking + UI**: bake the JWT/URL; admin toggle "issue as OB 3.0"; assertion
  page download link; email copy; i18n strings. ~1 day.
- **Migration**: `cli.py` idempotent-ALTER adds any new columns.

### Tier 2 — real OB 3.0 for the JWT profile · +3–5 days

- **Revocation → Bitstring Status List**: add `ob3_status_index` to `Assertion`,
  maintain a gzip+base64url bitstring served as a signed status-list VC at
  `/status/…`, set `credentialStatus` on issue, flip the bit on revoke.
  ~100 lines.
- **Verify others' OB 3.0** (currently `verify.py` just says "unsupported"):
  detect VC-JWT, resolve the issuer key via `did:web` (reuses the existing
  SSRF-screened fetch), `did:key`, `did:jwk`; check signature, `validUntil`,
  and status-list bit. ~200 lines + DID helpers.

### Tier 3 — the parts to deliberately *not* do

- **Data Integrity proofs** (`eddsa-rdfc-2022`): need RDF Dataset Canonicalization
  (URDNA2015/RDFC-1.0). No Debian package; `pyld` is pip-only, which is
  off-limits here. **This is the one hard blocker.** Consequence: credentials
  this server issues as VC-JWT won't verify in a wallet that only accepts Data
  Integrity, and vice versa. 1EdTech tests both formats; certification can be
  for one.
- **OID4VCI / wallet issuance, Presentation Exchange, CLR**: weeks, separate
  project. Without it you're limited to the hashed-email identity fallback (no
  holder key binding).
- **1EdTech certification**: conformance suite, hosted JSON schema, exact
  context pinning — its own effort on top of Tier 2.

### Other things to decide up front

- **Target version** — OB 3.0.0→3.0.3 and the VCDM 1.1→2.0 move renamed fields
  (`issuanceDate`→`validFrom`, `expirationDate`→`validUntil`, preferred type
  `OpenBadgeCredential`→`AchievementCredential`). Pick one context URL and stick
  to it.
- **Dual emission** — keep serving OB 2.0 at the same URLs and add 3.0 alongside
  (recommended), or switch. The models don't need to change either way.

## Bottom line

The conceptual distance is large, but a genuinely useful subset — *this server
issues and verifies OB 3.0 credentials in the VC-JWT profile with `did:web` and
status-list revocation* — is roughly **1–1.5 weeks** and needs **no new system
packages**. The ceiling (Data Integrity proofs, wallet protocols, certification)
is much higher and partly blocked by the apt-only constraint.
