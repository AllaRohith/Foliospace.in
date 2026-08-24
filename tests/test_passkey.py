"""Tests for app.services.passkey — WebAuthn / Passkey service.

Mirrors `tests/test_url_safety.py` style: pure unit tests, no real DB or
WebAuthn ceremony. `py_webauthn` is mocked where needed; the DB layer is
mocked at the `psycopg.connect` boundary.

Run from the repo root:
    python3 -m unittest tests.test_passkey -v
"""
import base64
import json
import secrets
import unittest
from types import SimpleNamespace
from unittest import mock


# ── Helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _bytes(b64u: str) -> bytes:
    pad = "=" * (-len(b64u) % 4)
    return base64.urlsafe_b64decode(b64u + pad)


class _MockCursor:
    """A real context-manager cursor mock. Returned by `make_conn`.

    Tracks `executed` queries and returns the queued values in order.
    """
    def __init__(self, results):
        self._results = list(results)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        if not self._results:
            return None
        nxt = self._results.pop(0)
        return None if nxt is _SENTINEL else nxt

    def fetchall(self):
        if not self._results:
            return []
        nxt = self._results.pop(0)
        return [] if nxt is _SENTINEL else nxt


_SENTINEL = object()


class _ConnCtx:
    """Context manager that yields a mock conn whose `.cursor()` returns
    `_MockCursor` instances. `commit()` / `rollback()` are no-ops."""

    def __init__(self, results_per_cursor=None):
        self._cursors = []
        self._results_per_cursor = results_per_cursor or []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        if self._results_per_cursor:
            results = self._results_per_cursor.pop(0)
        else:
            results = []
        cur = _MockCursor(results)
        self._cursors.append(cur)
        return cur

    def commit(self):
        pass

    def rollback(self):
        pass


def make_conn(results=None):
    """Build a mock DB connection whose cursor() returns real context-manager
    mocks. `results` is either a list (one cursor consumes them all) or a list
    of lists (one per `cursor()` call)."""
    if results and results and isinstance(results[0], list):
        per_cursor = results
    else:
        per_cursor = [results or []]
    return _ConnCtx(per_cursor)


# ── RP helpers ───────────────────────────────────────────────────────────────────────────────────────────────

class RpHelpersTests(unittest.TestCase):
    def test_rp_id_defaults_to_public_base_url_host(self):
        from app.services import passkey
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}, clear=False):
            self.assertEqual(passkey._rp_id(), "foliospace.in")

    def test_rp_id_localhost_aliases_127(self):
        from app.services import passkey
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "http://127.0.0.1:8000"}, clear=False):
            self.assertEqual(passkey._rp_id(), "localhost")

    def test_rp_id_strips_uppercase(self):
        from app.services import passkey
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://FolioSpace.in"}, clear=False):
            self.assertEqual(passkey._rp_id(), "foliospace.in")

    def test_rp_name_constant(self):
        from app.services import passkey
        self.assertEqual(passkey._rp_name(), "FolioSpace")
        self.assertEqual(passkey.RP_NAME, "FolioSpace")

    def test_allowed_origins_excludes_https_localhost(self):
        from app.services import passkey
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "http://localhost:8000"}, clear=False):
            origins = passkey._allowed_origins()
            self.assertIn("http://localhost", origins)
            self.assertNotIn("https://localhost", origins)

    def test_allowed_origins_https_for_prod(self):
        from app.services import passkey
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}, clear=False):
            origins = passkey._allowed_origins()
            self.assertIn("https://foliospace.in", origins)


# ── b64url helpers ───────────────────────────────────────────────────────────────────────────────────────────

class B64uTests(unittest.TestCase):
    def test_roundtrip(self):
        from app.services import passkey
        payload = secrets.token_bytes(64)
        self.assertEqual(passkey.b64u_decode(passkey.b64u_encode(payload)), payload)

    def test_decode_handles_missing_padding(self):
        from app.services import passkey
        raw = b"hello"
        encoded = _b64u(raw)
        self.assertNotIn("=", encoded)
        self.assertEqual(passkey.b64u_decode(encoded), raw)

    def test_decode_strips_empty_string(self):
        from app.services import passkey
        self.assertEqual(passkey.b64u_decode(""), b"")


# ── Challenge consume logic ────────────────────────────────────────────────────────────────────────────────

class ChallengeConsumeTests(unittest.TestCase):
    """Direct unit tests on _consume_challenge using a fake psycopg connection."""

    def _row(self, **over):
        from datetime import datetime, timedelta, timezone
        row = {
            "id": 1,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "email_hint": None,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=300),
            "consumed_at": None,
            "attempts": 0,
        }
        row.update(over)
        return row

    def _patched(self, results):
        from app.services import passkey
        conn = make_conn(results)
        return passkey, conn

    def test_happy_path_returns_row(self):
        from app.services import passkey
        passkey, ctx = self._patched([self._row()])
        with mock.patch.dict("os.environ", {"DATABASE_URL": "postgres://x"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                out = passkey._consume_challenge(b"abc", "register")
        self.assertIsNotNone(out)
        self.assertEqual(out["user_id"], "11111111-1111-1111-1111-111111111111")

    def test_lockout_after_three_attempts(self):
        from app.services import passkey
        passkey, ctx = self._patched([self._row(attempts=2)])
        with mock.patch.dict("os.environ", {"DATABASE_URL": "postgres://x"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with self.assertRaises(passkey.PasskeyAttemptLockout):
                    passkey._consume_challenge(b"abc", "register")

    def test_already_consumed_raises_expired(self):
        from app.services import passkey
        from datetime import datetime, timezone
        passkey, ctx = self._patched([self._row(consumed_at=datetime.now(timezone.utc))])
        with mock.patch.dict("os.environ", {"DATABASE_URL": "postgres://x"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with self.assertRaises(passkey.PasskeyChallengeExpired):
                    passkey._consume_challenge(b"abc", "register")

    def test_expired_raises(self):
        from app.services import passkey
        from datetime import datetime, timedelta, timezone
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        passkey, ctx = self._patched([self._row(expires_at=past)])
        with mock.patch.dict("os.environ", {"DATABASE_URL": "postgres://x"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with self.assertRaises(passkey.PasskeyChallengeExpired):
                    passkey._consume_challenge(b"abc", "register")

    def test_not_found_raises(self):
        from app.services import passkey
        passkey, ctx = self._patched([])
        with mock.patch.dict("os.environ", {"DATABASE_URL": "postgres://x"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with self.assertRaises(passkey.PasskeyChallengeExpired):
                    passkey._consume_challenge(b"missing", "register")


# ── Anti-enumeration on login begin ─────────────────────────────────────────────────────────────────────────────────

class LoginBeginAntiEnumTests(unittest.TestCase):
    def _stub_wa(self):
        """Return a stub webauthn module dict; all functions return a basic
        dataclass-like with the fields our serializer reads."""
        class _Opts:
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

        stub = {
            "generate_authentication_options": mock.MagicMock(return_value=_Opts(
                challenge=b"\xaa" * 32,
                rp_id="foliospace.in",
                timeout=300000,
                user_verification=type("UV", (), {"value": "required"})(),
                allow_credentials=[],
                hints=[],
            )),
            "generate_registration_options": mock.MagicMock(),
            "verify_authentication_response": mock.MagicMock(),
            "verify_registration_response": mock.MagicMock(),
            "COSEAlgorithmIdentifier": mock.MagicMock(),
            "PublicKeyCredentialDescriptor": mock.MagicMock(),
            "ResidentKeyRequirement": mock.MagicMock(),
            "UserVerificationRequirement": mock.MagicMock(
                REQUIRED=type("UV", (), {"value": "required"})(),
            ),
            "AttestationConveyancePreference": mock.MagicMock(),
            "AuthenticatorAttachment": mock.MagicMock(),
            "PublicKeyCredentialType": mock.MagicMock(),
        }
        return stub

    def test_unknown_email_returns_same_shape(self):
        from app.services import passkey

        # 1st cursor: user lookup (None). 2nd: INSERT RETURNING id.
        ctx = make_conn([[], [{"id": 1}]])
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with mock.patch.object(passkey, "_webauthn", return_value=self._stub_wa()):
                    payload = passkey.start_login("ghost@example.com")

        self.assertIn("challenge", payload)
        self.assertIn("rpId", payload)
        self.assertIn("allowCredentials", payload)
        self.assertEqual(payload["allowCredentials"], [])
        self.assertEqual(payload["userVerification"], "required")

    def test_known_user_returns_empty_when_no_passkey(self):
        from app.services import passkey

        user_row = {"id": "11111111-1111-1111-1111-111111111111", "email_verified": True}
        # 1st cursor: user lookup. 2nd: INSERT RETURNING id.
        ctx = make_conn([[user_row], [{"id": 1}]])
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with mock.patch.object(passkey, "list_user_passkeys", return_value=[]):
                    with mock.patch.object(passkey, "_webauthn", return_value=self._stub_wa()):
                        payload = passkey.start_login("real@example.com")
        self.assertEqual(payload["allowCredentials"], [])


# ── Pre-verified email gate ────────────────────────────────────────────────────────────────────────────────

class VerifiedEmailGateTests(unittest.TestCase):
    def _user_row(self, verified=True, deleted=False):
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "a@b.in",
            "email_verified": verified,
            "deleted_at": None if not deleted else "2025-01-01",
        }

    def test_register_blocked_when_email_not_verified(self):
        from app.services import passkey

        ctx = make_conn([self._user_row(verified=False)])
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with self.assertRaises(passkey.PasskeyUnverifiedEmail):
                    passkey.start_registration("11111111-1111-1111-1111-111111111111")

    def test_register_blocked_when_user_deleted(self):
        from app.services import passkey

        ctx = make_conn([self._user_row(deleted=True)])
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with self.assertRaises(passkey.PasskeyUnverifiedEmail):
                    passkey.start_registration("11111111-1111-1111-1111-111111111111")

    def test_register_blocked_when_already_enrolled(self):
        from app.services import passkey

        ctx = make_conn([self._user_row(verified=True)])
        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with mock.patch.object(
                    passkey,
                    "list_user_passkeys",
                    return_value=[{"credential_id_b64u": "abc", "transports": []}],
                ):
                    with self.assertRaises(passkey.PasskeyAlreadyEnrolled):
                        passkey.start_registration("11111111-1111-1111-1111-111111111111")


# ── Counter regression on login ────────────────────────────────────────────────────────────────────────────

class CounterRegressionTests(unittest.TestCase):
    def test_login_revokes_when_counter_regresses(self):
        from app.services import passkey

        class _V:
            new_sign_count = 5  # stored is 10 → regression
            credential_id = b"\x01\x02"
            user_verified = True

        cred_row = {
            "id": 7,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "credential_id": b"\x01\x02",
            "public_key": b"\x03\x04",
            "sign_count": 10,
        }
        user_row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "a@b.in",
            "email_verified": True,
            "deleted_at": None,
        }

        ctx = make_conn([[cred_row], [user_row], [None]])

        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with mock.patch.object(passkey, "_consume_challenge",
                                       return_value={"user_id": cred_row["user_id"],
                                                     "email_hint": None}):
                    with mock.patch.dict(passkey._webauthn_cache,
                                         {"verify_authentication_response": mock.MagicMock(return_value=_V())}):
                        with mock.patch.object(passkey.user_auth, "audit_user"):
                            _cdj = _b64u(json.dumps({
                                "type": "webauthn.get",
                                "challenge": _b64u(b"\xaa\xbb"),
                                "origin": "https://foliospace.in",
                                "crossOrigin": False,
                            }).encode("utf-8"))
                            assertion = {
                                "id": "AQID",
                                "rawId": "AQID",
                                "type": "public-key",
                                "response": {
                                    "clientDataJSON": _cdj,
                                    "authenticatorData": _b64u(b"\x01"),
                                    "signature": _b64u(b"\x02"),
                                },
                            }
                            with self.assertRaises(passkey.PasskeyCounterRegression):
                                passkey.complete_login(assertion, request=mock.MagicMock())


# ── Audit log on success ────────────────────────────────────────────────────────────────────────────────────

class AuditLogTests(unittest.TestCase):
    def test_login_writes_audit_row(self):
        from app.services import passkey

        class _V:
            new_sign_count = 11
            credential_id = b"\x01\x02"

        cred_row = {
            "id": 9,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "credential_id": b"\x01\x02",
            "public_key": b"\x03\x04",
            "sign_count": 10,
        }
        user_row = {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "a@b.in",
            "email_verified": True,
            "deleted_at": None,
        }

        ctx = make_conn([[cred_row], [user_row], [None]])

        with mock.patch.dict("os.environ", {"PUBLIC_BASE_URL": "https://foliospace.in"}):
            with mock.patch.object(passkey, "_connect", return_value=ctx):
                with mock.patch.object(passkey, "_consume_challenge",
                                       return_value={"user_id": cred_row["user_id"],
                                                     "email_hint": None}):
                    with mock.patch.dict(passkey._webauthn_cache,
                                         {"verify_authentication_response": mock.MagicMock(return_value=_V())}):
                        with mock.patch.object(passkey.user_auth, "audit_user") as audit:
                            _cdj = _b64u(json.dumps({
                                "type": "webauthn.get",
                                "challenge": _b64u(b"\xaa"),
                                "origin": "https://foliospace.in",
                                "crossOrigin": False,
                            }).encode("utf-8"))
                            assertion = {
                                "id": "AQID",
                                "rawId": "AQID",
                                "type": "public-key",
                                "response": {
                                    "clientDataJSON": _cdj,
                                    "authenticatorData": _b64u(b"\x01"),
                                    "signature": _b64u(b"\x02"),
                                },
                            }
                            user_id = passkey.complete_login(assertion, request=mock.MagicMock())
                            self.assertEqual(user_id, cred_row["user_id"])
                            audit.assert_called()
                            first_call_args = audit.call_args_list[0]
                            self.assertEqual(first_call_args[0][2], "passkey.login")


# ── Exception hierarchy ───────────────────────────────────────────────────────────────────────────────────────

class ExceptionHierarchyTests(unittest.TestCase):
    def test_all_errors_subclass_passkey_error(self):
        from app.services import passkey
        names = [n for n in dir(passkey) if n.startswith("Passkey") and n != "PasskeyError"]
        for n in names:
            cls = getattr(passkey, n)
            self.assertTrue(
                issubclass(cls, passkey.PasskeyError),
                f"{n} is not a subclass of PasskeyError",
            )

    def test_each_error_has_code(self):
        from app.services import passkey
        names = [n for n in dir(passkey) if n.startswith("Passkey") and n != "PasskeyError"]
        for n in names:
            cls = getattr(passkey, n)
            self.assertTrue(hasattr(cls, "code"), f"{n} missing .code")
            self.assertIsInstance(cls.code, str)
            self.assertGreater(len(cls.code), 0)


# ── /dashboard/passkeys page context ─────────────────────────────────────────────────────────────────────────

class DashboardPageContextTests(unittest.TestCase):
    """Regression: dashboard passkeys page must include `user` in template context.

    The shared `_dash_sidebar.html` partial references `user.slug`, `user.is_internal`,
    `user.display_name`, `user.email`, and the `plan_summary` macro reads `plan`/
    `plan_expires_at`/`payment_failed_at`. Earlier, only `u` was passed → 500 with
    `jinja2.exceptions.UndefinedError: 'user' is undefined`.
    """

    def _make_request(self):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/dashboard/passkeys",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
        return Request(scope)

    def _run(self, coro):
        import asyncio

        return asyncio.get_event_loop().run_until_complete(coro)

    def test_passkeys_page_context_has_user(self):
        import asyncio
        from app.routers import passkey as passkey_router

        fake_user = {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "a@b.in",
            "slug": "alice",
            "display_name": "Alice",
            "email_verified": True,
            "plan": "free",
            "is_internal": False,
            "plan_expires_at": None,
            "payment_failed_at": None,
        }
        captured = {}

        def _fake_template_response(request, name, ctx):
            captured["name"] = name
            captured["ctx"] = ctx
            return SimpleNamespace(headers={}, body=b"")

        req = self._make_request()
        with mock.patch.object(
            passkey_router.user_auth, "require_user", return_value=fake_user
        ), mock.patch.object(
            passkey_router.passkey_svc, "list_user_passkeys", return_value=[]
        ), mock.patch.object(
            passkey_router.templates, "TemplateResponse", side_effect=_fake_template_response
        ):
            self._run(passkey_router.passkeys_page(req))

        ctx = captured.get("ctx", {})
        self.assertIn("user", ctx, "dashboard passkeys context must include `user`")
        self.assertIs(ctx["user"], fake_user)
        # All sidebar-required fields must reach the template untouched.
        for key in ("slug", "email", "display_name", "is_internal", "plan"):
            self.assertIn(key, ctx["user"], f"user context missing `{key}` for sidebar")


# ── extract_challenge regression ─────────────────────────────────────────────────────────────────────────────

class ExtractChallengeTests(unittest.TestCase):
    """Regression for the KeyError 'challenge' bug hit on Render 2026-08-24.

    The browser's PublicKeyCredential JSON has NO top-level `challenge` key —
    the challenge bytes live base64url-encoded inside `response.clientDataJSON`.
    complete_registration / complete_login used to do `attestation["challenge"]`
    and 500 with KeyError. extract_challenge decodes the real shape.
    """

    def _cdj(self, raw_challenge: bytes, kind: str = "webauthn.create") -> str:
        return base64.urlsafe_b64encode(json.dumps({
            "type": kind,
            "challenge": base64.urlsafe_b64encode(raw_challenge).rstrip(b"=").decode("ascii"),
            "origin": "https://foliospace.in",
            "crossOrigin": False,
        }, separators=(",", ":")).encode("utf-8")).rstrip(b"=").decode("ascii")

    def test_returns_raw_challenge_bytes(self):
        from app.services import passkey
        raw = b"\xaa" * 32
        cred = {
            "id": "x", "rawId": "x", "type": "public-key",
            "response": {"clientDataJSON": self._cdj(raw),
                         "attestationObject": "y"},
        }
        self.assertEqual(passkey.extract_challenge(cred), raw)

    def test_login_shape(self):
        from app.services import passkey
        raw = b"\xbb" * 16
        cred = {
            "id": "x", "rawId": "x", "type": "public-key",
            "response": {"clientDataJSON": self._cdj(raw, kind="webauthn.get"),
                         "authenticatorData": "z", "signature": "w"},
        }
        self.assertEqual(passkey.extract_challenge(cred), raw)

    def test_missing_client_data_raises(self):
        from app.services import passkey
        with self.assertRaises(passkey.PasskeyAttestationFailed):
            passkey.extract_challenge({"response": {}, "id": "x", "rawId": "x"})

    def test_garbage_client_data_raises(self):
        from app.services import passkey
        with self.assertRaises(passkey.PasskeyAttestationFailed):
            passkey.extract_challenge({
                "response": {"clientDataJSON": "!!not-base64!!"},
                "id": "x", "rawId": "x",
            })

    def test_json_without_challenge_field_raises(self):
        from app.services import passkey
        cdata = base64.urlsafe_b64encode(b'{"type":"webauthn.create","origin":"x"}').rstrip(b"=")
        with self.assertRaises(passkey.PasskeyAttestationFailed):
            passkey.extract_challenge({
                "response": {"clientDataJSON": cdata.decode("ascii")},
                "id": "x", "rawId": "x",
            })


# ── VerifiedRegistration field access ──────────────────────────────────────────────────────────────────────

class CompleteRegistrationFieldAccessTests(unittest.TestCase):
    """Regression for the AttributeError 'credential' bug hit on Render 2026-08-24.

    complete_registration used to read `verification.credential.id`,
    `verification.credential.transports`, `verification.credential.backup_eligible`,
    `verification.credential.backup_state` — but py_webauthn's VerifiedRegistration
    (identical shape on 2.x and 3.x) is a flat dataclass with credential_id /
    credential_public_key / credential_backed_up. None of the original fields exist.

    This test verifies complete_registration reads the CORRECT field names and the
    DB INSERT receives the right types (bytes for credential_id/public_key, UUID
    for aaguid, None for transports, bool for the backup flags).
    """

    def _stub_verified(self):
        from dataclasses import make_dataclass
        return make_dataclass("StubVerified", [
            ("credential_id", bytes),
            ("credential_public_key", bytes),
            ("sign_count", int),
            ("aaguid", str),
            ("fmt", str),
            ("credential_type", str),
            ("user_verified", bool),
            ("attestation_object", bytes),
            ("credential_device_type", str),
            ("credential_backed_up", bool),
        ])(
            credential_id=b"\x01\x02\x03\x04",
            credential_public_key=b"\xde\xad\xbe\xef" * 8,
            sign_count=0,
            aaguid="550e8400-e29b-41d4-a716-446655440000",
            fmt="none",
            credential_type="public-key",
            user_verified=True,
            attestation_object=b"\xa0",
            credential_device_type="single_device",
            credential_backed_up=False,
        )

    def _setup_patches(self, passkey):
        raw_challenge = b"\xaa" * 32
        cdata = json.dumps({
            "type": "webauthn.create",
            "challenge": base64.urlsafe_b64encode(raw_challenge).rstrip(b"=").decode("ascii"),
            "origin": "https://foliospace.in",
            "crossOrigin": False,
        }, separators=(",", ":")).encode("utf-8")
        cred = {
            "id": "AQIDBA", "rawId": "AQIDBA", "type": "public-key",
            "response": {
                "clientDataJSON": base64.urlsafe_b64encode(cdata).rstrip(b"=").decode("ascii"),
                "attestationObject": "ignored",
            },
        }
        captured = {}
        cursor = mock.MagicMock()
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = lambda *a: False
        cursor.execute = lambda sql, params=(): captured.setdefault("params", params)
        cursor.fetchone = lambda: {"id": 999}
        conn = mock.MagicMock()
        conn.__enter__ = lambda s: s
        conn.__exit__ = lambda *a: False
        conn.cursor = lambda: cursor
        # Make sure the cache is populated before we patch it (other tests need it).
        passkey._webauthn()
        self._cache_patcher = mock.patch.dict(
            passkey._webauthn_cache,
            {"verify_registration_response": mock.MagicMock(return_value=self._stub_verified())},
        )
        self._cache_patcher.start()
        self.addCleanup(self._cache_patcher.stop)
        self._connect_patcher = mock.patch.object(passkey, "_connect", return_value=conn)
        self._connect_patcher.start()
        self.addCleanup(self._connect_patcher.stop)
        self._require_patcher = mock.patch.object(
            passkey, "_require_verified_user",
            return_value={"id": "11111111-1111-1111-1111-111111111111", "email": "a@b.in"},
        )
        self._require_patcher.start()
        self.addCleanup(self._require_patcher.stop)
        self._consume_patcher = mock.patch.object(
            passkey, "_consume_challenge",
            return_value={"user_id": "11111111-1111-1111-1111-111111111111", "email_hint": None},
        )
        self._consume_patcher.start()
        self.addCleanup(self._consume_patcher.stop)
        return cred, captured

    def test_does_not_attribute_error(self):
        from app.services import passkey
        cred, captured = self._setup_patches(passkey)
        result = passkey.complete_registration(
            "11111111-1111-1111-1111-111111111111", cred, "Test",
            request=mock.MagicMock(),
        )
        self.assertIn("id", result)
        self.assertIn("credential_id", result)

    def test_insert_uses_correct_field_names(self):
        from app.services import passkey
        cred, captured = self._setup_patches(passkey)
        passkey.complete_registration(
            "11111111-1111-1111-1111-111111111111", cred, "Test",
            request=mock.MagicMock(),
        )
        params = captured["params"]
        self.assertEqual(params[1], b"\x01\x02\x03\x04",
                         "credential_id must come from .credential_id, not .id")
        self.assertEqual(params[2], b"\xde\xad\xbe\xef" * 8,
                         "public_key must come from .credential_public_key")
        self.assertIsNone(params[4],
                          "transports not exposed by py_webauthn — must be NULL")
        import uuid
        self.assertEqual(params[5], uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
                         "aaguid string must parse to UUID")
        self.assertIs(params[6], True,
                      "user_verified must come from .user_verified")
        self.assertIs(params[7], False,
                      "backup_eligible mirrors .credential_backed_up")
        self.assertIs(params[8], False,
                      "backup_state must come from .credential_backed_up")


# ── webauthn 3.x API compatibility ─────────────────────────────────────────────────────────────────────────

class WebauthnCrossVersionTests(unittest.TestCase):
    """Regression: serialize for both webauthn 2.x AND 3.x.

    Render currently runs webauthn 2.2.0 (per `pip install --dry-run -r
    requirements.txt`). 3.x has been released but pip resolves to 2.2.0
    because nothing in the requirements graph pulls a newer one. So the
    serializers MUST tolerate both:

    - 2.x: raw strings (e.g. attestation='none', user_verification='required',
      transports=['usb']), no `hints` field on either Options dataclass.
    - 3.x: enum members with `.value`, `hints` field on
      PublicKeyCredentialCreationOptions (was added), absent on
      PublicKeyCredentialRequestOptions (was removed).

    Three historical bugs encoded here:
    1. Passing `authenticator_selection` as a dict instead of
       `AuthenticatorSelectionCriteria` dataclass — fails on BOTH versions.
    2. `_serialize_reg_options` accessing `opts.attestation.value` — fails on 2.x
       (it's a string, not an enum).
    3. Accessing `opts.hints` — fails on 2.x (no field) AND on 3.x
       PublicKeyCredentialRequestOptions (no field there either).
    """

    def setUp(self):
        import webauthn
        try:
            import dataclasses
            from webauthn.helpers.structs import (
                PublicKeyCredentialCreationOptions,
                PublicKeyCredentialRequestOptions,
            )
            self._pkc_fields = [f.name for f in dataclasses.fields(PublicKeyCredentialCreationOptions)]
            self._pkr_fields = [f.name for f in dataclasses.fields(PublicKeyCredentialRequestOptions)]
        except Exception as e:
            self.skipTest(f"py_webauthn not importable: {e}")
        self._version = webauthn.__version__

    def _build_registration(self):
        from app.services import passkey as pk
        wa = pk._webauthn()
        return wa["generate_registration_options"](
            rp_id="localhost",
            rp_name="FolioSpace",
            user_id=b"x" * 16,
            user_name="a@b.in",
            user_display_name="a@b.in",
            challenge=b"x" * 32,
            attestation=wa["AttestationConveyancePreference"].NONE,
            authenticator_selection=wa["AuthenticatorSelectionCriteria"](
                resident_key=wa["ResidentKeyRequirement"].PREFERRED,
                user_verification=wa["UserVerificationRequirement"].REQUIRED,
                authenticator_attachment=wa["AuthenticatorAttachment"].PLATFORM,
                require_resident_key=False,
            ),
            supported_pub_key_algs=[
                wa["COSEAlgorithmIdentifier"].ECDSA_SHA_256,
                wa["COSEAlgorithmIdentifier"].EDDSA,
                wa["COSEAlgorithmIdentifier"].RSASSA_PSS_SHA_256,
            ],
            timeout=300000,
        )

    def _build_authentication(self):
        from app.services import passkey as pk
        wa = pk._webauthn()
        return wa["generate_authentication_options"](
            rp_id="localhost",
            challenge=b"x" * 32,
            timeout=300000,
            user_verification=wa["UserVerificationRequirement"].REQUIRED,
            allow_credentials=[],
        )

    def test_reg_serializer_works_on_this_version(self):
        from app.services import passkey as pk
        opts = self._build_registration()
        out = pk._serialize_reg_options(opts)
        # wire format the browser expects
        self.assertEqual(out["rp"]["id"], "localhost")
        self.assertEqual(out["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(out["authenticatorSelection"]["authenticatorAttachment"], "platform")
        self.assertEqual(out["authenticatorSelection"]["residentKey"], "preferred")
        self.assertEqual(out["attestation"], "none")
        # hints is optional; only present when the library populates it
        if "hints" in self._pkc_fields:
            self.assertNotIn("hints", out)  # None → skipped

    def test_authn_serializer_works_on_this_version(self):
        from app.services import passkey as pk
        opts = self._build_authentication()
        out = pk._serialize_authn_options(opts)
        self.assertEqual(out["userVerification"], "required")
        self.assertEqual(out["rpId"], "localhost")

    def test_enum_or_str_handles_strings(self):
        from app.services.passkey import _enum_or_str
        self.assertEqual(_enum_or_str("required"), "required")
        self.assertEqual(_enum_or_str(None), None)
        # 3.x enum — check by mocking an enum-like object
        class _FakeEnum:
            value = "preferred"
        self.assertEqual(_enum_or_str(_FakeEnum()), "preferred")


# ── JS login-credential serializer (static source check) ───────────────────────────────────────────────────

class CredentialToJSONSourceTests(unittest.TestCase):
    """Regression for the Render 2026-08-24 'authenticatorData missing' bug.

    The login-side JS serializer used to only include response.clientDataJSON
    in the credential posted to /passkey/login/complete. The browser's
    AuthenticatorAssertionResponse ALSO has authenticatorData, signature, and
    optionally userHandle — py_webauthn's verify_authentication_response
    requires all three. We re-introduced them; this test pins the source so
    nobody strips them out again.
    """

    def _read(self, name: str) -> str:
        import pathlib
        return pathlib.Path(
            f"/Users/rohithnaidualla/Desktop/FolioSpace/app/static/js/{name}"
        ).read_text()

    def _extract(self, src: str) -> str:
        # Grab everything from `function credentialToJSON(` to the closing brace
        # of its body. Brace counting tolerates nested braces in inner objects.
        start = src.index("function credentialToJSON(")
        depth = 0
        i = src.index("{", start)
        end = None
        for j in range(i, len(src)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        self.assertIsNotNone(end, "could not find end of credentialToJSON")
        return src[i:end]

    def test_unminified_includes_authenticator_data_and_signature(self):
        src = self._read("passkey.js")
        body = self._extract(src)
        self.assertIn("authenticatorData", body,
                      "credentialToJSON must include authenticatorData")
        self.assertIn("signature", body,
                      "credentialToJSON must include signature")
        self.assertIn("userHandle", body,
                      "credentialToJSON must handle userHandle (resident-key flows)")

    def test_minified_includes_authenticator_data_and_signature(self):
        src = self._read("passkey.min.js")
        self.assertIn("function credentialToJSON(", src,
                      "credentialToJSON missing from min.js")
        body = self._extract(src)
        self.assertIn("authenticatorData", body,
                      "credentialToJSON in min.js must include authenticatorData")
        self.assertIn("signature", body,
                      "credentialToJSON in min.js must include signature")

    def test_login_response_carries_authenticator_data_and_signature(self):
        # Sanity check: the function emitted to /passkey/login/complete is
        # `credentialToJSON(cred)`, not `attestationToJSON(cred)`. If someone
        # swaps them, login would silently break.
        src = self._read("passkey.js")
        # credentialToJSON must be called as a function (not just defined).
        call_sites = src.count("credentialToJSON(") - src.count("function credentialToJSON(")
        self.assertGreaterEqual(call_sites, 1,
            "credentialToJSON must be called at least once (login handler)")
        # attestationToJSON must NOT be called by passkeyLogin.
        # Check that the substring around the login handler only references credentialToJSON.
        login_idx = src.index("function passkeyLogin(")
        # Find the next top-level function declaration after passkeyLogin
        register_idx = src.index("function passkeyRegister(", login_idx)
        login_block = src[login_idx:register_idx]
        self.assertIn("credentialToJSON(", login_block,
            "passkeyLogin must call credentialToJSON")
        self.assertNotIn("attestationToJSON(", login_block,
            "passkeyLogin must NOT call attestationToJSON")


if __name__ == "__main__":
    unittest.main()
