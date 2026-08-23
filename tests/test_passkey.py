"""Tests for app.services.passkey — WebAuthn / Passkey service.

Mirrors `tests/test_url_safety.py` style: pure unit tests, no real DB or
WebAuthn ceremony. `py_webauthn` is mocked where needed; the DB layer is
mocked at the `psycopg.connect` boundary.

Run from the repo root:
    python3 -m unittest tests.test_passkey -v
"""
import base64
import secrets
import unittest
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
                            assertion = {
                                "id": "AQID",
                                "rawId": "AQID",
                                "challenge": _b64u(b"\xaa\xbb"),
                                "type": "public-key",
                                "response": {
                                    "clientDataJSON": _b64u(b"\x00"),
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
                            assertion = {
                                "id": "AQID",
                                "rawId": "AQID",
                                "challenge": _b64u(b"\xaa"),
                                "type": "public-key",
                                "response": {
                                    "clientDataJSON": _b64u(b"\x00"),
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


if __name__ == "__main__":
    unittest.main()
