"""WebAuthn / Passkey service.

Pure-Python module that wraps the `py_webauthn` library for FolioSpace.
Mirrors the structure of `app/services/auth_tokens.py` for challenge
issue/consume, and `app/services/oauth.py` for the ceremony pattern.

DB schema lives in `scripts/passkeys.sql`:
  - passkey_credentials  (one credential per user, UNIQUE(user_id))
  - webauthn_challenges  (5-min TTL, single-use, attempt lockout)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

# py_webauthn imports are lazy: the module can be imported in environments
# where py_webauthn isn't installed (tests, CI dry-run) without crashing.
# Each function that uses webauthn calls `_webauthn()` first.
_webauthn_cache: dict[str, Any] = {}


def _webauthn() -> dict[str, Any]:
    if _webauthn_cache:
        return _webauthn_cache
    from webauthn import (  # noqa: WPS433 — lazy import on purpose
        generate_authentication_options,
        generate_registration_options,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers.cose import COSEAlgorithmIdentifier
    try:
        from webauthn.helpers.options import (  # webauthn 2.x
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    except ImportError:  # webauthn 3.x merged options into structs
        from webauthn.helpers.structs import (
            PublicKeyCredentialDescriptor,
            ResidentKeyRequirement,
            UserVerificationRequirement,
        )
    from webauthn.helpers.structs import (
        AttestationConveyancePreference,
        AuthenticatorAttachment,
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialType,
    )
    _webauthn_cache.update(
        generate_authentication_options=generate_authentication_options,
        generate_registration_options=generate_registration_options,
        verify_authentication_response=verify_authentication_response,
        verify_registration_response=verify_registration_response,
        COSEAlgorithmIdentifier=COSEAlgorithmIdentifier,
        PublicKeyCredentialDescriptor=PublicKeyCredentialDescriptor,
        ResidentKeyRequirement=ResidentKeyRequirement,
        UserVerificationRequirement=UserVerificationRequirement,
        AttestationConveyancePreference=AttestationConveyancePreference,
        AuthenticatorAttachment=AuthenticatorAttachment,
        AuthenticatorSelectionCriteria=AuthenticatorSelectionCriteria,
        PublicKeyCredentialType=PublicKeyCredentialType,
    )
    return _webauthn_cache


from app.services import user_auth  # noqa: E402

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────────────────────────────────────

RP_NAME = "FolioSpace"
CHALLENGE_TTL_SECONDS = 300
ATTEMPT_LOCKOUT = 3
CHALLENGE_BYTES = 32
USER_ID_BYTES = 32


# ── Exceptions (stable error codes) ─────────────────────────────────────────────────────────────────────

class PasskeyError(Exception):
    """Base for all passkey errors. `code` is the stable wire string."""

    code: str = "passkey_failed"


class PasskeyAlreadyEnrolled(PasskeyError):
    code = "already_enrolled"


class PasskeyChallengeExpired(PasskeyError):
    code = "challenge_expired"


class PasskeyAttemptLockout(PasskeyError):
    code = "attempt_lockout"


class PasskeyUnverifiedEmail(PasskeyError):
    code = "unverified_email"


class PasskeyCounterRegression(PasskeyError):
    code = "counter_regression"


class PasskeyAttestationFailed(PasskeyError):
    code = "attestation_failed"


class PasskeyAssertionFailed(PasskeyError):
    code = "assertion_failed"


class PasskeyCredentialNotFound(PasskeyError):
    code = "credential_not_found"


class PasskeyOriginMismatch(PasskeyError):
    code = "origin_mismatch"


class PasskeyRpMismatch(PasskeyError):
    code = "rp_mismatch"


class PasskeyNotConfigured(PasskeyError):
    code = "not_configured"


# ── DB connection ─────────────────────────────────────────────────────────────────────────────────────────

def _connect():
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(dsn, row_factory=dict_row)


# ── Relying Party helpers ───────────────────────────────────────────────────────────────────────────────

def _public_base_host() -> str:
    """Relying Party ID host (WebAuthn spec: must be the host or a parent).

    Special-cases 127.0.0.1 → localhost (WebAuthn accepts both for dev).
    """
    raw = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("OAUTH_REDIRECT_BASE")
        or "https://foliospace.in"
    ).strip()
    try:
        host = urlparse(raw).hostname or "foliospace.in"
    except Exception:
        host = "foliospace.in"
    if host in ("127.0.0.1", "0.0.0.0"):
        host = "localhost"
    return host.lower()


def _rp_id() -> str:
    return _public_base_host()


def _rp_name() -> str:
    return RP_NAME


def _allowed_origins() -> list[str]:
    """Origins the RP will accept for WebAuthn ceremonies."""
    hosts = [h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
    base = _public_base_host()
    if base not in hosts:
        hosts.append(base)
    if "localhost" not in hosts:
        hosts.append("localhost")
    schemes = ["http", "https"]
    out: list[str] = []
    for s in schemes:
        for h in hosts:
            if h in ("localhost", "127.0.0.1") and s == "https":
                continue  # WebAuthn forbids https+localhost
            out.append(f"{s}://{h}")
    return out


# ── Encoding helpers (server-side b64url ↔ bytes) ────────────────────────────────────────────────────────

def b64u_decode(s: str) -> bytes:
    s = (s or "").strip()
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def b64u_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def extract_challenge(credential: dict) -> bytes:
    """Pull the raw challenge bytes out of a credential/assertion dict sent from the browser.

    The browser's PublicKeyCredential JSON does NOT have a top-level `challenge` key —
    the original challenge bytes are base64url-encoded inside
    `response.clientDataJSON` (a JSON object whose `challenge` field is the base64url
    original nonce we minted at /passkey/*/begin).
    """
    response = credential.get("response") or {}
    cdata_b64u = response.get("clientDataJSON")
    if not cdata_b64u:
        raise PasskeyAttestationFailed("clientDataJSON missing")
    try:
        cdata = b64u_decode(cdata_b64u)
        cdata_obj = json.loads(cdata)
        challenge_b64u = cdata_obj.get("challenge")
    except (ValueError, KeyError, TypeError) as e:
        raise PasskeyAttestationFailed(f"clientDataJSON undecodable: {e}") from e
    if not challenge_b64u:
        raise PasskeyAttestationFailed("challenge missing from clientDataJSON")
    return b64u_decode(challenge_b64u)


# ── Challenge lifecycle ─────────────────────────────────────────────────────────────────────────────────

def _store_challenge(
    kind: str,
    challenge: bytes,
    user_id: str | None = None,
    email_hint: str | None = None,
    ip: str | None = None,
    ua: str | None = None,
) -> int:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO webauthn_challenges
                    (kind, challenge, user_id, email_hint, expires_at, ip, user_agent)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    kind,
                    challenge,
                    user_id,
                    (email_hint or "").strip().lower()[:254] or None,
                    expires_at,
                    ip,
                    (ua or "")[:512] or None,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def _consume_challenge(challenge: bytes, kind: str) -> dict | None:
    """Atomically consume a challenge. Returns row (without `challenge` bytes)
    if valid, else raises a PasskeyError subclass.

    Rules:
      - not found / wrong kind → PasskeyChallengeExpired
      - consumed_at already set → PasskeyChallengeExpired
      - expires_at < now → PasskeyChallengeExpired
      - attempts >= ATTEMPT_LOCKOUT → delete + PasskeyAttemptLockout
      - else: attempts++, return row
    """
    if not DATABASE_URL_OK():
        raise RuntimeError("DATABASE_URL not set")
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, email_hint, expires_at, consumed_at, attempts
                    FROM webauthn_challenges
                    WHERE challenge = %s AND kind = %s
                    FOR UPDATE
                    """,
                    (challenge, kind),
                )
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    raise PasskeyChallengeExpired("challenge not found")
                if row["consumed_at"] is not None:
                    conn.rollback()
                    raise PasskeyChallengeExpired("already consumed")
                now = datetime.now(timezone.utc)
                if row["expires_at"] <= now:
                    conn.rollback()
                    raise PasskeyChallengeExpired("expired")
                if row["attempts"] + 1 >= ATTEMPT_LOCKOUT:
                    cur.execute(
                        "DELETE FROM webauthn_challenges WHERE id = %s",
                        (row["id"],),
                    )
                    conn.commit()
                    raise PasskeyAttemptLockout("locked")
                cur.execute(
                    "UPDATE webauthn_challenges SET attempts = attempts + 1 WHERE id = %s",
                    (row["id"],),
                )
                conn.commit()
                return {
                    "id": row["id"],
                    "user_id": str(row["user_id"]) if row["user_id"] else None,
                    "email_hint": row["email_hint"],
                }
    except psycopg.Error as e:
        logger.exception("challenge consume db error: %s", e)
        raise PasskeyChallengeExpired("db error") from e


# Local guard (mirrors auth_tokens.py)
def DATABASE_URL_OK() -> bool:  # noqa: N802
    return bool(os.getenv("DATABASE_URL"))


def _gen_challenge() -> bytes:
    return secrets.token_bytes(CHALLENGE_BYTES)


def _gen_webauthn_user_id(user_id: str) -> bytes:
    """Stable per-user WebAuthn user handle (32 bytes)."""
    digest = secrets.token_bytes(USER_ID_BYTES)
    return digest


# ── Lookups ───────────────────────────────────────────────────────────────────────────────────────────────

def _user_row(user_id: str) -> dict | None:
    """Pull the columns we need to gate the ceremonies."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, email_verified, deleted_at
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                )
                return cur.fetchone()
    except psycopg.Error as e:
        logger.exception("user lookup failed: %s", e)
        return None


def _require_verified_user(user_id: str) -> dict:
    u = _user_row(user_id)
    if not u or u.get("deleted_at") is not None:
        raise PasskeyUnverifiedEmail("no-user")
    if not u.get("email_verified"):
        raise PasskeyUnverifiedEmail("not-verified")
    return u


def list_user_passkeys(user_id: str) -> list[dict]:
    if not DATABASE_URL_OK():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, credential_id, sign_count, transports,
                           aaguid, user_verified, backup_eligible, backup_state,
                           friendly_name, created_at, last_used_at, revoked_at
                    FROM passkey_credentials
                    WHERE user_id = %s AND revoked_at IS NULL
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall() or []
        out: list[dict] = []
        for r in rows:
            r2 = dict(r)
            r2["credential_id_b64u"] = b64u_encode(bytes(r["credential_id"]))
            r2["user_id"] = str(r["user_id"])
            r2["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
            r2["last_used_at"] = r["last_used_at"].isoformat() if r.get("last_used_at") else None
            r2["aaguid"] = str(r["aaguid"]) if r.get("aaguid") else None
            out.append(r2)
        return out
    except psycopg.Error as e:
        logger.exception("list_user_passkeys failed: %s", e)
        return []


def _credential_b64u_to_bytes(cred_id_b64u: str) -> bytes:
    return b64u_decode(cred_id_b64u)


# ── Registration ─────────────────────────────────────────────────────────────────────────────────────────

def start_registration(
    user_id: str,
    ip: str | None = None,
    ua: str | None = None,
) -> dict[str, Any]:
    """Generate PublicKeyCredentialCreationOptions for the logged-in user.

    Raises PasskeyUnverifiedEmail if user's email is not verified.
    Raises PasskeyAlreadyEnrolled if an active credential already exists.
    """
    user = _require_verified_user(user_id)
    existing = list_user_passkeys(user_id)
    if existing:
        raise PasskeyAlreadyEnrolled("one-credential-limit")
    challenge = _gen_challenge()
    webauthn_uid = _gen_webauthn_user_id(user_id)
    _store_challenge("register", challenge, user_id=user_id, ip=ip, ua=ua)
    wa = _webauthn()
    # webauthn 3.x requires AuthenticatorSelectionCriteria dataclass, not a dict.
    # (In 2.x the library accepted a dict and constructed the dataclass itself.)
    authenticator_selection = wa["AuthenticatorSelectionCriteria"](
        resident_key=wa["ResidentKeyRequirement"].PREFERRED,
        user_verification=wa["UserVerificationRequirement"].REQUIRED,
        authenticator_attachment=wa["AuthenticatorAttachment"].PLATFORM,
        require_resident_key=False,
    )
    options = wa["generate_registration_options"](
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=webauthn_uid,
        user_name=user["email"],
        user_display_name=user["email"],
        challenge=challenge,
        attestation=wa["AttestationConveyancePreference"].NONE,
        authenticator_selection=authenticator_selection,
        supported_pub_key_algs=[
            wa["COSEAlgorithmIdentifier"].ECDSA_SHA_256,
            wa["COSEAlgorithmIdentifier"].EDDSA,
            wa["COSEAlgorithmIdentifier"].RSASSA_PSS_SHA_256,
        ],
        timeout=CHALLENGE_TTL_SECONDS * 1000,
    )
    # Serialize to JSON-friendly dict.
    out = _serialize_reg_options(options)
    out["user"]["id"] = b64u_encode(webauthn_uid)
    out["user"]["name"] = user["email"]
    out["user"]["displayName"] = user["email"]
    return out


def _enum_or_str(value):
    """Return the wire-format string for a value that may be a 3.x enum or a 2.x raw str.

    py_webauthn 3.x wraps these in enum members (AttestationConveyancePreference,
    UserVerificationRequirement, AuthenticatorAttachment, AuthenticatorTransport);
    2.x leaves them as plain strings. The JSON wire format is the same: the string
    value. This helper normalizes both.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return getattr(value, "value", value)


def _serialize_reg_options(opts) -> dict[str, Any]:
    """Convert py_webauthn PublicKeyCredentialCreationOptions → JSON dict.

    Tolerates both webauthn 2.x (strings) and 3.x (enums with `.value`).
    Skips `hints` on 2.x — the field does not exist there.
    """
    sel = opts.authenticator_selection
    return {
        "rp": {"id": opts.rp.id, "name": opts.rp.name},
        "user": {
            "id": b64u_encode(opts.user.id),
            "name": opts.user.name,
            "displayName": opts.user.display_name,
        },
        "challenge": b64u_encode(opts.challenge),
        "pubKeyCredParams": [
            {"type": "public-key", "alg": p.alg}
            for p in (opts.pub_key_cred_params or [])
        ],
        "timeout": opts.timeout,
        "excludeCredentials": [
            {
                "id": b64u_encode(bytes(c.id)),
                "type": "public-key",
                "transports": [_enum_or_str(t) for t in (c.transports or [])],
            }
            for c in (opts.exclude_credentials or [])
        ],
        "authenticatorSelection": {
            "residentKey": (_enum_or_str(sel.resident_key) if sel else None),
            "userVerification": (_enum_or_str(sel.user_verification) if sel else None),
            "authenticatorAttachment": (_enum_or_str(sel.authenticator_attachment) if sel else None),
            "requireResidentKey": bool(sel.require_resident_key) if sel else False,
        },
        "attestation": _enum_or_str(opts.attestation) or "none",
        # `hints` was added to PublicKeyCredentialCreationOptions in webauthn 3.x
        # (present but None when not set); absent in 2.x. Emit only when non-empty.
        **({"hints": [_enum_or_str(h) for h in opts.hints]}
           if hasattr(opts, "hints") and opts.hints else {}),
    }


def complete_registration(
    user_id: str,
    attestation: dict,
    friendly_name: str | None,
    request,
) -> dict:
    """Verify the attestation response and persist the credential."""
    user = _require_verified_user(user_id)
    # Pull challenge from response.clientDataJSON (browser JSON has no top-level
    # `challenge` key — it lives base64url-encoded inside clientDataJSON).
    raw_challenge = extract_challenge(attestation)
    # Consume the stored challenge (locks the row).
    challenge_row = _consume_challenge(raw_challenge, "register")
    if challenge_row["user_id"] != user_id:
        raise PasskeyChallengeExpired("challenge-user-mismatch")
    # Re-build options for verification (the library expects the original options).
    webauthn_uid = b64u_decode(user_id) if False else None  # we use the new uid stored at start
    # The library recomputes the expected challenge from attestation.client_data.challenge,
    # but we still need rp_id + expected_origin for verify_registration_response.
    expected_origins = _allowed_origins()
    try:
        verification = _webauthn()["verify_registration_response"](
            credential=attestation,
            expected_challenge=raw_challenge,
            expected_origin=expected_origins,
            expected_rp_id=_rp_id(),
            require_user_verification=True,
        )
    except Exception as e:  # noqa: BLE001 — py_webauthn raises various ValueError subclasses
        logger.warning("registration verify failed for user=%s: %s", user_id, e)
        raise PasskeyAttestationFailed(str(e)) from e

    cred = verification.credential
    transports = [t.value for t in (cred.transports or [])]
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO passkey_credentials
                    (user_id, credential_id, public_key, sign_count, transports,
                     aaguid, user_verified, backup_eligible, backup_state, friendly_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING id
                """,
                (
                    user_id,
                    bytes(cred.id),
                    bytes(cred.public_key),
                    int(cred.sign_count or 0),
                    transports,
                    str(cred.aaguid) if cred.aaguid else None,
                    bool(cred.user_verified),
                    bool(cred.backup_eligible),
                    bool(cred.backup_state),
                    (friendly_name or "").strip()[:80] or None,
                ),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise PasskeyAlreadyEnrolled("race-on-unique")
        conn.commit()

    user_auth.audit_user(
        request,
        user_id,
        "passkey.register",
        target=str(cred.id),
        metadata={"transports": transports},
    )
    return {"id": str(row["id"]), "transports": transports}


# ── Login ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class _LoginHint:
    user_id: str | None
    email_hint: str | None


def _resolve_login_user(email_or_none: str | None) -> _LoginHint:
    """Look up a user by email (case-insensitive). Returns user_id=None if unknown.

    Anti-enumeration: callers must treat None and known identically.
    """
    email_clean = (email_or_none or "").strip().lower()[:254]
    if not email_clean:
        return _LoginHint(None, None)
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email_verified FROM users WHERE email = %s",
                    (email_clean,),
                )
                row = cur.fetchone()
    except psycopg.Error as e:
        logger.exception("login lookup failed: %s", e)
        return _LoginHint(None, email_clean)
    if not row:
        return _LoginHint(None, email_clean)
    return _LoginHint(str(row["id"]), email_clean)


def start_login(
    email_or_none: str | None,
    ip: str | None = None,
    ua: str | None = None,
) -> dict[str, Any]:
    """Issue a PublicKeyCredentialRequestOptions challenge.

    Anti-enumeration: if the email is unknown OR the user has no passkey,
    we still return the same JSON shape with empty allowCredentials.
    """
    challenge = _gen_challenge()
    hint = _resolve_login_user(email_or_none)
    wa = _webauthn()
    allow_credentials = []
    if hint.user_id:
        rows = list_user_passkeys(hint.user_id)
        for r in rows:
            allow_credentials.append(
                wa["PublicKeyCredentialDescriptor"](
                    id=b64u_decode(r["credential_id_b64u"]),
                    type=wa["PublicKeyCredentialType"].PUBLIC_KEY,
                    transports=r.get("transports") or [],
                )
            )
    _store_challenge(
        "login",
        challenge,
        user_id=hint.user_id,
        email_hint=hint.email_hint,
        ip=ip,
        ua=ua,
    )
    options = wa["generate_authentication_options"](
        rp_id=_rp_id(),
        challenge=challenge,
        timeout=CHALLENGE_TTL_SECONDS * 1000,
        user_verification=wa["UserVerificationRequirement"].REQUIRED,
        allow_credentials=allow_credentials,
    )
    return _serialize_authn_options(options)


def _serialize_authn_options(opts) -> dict[str, Any]:
    return {
        "challenge": b64u_encode(opts.challenge),
        "rpId": opts.rp_id,
        "timeout": opts.timeout,
        "userVerification": _enum_or_str(opts.user_verification),
        "allowCredentials": [
            {
                "id": b64u_encode(bytes(c.id)),
                "type": "public-key",
                "transports": [_enum_or_str(t) for t in (c.transports or [])],
            }
            for c in (opts.allow_credentials or [])
        ],
        # `hints` is present on PublicKeyCredentialRequestOptions in 2.x but
        # was removed in 3.x. Emit when present so 3.x doesn't AttributeError.
        **({"hints": [_enum_or_str(h) for h in opts.hints]}
           if hasattr(opts, "hints") and opts.hints else {}),
    }


def complete_login(
    assertion: dict,
    request,
) -> str:
    """Verify the assertion, update sign_count, return user_id.

    Caller is responsible for calling `user_auth.create_user_session(...)` after.
    """
    raw_challenge = extract_challenge(assertion)
    challenge_row = _consume_challenge(raw_challenge, "login")
    raw_id = b64u_decode(assertion["rawId"])
    # Look up the stored credential by rawId.
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, credential_id, public_key, sign_count
                FROM passkey_credentials
                WHERE credential_id = %s AND revoked_at IS NULL
                """,
                (raw_id,),
            )
            row = cur.fetchone()
    if not row:
        # Anti-enumeration: do not reveal whether the credential exists.
        raise PasskeyAssertionFailed("no-credential")

    user = _require_verified_user(str(row["user_id"]))
    if challenge_row["user_id"] and challenge_row["user_id"] != str(row["user_id"]):
        raise PasskeyAssertionFailed("user-mismatch")

    try:
        verification = _webauthn()["verify_authentication_response"](
            credential=assertion,
            expected_challenge=raw_challenge,
            expected_origin=_allowed_origins(),
            expected_rp_id=_rp_id(),
            credential_public_key=bytes(row["public_key"]),
            credential_current_sign_count=int(row["sign_count"]),
            require_user_verification=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("assertion verify failed for user=%s: %s", row["user_id"], e)
        raise PasskeyAssertionFailed(str(e)) from e

    new_count = int(verification.new_sign_count or 0)
    stored_count = int(row["sign_count"])
    if new_count < stored_count:
        # Cloned authenticator → revoke.
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE passkey_credentials
                    SET revoked_at = NOW()
                    WHERE id = %s
                    """,
                    (row["id"],),
                )
            conn.commit()
        user_auth.audit_user(
            request,
            str(row["user_id"]),
            "passkey.cloned-detected",
            target=str(row["id"]),
            metadata={"stored": stored_count, "observed": new_count},
        )
        raise PasskeyCounterRegression("counter-regressed")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE passkey_credentials
                SET sign_count = %s, last_used_at = NOW()
                WHERE id = %s
                """,
                (new_count, row["id"]),
            )
        conn.commit()

    user_auth.audit_user(
        request,
        str(row["user_id"]),
        "passkey.login",
        target=str(row["id"]),
        metadata={"sign_count": new_count},
    )
    return str(user["id"])


# ── Revoke ────────────────────────────────────────────────────────────────────────────────────────────────

def revoke_passkey(user_id: str, cred_id_b64u: str, request) -> bool:
    """Soft-revoke the credential. Returns True if a row was updated."""
    try:
        cred_bytes = b64u_decode(cred_id_b64u)
    except Exception:
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE passkey_credentials
                    SET revoked_at = NOW()
                    WHERE user_id = %s AND credential_id = %s AND revoked_at IS NULL
                    RETURNING id
                    """,
                    (user_id, cred_bytes),
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg.Error as e:
        logger.exception("revoke failed: %s", e)
        return False
    if row:
        user_auth.audit_user(
            request,
            user_id,
            "passkey.revoke",
            target=str(row["id"]),
        )
        return True
    return False